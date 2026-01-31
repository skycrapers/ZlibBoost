"""
Leakage power SPICE deck generator.

Implements the SPICE deck generator for leakage power simulation, which is the
simplest characterization type focused on static conditions.
"""

from typing import List, Dict
from .base import BaseSpiceGenerator
from zlibboost.database.models.cell import PinCategory


class LeakageSpiceGenerator(BaseSpiceGenerator):
    """
    SPICE generator for leakage power simulation.

    Measures static power consumption of a cell in different logic states.
    """
    
    def __init__(self, arc, cell, library_db, sim_type=None):
        """
        Initialize LeakageSpiceGenerator.

        Args:
            arc: TimingArc to generate a SPICE deck for.
            cell: Cell containing the arc.
            library_db: Library database with templates and waveforms.
            sim_type: Simulation type from factory (optional, defaults to 'leakage').
        """
        super().__init__(arc, cell, library_db, sim_type or 'leakage')

    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get file specifications for leakage simulation.

        Leakage type generates a single file for static power measurement.

        Returns:
            List[Dict[str, str]]: Single file specification with subdirectory path.
        """
        # Build filename using base method
        filename = f"{self._build_base_filename()}.sp"
        
        # Generate complete deck content
        content = self.generate_deck()
        
        return [{
            'filename': filename,
            'content': content
        }]

    def _generate_body(self) -> str:
        """
        Generate leakage-specific SPICE body.

        Returns:
            str: SPICE body section for leakage simulation.
        """
        lines = []

        # Generate measurement statements
        lines.extend(self._generate_leakage_measurements())
        lines.append("")

        # Generate voltage sources for condition pins
        lines.extend(self._generate_condition_voltage_sources())
        lines.append("")

        # Generate load capacitances (minimal for leakage)
        lines.extend(self._generate_leakage_capacitances())
        lines.append("")

        # Generate timing parameters
        lines.extend(self._generate_leakage_timing_params())
        lines.append("")

        # Generate simulator options
        lines.append(self._write_leakage_options())

        return '\n'.join(lines)

    def _generate_leakage_measurements(self) -> List[str]:
        """
        Generate leakage current measurement statements.

        Returns:
            List[str]: Measurement statements.
        """
        lines = []

        # Measure supply currents
        lines.append(".meas tran ZlibBoostLeakage000 FIND i(VVSS) AT=tran_tend")
        lines.append(".meas tran ZlibBoostLeakage001 FIND i(VVDD) AT=tran_tend")

        # Measure input pin currents
        leakage_counter = 2
        for pin_name in self.cell.get_input_pins():
            lines.append(
                f".meas tran ZlibBoostLeakage{leakage_counter:03} FIND i(V{pin_name}) AT=tran_tend")
            leakage_counter += 1

        # Calculate total leakage current and power
        if leakage_counter > 2:
            total_leakage_expr = ' + '.join([
                f'abs(ZlibBoostLeakage{num:03})'
                for num in range(1, leakage_counter)
            ])
            lines.append(f".meas tran TotalLeakageCurrent PARAM='{total_leakage_expr}'")
            lines.append(f".meas tran LeakagePower PARAM='TotalLeakageCurrent*{self.V_HIGH}'")

        return lines

    def _generate_condition_voltage_sources(self) -> List[str]:
        """
        Generate voltage sources for condition pins based on logic state.

        Returns:
            List[str]: Voltage source statements.
        """
        lines = []

        # Determine output state for complex logic
        q_value = self._determine_output_state()

        # Generate voltage sources for each input pin
        input_conditions = getattr(self, "_input_conditions", {})
        output_conditions = getattr(self, "_output_conditions", {})

        for pin_name in self.cell.get_input_pins():
            pin_info = self.cell.pins[pin_name]

            # Get pin value from condition or use default
            if pin_name in input_conditions:
                pin_value_char = input_conditions[pin_name]
                pin_value = self.V_HIGH if pin_value_char == '1' else self.V_LOW
            else:
                # Default state for pins not in condition
                pin_value = self.V_LOW

            # Generate PWL based on pin type
            if pin_info.is_clock():
                lines.append(self._generate_clock_leakage_pwl(pin_name, pin_value))
            elif pin_info.is_data():
                lines.append(self._generate_data_leakage_pwl(pin_name, pin_value, q_value))
            elif pin_info.is_reset() and pin_info.has_category(PinCategory.SYNC):
                lines.append(self._generate_sync_control_leakage_pwl(pin_name, pin_value))
            elif pin_info.is_set() and pin_info.has_category(PinCategory.SYNC):
                lines.append(self._generate_sync_control_leakage_pwl(pin_name, pin_value))
            elif pin_info.is_reset() and pin_info.has_category(PinCategory.ASYNC):
                lines.append(self._generate_async_control_leakage_pwl(pin_name, pin_value))
            elif pin_info.is_set() and pin_info.has_category(PinCategory.ASYNC):
                lines.append(self._generate_async_control_leakage_pwl(pin_name, pin_value))
            elif pin_info.has_category(PinCategory.SCAN_ENABLE):
                lines.append(self._generate_scan_enable_leakage_pwl(pin_name, pin_value))
            elif pin_info.has_category(PinCategory.ENABLE):
                lines.append(self._generate_enable_leakage_pwl(pin_name, pin_value))
            else:
                # Default case
                lines.append(f"V{pin_name} {pin_name} 0 {pin_value:.4f}")

        return lines

    def _determine_output_state(self) -> float:
        """
        Determine expected output state from condition.

        Returns:
            float: Expected output voltage level.
        """
        # Look for output pins in condition to determine expected state
        for pin_name, pin_value in getattr(self, "_output_conditions", {}).items():
            if pin_name not in self.cell.pins:
                continue
            pin_info = self.cell.pins[pin_name]
            if pin_info.is_negative:
                return self.V_LOW if pin_value == '1' else self.V_HIGH
            return self.V_HIGH if pin_value == '1' else self.V_LOW

        # Default state
        return self.V_LOW

    def _generate_clock_leakage_pwl(self, pin_name: str, final_value: float) -> str:
        """Generate PWL for clock pins in leakage simulation."""
        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {self.V_LOW}\n"
                f"+ 1e-11 {self.V_HIGH}\n"
                f"+ 1e-9 {self.V_HIGH}\n"
                f"+ 1.1e-9 {final_value:.4f})")

    def _generate_data_leakage_pwl(self, pin_name: str, final_value: float, q_value: float) -> str:
        """Generate PWL for data pins in leakage simulation."""
        if q_value == self.V_HIGH:
            initial_value = self.V_HIGH
        else:
            initial_value = self.V_LOW

        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {initial_value}\n"
                f"+ 'change_tend' {initial_value}\n"
                f"+ 'change_tend+1e-12' {final_value:.4f})")

    def _generate_sync_control_leakage_pwl(self, pin_name: str, final_value: float) -> str:
        """Generate PWL for synchronous control pins in leakage simulation."""
        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {self.V_HIGH}\n"
                f"+ 'change_tend' {self.V_HIGH}\n"
                f"+ 'change_tend+1e-12' {final_value:.4f})")

    def _generate_async_control_leakage_pwl(self, pin_name: str, final_value: float) -> str:
        """Generate PWL for asynchronous control pins in leakage simulation."""
        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {self.V_HIGH}\n"
                f"+ 'change_tend' {self.V_HIGH}\n"
                f"+ 'change_tend+1e-12' {final_value:.4f})")

    def _generate_scan_enable_leakage_pwl(self, pin_name: str, final_value: float) -> str:
        """Generate PWL for scan enable pins in leakage simulation."""
        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {self.V_LOW}\n"
                f"+ 'change_tend' {self.V_LOW}\n"
                f"+ 'change_tend+1e-12' {final_value:.4f})")

    def _generate_enable_leakage_pwl(self, pin_name: str, final_value: float) -> str:
        """Generate PWL for enable pins in leakage simulation."""
        return (f"V{pin_name} {pin_name} 0 pwl(\n"
                f"+ 0 {self.V_HIGH}\n"
                f"+ 'change_tend' {self.V_HIGH}\n"
                f"+ 'change_tend+1e-12' {final_value:.4f})")

    def _generate_leakage_capacitances(self) -> List[str]:
        """
        Generate minimal load capacitances for leakage simulation.

        Returns:
            List[str]: Capacitance statements.
        """
        lines = []
        cap_counter = 0

        for pin_name in self.cell.get_output_pins():
            lines.append(f".param {pin_name}_cap=1.0000000e-20")
            lines.append(f"C{cap_counter:02}_0 {pin_name} 0 '{pin_name}_cap'")
            cap_counter += 1

        return lines

    def _generate_leakage_timing_params(self) -> List[str]:
        """
        Generate timing parameters for leakage simulation.

        Returns:
            List[str]: Parameter statements.
        """
        simulator = self.spice_params.get('spice_simulator', 'spectre').lower()
        if simulator == 'ngspice':
            options = [
                ".param change_tend=1.000000e-08",
                ".param tran_tend=1.000000e-07"
            ]
        else:            
            options = [
                ".param change_tend=1.000000e-08",
                ".param tran_tend=1.000000e-04"
            ]
        return options

    def _write_leakage_options(self) -> str:
        """
        Generate leakage-specific simulator options.

        Returns:
            str: Simulator options for leakage simulation.
        """
        simulator = self.spice_params.get('spice_simulator', 'spectre').lower()

        if simulator == 'hspice':
            options = (".option MEASFILE=1 nomod numdgt=6 measdgt=6 ingold=2 "
                       "method=gear gmin=1e-15 gminfloatdefault=gmindc "
                       "redefinedparams=ignore rabsshort=1m limit=delta save=nooutput\n"
                       ".tran 1.00e-12 'tran_tend' lteratio=10 ckptperiod=1800")
        else:
            options = (".option nomod numdgt=6 measdgt=6 ingold=2 measout=0 "
                       "method=gear gmin=1e-15 gminfloatdefault=gmindc "
                       "redefinedparams=ignore rabsshort=1m limit=delta save=nooutput\n"
                       ".tran 1.00e-12 'tran_tend' lteratio=10 ckptperiod=1800 skipdc=useprevic")

        return options
