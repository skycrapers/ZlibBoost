"""
Delay SPICE deck generator for timing arcs.

Implements the SPICE deck generator used for delay/transition/power
characterization with parameter sweeps.
"""
from typing import List, Dict, Optional

from zlibboost.database.models.timing_arc import TableType, TransitionDirection
from zlibboost.simulation.polarity import resolve_output_pin
from zlibboost.core.logger import get_logger
from .base import BaseSpiceGenerator


class DelaySpiceGenerator(BaseSpiceGenerator):

    def __init__(self, arc, cell, library_db, sim_type=None):
        """
    Initialize DelaySpiceGenerator with specific parameters.

        Args:
            arc: TimingArc to generate a SPICE deck for.
            cell: Cell containing the arc.
            library_db: Library database with templates and waveforms.
            sim_type: Simulation type from factory (optional, defaults to 'delay').
        """
        # Call the base class constructor
        super().__init__(arc, cell, library_db, sim_type or 'delay')

    # Get the first delay Template class
        self.delay_template = self.library_db.get_templates_by_type('delay')[0]
        if not self.delay_template:
            raise ValueError(f"No delay template found for cell {self.cell.name}")

        # Get delay Waveform class
        self.delay_waveform = self.library_db.get_driver_waveform('delay_waveform')
        if not self.delay_waveform:
            raise ValueError(f"No delay waveform found for cell {self.cell.name}")

    # Get configuration thresholds
        self.delay_inp_rise = self.spice_params.get('delay_inp_rise')
        self.delay_inp_fall = self.spice_params.get('delay_inp_fall')
        self.delay_out_rise = self.spice_params.get('delay_out_rise')
        self.delay_out_fall = self.spice_params.get('delay_out_fall')
        self.measure_slew_lower_rise = self.spice_params.get('measure_slew_lower_rise')
        self.measure_slew_upper_rise = self.spice_params.get('measure_slew_upper_rise')
        self.measure_slew_lower_fall = self.spice_params.get('measure_slew_lower_fall')
        self.measure_slew_upper_fall = self.spice_params.get('measure_slew_upper_fall')
        
    # Input capacitance measurement thresholds
        self.measure_cap_lower_rise = self.spice_params.get('measure_cap_lower_rise')
        self.measure_cap_lower_fall = self.spice_params.get('measure_cap_lower_fall')
        self.measure_cap_upper_rise = self.spice_params.get('measure_cap_upper_rise')
        self.measure_cap_upper_fall = self.spice_params.get('measure_cap_upper_fall')

    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get file specifications for delay simulation.

        Delay type generates a single file containing all parameter sweeps
        with .alter statements for each combination.

        Returns:
            List[Dict[str, str]]: Single file specification with subdirectory path.
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
    Generate delay-specific SPICE body with parameter sweeping.

        Returns:
            str: SPICE body section for delay simulation.
        """
        lines = []

        # 1. Add delay measurement
        lines.extend(self._generate_delay_measurement())

        # 2. Add transition measurements
        lines.extend(self._generate_transition_measurements())

        # 3. Add PWL voltage sources
        lines.extend(self._generate_pwl_voltage_sources())

        # 4. Add load capacitance
        lines.extend(self._generate_output_capacitances())

        # 5. Add switching power measurement (includes ZlibBoostPower measurements)
        lines.extend(self._generate_switching_power_measurement())

        # 6. Add basic parameters definition
        lines.extend(self._generate_basic_parameters())

        # 7. Add input capacitance measurement
        lines.extend(self._generate_input_capacitance_measurement())

        # 8. Add simulation options
        lines.extend(self._generate_simulation_options())

        # 9. Add parameter sweeping
        sweep_blocks = self._generate_parameter_sweeps()
        if sweep_blocks:
            lines.extend(sweep_blocks)

        return "\n".join(lines)

    def _get_input_cap_measure_pins(self) -> List[str]:
        """Pins that should receive input capacitance measurements.

        For delay arcs, only measure capacitance on the related pin (clock).
        Data pin capacitance is NOT measured in delay arcs to avoid timing
        violations during pre-simulation. Data pin cap should be measured
        in hidden arcs instead (matching legacy behavior).
        """
        pins: List[str] = []
        if self.arc.related_pin and self.arc.related_pin not in pins:
            pins.append(self.arc.related_pin)
        # NOTE: Data pins are intentionally excluded from cap measurement
        # in delay arcs. Early pulses for cap measurement would conflict
        # with the pre-simulation clock edge (CP_t14), causing Q to be
        # incorrectly set. This matches legacy behavior.
        return pins

    @staticmethod
    def _sanitize_measure_label(pin_name: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in pin_name)

    def _logic_state_voltage(self, state: str) -> float:
        normalized = str(state).lower()
        return self.V_HIGH if normalized in {"1", "true", "high"} else self.V_LOW

    def _build_data_pin_measure_pwl(
        self,
        pin_name: str,
        final_voltage: float,
        pulse_index: int,
    ) -> List[str]:
        """Construct a brief pulse to excite data pins for capacitance measurement."""
        base = 1e-12
        spacing = 5e-12
        start = base + pulse_index * spacing
        high = self.V_HIGH
        low = self.V_LOW
        lines = [
            f"V{pin_name} {pin_name} 0 pwl(",
            f"+ 0 {low:.4f}",
            f"+ {start:.3e} {low:.4f}",
            f"+ {start + 1e-12:.3e} {high:.4f}",
            f"+ {start + 2e-12:.3e} {high:.4f}",
            f"+ {start + 3e-12:.3e} {low:.4f}",
            f"+ 'quarter_tran_tend' {final_voltage:.4f}",
            f"+ 'quarter_tran_tend+1e-12' {final_voltage:.4f})",
            "",
        ]
        return lines

    def _build_input_cap_measurement_block(self, pin: str) -> List[str]:
        """Generate measurement statements for a specific pin."""
        lines: List[str] = []
        is_related = pin == self.arc.related_pin

        rise_lower_v = round(self.measure_cap_lower_rise * self.V_HIGH, 6)
        rise_upper_v = round(self.measure_cap_upper_rise * self.V_HIGH, 6)
        fall_lower_v = round(self.measure_cap_lower_fall * self.V_HIGH, 6)
        fall_upper_v = round(self.measure_cap_upper_fall * self.V_HIGH, 6)
        rise_delta_v = round((self.measure_cap_upper_rise - self.measure_cap_lower_rise) * self.V_HIGH, 6)
        fall_delta_v = round((self.measure_cap_upper_fall - self.measure_cap_lower_fall) * self.V_HIGH, 6)

        if is_related:
            t1, t2, t3, t4 = "icap_t1", "icap_t2", "icap_t3", "icap_t4"
            cap1, cap2 = "ZlibBoostCap1", "ZlibBoostCap2"
            rise_name, fall_name = "risecap", "fallcap"
            rise_order = "rise=last"
            fall_order = "fall=last"
            direction = self.arc.related_transition or TransitionDirection.RISE.value
        else:
            label = self._sanitize_measure_label(pin)
            t1 = f"icap_{label}_t1"
            t2 = f"icap_{label}_t2"
            t3 = f"icap_{label}_t3"
            t4 = f"icap_{label}_t4"
            cap1 = f"ZlibBoostCap_{label}1"
            cap2 = f"ZlibBoostCap_{label}2"
            rise_name = f"inputrisecap_{pin}"
            fall_name = f"inputfallcap_{pin}"
            rise_order = "rise=1"
            fall_order = "fall=1"
            direction = TransitionDirection.RISE.value

        if direction == TransitionDirection.RISE.value:
            lines.append(f".meas tran {t1} WHEN V({pin}) = {rise_lower_v} {rise_order}")
            lines.append(f".meas tran {t2} WHEN V({pin}) = {rise_upper_v} {rise_order}")
            lines.append(f".meas tran {t3} WHEN V({pin}) = {fall_upper_v} {fall_order}")
            lines.append(f".meas tran {t4} WHEN V({pin}) = {fall_lower_v} {fall_order}")
            lines.append(f".meas tran {cap1} INTEG i(V{pin}) from='{t1}' to='{t2}'")
            lines.append(f".meas tran {cap2} INTEG i(V{pin}) from='{t3}' to='{t4}'")
            lines.append(f".meas tran {rise_name} PARAM='abs({cap1})/{rise_delta_v}'")
            lines.append(f".meas tran {fall_name} PARAM='abs({cap2})/{fall_delta_v}'\n")
        else:
            lines.append(f".meas tran {t1} WHEN V({pin}) = {fall_upper_v} {fall_order}")
            lines.append(f".meas tran {t2} WHEN V({pin}) = {fall_lower_v} {fall_order}")
            lines.append(f".meas tran {t3} WHEN V({pin}) = {rise_lower_v} {rise_order}")
            lines.append(f".meas tran {t4} WHEN V({pin}) = {rise_upper_v} {rise_order}")
            lines.append(f".meas tran {cap1} INTEG i(V{pin}) from='{t1}' to='{t2}'")
            lines.append(f".meas tran {cap2} INTEG i(V{pin}) from='{t3}' to='{t4}'")
            lines.append(f".meas tran {fall_name} PARAM='abs({cap1})/{fall_delta_v}'")
            lines.append(f".meas tran {rise_name} PARAM='abs({cap2})/{rise_delta_v}'\n")

        return lines

    def _generate_delay_measurement(self) -> List[str]:
        """
        Generate SPICE measurement command(s) for delay between input and output pins.

        This method constructs a `.meas tran` statement for measuring the propagation delay
        between the specified input and output pins of an arc, based on their transition directions
        (rise or fall). The voltage thresholds for triggering and targeting the measurement are
        calculated using predefined delay ratios and the high voltage level.

        Returns:
            List[str]: Generated SPICE measurement command(s).
        """

        lines = []

        # Get input and output pin names
        input_pin = self.arc.related_pin
        output_pin = self.arc.pin

        # Get transition directions for both input and output
        output_edge = self.arc.pin_transition
        input_edge = self.arc.related_transition

        # Determine threshold parameters based on transition directions
        if input_edge == TransitionDirection.RISE.value:
            delay_inp = self.delay_inp_rise
        else:
            delay_inp = self.delay_inp_fall
        if output_edge == TransitionDirection.RISE.value:
            delay_out = self.delay_out_rise
        else:
            delay_out = self.delay_out_fall

        # Calculate threshold voltage based on delay ratios, round to 6 decimal places
        delay_inp_voltage = round(delay_inp * self.V_HIGH, 6)
        delay_out_voltage = round(delay_out * self.V_HIGH, 6)

        lines.append(
            f".meas tran ZlibBoostDelay "
            f"trig v({input_pin}) val={delay_inp_voltage} {input_edge}=last "
            f"targ v({output_pin}) val={delay_out_voltage} {output_edge}=last\n"
        )

        return lines

    def _generate_transition_measurements(self) -> List[str]:
        """
        Generate SPICE deck measurement lines for input and output transition times.

        Determines the appropriate voltage thresholds for measuring transitions based on
        the arc's table type (rise or fall transition). Constructs SPICE .meas statements
        for both lower and upper voltage thresholds using the arc's pin and transition type.

        Raises:
            ValueError: If the arc's table type is unsupported.

        Returns:
            List[str]: SPICE deck lines for transition measurements.
        """
        lines = []

        # Determine voltage thresholds based on transition type, round to 6 decimal places
        # Treat cell_rise as rise-transition class and cell_fall as fall-transition class
        if self.arc.table_type in (TableType.RISE_TRANSITION.value, TableType.CELL_RISE.value):
            measure_slew_lower_voltage = round(self.measure_slew_lower_rise * self.V_HIGH, 6)
            measure_slew_upper_voltage = round(self.measure_slew_upper_rise * self.V_HIGH, 6)
        elif self.arc.table_type in (TableType.FALL_TRANSITION.value, TableType.CELL_FALL.value):
            measure_slew_lower_voltage = round(self.measure_slew_lower_fall * self.V_HIGH, 6)
            measure_slew_upper_voltage = round(self.measure_slew_upper_fall * self.V_HIGH, 6)
        else:
            # If table type is unrelated to transition (e.g., unexpected), skip transition measurements
            get_logger(__name__).debug(
                f"Skip transition measurements for table_type={self.arc.table_type} in delay generator"
            )
            return lines

        # Add input transition measurement
        lines.append(
            f".meas tran ZlibBoostTransition0 trig at=0 targ v({self.arc.pin}) "
            f"val={measure_slew_lower_voltage} {self.arc.pin_transition}=last"
        )
        lines.append(
            f".meas tran ZlibBoostTransition1 trig at=0 targ v({self.arc.pin}) "
            f"val={measure_slew_upper_voltage} {self.arc.pin_transition}=last\n"
        )

        return lines

    def _generate_pwl_voltage_sources(self) -> List[str]:
        """
        Generate Piecewise Linear (PWL) voltage source definitions for SPICE simulations,
        tailored for parameter sweeping and timing analysis.

        The method constructs SPICE deck lines for voltage sources based on the pin categories
        (e.g., reset, set, data, clock, scan enable, sync/async) and the simulation context.
        It applies special handling for different pin types, including input, condition, and clock pins,
        and generates appropriate PWL patterns using simulation parameters and waveform indices.

        Returns:
            List[str]: SPICE deck lines for PWL voltage sources.

        """
        lines = []

        # Get pin categories for special handling
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        data_pins = self.cell.get_data_pins()
        clock_positive_pins = self.cell.get_clock_positive_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        sync_pins = self.cell.get_sync_pins()
        async_pins = self.cell.get_async_pins()
        arc_output_polarity = resolve_output_pin(self.cell, self.arc.pin)
        arc_pin_is_negative = arc_output_polarity.is_negative if arc_output_polarity else False

        # Get t_count from waveform (number of time points - 1)
        t_count = len(self.delay_waveform.index_2) - 1

        # 1. Generate PWL voltage source for related pin
        related_pin = self.arc.related_pin
        lines.append(f"V{related_pin} {related_pin} 0  pwl(")
        # Check if related pin is reset or set pin - use different PWL pattern
        if related_pin in reset_pins or related_pin in set_pins:
            # For reset/set pins: simple fixed voltage pattern
            lines.append(f"+ 0 {self.V_LOW}")
            lines.append(f"+ 1e-12 {self.V_HIGH}")
        else:
            # For normal pins: parameter-based PWL pattern
            lines.append(f"+ '{related_pin}_t0' '{related_pin}_v0'")
            lines.append(f"+ '{related_pin}_t{t_count}' '{related_pin}_v{t_count}'")
            lines.append(f"+ 'eighth_tran_tend' '{related_pin}_v{t_count}'")
            lines.append(f"+ 'eighth_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v0'")
        # Write related voltage and time pairs from t0 to t_count
        for i in range(t_count):
            lines.append(f"+ 'half_tran_tend+{related_pin}_t{i}' '{related_pin}_v{i}'")
        lines.append(f"+ 'half_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v{t_count}')\n")

        # 2. Generate voltage sources for condition pins
        if hasattr(self.arc, 'condition_dict') and self.arc.condition_dict:
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_info = self.cell.pins.get(pin_condition)
                if pin_info and pin_info.direction == 'internal':
                    continue
                normalized_state = "1" if pin_state in {1, "1", True, "true", "TRUE", "high", "HIGH"} else "0"
                pin_value = self.V_HIGH if normalized_state == "1" else self.V_LOW
                table_type = self.arc.table_type
                if table_type == TableType.CELL_RISE.value:
                    effective_table_type = TableType.RISE_TRANSITION.value
                elif table_type == TableType.CELL_FALL.value:
                    effective_table_type = TableType.FALL_TRANSITION.value
                else:
                    effective_table_type = table_type
                if pin_condition in data_pins:
                    if pin_condition == related_pin:
                        # Data pin is being actively swept as the related pin.
                        if ((not arc_pin_is_negative and
                             effective_table_type == TableType.RISE_TRANSITION.value) or
                            (arc_pin_is_negative and
                             effective_table_type == TableType.FALL_TRANSITION.value)):
                            lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                            lines.append(f"+ 0 {self.V_LOW}")
                            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                            lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                            lines.append("")
                        elif ((not arc_pin_is_negative and
                               effective_table_type == TableType.FALL_TRANSITION.value) or
                              (arc_pin_is_negative and
                               effective_table_type == TableType.RISE_TRANSITION.value)):
                            lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                            lines.append(f"+ 0 {self.V_HIGH}")
                            lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                            lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                            lines.append("")
                        else:
                            raise ValueError(
                                f"Unsupported table_type {self.arc.table_type} for data pin {pin_condition} "
                                f"in cell: {self.cell.name}, arc table type: {self.arc.table_type}"
                            )
                    else:
                        # Data pin that is not the related pin (not being actively swept).
                        # Use legacy pattern: hold initial value until quarter_tran_tend,
                        # then transition to final value. No early pulse for cap measurement
                        # to avoid timing violations during pre-simulation.
                        # Determine initial value based on output transition type
                        if ((not arc_pin_is_negative and
                             effective_table_type == TableType.RISE_TRANSITION.value) or
                            (arc_pin_is_negative and
                             effective_table_type == TableType.FALL_TRANSITION.value)):
                            # Q rises: D should be low initially, then transition to final value
                            initial_value = self.V_LOW
                        else:
                            # Q falls: D should be high initially, then transition to final value
                            initial_value = self.V_HIGH
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {initial_value:.4f}")
                        lines.append(f"+ 'quarter_tran_tend' {initial_value:.4f}")
                        lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                        lines.append("")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Synchronous reset pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Synchronous set pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in reset_pins and pin_condition in async_pins:
                    # Asynchronous reset pin handling
                    if ((not arc_pin_is_negative and
                         effective_table_type == TableType.RISE_TRANSITION.value) or
                        (arc_pin_is_negative and
                         effective_table_type == TableType.FALL_TRANSITION.value)):
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                        lines.append("")
                    else:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {pin_value:.4f})")
                        lines.append("")
                elif pin_condition in set_pins and pin_condition in async_pins:
                    # Asynchronous set pin handling
                    if ((not arc_pin_is_negative and
                         effective_table_type == TableType.FALL_TRANSITION.value) or
                        (arc_pin_is_negative and
                         effective_table_type == TableType.RISE_TRANSITION.value)):
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                        lines.append("")
                    else:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {pin_value:.4f})")
                        lines.append("")
                elif pin_condition in clock_positive_pins:
                    # Legacy behaviour: always generate a pre-simulation clock pulse so
                    # sequential outputs reach a deterministic state before the measured edge.
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in clock_negative_pins:
                    # Legacy behaviour: always generate a pre-simulation clock pulse.
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value:.4f})")
                    lines.append("")
                elif pin_condition in scan_enable_pins:
                    # Scan enable pin handling - use quarter_tran_tend pattern
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                    lines.append("")
                else:
                    # Default condition pin handling - simple constant voltage
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value:.4f})")
                    lines.append("")

        # NOTE: Legacy delay simulation does NOT use .ic statements for output pins.
        # The pre-simulation clock edge (CP_t14 -> eighth_tran_tend) sets the initial
        # output state naturally through circuit behavior, so explicit .ic is not needed.

        return lines

    def _generate_switching_power_measurement(self) -> List[str]:
        """
        Generate switching power measurement including required ZlibBoostPower measurements.
        
        This method generates the complete switching power measurement sequence:
        1. ZlibBoostPower000 - VVSS current integration
        2. ZlibBoostPower001 - VVDD current integration  
        3. SwitchingPower - Final power calculation based on transition type
        
        The switching power calculation differs between rise and fall transitions:
        - Rise transition: includes capacitive energy term
        - Fall transition: only includes power supply term
        
        Returns:
            List[str]: Complete SPICE measurement commands for switching power analysis.
        """
        lines = []
        
        # Step 1: Add power supply current measurements
        lines.append(".meas tran ZlibBoostPower000 INTEG i(VVSS) from='half_tran_tend' to='tran_tend'")
        lines.append(".meas tran ZlibBoostPower001 INTEG i(VVDD) from='half_tran_tend' to='tran_tend'")
        
        # Step 2: Calculate switching power based on transition type
        # Count output pins for power averaging
        output_counter = len(self.cell.get_output_pins())
        
        # Get the output pin for this arc
        output_pin = self.arc.pin
        
        def _complement_output(pin_name: str, outputs: List[str]) -> Optional[str]:
            if pin_name.endswith("N") and pin_name[:-1] in outputs:
                return pin_name[:-1]
            candidate = f"{pin_name}N"
            return candidate if candidate in outputs else None

        # Liberate internal_power does not include energy used to charge output loads.
        # For sequential cells with complementary outputs (e.g. Q/QN), a "fall" on the
        # measured pin implies the complement rises and charges its load; subtract that
        # capacitive term so fall_power aligns with Liberate.
        rising_outputs: List[str] = []
        if self.arc.pin_transition == TransitionDirection.RISE.value:
            rising_outputs = [output_pin]
        elif self.arc.pin_transition == TransitionDirection.FALL.value:
            complement = _complement_output(output_pin, self.cell.get_output_pins())
            if complement:
                rising_outputs = [complement]

        cap_term = ""
        if rising_outputs:
            cap_sum = "+".join(f"{pin_name}_cap" for pin_name in rising_outputs)
            cap_term = f"-({cap_sum})*{self.V_HIGH}*{self.V_HIGH}"

        lines.append(
            f".meas tran SwitchingPower PARAM="
            f"'(-ZlibBoostPower001*{self.V_HIGH}{cap_term})/{output_counter}'\n"
        )
        
        return lines

    def _generate_basic_parameters(self) -> List[str]:
        """
    Generate basic timing and derived parameters for delay simulation.
        
        This method generates the core timing parameters that define the simulation 
        timeframe and derived parameters used throughout the delay measurement process.
        These parameters are based on the legacy SPICE generator implementation.
        
        The timing parameters include:
        - tran_tend: Total simulation time for delay measurements
        - half_tran_tend: Half the simulation time (used in power measurements)
        - quarter_tran_tend: Quarter simulation time (used in PWL voltage sources)
        - eighth_tran_tend: Eighth simulation time (used in clock transitions)
        
        Returns:
            List[str]: Basic parameter definitions including timing and derived parameters.
        """
        lines = []
        
        # Core timing parameter - use delay-specific value from legacy implementation
        lines.append(".param tran_tend=1.7664100e-8")
        
        # Derived timing parameters used in PWL sources, measurements, and power analysis
        lines.append(".param half_tran_tend=tran_tend/2")
        lines.append(".param quarter_tran_tend=tran_tend/4") 
        lines.append(".param eighth_tran_tend=tran_tend/8\n")
        
        return lines

    def _generate_input_capacitance_measurement(self) -> List[str]:
        """
    Generate input capacitance measurement commands for delay simulation.
        """
        pins = self._get_input_cap_measure_pins()
        if not pins:
            return []

        lines: List[str] = []
        for pin in pins:
            lines.extend(self._build_input_cap_measurement_block(pin))
        return lines

    def _generate_parameter_sweeps(self) -> List[str]:
        """
    Generate parameter sweeps for delay simulation.
        
        This method generates .alter statements to sweep through different parameter
        combinations based on the delay template and waveform configurations. Each
        parameter combination represents a different operating point for characterization.
        
        The sweeps include:
        - Input slew variations (from template index_1)
        - Load capacitance variations (from template index_2) 
        - PWL voltage source timing variations (from waveform values)
        
        The parameter sweeps follow the legacy pattern with proper .alter formatting
        to enable multi-point characterization in a single SPICE simulation.
        
        Returns:
            List[str]: Parameter sweep blocks with .alter statements.
        """
        sweep_blocks = []
        
        # Get template and waveform data for parameter sweeps
        template_index_1 = self.delay_template.index_1  # Input slew values
        template_index_2 = self.delay_template.index_2  # Load capacitance values
        waveform_values = self.delay_waveform.values    # PWL timing data
        
        # Get voltage levels based on transition direction
        voltage_levels = self.delay_waveform.index_2
        if self.arc.related_transition == TransitionDirection.FALL.value:
            voltage_levels = list(reversed(voltage_levels))
        
        # Scale voltage levels by supply voltage
        scaled_voltages = [round(v * self.V_HIGH, 6) for v in voltage_levels]
        
        # Convert waveform values to time lists for each input slew condition
        time_lists = []
        for row in waveform_values:
            if isinstance(row, str):
                time_values = [float(t) for t in row.split(", ")]
            else:
                time_values = list(row)
            time_lists.append(time_values)
        
        first_sweep = True
        
        # Generate parameter sweeps for each combination of input slew and load capacitance
        for index_1_idx, input_slew in enumerate(template_index_1):
            if index_1_idx < len(time_lists):
                time_values = time_lists[index_1_idx]
                
                for load_cap in template_index_2:
                    sweep_lines = []
                    
                    # Add .alter statement for all sweeps except the first
                    if not first_sweep:
                        sweep_lines.append("\n.alter")
                    first_sweep = False
                    
                    # Add PWL voltage source timing parameters
                    related_pin = self.arc.related_pin
                    for i, (voltage, time) in enumerate(zip(scaled_voltages, time_values)):
                        sweep_lines.append(f".param {related_pin}_t{i}={time}e-9")
                        sweep_lines.append(f".param {related_pin}_v{i}={voltage}e+00")
                    
                    # Add load capacitance parameters for output pins
                    output_pins = self.cell.get_output_pins()
                    for output_pin in output_pins:
                        sweep_lines.append(f".param {output_pin}_cap={load_cap}e-12")
                    
                    # Add timing parameter
                    sweep_lines.append(".param tran_tend=1.7664100e-8")
                    
                    # Add sweep block to output
                    sweep_blocks.append("\n".join(sweep_lines))
        
        return sweep_blocks
