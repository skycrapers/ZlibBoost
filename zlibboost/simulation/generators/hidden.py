"""
Hidden power SPICE deck generator.

Implements the SPICE deck generator for hidden/dynamic power measurement by
integrating supply currents during switching.
"""

from typing import List, Dict, Optional

from zlibboost.database.models.timing_arc import TransitionDirection
from zlibboost.simulation.polarity import resolve_output_pin
from .base import BaseSpiceGenerator


class HiddenSpiceGenerator(BaseSpiceGenerator):

    def __init__(self, arc, cell, library_db, sim_type=None):
        """
        Initialize HiddenSpiceGenerator with timing arc, cell, and library database.

        Args:
            arc: TimingArc to generate SPICE deck for
            cell: Cell containing the arc
            library_db: Library database with templates and waveforms
            sim_type: Simulation type from factory (optional, defaults to 'hidden')
        """
        # Call base class initializer
        super().__init__(arc, cell, library_db, sim_type or 'hidden')
        
        # Get delay waveform for hidden power measurement
        self.delay_waveform = self.library_db.get_driver_waveform('delay_waveform')
        if not self.delay_waveform:
            raise ValueError(f"No delay waveform found for cell {self.cell.name}")
        
        # Get constraint waveform for i1/i2 indexing
        self.constraint_waveform = self.library_db.get_driver_waveform('constraint_waveform')
        

    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get file specifications for hidden power simulation.

        Hidden type generates a single file containing all parameter sweeps
        with .alter statements for each combination.
        
        Returns:
            List[Dict]: Single file specification with subdirectory path
        """
        # Build filename using base method
        filename = f"{self._build_base_filename()}.sp"
        
        # Generate complete deck content (including all .alter statements)
        content = self.generate_deck()
        
        return [{
            'filename': filename,
            'content': content
        }]

    def _generate_body(self) -> str:
        """
        Generate hidden power-specific SPICE body with power measurements.

        Hidden power testing measures current integration during switching:
        1. Power measurement from VSS and VDD supplies
        2. Integration window from half_tran_tend to tran_tend
        3. State-dependent PWL generation based on pin types

        Returns:
            SPICE body section for hidden power measurement
        """
        lines = []

        # 1. Add power measurement commands
        lines.extend(self._generate_power_measurements())

        # 2. Add main pin PWL and condition PWL (following legacy order)
        lines.extend(self._generate_pwl_sources())

        # 3. Add basic parameters definition
        lines.extend(self._generate_basic_parameters())

        # 4. Add load capacitance
        lines.extend(self._generate_output_capacitances())

        # 5. Add simulation options
        lines.extend(self._generate_simulation_options())

        # 6. Add parameter sweeps for hidden power characterization
        lines.extend(self._generate_parameter_sweeps())

        return "\n".join(lines)

    def _generate_power_measurements(self) -> List[str]:
        """
        Generate SPICE .meas statements for hidden power measurement.

        Measures integrated current from power supplies during the second half
        of the transition period to capture dynamic power consumption.

        Returns:
            List[str]: Power measurement commands
        """
        lines = []
        
        # Integrate current from VSS (ground)
        lines.append(".meas tran ZlibBoostPower000 INTEG i(VVSS) from='half_tran_tend' to='tran_tend'")
        
        # Integrate current from VDD (power)
        lines.append(".meas tran ZlibBoostPower001 INTEG i(VVDD) from='half_tran_tend' to='tran_tend'")
        
        # Calculate hidden power (negative of VDD current * voltage)
        lines.append(f".meas tran HiddenPower PARAM='-(ZlibBoostPower001)*{self.V_HIGH}'")
        lines.append("")
        
        return lines

    def _generate_pwl_sources(self) -> List[str]:
        """
        Generate PWL voltage sources for main pin and condition pins.
        
        This method follows the legacy code structure where:
        1. Main pin PWL is generated based on main pin type
        2. Condition PWL is generated within the same context, with Q value 
           determined inside the loop for each condition
        3. The condition PWL generation logic depends on the MAIN pin type,
           not the condition pin type
           
        Returns:
            List[str]: PWL source definitions
        """
        lines = []
        
        # Get main pin and pin categories
        main_pin = self.arc.pin
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        async_pins = self.cell.get_async_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        scan_in_pins = self.cell.get_scan_in_pins()
        enable_pins = self.cell.get_enable_pins()
        # Get waveform parameters
        t_count = len(self.delay_waveform.index_2) - 1
        
        # Process based on main pin type (following legacy structure exactly)
        if main_pin in clock_pins or main_pin in clock_negative_pins:
            # Clock pin: standard pulse pattern
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ '{main_pin}_t0' '{main_pin}_v0'")
            lines.append(f"+ '{main_pin}_t{t_count}' '{main_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend' '{main_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for clock main pin
            lines.extend(self._generate_clock_main_conditions())
            
        elif main_pin in data_pins:
            # Data pin: Q-dependent initial state
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            
            presim_target = self._resolve_presim_target_voltage()
            if presim_target is not None:
                lines.append(f"+ 0 {presim_target}")
                lines.append(f"+ 'quarter_tran_tend' {presim_target}")
            else:
                # Legacy fallback: infer from any output constraint in merged conditions
                if self._merged_conditions:
                    for pin_condition, pin_state in self._merged_conditions.items():
                        polarity, q_value = self._resolve_condition_output(pin_condition, pin_state)
                        if polarity and not polarity.is_negative:
                            if q_value == self.V_LOW:
                                lines.append(f"+ 0 {self.V_LOW}")
                                lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                            else:
                                lines.append(f"+ 0 {self.V_HIGH}")
                                lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                            break
                        elif polarity and polarity.is_negative:
                            if q_value == self.V_LOW:
                                lines.append(f"+ 0 {self.V_LOW}")
                                lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                            else:
                                lines.append(f"+ 0 {self.V_HIGH}")
                                lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                            break
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for data main pin
            lines.extend(self._generate_data_main_conditions())
            
        elif main_pin in sync_pins and main_pin in reset_pins:
            # Sync reset: initial HIGH
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for sync reset main pin
            lines.extend(self._generate_sync_reset_main_conditions())
            
        elif main_pin in sync_pins and main_pin in set_pins:
            # Sync set: initial HIGH
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for sync set main pin
            lines.extend(self._generate_sync_set_main_conditions())
            
        elif main_pin in async_pins and main_pin in reset_pins:
            # Async reset: initial LOW
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for async reset main pin
            lines.extend(self._generate_async_reset_main_conditions())
            
        elif main_pin in async_pins and main_pin in set_pins:
            # Async set: initial LOW
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for async set main pin
            lines.extend(self._generate_async_set_main_conditions())
            
        elif main_pin in scan_enable_pins:
            # Scan enable: initial LOW, transition at quarter_tran_tend
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for scan enable main pin
            lines.extend(self._generate_scan_enable_main_conditions())
            
        elif main_pin in scan_in_pins:
            # Scan in: uses parameterized initial value
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 '{main_pin}_v0'")
            lines.append(f"+ 'quarter_tran_tend' '{main_pin}_v0'")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for scan in main pin
            lines.extend(self._generate_scan_in_main_conditions())
            
        elif main_pin in enable_pins:
            # Enable: initial HIGH, transition at quarter_tran_tend
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ 0 {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
            lines.append(f"+ 'quarter_tran_tend+1e-12' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for enable main pin
            lines.extend(self._generate_enable_main_conditions())
        
        else:
            # Default case: parameterized pulse pattern (for any other pin types)
            lines.append(f"V{main_pin} {main_pin} 0 pwl(")
            lines.append(f"+ '{main_pin}_t0' '{main_pin}_v0'")
            lines.append(f"+ '{main_pin}_t{t_count}' '{main_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend' '{main_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' '{main_pin}_v0'")
            lines.extend(self._write_pin_values(main_pin, t_count))
            
            # Generate condition PWL for default main pin
            lines.extend(self._generate_default_main_conditions())
            
        if lines:
            lines.append("")
            
        return lines

    def _resolve_condition_output(self, pin_name: str, pin_state: str):
        """Return polarity info and physical voltage for an output condition pin."""
        polarity = resolve_output_pin(self.cell, pin_name)
        if not polarity:
            return None, None
        voltage = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
        return polarity, voltage

    def _resolve_presim_target_voltage(self) -> Optional[float]:
        """Resolve the desired output state voltage for pre-simulation.

        Hidden decks use a pre-simulation clock edge (rather than `.ic`) to reach a
        deterministic sequential state. For flip-flops, this typically means
        driving data-like pins to match the constrained output state during the
        pre-sim window, then switching them to the requested input condition
        before the measured edge.
        """

        output_conditions = getattr(self, "_output_conditions", {}) or {}
        if not output_conditions:
            return None

        # Prefer explicit non-inverted outputs (e.g., Q=0/1).
        for pin_name, pin_state in output_conditions.items():
            polarity = resolve_output_pin(self.cell, pin_name)
            if polarity and not polarity.is_negative:
                return polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)

        # Fall back: if only inverted outputs are constrained (e.g., QN),
        # infer the "true" output voltage.
        for pin_name, pin_state in output_conditions.items():
            polarity = resolve_output_pin(self.cell, pin_name)
            if not polarity:
                continue
            voltage = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
            if polarity.is_negative:
                return self.V_HIGH if voltage == self.V_LOW else self.V_LOW
            return voltage

        return None

    def _generate_clock_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is clock type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin (following legacy double loop structure)
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition in the condition_dict
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                    
                # Check if pin_condition matches pin_name
                if pin_condition != pin_name:
                    continue

                # Generate PWL based on condition pin type
                if pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_HIGH:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    else:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines

    def _generate_data_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is data type."""
        lines = []
        
        if not self._merged_conditions:
            return lines
            
        # Get pin categories  
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin (following legacy double loop structure)
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition in the condition_dict
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                # Check if pin_condition matches pin_name
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines

    def _generate_sync_reset_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is sync reset type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines

    def _generate_sync_set_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is sync set type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():                    
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines

    def _generate_async_reset_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is async reset type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
            
                if pin_condition != pin_name:
                    continue

                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines

    def _generate_async_set_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is async set type."""
        lines = []
        
        if not self._merged_conditions:
            return lines
            
        # Get pin categories
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                    
                if pin_condition != pin_name:
                    continue
                if pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines
    
    def _generate_scan_enable_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is scan enable type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin (following legacy structure from lines 1254-1278)
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type (following legacy lines 1264-1278)
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines
    
    def _generate_scan_in_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is scan in type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories (following legacy lines 1283-1318)
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        enable_pins = self.cell.get_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines
    
    def _generate_enable_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin is enable type."""
        lines = []
        
        if not self._merged_conditions:
            return lines

        presim_target = self._resolve_presim_target_voltage()
            
        # Get pin categories (following legacy lines 1320-1353)
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        data_pins = self.cell.get_data_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Generate PWL based on condition pin type
                if pin_condition in clock_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in data_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    init_voltage = presim_target if presim_target is not None else self.V_LOW
                    if init_voltage == self.V_LOW:
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    else:
                        lines.append(f"+ 0 {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")
                
        return lines
    
    def _generate_default_main_conditions(self) -> List[str]:
        """Generate condition PWL when main pin doesn't match any specific type."""
        lines = []
        
        if not self._merged_conditions:
            return lines
            
        # Get input pins (following legacy lines 1355-1368)
        input_pins = self.cell.get_input_pins()
        
        # Process each input pin
        for pin_name in input_pins:
            # Skip the main pin
            if pin_name == self.arc.pin:
                continue
                
            # Check if this pin has a condition
            for pin_condition, pin_state in self._merged_conditions.items():                    
                pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW
                
                if pin_condition != pin_name:
                    continue
                # Simple constant value for default case
                lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                lines.append(f"+ 0 {pin_value:.4f})")
                lines.append("")
                
        return lines

    def _generate_basic_parameters(self) -> List[str]:
        """
        Generate basic timing parameters for hidden power simulation.

        Returns:
            List[str]: Basic parameter definitions
        """
        lines = []
        
        # Derived timing parameters
        lines.append(".param half_tran_tend=tran_tend/2")
        lines.append(".param quarter_tran_tend=tran_tend/4")
        lines.append(".param eighth_tran_tend=tran_tend/8")
        lines.append("")
        
        return lines

    def _generate_parameter_sweeps(self) -> List[str]:
        """
        Generate parameter sweeps for hidden power characterization.
        
        Uses delay_waveform to sweep through different input slew rates.
        Generates .alter statements for multiple simulation runs.
        
        Returns:
            List[str]: Parameter definitions and .alter statements
        """
        lines = []
        
        # Get main pin and transition direction
        main_pin = self.arc.pin
        output_edge = self.arc.pin_transition
        
        # Get waveform dimensions
        index_2 = self.delay_waveform.index_2
        values = self.delay_waveform.values
        
        # Determine voltage pattern based on transition direction
        if output_edge == TransitionDirection.RISE.value:
            volt = index_2
        else:
            volt = list(reversed(index_2))
            
        # Scale voltages
        volt = [v * self.V_HIGH for v in volt]
        
        # Convert time values to list format
        time_list = [list(map(float, row)) for row in values]
        
        # Generate parameter sets for each input slew rate
        first = True
        for index_1 in range(len(time_list)):
            if not first:
                lines.append(".alter")
            first = False
            
            # Generate voltage and time parameters for main pin
            for i, (v, t) in enumerate(zip(volt, time_list[index_1])):
                lines.append(f".param {main_pin}_t{i}={t}e-9")
                lines.append(f".param {main_pin}_v{i}={v}e+00")
            
            # Generate output capacitance parameters
            for pin_name in self.cell.get_output_pins():
                lines.append(f".param {pin_name}_cap=1.0000000e-20")
            
            # Add simulation time parameter
            lines.append(".param tran_tend=1.0000100e-08")
            
            if index_1 < len(time_list) - 1:
                lines.append("")
        
        return lines
