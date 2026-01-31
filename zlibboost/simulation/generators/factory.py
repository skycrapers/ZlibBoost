# zlibboost/simulation/generators/factory.py
"""
SPICE generator factory.

Provides centralized creation of SPICE generators for the supported
simulation types (delay, leakage, setup/hold/recovery/removal, mpw, hidden),
replacing if/elif chains with a clean type-to-class mapping.

Notes:
- Dynamic power and input capacitance measurements are implemented inside the
    DelaySpiceGenerator. Routing here classifies transition table arcs as
    "delay"; other table types should be integrated as needed.
"""

import os
from typing import List, Tuple, Any, Dict
from zlibboost.core.logger import get_logger
from zlibboost.database.models import Cell, TimingArc, TableType, TimingType
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.simulation.generators.base import BaseSpiceGenerator
from .leakage import LeakageSpiceGenerator
from .delay import DelaySpiceGenerator
from .setup import SetupSpiceGenerator
from .mpw import MpwSpiceGenerator
from .hidden import HiddenSpiceGenerator


class SpiceGeneratorFactory:
    """
    Factory class for creating appropriate SPICE generators.

    This factory determines the simulation type based on timing arc properties
    and creates the corresponding generator with full parameter sweeping support.
    """

    # Generator class mapping for different simulation types
    _GENERATOR_MAP = {
        'leakage': LeakageSpiceGenerator,
        'delay': DelaySpiceGenerator,
        # Reuse SetupSpiceGenerator for other constraint types
        'setup': SetupSpiceGenerator,
        'hold': SetupSpiceGenerator,
        'recovery': SetupSpiceGenerator,
        'removal': SetupSpiceGenerator,
        # Add other generator classes here as needed
        'mpw': MpwSpiceGenerator,
        'hidden': HiddenSpiceGenerator,
    }

    @classmethod
    def get_generator(cls, arc: TimingArc, cell: Cell, library_db: CellLibraryDB) -> 'BaseSpiceGenerator':
        """
        Create appropriate SPICE generator for given timing arc.

        Args:
            arc: TimingArc to generate SPICE deck for
            cell: Cell containing the arc
            library_db: Library database with templates and waveforms

        Returns:
            Appropriate SPICE generator instance

        Raises:
            ValueError: If simulation type is not supported
        """
        # Determine simulation type from arc properties
        sim_type = cls._determine_simulation_type(arc)

        # Get generator class from mapping
        generator_class = cls._GENERATOR_MAP.get(sim_type)
        if not generator_class:
            raise ValueError(
                f"Unsupported simulation type: '{sim_type}'."
            )

        # Create and return generator instance with sim_type
        return generator_class(arc, cell, library_db, sim_type)

    @classmethod
    def get_supported_simulation_types(cls) -> list:
        """
        Get list of currently supported simulation types.

        Returns:
            List of supported simulation type strings
        """
        return list(cls._GENERATOR_MAP.keys())

    @classmethod
    def is_simulation_type_supported(cls, sim_type: str) -> bool:
        """
        Check if a simulation type is supported.

        Args:
            sim_type: Simulation type string

        Returns:
            True if supported, False otherwise
        """
        return sim_type in cls._GENERATOR_MAP

    @staticmethod
    def _determine_simulation_type(arc: TimingArc) -> str:
        """
        Determine simulation type based on timing arc properties.

        Args:
            arc: TimingArc to analyze

        Returns:
            Simulation type string

        Raises:
            ValueError: If simulation type cannot be determined
        """
        # Priority order for type determination

        # 1. Leakage power simulation
        if arc.table_type == TableType.LEAKAGE_POWER.value:
            return 'leakage'

        # 2. Delay simulation:
        #   - Cell rise and fall (propagation delay)
        #   - Rise and fall transitions (slew time)
        #   - Rise and fall power (dynamic power)
        #   - Input capacitance
        # Route both transition tables and cell rise/fall tables to the delay generator.
        if arc.table_type in [
            TableType.CELL_RISE.value,
            TableType.CELL_FALL.value,
        ]:
            return 'delay'

        # 3. Constraint timing simulations
        if arc.timing_type in [TimingType.SETUP_RISING.value, TimingType.SETUP_FALLING.value]:
            return 'setup'
        elif arc.timing_type in [TimingType.HOLD_RISING.value, TimingType.HOLD_FALLING.value]:
            return 'hold'
        elif arc.timing_type in [TimingType.RECOVERY_RISING.value, TimingType.RECOVERY_FALLING.value]:
            return 'recovery'
        elif arc.timing_type in [TimingType.REMOVAL_RISING.value, TimingType.REMOVAL_FALLING.value]:
            return 'removal'
        elif arc.timing_type == TimingType.MIN_PULSE_WIDTH.value:
            return 'mpw'

        # 4. Hidden power simulation
        elif arc.timing_type == TimingType.HIDDEN.value:
            return 'hidden'

        # No type matches
        else:
            return 'other'

    @classmethod
    def generate_files_for_arc(
        cls, arc: TimingArc, cell: Cell, library_db: CellLibraryDB, output_dir: str
    ) -> List[str]:
        """
        Generate SPICE files for a specific timing arc.

        Factory's responsibility is minimal:
        1. Determine simulation type
        2. Create appropriate generator
        3. Create cell base directory
        4. Delegate file generation to the generator

        Args:
            arc: TimingArc to generate files for
            cell: Cell containing the arc
            library_db: Library database with templates and waveforms
            output_dir: Directory to output generated files

        Returns:
            List[str]: List of generated file paths
        """
        logger = get_logger(__name__)
        # Determine simulation type
        sim_type = cls._determine_simulation_type(arc)
        logger.debug(
            f"Route arc: cell={cell.name} arc={arc.get_arc_key()} -> sim_type={sim_type}"
        )

        # No generation for 'other' type
        if sim_type == 'other':
            logger.debug(
                f"Skip arc (no generator): cell={cell.name} arc={arc.get_arc_key()}"
            )
            return []

        # Get appropriate generator class
        generator_class = cls._GENERATOR_MAP.get(sim_type)
        if generator_class is None:
            return []

        # Create generator instance - pass sim_type to generator
        generator = generator_class(arc, cell, library_db, sim_type)

        # Generator handles all directory structure and file generation
        files = generator.generate_files(output_dir)
        logger.debug(
            f"Generated {len(files)} file(s) for arc: cell={cell.name} sim_type={sim_type}"
        )
        return files

    @classmethod
    def generate_files_for_cell(
        cls, cell: Cell, library_db: CellLibraryDB, output_dir: str
    ) -> List[str]:
        """
        Generate all SPICE files for a single cell.

        Iterates through all timing arcs and generates files for each.

        Args:
            cell: Cell to generate files for
            library_db: Library database with templates and waveforms  
            output_dir: Directory to output generated files

        Returns:
            List[str]: List of all generated file paths
        """
        logger = get_logger(__name__)
        all_files: List[str] = []
        sim_counts: Dict[str, int] = {}
        for arc in cell.timing_arcs:
            files = cls.generate_files_for_arc(
                arc, cell, library_db, output_dir)
            all_files.extend(files)
            sim_type = cls._determine_simulation_type(arc)
            if files:
                sim_counts[sim_type] = sim_counts.get(sim_type, 0) + 1
        logger.info(
            f"Cell {cell.name}: written={len(all_files)} by_type={sim_counts}"
        )
        return all_files

    @classmethod
    def generate_files_for_library(
        cls, library_db: CellLibraryDB, output_dir: str
    ) -> Dict[str, List[str]]:
        """
        Generate all SPICE files for entire library.

        Iterates through all cells and generates files for each.

        Args:
            library_db: Library database with templates and waveforms
            output_dir: Directory to output generated files

        Returns:
            Dict[str, List[str]]: Dictionary mapping cell names to their generated file paths
        """
        logger = get_logger(__name__)
        results: Dict[str, List[str]] = {}
        for cell_name, cell in library_db.cells.items():
            files = cls.generate_files_for_cell(cell, library_db, output_dir)
            results[cell_name] = files
        logger.info(
            f"Library generation complete: cells={len(results)} total_files={sum(len(v) for v in results.values())}"
        )
        return results
