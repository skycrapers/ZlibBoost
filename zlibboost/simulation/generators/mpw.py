"""
Minimum Pulse Width (MPW) constraint SPICE deck generator for timing arcs.

This module implements the SPICE deck generator for minimum pulse width constraint simulation.
MPW constraints ensure that clock or control signals maintain their active state for sufficient
time to guarantee proper circuit operation.

The implementation is based on pulse search methodology, where pulse width is gradually reduced
until the circuit fails to operate correctly, thereby determining the minimum viable pulse width.
"""

from typing import List, Dict

from zlibboost.database.models.timing_arc import TableType, TransitionDirection
from zlibboost.simulation.polarity import resolve_output_pin
from .base import BaseSpiceGenerator


class MpwSpiceGenerator(BaseSpiceGenerator):

    def __init__(self, arc, cell, library_db, sim_type=None):
        """
        Initialize MpwSpiceGenerator with timing arc, cell, and library database.

        Args:
            arc: TimingArc to generate SPICE deck for
            cell: Cell containing the arc
            library_db: Library database with templates and waveforms
            sim_type: Simulation type from factory (optional, defaults to 'mpw')
        """
        # Call base class initializer
        super().__init__(arc, cell, library_db, sim_type or 'mpw')

        raw_bound = library_db.get_spice_params().get('mpw_search_bound', 0.0)
        self.mpw_search_bound = float(raw_bound)
        self.mpw_search_bound_seconds = self._normalize_time(self.mpw_search_bound)

        # Store i1/i2 indices for parameter generation (can be set externally)
        self.i1 = 0
        self.i2 = 0

    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get file specifications for MPW constraint simulation.
        
        MPW type generates i1 dimension files (no i2), where each file
        tests a different pulse width scenario.
        
        Returns:
            List[Dict]: File specifications for all i1 values
        """
        files = []
        
        # Get constraint waveform for index values
        constraint_waveform = self.library_db.get_driver_waveform("constraint_waveform")
        index_1 = getattr(constraint_waveform, 'index_1', [])
        index_1_count = len(index_1) if index_1 else 1
        
        # Generate files for i1 dimension only
        for i1 in range(index_1_count):
            # Set current index
            self.i1 = i1
            
            # Build filename with i1 index
            base_filename = self._build_base_filename()
            filename = f"{base_filename}_i1_{i1}.sp"
            
            # Generate content for this i1 value
            content = self.generate_deck()
            
            files.append({
                'filename': filename,
                'content': content
            })
        
        return files

    def _generate_body(self) -> str:
        """
        Generate MPW constraint-specific SPICE body with pulse width testing.

        MPW testing uses a two-pulse methodology:
        1. First pulse: Reference with normal timing
        2. Second pulse: Test pulse with reduced width (mpw_search_bound adjustment)

        The circuit response is measured to determine if the reduced pulse width
        is sufficient for proper operation.

        Returns:
            SPICE body section for MPW constraint simulation
        """
        lines = []

        # 1. Add MPW measurement commands
        lines.extend(self._generate_delay_measurements())

        # 2. Add degradation measurement commands
        lines.extend(self._generate_degradation_measurements())

        # 3. Add related PWL
        lines.extend(self._generate_related_pwl())

        # 4. Add condition PWL
        lines.extend(self._generate_condition_pwl())

        # 5. Add basic parameters definition
        lines.extend(self._generate_basic_parameters())

        # 6. Add load capacitance
        lines.extend(self._generate_output_capacitances())

        # 7. Add simulation options
        lines.extend(self._generate_simulation_options())

        # 8. Add parameter sweeps for MPW characterization
        lines.extend(self._generate_parameter_sweeps(i1=self.i1))

        return "\n".join(lines)

    def _generate_delay_measurements(self) -> List[str]:
        """
        Generate a SPICE .meas statement to measure the propagation delay between two pins.

        This method inspects the arc's transition directions and constructs a single
        transient measurement string (named "ZlibBoostDelay") that captures the time
        difference between two threshold crossings. The voltage threshold used for the
        measurement is V_HIGH * 0.5 (typically VDD/2). The exact trigger/target pins
        and whether the measurement uses rising or falling threshold crossings depend
        on the output transition direction.

        Returns:
            List[str]: A list containing the generated .meas tran statement string.
        """
        lines = []

        # Get transition directions for both input and output
        output_edge = self.arc.pin_transition

        # Voltage threshold for measurements (typically VDD/2)
        threshold = self.V_HIGH * 0.5

        if output_edge == TransitionDirection.RISE.value:
            # For rising edge output: measure high pulse width (rise->fall)
            lines.append(f".meas tran ZlibBoostDelay trig v({self.arc.pin}) val={threshold} "
                         f"rise=last TD=half_tran_tend targ v({self.arc.related_pin}) val={threshold} "
                         f"fall=last TD=half_tran_tend")
        else:
            # For falling edge output: measure low pulse width (fall->rise)
            lines.append(f".meas tran ZlibBoostDelay trig v({self.arc.related_pin}) val={threshold} "
                         f"fall=last TD=half_tran_tend targ v({self.arc.pin}) val={threshold} "
                         f"rise=last TD=half_tran_tend")
        lines.append("")
        return lines

    def _infer_pin_states(self) -> Dict[str, bool]:
        """Infer logical states for pins using known conditions and logic functions.

        Returns:
            Dict[str, bool]: Mapping of pin names to inferred logical states (True for '1').
        """
        assignments: Dict[str, bool] = {}

        # Seed assignments with explicit condition bits
        for pin_name, pin_state in self.arc.condition_dict.items():
            if pin_state == '1':
                assignments[pin_name] = True
            elif pin_state == '0':
                assignments[pin_name] = False

        # Iteratively resolve pins that have logic functions and known dependencies
        resolved = True
        while resolved:
            resolved = False
            known_keys = set(assignments.keys())
            for pin_name, pin_info in self.cell.pins.items():
                if pin_name in assignments:
                    continue

                analyzer = getattr(pin_info, 'function', None)
                if analyzer is None:
                    continue

                variables = analyzer.get_variables()
                if variables and not variables.issubset(known_keys):
                    continue

                try:
                    result = analyzer.evaluate(assignments)
                except Exception:
                    continue

                assignments[pin_name] = bool(result)
                resolved = True

        return assignments

    def _generate_degradation_measurements(self) -> List[str]:
        """
        Generate SPICE .meas statements to measure signal degradation over time.

        This method constructs a series of transient measurement strings that capture
        the voltage levels at specific time intervals, allowing for analysis of signal
        integrity and degradation.

        Returns:
            List[str]: A list containing the generated .meas tran statement strings.
        """
        lines = []

        output_conditions = []
        for pin_condition, pin_state in self.arc.condition_dict.items():
            polarity = resolve_output_pin(self.cell, pin_condition)
            if polarity:
                output_conditions.append((polarity, pin_state))

        if not output_conditions:
            metadata_outputs = (self.arc.metadata or {}).get("expected_outputs") or {}
            for pin_name, logical_state in metadata_outputs.items():
                polarity = resolve_output_pin(self.cell, pin_name)
                if polarity and logical_state in {"0", "1"}:
                    output_conditions.append((polarity, logical_state))

        if not output_conditions:
            inferred_states: Dict[str, bool] = {}
            try:
                inferred_states = self._infer_pin_states()
            except Exception:  # pragma: no cover - defensive fallback
                inferred_states = {}

            preferred_outputs = self.cell.get_outpositive_pins() or self.cell.get_output_pins()

            for pin_name in preferred_outputs:
                if pin_name not in inferred_states:
                    continue

                polarity = resolve_output_pin(self.cell, pin_name)
                if not polarity:
                    continue

                pin_state = '1' if inferred_states[pin_name] else '0'
                output_conditions.append((polarity, pin_state))
                break

        if not output_conditions:
            return lines
        # Use the primary output only to avoid duplicate measurement names
        output_conditions = [output_conditions[0]]

        # Get main pin name
        main_pin = self.arc.pin

        # Voltage threshold for measurements (typically VDD/2)
        threshold = self.V_HIGH * 0.5
        pin_info = self.cell.pins.get(main_pin)
        trigger_edge = "fall" if getattr(pin_info, "is_negative", False) else "rise"

        for polarity, pin_state in output_conditions:
            target_pin = polarity.name

            expects_high = polarity.expects_high(pin_state)
            if polarity.is_negative:
                high_edge = "fall"
                low_edge = "rise"
            else:
                high_edge = "rise"
                low_edge = "fall"
            target_edge = low_edge if expects_high else high_edge

            self.q_value = polarity.logical_to_voltage(
                pin_state, self.V_HIGH, self.V_LOW
            )

            lines.append(
                f".meas tran DegradeDelay trig v({main_pin}) val={threshold} "
                f"{trigger_edge}=last TD=half_tran_tend "
                f"targ v({target_pin}) val={threshold} {target_edge}=last TD=half_tran_tend"
            )
            lines.append(
                f".meas tran HalfTranQ FIND v({target_pin}) AT=half_tran_tend"
            )
            if target_edge == "fall":
                lines.append(
                    f".meas tran glitch_peak_rise MAX v({target_pin}) "
                    f"FROM=half_tran_tend TO=tran_tend"
                )
            else:
                lines.append(
                    f".meas tran glitch_peak_fall MIN v({target_pin}) "
                    f"FROM=half_tran_tend TO=tran_tend"
                )

        if lines:
            lines.append("")
        return lines

    def _generate_related_pwl(self) -> List[str]:
        """
        Generate PWL (Piecewise Linear) source definitions for the related pin.

        This method creates PWL voltage sources for the related pin based on the
        arc's transition direction and the cell's clock, set, reset, and async pins.

        Returns:
            List[str]: A list containing the generated PWL source definition strings.
        """
        lines = []

        # Get pin name
        related_pin = self.arc.related_pin

        lines.append(f"V{related_pin} {related_pin} 0 pwl(")

        if related_pin in self.cell.get_clock_pins():
            # Related pin is clock pin
            lines.append(f"+ '{related_pin}_t0' '{related_pin}_v0'")
            lines.append(f"+ '{related_pin}_t1' '{related_pin}_v1'")
            if related_pin == self.arc.pin:
                lines.append(f"+ 'eighth_tran_tend' '{related_pin}_v1'")
                lines.append(
                    f"+ 'eighth_tran_tend+{related_pin}_t1' '{related_pin}_v0'"
                )
        elif related_pin in self.cell.get_reset_pins() and hasattr(self, 'q_value') and self.q_value == self.V_LOW:
            # Related pin is reset pin and Q value is low
            lines.append(f"+ '{related_pin}_t0' {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
        elif related_pin in self.cell.get_set_pins() and hasattr(self, 'q_value') and self.q_value == self.V_HIGH:
            # Related pin is set pin and Q value is high
            lines.append(f"+ '{related_pin}_t0' {self.V_LOW}")
            lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")

        # Add other half transition points
        lines.append(f"+ 'half_tran_tend+{related_pin}_t0' '{related_pin}_v0'")
        lines.append(f"+ 'half_tran_tend+{related_pin}_t1' '{related_pin}_v1'")
        lines.append(f"+ 'half_tran_tend+{related_pin}_t2' '{related_pin}_v2'")
        lines.append(
            f"+ 'half_tran_tend+{related_pin}_t3' '{related_pin}_v3')")
        lines.append("")
        return lines

    def _generate_condition_pwl(self) -> List[str]:
        """
        Generate PWL (Piecewise Linear) source definitions for condition pins.

        This method creates voltage sources for all condition pins based on their types
        and the expected output value (q_value). The PWL patterns vary depending on:
        - Pin type (data, clock, reset, set, scan_enable, scan_in, enable)
        - Pin synchronization (sync vs async)
        - Expected output value (V_HIGH vs V_LOW)

        The timing patterns use predefined time intervals:
        - quarter_tran_tend: 1/4 of transition time
        - eighth_tran_tend: 1/8 of transition time
        - Small delta (1e-12): For instantaneous transitions

        Returns:
            List[str]: PWL source definitions for all condition pins
        """
        lines = []
        q_value = getattr(self, 'q_value', self.V_LOW)

        # Get pin categories for condition logic
        data_pins = self.cell.get_data_pins()
        clock_pins = self.cell.get_clock_pins()
        clock_negative_pins = self.cell.get_clock_negative_pins()
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        sync_pins = self.cell.get_sync_pins()
        async_pins = self.cell.get_async_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        scan_in_pins = self.cell.get_scan_in_pins()
        enable_pins = self.cell.get_enable_pins()

        # Generate PWL sources for each condition pin
        for pin_condition, pin_state in self.arc.condition_dict.items():
            # MPW condition sources should skip output pins (Q/QN) to avoid
            # generating redundant or conflicting PWL definitions.
            if resolve_output_pin(self.cell, pin_condition):
                continue
            # Avoid duplicating stimulus for the primary clock/related pin
            if pin_condition in {self.arc.pin, self.arc.related_pin}:
                continue
            pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW

            # Start building PWL source
            lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")

            # Generate PWL based on output value (q_value) and pin type
            if pin_condition in data_pins:
                # Data pins preload the expected Q value, then settle to the condition.
                #
                # NOTE (latch MPW):
                # For latch enable MPW arcs, the enable pin can start in the
                # *transparent* state (e.g. active-high enable with a low pulse).
                # In that case, switching data during quarter_tran_tend would
                # propagate through the latch before the measured opening edge,
                # producing a negative/NaN DegradeDelay and preventing MPW
                # optimization from finding a reference. Instead, switch data
                # only after the enable has closed (half_tran_tend+<EN>_t1).
                start_value = self.V_HIGH if q_value == self.V_HIGH else self.V_LOW
                lines.append(f"+ 0 {start_value:.4f}")

                latch_en = self.arc.pin if self.arc.pin in enable_pins else None
                if self.cell.is_latch and latch_en:
                    en_info = self.cell.pins.get(latch_en)
                    open_when_high = not bool(getattr(en_info, "is_negative", False))
                    starts_high = self.arc.pin_transition == TransitionDirection.FALL.value
                    starts_open = starts_high if open_when_high else not starts_high

                    if starts_open:
                        # Wait until the enable's closing edge completes (t1),
                        # then switch data while the latch is opaque.
                        lines.append(
                            f"+ 'half_tran_tend+{latch_en}_t1' {start_value:.4f}"
                        )
                        lines.append(
                            f"+ 'half_tran_tend+{latch_en}_t1+1e-12' {pin_value:.4f})"
                        )
                        lines.append("")
                        continue

                lines.append(f"+ 'quarter_tran_tend' {start_value:.4f}")
                lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")
                lines.append("")
                continue

            if q_value == self.V_HIGH:
                # When expected output is HIGH
                if pin_condition in clock_pins:
                    # Clock pins: Start LOW, rise at eighth_tran_tend, then switch at quarter
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in clock_negative_pins:
                    # Negative clock pins: Start HIGH, fall at eighth_tran_tend, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Synchronous reset pins: Hold HIGH until quarter, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Synchronous set pins: Hold HIGH until quarter, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in set_pins and pin_condition in async_pins:
                    # Asynchronous set pins: Hold LOW until quarter, then switch
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in reset_pins and pin_condition in async_pins:
                    # Asynchronous reset pins: Constant value (no switching)
                    lines.append(f"+ 0 {pin_value:.4f})")

                elif pin_condition in scan_enable_pins:
                    # Scan enable pins: Hold LOW until quarter, then switch
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in scan_in_pins or pin_condition in enable_pins:
                    # Scan input and enable pins: Constant value
                    lines.append(f"+ 0 {pin_value:.4f})")

            elif q_value == self.V_LOW:
                # When expected output is LOW
                if pin_condition in data_pins:
                    # Data pins: Start LOW, hold until quarter_tran_tend, then switch
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in clock_pins:
                    # Clock pins: Start LOW, rise at eighth_tran_tend, then switch at quarter
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in clock_negative_pins:
                    # Negative clock pins: Start HIGH, fall at eighth_tran_tend, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'eighth_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Synchronous reset pins: Hold HIGH until quarter, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Synchronous set pins: Hold HIGH until quarter, then switch
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in reset_pins and pin_condition in async_pins:
                    # Asynchronous reset pins: Hold LOW until quarter, then switch
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in set_pins and pin_condition in async_pins:
                    # Asynchronous set pins: Constant value (no switching)
                    lines.append(f"+ 0 {pin_value:.4f})")

                elif pin_condition in scan_enable_pins:
                    # Scan enable pins: Hold LOW until quarter, then switch
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(
                        f"+ 'quarter_tran_tend+1e-12' {pin_value:.4f})")

                elif pin_condition in scan_in_pins or pin_condition in enable_pins:
                    # Scan input and enable pins: Constant value
                    lines.append(f"+ 0 {pin_value:.4f})")

            lines.append("")

        return lines

    def _generate_basic_parameters(self) -> List[str]:
        """
        Generate basic timing parameters for MPW constraint simulation.

        Returns:
            List[str]: Basic parameter definitions for MPW constraint simulation
        """
        lines = []

        # Derived timing parameters
        lines.append(".param half_tran_tend=tran_tend/2")
        lines.append(".param quarter_tran_tend=tran_tend/4")
        lines.append(".param eighth_tran_tend=tran_tend/8\n")

        return lines

    def _generate_parameter_sweeps(self, i1: int = 0) -> List[str]:
        """
        Generate parameter sweeps for MPW constraint characterization.
        
        MPW testing uses a special parameter sweep approach:
        1. Sweeps through different input slew rates (constraint_waveform index_1)
        2. Adjusts pulse width using mpw_search_bound parameter
        3. Generates voltage and timing parameters for PWL sources
        
        The mpw_search_bound parameter is used to reduce the pulse width in the
        second pulse to find the minimum viable pulse width.
        
        Args:
            i1: Index for constraint waveform index_1 (input slew rate)
            
        Returns:
            List[str]: Parameter definitions for the specified sweep point
        """
        lines = []
        
        # Get constraint waveform class for MPW testing
        constraint_waveform = self.library_db.get_driver_waveform("constraint_waveform")
        if not constraint_waveform:
            raise ValueError(f"No delay waveform found for cell {self.cell.name}")
            
        # Get index_1 (input slew rates) from constraint waveform
        index_1 = constraint_waveform.index_1
        
        # Determine voltage levels based on transition direction
        if self.arc.pin_transition == TransitionDirection.RISE.value:
            volt_index = [0, 1, 1, 0]  # Rise transition pattern
        else:
            volt_index = [1, 0, 0, 1]  # Fall transition pattern
            
        # Scale voltage levels by supply voltage
        volt_index = [v * self.V_HIGH for v in volt_index]
        
        # Generate time values with mpw_search_bound adjustment
        # Time pattern: [0, slew/0.8, mpw_bound, mpw_bound + slew/0.8]
        if i1 < len(index_1):
            slew_time_raw = float(index_1[i1])
            slew_time = self._normalize_time(slew_time_raw)
            time_values = [
                0.0,
                slew_time / 0.8,
                self.mpw_search_bound_seconds,
                self.mpw_search_bound_seconds + slew_time / 0.8,
            ]

            pin = self.arc.pin
            for idx, (voltage, time_seconds) in enumerate(zip(volt_index, time_values)):
                lines.append(f".param {pin}_t{idx}={time_seconds:.12g}")
                lines.append(f".param {pin}_v{idx}={voltage}e+00")
                
        # Add output capacitance parameters
        for output_pin in self.cell.get_output_pins():
            lines.append(f".param {output_pin}_cap=1.5000000e-16")
            
        # Add simulation time parameter
        lines.append(".param tran_tend=1.7664100e-8\n")
        
        return lines

    @staticmethod
    def _normalize_time(value: float) -> float:
        numeric = float(value)
        if abs(numeric) <= 1e-18:
            return 0.0
        if abs(numeric) > 1e-6:
            return numeric * 1e-9
        return numeric
