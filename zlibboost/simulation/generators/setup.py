"""
Setup/hold/recovery/removal constraint SPICE deck generator.

Implements the SPICE deck generator for setup-like constraint simulations where
data must meet timing relative to a clock or control edge.
"""
from typing import List, Dict

from zlibboost.database.models.timing_arc import TransitionDirection
from zlibboost.simulation.polarity import resolve_output_pin
from .base import BaseSpiceGenerator


class SetupSpiceGenerator(BaseSpiceGenerator):

    def __init__(self, arc, cell, library_db, sim_type=None):
        """
        Initialize SetupSpiceGenerator with specific parameters.

        Args:
            arc: TimingArc to generate a SPICE deck for.
            cell: Cell containing the arc.
            library_db: Library database with templates and waveforms.
            sim_type: Simulation type from factory (optional).
        """
        # Call the base class constructor
        super().__init__(arc, cell, library_db, sim_type or 'setup')

        # # Get constraint Waveform class for parameter generation
        self.constraint_waveform = self.library_db.get_driver_waveform('constraint_waveform')
        if not self.constraint_waveform:
            raise ValueError(f"No constraint waveform found for cell {self.cell.name}")
        
        # Store i1/i2 indices for parameter generation (can be set externally)
        self.i1 = 0
        self.i2 = 0

    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get file specifications for setup/hold/recovery/removal constraints.

        Constraint types generate i1×i2 matrix files, where each combination
        represents a different timing relationship between data and clock pins.

        Returns:
            List[Dict[str, str]]: File specs for all i1×i2 combinations.
        """
        files = []
        
        # Get index range from constraint waveform
        index_1 = getattr(self.constraint_waveform, 'index_1', [])
        index_1_count = len(index_1) if index_1 else 1
        
        # Generate i1×i2 matrix of files
        for i1 in range(index_1_count):
            for i2 in range(index_1_count):
                # Set current indices for generate_deck
                self.i1 = i1
                self.i2 = i2
                
                # Build filename with indices
                base_filename = self._build_base_filename()
                filename = f"{base_filename}_i1_{i1}_i2_{i2}.sp"
                
                # Generate content for this i1/i2 combination
                content = self.generate_deck()
                
                files.append({
                    'filename': filename,
                    'content': content
                })
        
        return files

    def set_indices(self, i1: int, i2: int) -> None:
        """
        Set i1/i2 indices used for constraint waveform parameter selection.

        Validates indices against the constraint waveform's index_1 size to
        mirror legacy behavior where each (i1, i2) pair represents a distinct
        timing relationship.

        Args:
            i1: Index for the main (data) pin timing row.
            i2: Index for the related (clock) pin timing row.

        Raises:
            ValueError: If either index is out of range.
        """
        index_1_count = len(self.constraint_waveform.index_1)
        if i1 < 0 or i2 < 0 or i1 >= index_1_count or i2 >= index_1_count:
            raise ValueError(f"Invalid indices: i1={i1}, i2={i2}. Max index is {index_1_count-1}")
        self.i1 = i1
        self.i2 = i2

    def _generate_body(self) -> str:
        """
        Generate setup constraint-specific SPICE body with parameter sweeping.

        Setup constraints require multiple simulations across different timing relationships
        between data and clock pins. Each combination of i1 and i2 indices represents
        different timing relationships to characterize the setup requirement.

        Returns:
            str: SPICE body section for setup constraint simulation with parameter sweeping.
        """
        lines = []

        # 1. Add setup delay measurement
        lines.extend(self._generate_delay_measurement())

        # 2. Add degradation measurement for output analysis
        lines.extend(self._generate_degradation_measurement())

        # # 3. Add PWL for related pins
        lines.extend(self._generate_related_pwl())

        # # 4. Add condition pin Piecewise Linear Voltage Source
        lines.extend(self._generate_condition_pwl())

        # 5. Add basic parameters definition
        lines.extend(self._generate_basic_parameters())

        # 6. Add load capacitance
        lines.extend(self._generate_output_capacitances())

        # 7. Add simulation options
        lines.extend(self._generate_simulation_options())

        # 8. Add parameter sweeping for i1 and i2 combinations
        lines.extend(self._generate_parameter_sweeps(self.i1, self.i2))

        return "\n".join(lines)

    def _generate_delay_measurement(self) -> List[str]:
        """
        Generate SPICE measurement command for setup delay analysis.

        For setup constraints, we measure the time difference between data pin transition
        and clock pin transition. The measurement direction (trigger vs target) depends on
        the timing type:
        - setup/non_seq_setup/recovery: data pin triggers, related pin targets
        - hold/non_seq_hold/removal: related pin triggers, data pin targets

        Returns:
            List[str]: SPICE measurement commands for setup constraint.
        """
        lines = []

        # Get input and output pin names
        related_pin = self.arc.related_pin
        main_pin = self.arc.pin

        # Get transition directions for both input and output
        output_edge = self.arc.pin_transition
        input_edge = self.arc.related_transition

        # Determine measurement direction based on timing type (matches legacy logic)
        timing_type = self.arc.timing_type.lower()

        # Threshold voltage selection: match legacy removal measurement which uses
        # a lower threshold to avoid slew-dominated offsets.
        threshold_ratio = 0.1 if "removal" in timing_type else 0.5
        threshold_voltage = round(threshold_ratio * self.V_HIGH, 6)
        
        if 'setup' in timing_type or 'recovery' in timing_type:
            # Setup/recovery: data pin triggers, related pin targets
            lines.append(
                f".meas tran ZlibBoostDelay "
                f"trig v({main_pin}) val={threshold_voltage} {output_edge}=last "
                f"targ v({related_pin}) val={threshold_voltage} {input_edge}=last\n"
            )
        elif 'hold' in timing_type or 'removal' in timing_type:
            # Hold/removal: related pin triggers, data pin targets
            lines.append(
                f".meas tran ZlibBoostDelay "
                f"trig v({related_pin}) val={threshold_voltage} {input_edge}=last "
                f"targ v({main_pin}) val={threshold_voltage} {output_edge}=last\n"
            )
        else:
            # Default to setup behavior for other timing types
            lines.append(
                f".meas tran ZlibBoostDelay "
                f"trig v({main_pin}) val={threshold_voltage} {output_edge}=last "
                f"targ v({related_pin}) val={threshold_voltage} {input_edge}=last\n"
            )

        return lines

    def _generate_degradation_measurement(self) -> List[str]:
        """
        Generate degradation and glitch measurements for output pins.

        These measurements analyze how setup violations affect the output behavior,
        including glitch detection and output degradation analysis.

        Returns:
            List[str]: SPICE measurement commands for output degradation analysis.
        """
        lines: List[str] = []

        related_pin = self.arc.related_pin or self.arc.pin
        related_edge = (self.arc.related_transition or "rise").lower()
        threshold_voltage = round(0.5 * self.V_HIGH, 6)

        output_conditions = dict(getattr(self, "_output_conditions", {}) or {})
        normalized_output_conditions = {
            self._normalize_output_condition_pin(pin): value
            for pin, value in output_conditions.items()
        }

        output_pins = list(self.cell.get_output_pins() or [])
        if not output_pins and not normalized_output_conditions:
            return lines

        primary_output = None
        for output_pin in output_pins:
            if output_pin in normalized_output_conditions:
                primary_output = output_pin
                break
        if primary_output is None and normalized_output_conditions:
            primary_output = sorted(normalized_output_conditions.keys())[0]
        if primary_output is None and output_pins:
            primary_output = output_pins[0]
        if primary_output is None:
            return lines

        polarity = resolve_output_pin(self.cell, primary_output)
        is_negative_output = bool(polarity is not None and polarity.is_negative)

        # Legacy behaviour: choose output measurement direction based on the
        # *initial* output voltage (low -> rise, high -> fall), and emit only
        # the matching glitch-peak measurement.
        output_edge: str | None = None
        initial_output = normalized_output_conditions.get(primary_output)
        if initial_output in {"0", "1"}:
            output_edge = "rise" if initial_output == "0" else "fall"

        if output_edge is None:
            # Fallback heuristic when output state is unavailable.
            timing_type = (self.arc.timing_type or "").lower()
            is_hold_like = any(token in timing_type for token in ("hold", "removal", "non_seq_hold"))
            data_edge = (self.arc.pin_transition or TransitionDirection.RISE.value).lower()
            logical_edge = data_edge
            if is_hold_like:
                logical_edge = "fall" if data_edge == "rise" else "rise"
            output_edge = logical_edge
            if is_negative_output:
                output_edge = "fall" if logical_edge == "rise" else "rise"

        lines.append(
            f".meas tran DegradeDelay "
            f"trig v({related_pin}) val={threshold_voltage} {related_edge}=last "
            f"targ v({primary_output}) val={threshold_voltage} {output_edge}=last"
        )

        if not is_negative_output:
            glitch_name = "glitch_peak_rise" if output_edge == "rise" else "glitch_peak_fall"
            glitch_extrema = "MAX" if output_edge == "rise" else "MIN"
        else:
            glitch_name = "glitch_peak_fall" if output_edge == "rise" else "glitch_peak_rise"
            glitch_extrema = "MIN" if output_edge == "rise" else "MAX"

        lines.append(
            f".meas tran {glitch_name} {glitch_extrema} v({primary_output}) "
            f"FROM=half_tran_tend TO=tran_tend"
        )
        lines.append(
            f".meas tran half_tran_tend_q FIND v({primary_output}) AT=half_tran_tend"
        )
        lines.append("")
        return lines

    def _generate_related_pwl(self) -> List[str]:
        """
        Generate PWL voltage sources for related pin in setup constraint simulation.

        Setup constraints require specific timing relationships between related pin.
        The PWL patterns are generated based on constraint waveform parameters and the
        timing relationship being characterized. Supports both standard setup and
        non-sequential setup patterns from legacy implementation.

        Returns:
            List[str]: PWL voltage source definitions for setup constraint simulation.
        """
        lines = []

        # Get waveform parameters
        t_count = len(self.constraint_waveform.index_2) - 1

        # Get pin names
        related_pin = self.arc.related_pin  # Used in related PWL generation
        timing_type = self.arc.timing_type.lower()

        # Generate PWL for clock pin (related pin)
        lines.append(f"V{related_pin} {related_pin} 0  pwl(")

        # Standard setup constraint pattern for clock (matches legacy lines 352-358)
        if ('setup' in timing_type or 'hold' in timing_type or 'recovery' in timing_type or 'removal' in timing_type) and 'non_seq' not in timing_type:
            lines.append(f"+ '{related_pin}_t0' '{related_pin}_v0'")
            lines.append(f"+ '{related_pin}_t{t_count}' '{related_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend' '{related_pin}_v{t_count}'")
            lines.append(f"+ 'quarter_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v0'")

        # Non-sequential setup/hold pattern (matches legacy lines 360-380)
        elif 'non_seq_setup' in timing_type or 'non_seq_hold' in timing_type:
            # Get pin categories for non-sequential logic
            set_pins = self.cell.get_set_pins()
            reset_pins = self.cell.get_reset_pins()

            # Complex condition-based logic for non-sequential setups
            if hasattr(self.arc, 'condition_dict') and self.arc.condition_dict:
                for pin_condition, pin_state in self.arc.condition_dict.items():
                    pin_value = self.V_HIGH if pin_state == '1' else self.V_LOW

                    polarity = resolve_output_pin(self.cell, pin_condition)
                    if polarity:
                        q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    else:
                        q_value = self.V_LOW  # Default value
                    
                    # Special PWL generation based on q_value and pin type (matches legacy lines 362-380)
                    if q_value == self.V_LOW and related_pin in set_pins:
                        lines.append(f"+ '{related_pin}_t0' {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                        lines.append(f"+ 'quarter_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v0'")
                        break
                    elif q_value == self.V_HIGH and related_pin in reset_pins:
                        lines.append(f"+ '{related_pin}_t0' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v0'")
                        break
            
            # If no special conditions matched, fallback to default non-sequential pattern
            if not any('quarter_tran_tend+' in line for line in lines):
                lines.append(f"+ '{related_pin}_t0' '{related_pin}_v0'")
                lines.append(f"+ '{related_pin}_t{t_count}' '{related_pin}_v{t_count}'")
                lines.append(f"+ 'quarter_tran_tend' '{related_pin}_v{t_count}'")
                lines.append(f"+ 'quarter_tran_tend+{related_pin}_t{t_count}' '{related_pin}_v0'")

        # Add second cycle PWL pattern from t0 to t_count
        lines.extend(self._write_pin_values(related_pin, t_count))

        return lines

    def _generate_condition_pwl(self) -> List[str]:
        """
        Generate piecewise linear (PWL) voltage source definitions for simulation conditions
        based on the main pin type and its associated condition pins.

        This method constructs a list of strings, each representing a PWL voltage source
        statement for a specific pin, tailored according to the pin's category (e.g., data,
        reset, set, sync, async, scan, enable, output). The generated PWL sources are used
        to drive the appropriate voltage levels during simulation, ensuring correct stimulus
        for timing and functional verification.
        The method handles various pin categories and their combinations, such as:
            - Data pins
            - Synchronous/asynchronous reset and set pins
            - Scan and scan enable pins
            - Enable pins
            - Output pins (positive/negative)
        For each pin, the voltage waveform is determined by its state in the arc's condition
        dictionary and its membership in specific pin categories.

        Returns:
            List[str]: PWL voltage source definitions for simulation netlists.
        """
        lines = []

        # Get pin names
        main_pin = self.arc.pin

        # Get t_count from constraint waveform
        t_count = len(self.constraint_waveform.index_2) - 1
        
        # Get pin categories for special handling
        reset_pins = self.cell.get_reset_pins()
        set_pins = self.cell.get_set_pins()
        data_pins = self.cell.get_data_pins()
        scan_enable_pins = self.cell.get_scan_enable_pins()
        scan_pins = self.cell.get_scan_pins()  # Use scan_pins instead of scan_in_pins
        enable_pins = self.cell.get_enable_pins()
        sync_pins = self.cell.get_sync_pins()
        async_pins = self.cell.get_async_pins()
        if main_pin in data_pins:
            # Data main pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Reset and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})")
                    lines.append("")

        elif main_pin in sync_pins and main_pin in reset_pins:
            # Sync and reset pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in data_pins:
                    # Data pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})")
                    lines.append("")

        elif main_pin in sync_pins and main_pin in set_pins:
            # Sync and set pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in data_pins:
                    # Data pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})")
                    lines.append("")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})")
                    lines.append("")

        elif main_pin in async_pins and main_pin in reset_pins:
            # Async and reset pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                q_value = self.V_LOW  # Default initial value
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in set_pins and pin_condition in async_pins:
                    # Set and async pin handling
                    if q_value == self.V_HIGH:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                    else:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {pin_value_positive:.4f})\n")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})\n")

        elif main_pin in async_pins and main_pin in set_pins:
            # Async and set pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                q_value = self.V_LOW  # Default initial value
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_negative}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend' {pin_value_positive}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in reset_pins and pin_condition in async_pins:
                    # Reset and async pin handling
                    if q_value == self.V_LOW:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                        lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                    else:
                        lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                        lines.append(f"+ 0 {pin_value_positive:.4f})\n")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})\n")

        elif main_pin in scan_enable_pins:
            # Scan enable pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                q_value = self.V_LOW  # Default initial value
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in data_pins:
                    # Data condition pin
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {q_value}")
                    lines.append(f"+ 'quarter_tran_tend' {q_value}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Reset and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})\n")

        elif main_pin in scan_pins:
            # Scan pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                q_value = self.V_LOW  # Default initial value
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in data_pins:
                    # Data condition pin
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {q_value}")
                    lines.append(f"+ 'quarter_tran_tend' {q_value}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Reset and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in scan_enable_pins:
                    # Scan enable condition pin
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})\n")

        elif main_pin in enable_pins:
            # Enable pin handling
            for pin_condition, pin_state in self.arc.condition_dict.items():
                pin_value_positive = self.V_HIGH if pin_state == '1' else self.V_LOW
                pin_value_negative = self.V_LOW if pin_state == '1' else self.V_HIGH
                q_value = self.V_LOW  # Default initial value
                polarity = resolve_output_pin(self.cell, pin_condition)
                # Different handling based on pin condition categories
                if polarity and not polarity.is_negative:
                    # Positive output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif polarity and polarity.is_negative:
                    # Negative output condition pin handling
                    q_value = polarity.logical_to_voltage(pin_state, self.V_HIGH, self.V_LOW)
                    lines.append(f"V{main_pin} {main_pin} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+{main_pin}_t{t_count}' {main_pin}_v0")
                    lines.extend(self._write_pin_values(main_pin, t_count))
                elif pin_condition in data_pins:
                    # Data condition pin
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {q_value}")
                    lines.append(f"+ 'quarter_tran_tend' {q_value}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in set_pins and pin_condition in sync_pins:
                    # Set and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in reset_pins and pin_condition in sync_pins:
                    # Reset and sync pin handling
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_HIGH}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                elif pin_condition in scan_enable_pins:
                    # Scan enable condition pin
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend' {self.V_LOW}")
                    lines.append(f"+ 'quarter_tran_tend+1e-12' {pin_value_positive:.4f})\n")
                else:
                    lines.append(f"V{pin_condition} {pin_condition} 0 pwl(")
                    lines.append(f"+ 0 {pin_value_positive:.4f})\n")

        if not self._has_driver(lines, main_pin):
            lines.extend(self._build_default_main_pin_driver(main_pin, t_count))

        return lines

    def _has_driver(self, lines: List[str], pin: str) -> bool:
        """Check whether the generated PWL block already drives the specified pin."""
        prefix = f"V{pin} {pin} "
        return any(fragment.strip().startswith(prefix) for fragment in lines)

    def _build_default_main_pin_driver(self, pin: str, t_count: int) -> List[str]:
        """
        Build a fallback PWL driver for the main pin when no specialized sequence was emitted.

        Mirrors legacy behaviour by holding the pin at its pre-transition level for a quarter
        cycle, then handing control over to the parameterized waveform values.
        """
        transition = (self.arc.pin_transition or TransitionDirection.RISE.value).lower()

        # Legacy setup/hold decks use a 2-cycle pattern:
        # - setup-like: hold at the pre-transition level in the first cycle
        # - hold-like:  hold at the opposite level in the first cycle to prime the flop
        timing_type = (self.arc.timing_type or "").lower()
        is_hold_like = any(token in timing_type for token in ("hold", "removal", "non_seq_hold"))

        if is_hold_like:
            start_high = transition == TransitionDirection.RISE.value
        else:
            start_high = transition == TransitionDirection.FALL.value

        hold_value = self.V_HIGH if start_high else self.V_LOW

        driver_lines = [
            f"V{pin} {pin} 0 pwl(",
            f"+ 0 {hold_value:.6f}",
            f"+ 'quarter_tran_tend' {hold_value:.6f}",
            f"+ 'quarter_tran_tend+{pin}_t{t_count}' '{pin}_v0'",
        ]
        driver_lines.extend(self._write_pin_values(pin, t_count))
        return driver_lines

    def _generate_basic_parameters(self) -> List[str]:
        """
        Generate basic timing parameters for setup constraint simulation.
        
        Setup constraints use the same timing framework as other constraint measurements
        but with specific parameter values optimized for timing analysis.
        
        Returns:
            List[str]: Basic parameter definitions for setup constraint simulation.
        """
        lines = []
        
        # Derived timing parameters
        lines.append(".param half_tran_tend=tran_tend/2")
        lines.append(".param quarter_tran_tend=tran_tend/4\n")
        
        return lines
    
    def _generate_parameter_sweeps(self, i1: int = 0, i2: int = 0) -> List[str]:
        """
        Generate parameter definitions for setup constraint characterization.

        Unlike delay measurements, setup constraints do NOT use .alter statements for 
        parameter sweeping. Instead, they use a single set of parameterized definitions
        that will be used with the PWL voltage sources. The actual sweeping is handled
        by the simulation framework through multiple deck generations.

        This matches the reference SPICE file format which shows parameterized PWL
        sources without .alter statements.

        Args:
            i1: Index for selecting timing values for the data pin (default: 0)
            i2: Index for selecting timing values for the clock pin (default: 0)

        Returns:
            List[str]: Parameter definitions for setup constraint simulation.
        """
        lines = []

        # Get constraint waveform dimensions
        index_2 = self.constraint_waveform.index_2
        values = self.constraint_waveform.values
        
        # Get pin names and transition directions
        data_pin = self.arc.pin
        clock_pin = self.arc.related_pin
        data_dir = self.arc.pin_transition
        clock_dir = self.arc.related_transition

        # Prepare voltage arrays based on transition directions
        if data_dir == TransitionDirection.RISE.value:
            data_volt = index_2
        else:
            data_volt = list(reversed(index_2))
        
        if clock_dir == TransitionDirection.RISE.value:
            clock_volt = index_2
        else:
            clock_volt = list(reversed(index_2))

        # Scale voltages to actual voltage levels
        data_volt = [v * self.V_HIGH for v in data_volt]
        clock_volt = [v * self.V_HIGH for v in clock_volt]

        # Convert time values to list format
        time_list = [list(map(float, row)) for row in values]
        
        # Validate indices
        index_1_count = len(self.constraint_waveform.index_1)
        if i1 >= index_1_count or i2 >= index_1_count:
            raise ValueError(f"Invalid indices: i1={i1}, i2={i2}. Max index is {index_1_count-1}")

        # Generate data pin parameters using i1 index (matches legacy logic)
        for i, (v, t) in enumerate(zip(data_volt, time_list[i1])):
            lines.append(f".param {data_pin}_t{i}={t}e-9")
            # Match legacy formatting: append 'e+00' to voltage values
            lines.append(f".param {data_pin}_v{i}={v}e+00")

        # Generate clock pin parameters using i2 index (matches legacy logic)
        for i, (v, t) in enumerate(zip(clock_volt, time_list[i2])):
            lines.append(f".param {clock_pin}_t{i}={t}e-9")
            # Match legacy formatting: append 'e+00' to voltage values
            lines.append(f".param {clock_pin}_v{i}={v}e+00")

        # Generate output capacitance parameters
        for pin_name in self.cell.get_output_pins():
            lines.append(f".param {pin_name}_cap=1.5000000e-16")

        # Add timing parameter
        lines.append(".param tran_tend=1.7664100e-7")

        return lines

    @staticmethod
    def _normalize_output_condition_pin(pin_name: str) -> str:
        """
        Normalize output condition pin names produced by arc generators.

        Legacy logic encodes output states as ``Q_state`` / ``QN_state`` etc.
        Strip common suffixes so the resulting name matches the actual pin.
        """
        if pin_name.endswith("_state"):
            candidate = pin_name[:-6]
            if candidate:
                return candidate
        return pin_name
