"""
Cell Library Database for managing timing library data.

This module provides the CellLibraryDB class for managing a complete
timing library including cells, templates, waveforms, and configuration.
"""

from typing import Dict, List, Any, Optional, Set
import numpy as np
import re

from zlibboost.core.exceptions import (
    ValidationError, CellNotFoundError, TemplateNotFoundError,
    WaveformNotFoundError, ConfigurationError
)
from zlibboost.core.logger import get_logger
from .models import Cell, TimingArc, Template, Waveform

logger = get_logger(__name__)


class CellLibraryDB:
    """
    Database class for managing cell timing library.
    
    This class manages the complete timing library including:
    - Cell definitions with pins and timing arcs
    - Timing templates for delay, power, and constraint characterization
    - Driver waveforms for simulation
    - Configuration parameters
    
    Attributes:
        cells: Dictionary mapping cell names to Cell objects
        templates: Dictionary mapping template names to Template objects
        driver_waveforms: Dictionary mapping waveform names to Waveform objects
        config_params: Dictionary of configuration parameters
    """
    
    def __init__(self):
        """Initialize empty cell library database."""
        self.cells: Dict[str, Cell] = {}
        self.templates: Dict[str, Template] = {}
        self.driver_waveforms: Dict[str, Waveform] = {}
        self.config_params: Dict[str, Any] = {}

        logger.info("Initialized new CellLibraryDB instance")
    
    # Cell management methods
    def add_cell(self, cell: Cell) -> None:
        """
        Add a cell to the library.
        
        Args:
            cell: Cell object to add
            
        Raises:
            ValidationError: If cell already exists
        """
        if cell.name in self.cells:
            raise ValidationError(f"Cell '{cell.name}' already exists in library")
        
        self.cells[cell.name] = cell
        logger.debug(f"Added cell '{cell.name}' to library")
    
    def get_cell(self, cell_name: str) -> Cell:
        """
        Get a cell by name.
        
        Args:
            cell_name: Name of the cell
            
        Returns:
            Cell object
            
        Raises:
            CellNotFoundError: If cell is not found
        """
        if cell_name not in self.cells:
            raise CellNotFoundError(f"Cell '{cell_name}' not found in library")
        
        return self.cells[cell_name]
    
    def has_cell(self, cell_name: str) -> bool:
        """Check if a cell exists in the library."""
        return cell_name in self.cells
    
    def remove_cell(self, cell_name: str) -> None:
        """
        Remove a cell from the library.
        
        Args:
            cell_name: Name of the cell to remove
            
        Raises:
            CellNotFoundError: If cell is not found
        """
        if cell_name not in self.cells:
            raise CellNotFoundError(f"Cell '{cell_name}' not found in library")
        
        del self.cells[cell_name]
        logger.debug(f"Removed cell '{cell_name}' from library")
    
    def get_all_cell_names(self) -> List[str]:
        """Get list of all cell names in the library."""
        return list(self.cells.keys())

    def get_all_template_names(self) -> List[str]:
        """Get list of all template names in the library."""
        return list(self.templates.keys())

    def get_all_waveform_names(self) -> List[str]:
        """Get list of all waveform names in the library."""
        return list(self.driver_waveforms.keys())

    # Arc definition management methods removed - TimingArcs are now created directly
    # by the ArcHandler and added to cells immediately
    
    # Template management methods
    def add_template(self, template: Template) -> None:
        """
        Add a template to the library.
        
        Args:
            template: Template object to add
            
        Raises:
            ValidationError: If template already exists
        """
        if template.name in self.templates:
            raise ValidationError(f"Template '{template.name}' already exists in library")
        
        self.templates[template.name] = template
        logger.debug(f"Added template '{template.name}' to library")
        self._maybe_add_flat_power_template(template)
        self._maybe_add_flat_constraint_template(template)
    
    def get_template(self, template_name: str) -> Template:
        """
        Get a template by name.
        
        Args:
            template_name: Name of the template
            
        Returns:
            Template object
            
        Raises:
            TemplateNotFoundError: If template is not found
        """
        if template_name not in self.templates:
            raise TemplateNotFoundError(f"Template '{template_name}' not found in library")
        
        return self.templates[template_name]
    
    def has_template(self, template_name: str) -> bool:
        """Check if a template exists in the library."""
        return template_name in self.templates

    def _maybe_add_flat_power_template(self, template: Template) -> None:
        """Ensure a 1D variant exists for power templates when needed."""

        if template.template_type != "power":
            return

        if not template.index_2:
            return

        if template.metadata.get("derived_flat_template"):
            return

        derived_name = self._build_flat_template_name(template.name, len(template.index_1))
        if derived_name in self.templates:
            template.metadata["derived_flat_template"] = derived_name
            return

        derived_template = Template(
            name=derived_name,
            template_type="power",
            index_1=list(template.index_1),
            index_2=[],
            metadata={
                "derived_from": template.name,
                "allow_empty_index_2": True,
            },
        )
        self.templates[derived_name] = derived_template
        template.metadata["derived_flat_template"] = derived_name
        logger.debug(
            "Added derived flat power template '%s' for base template '%s'",
            derived_name,
            template.name,
        )

    @staticmethod
    def _build_flat_template_name(base_name: str, rows: int) -> str:
        match = re.match(r"^(.*)_([0-9]+)x([0-9]+)(_.+)?$", base_name)
        if match:
            prefix = match.group(1)
            suffix = match.group(4) or ""
            return f"{prefix}_{rows}x1{suffix}"

        fallback = re.match(r"^(.*)_([0-9]+)$", base_name)
        if fallback:
            prefix = fallback.group(1)
            suffix = fallback.group(2)
            return f"{prefix}_{rows}x1_{suffix}"

        return f"{base_name}_{rows}x1"
    
    def get_templates_by_type(self, template_type: str) -> List[Template]:
        """
        Get all templates of a specific type.
        
        Args:
            template_type: Type of template ('delay', 'power', 'constraint')
            
        Returns:
            List of Template objects
        """
        return [
            template for template in self.templates.values()
        if template.template_type == template_type
        ]

    def _maybe_add_flat_constraint_template(self, template: Template) -> None:
        """Ensure constraint templates expose 3x1派生模板供MPW复用。"""

        if template.template_type != "constraint":
            return

        if not template.index_2:
            return

        if template.metadata.get("derived_flat_template"):
            return

        derived_name = self._build_flat_template_name(template.name, len(template.index_1))
        if derived_name in self.templates:
            template.metadata["derived_flat_template"] = derived_name
            return

        derived_template = Template(
            name=derived_name,
            template_type="constraint",
            index_1=list(template.index_1),
            index_2=[],
            metadata={
                "derived_from": template.name,
                "allow_empty_index_2": True,
            },
        )
        self.templates[derived_name] = derived_template
        template.metadata["derived_flat_template"] = derived_name
        logger.debug(
            "Added derived flat constraint template '%s' for base template '%s'",
            derived_name,
            template.name,
        )
    
    # Waveform management methods
    def add_driver_waveform(self, waveform: Waveform) -> None:
        """
        Add a driver waveform to the library.
        
        Args:
            waveform: Waveform object to add
            
        Raises:
            ValidationError: If waveform already exists
        """
        if waveform.name in self.driver_waveforms:
            raise ValidationError(f"Waveform '{waveform.name}' already exists in library")
        
        self.driver_waveforms[waveform.name] = waveform
        logger.debug(f"Added waveform '{waveform.name}' to library")
    
    def get_driver_waveform(self, waveform_name: str) -> Waveform:
        """
        Get a driver waveform by name.
        
        Args:
            waveform_name: Name of the waveform
            
        Returns:
            Waveform object
            
        Raises:
            WaveformNotFoundError: If waveform is not found
        """
        if waveform_name not in self.driver_waveforms:
            raise WaveformNotFoundError(f"Waveform '{waveform_name}' not found in library")
        
        return self.driver_waveforms[waveform_name]
    
    def has_driver_waveform(self, waveform_name: str) -> bool:
        """Check if a driver waveform exists in the library."""
        return waveform_name in self.driver_waveforms
    
    # Configuration management methods
    def update_config(self, params: Dict[str, Any]) -> None:
        """
        Update configuration parameters.
        
        Args:
            params: Dictionary of configuration parameters to update
        """
        self.config_params.update(params)
        logger.debug(f"Updated {len(params)} configuration parameters")
    
    def get_config_param(self, param_name: str, default: Any = None) -> Any:
        """
        Get a configuration parameter value.
        
        Args:
            param_name: Name of the parameter
            default: Default value if parameter is not found
            
        Returns:
            Parameter value or default
        """
        return self.config_params.get(param_name, default)
    
    def has_config_param(self, param_name: str) -> bool:
        """Check if a configuration parameter exists."""
        return param_name in self.config_params
    
    def get_spice_params(self) -> Dict[str, Any]:
        """
        Get parameters required for SPICE deck generation.
        
        Returns:
            Dictionary of SPICE parameters
            
        Raises:
            ConfigurationError: If required parameters are missing
        """
        required_params = [
            'voltage', 'temp', 'vdd_name', 'gnd_name', 'threads', 'spice_simulator',
            'measure_slew_lower_rise', 'measure_slew_lower_fall',
            'measure_slew_upper_rise', 'measure_slew_upper_fall',
            'delay_inp_rise', 'delay_inp_fall', 
            'delay_out_rise', 'delay_out_fall',
            'measure_cap_lower_fall', 'measure_cap_upper_fall',
            'measure_cap_lower_rise', 'measure_cap_upper_rise',
            'spicefiles_format', 'mpw_search_bound'
        ]
        optional_params = [
            'vpw_name',
            'vnw_name',
            'lib_dir',
            'spicefiles',
            'modelfiles',
            'lib_corner',
        ]
        
        params = {}
        missing_params = []
        
        for param in required_params:
            value = self.config_params.get(param)
            if value is None:
                missing_params.append(param)
            else:
                params[param] = value
        
        if missing_params:
            raise ConfigurationError(f"Required parameters missing: {missing_params}")
        
        for param in optional_params:
            value = self.config_params.get(param)
            if value is not None:
                params[param] = value
        
        return params
    
    def get_analyzer_params(self) -> Dict[str, Any]:
        """
        Get parameters required for result analysis.
        
        Returns:
            Dictionary of analyzer parameters
            
        Raises:
            ConfigurationError: If required parameters are missing
        """
        required_params = [
            'measure_slew_lower_rise', 'measure_slew_lower_fall',
            'measure_slew_upper_rise', 'measure_slew_upper_fall'
        ]
        
        missing_params = []
        for param in required_params:
            if param not in self.config_params:
                missing_params.append(param)
        
        if missing_params:
            raise ConfigurationError(f"Required analyzer parameters missing: {missing_params}")
        
        measure_slew_lower_rise = self.config_params['measure_slew_lower_rise']
        measure_slew_lower_fall = self.config_params['measure_slew_lower_fall']
        measure_slew_upper_rise = self.config_params['measure_slew_upper_rise']
        measure_slew_upper_fall = self.config_params['measure_slew_upper_fall']
        
        return {
            'scale_rise': 1 / (measure_slew_upper_rise - measure_slew_lower_rise),
            'scale_fall': 1 / (measure_slew_upper_fall - measure_slew_lower_fall)
        }
    
    # Statistics and information methods
    def get_library_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the library.
        
        Returns:
            Dictionary containing library statistics
        """
        total_timing_arcs = sum(len(cell.timing_arcs) for cell in self.cells.values())

        cell_types = {
            'sequential': sum(1 for cell in self.cells.values() if cell.is_sequential),
            'combinational': sum(1 for cell in self.cells.values() if cell.is_combinational)
        }

        base_templates = [
            template
            for template in self.templates.values()
            if not template.metadata.get("derived_from")
        ]

        template_types: Dict[str, int] = {}
        for template in base_templates:
            template_types[template.template_type] = template_types.get(template.template_type, 0) + 1

        return {
            'total_cells': len(self.cells),
            'total_templates': len(base_templates),
            'total_waveforms': len(self.driver_waveforms),
            'total_timing_arcs': total_timing_arcs,
            'cell_types': cell_types,
            'template_types': template_types,
            'config_params_count': len(self.config_params)
        }

    # Serialization methods
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert library to dictionary representation.

        Returns:
            Dictionary containing all library data
        """
        return {
            'cells': {name: cell.to_dict() for name, cell in self.cells.items()},
            'templates': {name: template.to_dict() for name, template in self.templates.items()},
            'driver_waveforms': {name: waveform.to_dict() for name, waveform in self.driver_waveforms.items()},
            'config_params': self.config_params.copy(),
            'stats': self.get_library_stats()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CellLibraryDB':
        """
        Create CellLibraryDB instance from dictionary.

        Args:
            data: Dictionary containing library data

        Returns:
            CellLibraryDB instance
        """
        library_db = cls()

        # Load cells
        cells_data = data.get('cells', {})
        for cell_name, cell_data in cells_data.items():
            cell = Cell.from_dict(cell_data)
            library_db.add_cell(cell)

        # Load templates
        templates_data = data.get('templates', {})
        for template_name, template_data in templates_data.items():
            template = Template.from_dict(template_data)
            library_db.add_template(template)

        # Load waveforms
        waveforms_data = data.get('driver_waveforms', {})
        for waveform_name, waveform_data in waveforms_data.items():
            waveform = Waveform.from_dict(waveform_data)
            library_db.add_driver_waveform(waveform)

        # Arc definitions are no longer supported - TimingArcs are created directly
        # by ArcHandler and added to cells immediately
        
        # Load configuration
        config_data = data.get('config_params', {})
        library_db.update_config(config_data)

        logger.info(f"Loaded library with {len(library_db.cells)} cells, "
                   f"{len(library_db.templates)} templates, "
                   f"{len(library_db.driver_waveforms)} waveforms")

        return library_db

    # Legacy compatibility methods (for backward compatibility)
    def add_template_legacy(self, template_type: str, index_1: List[float],
                           index_2: List[float], name: str) -> None:
        """
        Add a timing template using legacy interface.

        This method provides backward compatibility with the old CellTimingDB interface.

        Args:
            template_type: Type of template (delay, power, constraint)
            index_1: First dimension index values
            index_2: Second dimension index values
            name: Template name (e.g. delay_template_7x7)
        """
        template = Template(
            name=name,
            template_type=template_type,
            index_1=index_1,
            index_2=index_2
        )
        self.add_template(template)

    def add_driver_waveform_legacy(self, waveform_type: str, index_1: List[float],
                                  index_2: List[float], values: np.ndarray,
                                  name: str) -> None:
        """
        Add a driver waveform using legacy interface.

        This method provides backward compatibility with the old CellTimingDB interface.

        Args:
            waveform_type: Type of waveform
            index_1: First dimension index values
            index_2: Second dimension index values
            values: Waveform values array
            name: Waveform name
        """
        waveform = Waveform(
            name=name,
            waveform_type=waveform_type,
            index_1=index_1,
            index_2=index_2,
            values=values
        )
        self.add_driver_waveform(waveform)

    def __str__(self) -> str:
        """String representation of library."""
        stats = self.get_library_stats()
        return (
            f"CellLibraryDB(cells={stats['total_cells']}, "
            f"templates={stats['total_templates']}, "
            f"waveforms={stats['total_waveforms']})"
        )

    def __repr__(self) -> str:
        """Detailed string representation of library."""
        return (
            f"CellLibraryDB(cells={list(self.cells.keys())}, "
            f"templates={list(self.templates.keys())}, "
            f"waveforms={list(self.driver_waveforms.keys())})"
        )
