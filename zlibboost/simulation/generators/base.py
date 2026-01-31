"""
Base SPICE deck generator for all simulation types.

Defines a common superclass that all SPICE generators inherit from, using the
Template Method pattern to standardize deck generation and file I/O.
Subclasses implement simulation-specific body content and file specifications.
"""

import os
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from zlibboost.database.models import Cell, TimingArc
from zlibboost.database.library_db import CellLibraryDB


class BaseSpiceGenerator(ABC):
    """
    Base class for all SPICE deck generators.

    Provides the high-level flow for deck generation while delegating
    simulation-specific logic to subclasses.
    """

    def __init__(self, arc: TimingArc, cell: Cell, library_db: CellLibraryDB, sim_type: str = ""):
        """
        Initialize a SPICE generator instance.

        Args:
            arc: TimingArc to generate a SPICE deck for.
            cell: Cell that contains the timing arc.
            library_db: Library database with templates and configuration.
            sim_type: Simulation type provided by the factory (optional).
        """
        self.arc = arc
        self.cell = cell
        self.library_db = library_db
        self.sim_type = sim_type  # Store simulation type from factory
        self.spice_params = library_db.get_spice_params()
        self.V_HIGH = self.spice_params['voltage']
        self.V_LOW = 0.0

        # Parameter sweeping infrastructure
        self.templates = library_db.templates
        self.waveforms = library_db.driver_waveforms
        if hasattr(self.arc, "get_condition_inputs"):
            self._input_conditions = self.arc.get_condition_inputs(self.cell)  # type: ignore[attr-defined]
        else:
            self._input_conditions = dict(getattr(self.arc, "condition_dict", {}) or {})
        if hasattr(self.arc, "get_condition_outputs"):
            self._output_conditions = self.arc.get_condition_outputs(self.cell)  # type: ignore[attr-defined]
        else:
            self._output_conditions = dict(getattr(self.arc, "output_condition_dict", {}) or {})
        self._merged_conditions = dict(self._input_conditions)
        self._merged_conditions.update(self._output_conditions)

    def generate_files(self, output_dir: str) -> List[str]:
        """
        Generate and write all files for this arc.

        This template method:
        1) Gets file specifications from the subclass
        2) Creates the directory structure (cell_name/sim_type/)
        3) Writes all files to disk
        4) Returns the list of written file paths

        Args:
            output_dir: Base output directory (e.g., /output/).

        Returns:
            List[str]: List of written file paths.
        """
        # Create cell directory and arc type subdirectory
        cell_dir = os.path.join(output_dir, self.cell.name)
        arc_dir = os.path.join(cell_dir, self.sim_type)
        os.makedirs(arc_dir, exist_ok=True)

        # Get file specifications from subclass
        file_specs = self._get_file_specs()

        # Write all files
        written_files = []
        for spec in file_specs:
            filepath = self._write_file_from_spec(arc_dir, spec)
            written_files.append(filepath)

        return written_files

    @abstractmethod
    def _get_file_specs(self) -> List[Dict[str, str]]:
        """
        Get the list of file specifications to generate.

        Subclasses define which files to generate. Each specification includes
        a relative path and its content.

        Returns:
            List[Dict[str, str]]: File specifications, each containing:
                - 'filename': relative path, e.g. 'path/file.sp'
                - 'content': SPICE deck content as string
        """
        raise NotImplementedError

    def _write_file_from_spec(self, output_dir: str, spec: Dict[str, str]) -> str:
        """
        Write a file based on the provided specification.

        Args:
            output_dir: Base output directory.
            spec: File specification dictionary.

        Returns:
            str: Full path of the written file.
        """
        relative_path = spec['filename']
        content = spec['content']

        # Build full file path
        filepath = os.path.join(output_dir, relative_path)

        # Create subdirectories if needed
        file_dir = os.path.dirname(filepath)
        if file_dir != output_dir:
            os.makedirs(file_dir, exist_ok=True)

        # Write file
        with open(filepath, 'w') as f:
            f.write(content)

        return filepath

    def _build_base_filename(self) -> str:
        """
        Build the base filename (without index and extension).

        Helper for subclasses to construct consistent filenames.

        Returns:
            str: Base filename constructed from arc properties.
        """
        parts = [
            self.arc.pin,
            self.arc.related_pin,
            self.arc.timing_type,
            self.arc.table_type
        ]

        # Add vector (generated from condition_dict)
        vector = self._generate_vector()
        if vector:
            parts.append(vector)

        return "_".join(parts)

    def _generate_vector(self) -> str:
        """
        Generate a vector string from the arc's condition_dict.

        The vector encodes the state of each pin in the cell:
        - '0': Logic low (0V)
        - '1': Logic high (VDD)
        - 'R': Rising transition (0→VDD)
        - 'F': Falling transition (VDD→0)
        - 'x': Don't care state

        Returns:
            str: Vector string (e.g., "R0101", "F1x").
        """
        combined_conditions = dict(getattr(self, "_input_conditions", {}) or {})
        combined_conditions.update(getattr(self, "_output_conditions", {}) or {})

        if not combined_conditions:
            return ""

        # Get cell's pin order
        pin_order = self.cell.get_pin_order()

        vector_chars = []
        for pin in pin_order:
            # Check transitions first (legacy behavior: R/F has priority)
            if pin == self.arc.pin:
                # Main pin transition
                if self.arc.pin_transition == 'rise':
                    vector_chars.append('R')
                elif self.arc.pin_transition == 'fall':
                    vector_chars.append('F')
                else:
                    # No valid transition, use condition value if available
                    vector_chars.append(combined_conditions.get(pin, 'x'))
            elif pin == self.arc.related_pin:
                # Related pin transition
                if self.arc.related_transition == 'rise':
                    vector_chars.append('R')
                elif self.arc.related_transition == 'fall':
                    vector_chars.append('F')
                else:
                    # No valid transition, use condition value if available
                    vector_chars.append(combined_conditions.get(pin, 'x'))
            elif pin in combined_conditions:
                # Regular condition pin (not transition pin)
                vector_chars.append(combined_conditions[pin])
            else:
                # Pin not in condition, use 'x' for don't care
                vector_chars.append('x')

        return ''.join(vector_chars)

    def generate_deck(self) -> str:
        """
        Template method that defines the complete SPICE deck generation flow.

        Returns:
            str: Complete SPICE deck content.
        """
        header = self._generate_header()
        body = self._generate_body()
        footer = self._generate_footer()
        return f"{header}\n{body}\n{footer}"

    def _generate_header(self) -> str:
        """
        Generate the common SPICE file header.

        Returns:
            str: SPICE header section.
        """
        lines = []

        # File header with arc information
        lines.append(f"**** SPICE Deck for {self.cell.name}")
        lines.append(f"*** Arc: {self.arc.related_pin} -> {self.arc.pin}")
        lines.append(
            f"*** Type: {self.arc.timing_type}, Table: {self.arc.table_type}")
        lines.append(f"*** Condition: {self.arc.condition}")
        lines.append("")

        # Simulator-specific header
        simulator = self.spice_params.get('spice_simulator', 'spectre').lower()
        if simulator == 'hspice':
            lines.append("**** ZlibBoost Simulator language for HSPICE")
        elif simulator == 'spectre':
            lines.append("**** ZlibBoost spice deck for characterization")
            lines.append("simulator lang=spectre")
            lines.append("Opt1 options reltol=1e-4")
            lines.append("simulator lang=spice")
        lines.append("")

        # Include library files (convert relative path to absolute)
        modelfiles_dir = (self.spice_params.get('modelfiles') or '')
        if modelfiles_dir:
            modelfiles_dir = os.path.abspath(modelfiles_dir)
        lib_corner = self.spice_params.get('lib_corner')
        if lib_corner:
            lines.append(f".lib '{modelfiles_dir}' {lib_corner}")
        else:
            lines.append(f".inc '{modelfiles_dir}'")
        lines.append("")

        # Include cell netlist (convert relative path to absolute)
        spicefiles_dir = (self.spice_params.get('spicefiles') or '')
        if spicefiles_dir:
            spicefiles_dir = os.path.abspath(spicefiles_dir)
        spicefiles_format = self.spice_params.get('spicefiles_format', 'sp')
        lines.append(
            f".inc '{spicefiles_dir}/{self.cell.name}.{spicefiles_format}'")
        lines.append("")

        # Instantiate circuit
        instance_pins = self._resolve_instance_pin_order()
        pin_order = ' '.join(instance_pins).strip()
        lines.append(f"Xmy_circuit {pin_order} {self.cell.name}")
        lines.append("")

        # Power supplies
        vdd_name = self.spice_params.get('vdd_name', 'VDD')
        gnd_name = self.spice_params.get('gnd_name', 'VSS')
        lines.append(f"VVDD {vdd_name} 0 {self.V_HIGH}")
        lines.append(f"VVSS {gnd_name} 0 {self.V_LOW}")

        # Optional well bias
        vpw_name = self.spice_params.get('vpw_name')
        vnw_name = self.spice_params.get('vnw_name')
        if vnw_name and vpw_name:
            lines.append(f"VVNW {vnw_name} 0 {self.V_HIGH}")
            lines.append(f"VVPW {vpw_name} 0 {self.V_LOW}")

        # Temperature
        temp = self.spice_params.get('temp', 25)
        lines.append(f".temp {temp}")
        lines.append("")

        return '\n'.join(lines)

    def _resolve_instance_pin_order(self) -> List[str]:
        """Resolve the pin order for circuit instantiation.

        Prefer the pin order defined on the Cell model, but fall back to
        parsing the netlist's .subckt definition when the Cell pin order is
        missing pins (e.g., supply rails).
        """

        cell_pin_order = self.cell.get_pin_order()
        netlist_pin_order = self._parse_netlist_pin_order()

        if not netlist_pin_order:
            return cell_pin_order

        missing_pins = set(netlist_pin_order) - set(cell_pin_order)
        if missing_pins:
            return netlist_pin_order

        return cell_pin_order or netlist_pin_order

    def _parse_netlist_pin_order(self) -> List[str]:
        """Extract pin order from the cell netlist's .subckt definition."""

        spicefiles_dir = self.spice_params.get('spicefiles') or ''
        if spicefiles_dir:
            spicefiles_dir = os.path.abspath(spicefiles_dir)
        spicefiles_format = self.spice_params.get('spicefiles_format', 'sp')
        netlist_path = os.path.join(
            spicefiles_dir,
            f"{self.cell.name}.{spicefiles_format}",
        )

        pattern = re.compile(rf"^\s*\.subckt\s+{re.escape(self.cell.name)}\s+(.+)", re.IGNORECASE)

        try:
            with open(netlist_path, 'r') as netlist_file:
                for line in netlist_file:
                    match = pattern.match(line)
                    if match:
                        pin_list = match.group(1).strip()
                        return pin_list.split()
        except FileNotFoundError:
            return []
        except OSError:
            return []

        return []

    @abstractmethod
    def _generate_body(self) -> str:
        """
        Generate simulation-specific body content.

        Implement in subclasses to provide measurement statements,
        voltage sources (PWL), parameters, and sweeps for the given type.

        Returns:
            str: SPICE body section.
        """
        raise NotImplementedError

    def _generate_footer(self) -> str:
        """
        Generate the common SPICE file footer.

        Returns:
            str: SPICE footer section.
        """
        return ".end"

    def _generate_simulation_options(self) -> List[str]:
        """
        Generate simulator-specific options.

        Returns:
            List[str]: Simulator options section.
        """
        lines = []
        simulator = self.spice_params.get('spice_simulator', 'spectre').lower()
        base_options = ("autostop numdgt=6 measdgt=6 ingold=2 save=nooutput "
                        "method=gear gmin=1e-15 gminfloatdefault=gmindc "
                        "redefinedparams=ignore rabsshort=1m limit=delta save=nooutput")

        if simulator == 'hspice':
            lines.append(f".option MEASFILE=1 {base_options}")
            lines.append(
                f".tran 1.00e-12 'tran_tend' lteratio=10 ckptperiod=1800")
        else:  # spectre or others
            lines.append(f".option {base_options}")
            lines.append(
                f".tran 1.00e-12 'tran_tend' lteratio=10 ckptperiod=1800 skipdc=useprevic")
        lines.append("")
        return lines

    def _generate_output_capacitances(self) -> List[str]:
        """
        Generate load capacitances for output pins.

        Returns:
            List[str]: Load capacitance definitions for output pins.
        """
        lines = []
        cap_counter = 0

        for pin_name in self.cell.get_output_pins():
            lines.append(f"C{cap_counter:00}_0 {pin_name} 0 '{pin_name}_cap'")
            cap_counter += 1
        lines.append("")
        return lines

    def _get_template(self, template_name: str):
        """
        Get a template by name from the library database.

        Args:
            template_name: Name of the template.

        Returns:
            Template object or None if not found.
        """
        return self.templates.get(template_name)

    def _get_waveform(self, waveform_name: str):
        """
        Get a waveform by name from the library database.

        Args:
            waveform_name: Name of the waveform.

        Returns:
            Waveform object or None if not found.
        """
        return self.waveforms.get(waveform_name)

    def _write_pin_values(self, pin, t_count):
        """
        Write piecewise linear (PWL) voltage source values for a given pin.

        Args:
            pin: Pin name to write values for.
            t_count: Number of PWL segments (time points - 1).
        """
        lines = []
        for i in range(t_count):
            lines.append(f"+ 'half_tran_tend+{pin}_t{i}' '{pin}_v{i}'")
        lines.append(
            f"+ 'half_tran_tend+{pin}_t{t_count}' '{pin}_v{t_count}')\n")
        return lines
