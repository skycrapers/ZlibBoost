"""
Configuration management base classes for ZlibBoost.

This module provides the base configuration management functionality,
including parameter conversion, default values, and configuration schemas.
"""

from typing import Dict, Any, Optional, Union, Type
from pathlib import Path
from ..exceptions import ConfigError, InvalidValueError
from .validator import ConfigValidator


class ConfigManager:
    """
    Base configuration manager.
    
    Manages configuration parameters with validation, type conversion,
    and default value handling.
    """
    
    # Default configuration values
    DEFAULT_CONFIG = {
        # Timing measurement parameters
        "delay_inp_rise": 0.1,
        "delay_inp_fall": 0.1,
        "delay_out_rise": 0.9,
        "delay_out_fall": 0.9,
        "measure_slew_lower_rise": 0.1,
        "measure_slew_lower_fall": 0.1,
        "measure_slew_upper_rise": 0.9,
        "measure_slew_upper_fall": 0.9,
        "measure_cap_lower_rise": 0.1,
        "measure_cap_lower_fall": 0.1,
        "measure_cap_upper_rise": 0.9,
        "measure_cap_upper_fall": 0.9,
        
        # Simulation parameters
        "voltage": 1.8,
        "temp": 25,
        "threads": 4,
        "mpw_search_bound": 2.0,
        "subtract_hidden_power": 0,
        
        # Simulator settings
        "spice_simulator": "hspice",
        "vdd_name": "VDD",
        "gnd_name": "VSS",
        "vpw_name": "VPW",
        "vnw_name": "VNW",
        "lib_corner": "tt",
    }
    
    def __init__(self, validator: Optional[ConfigValidator] = None):
        """
        Initialize configuration manager.
        
        Args:
            validator: Configuration validator instance
        """
        self.validator = validator or ConfigValidator()
        self._config: Dict[str, Any] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default configuration values."""
        self._config = self.DEFAULT_CONFIG.copy()

    def update_config(self, config_dict: Dict[str, Any]) -> None:
        """
        Update configuration with new values.
        
        Args:
            config_dict: Dictionary of configuration parameters
            
        Raises:
            ConfigError: If configuration update fails
            InvalidValueError: If parameter values are invalid
        """
        if not isinstance(config_dict, dict):
            raise ConfigError("Configuration must be a dictionary")
            
        # Validate and convert each parameter
        validated_config = {}
        for param_name, value in config_dict.items():
            try:
                validated_value = self.validator.validate_parameter(param_name, value)
                validated_config[param_name] = validated_value
            except InvalidValueError as e:
                raise InvalidValueError(f"Configuration update failed: {str(e)}")
                
        # Update configuration
        self._config.update(validated_config)
        
        # Validate complete configuration
        self.validator.validate_config(self._config)

    def get_parameter(self, param_name: str, default: Any = None) -> Any:
        """
        Get configuration parameter value.
        
        Args:
            param_name: Name of the parameter
            default: Default value if parameter not found
            
        Returns:
            Parameter value
        """
        return self._config.get(param_name, default)

    def set_parameter(self, param_name: str, value: Any) -> None:
        """
        Set a single configuration parameter.
        
        Args:
            param_name: Name of the parameter
            value: Value to set
            
        Raises:
            InvalidValueError: If parameter value is invalid
        """
        validated_value = self.validator.validate_parameter(param_name, value)
        self._config[param_name] = validated_value

    def get_all_parameters(self) -> Dict[str, Any]:
        """
        Get all configuration parameters.
        
        Returns:
            Dictionary of all configuration parameters
        """
        return self._config.copy()

    def has_parameter(self, param_name: str) -> bool:
        """
        Check if parameter exists in configuration.
        
        Args:
            param_name: Name of the parameter
            
        Returns:
            True if parameter exists
        """
        return param_name in self._config

    def remove_parameter(self, param_name: str) -> None:
        """
        Remove a parameter from configuration.
        
        Args:
            param_name: Name of the parameter to remove
            
        Raises:
            ConfigError: If trying to remove required parameter
        """
        if param_name in self.validator.REQUIRED_PARAMS:
            raise ConfigError(f"Cannot remove required parameter: {param_name}")
            
        self._config.pop(param_name, None)

    def reset_to_defaults(self) -> None:
        """Reset configuration to default values."""
        self._load_defaults()

    def get_spice_parameters(self) -> Dict[str, Any]:
        """
        Get parameters relevant for SPICE simulation.
        
        Returns:
            Dictionary of SPICE-related parameters
        """
        spice_params = {}
        spice_param_names = {
            "voltage", "temp", "spice_simulator", "vdd_name", "gnd_name",
            "vpw_name", "vnw_name", "spicefiles", "modelfiles",
            "delay_inp_rise", "delay_inp_fall", "delay_out_rise", "delay_out_fall",
            "measure_slew_lower_rise", "measure_slew_lower_fall",
            "measure_slew_upper_rise", "measure_slew_upper_fall",
            "measure_cap_lower_rise", "measure_cap_lower_fall",
            "measure_cap_upper_rise", "measure_cap_upper_fall",
        }
        
        for param_name in spice_param_names:
            if param_name in self._config:
                spice_params[param_name] = self._config[param_name]
                
        return spice_params

    def get_analysis_parameters(self) -> Dict[str, Any]:
        """
        Get parameters relevant for result analysis.
        
        Returns:
            Dictionary of analysis-related parameters
        """
        analysis_params = {}
        analysis_param_names = {
            "mpw_search_bound", "subtract_hidden_power", "threads",
            "lib_corner", "report_path",
        }
        
        for param_name in analysis_param_names:
            if param_name in self._config:
                analysis_params[param_name] = self._config[param_name]
                
        return analysis_params

    def get_file_paths(self) -> Dict[str, str]:
        """
        Get all file path parameters.
        
        Returns:
            Dictionary of file path parameters
        """
        path_params = {}
        for param_name in self.validator.PATH_PARAMS:
            if param_name in self._config:
                path_params[param_name] = self._config[param_name]
                
        return path_params

    def validate_paths(self) -> None:
        """
        Validate that all required paths exist.
        
        Raises:
            ConfigError: If required paths don't exist
        """
        path_params = self.get_file_paths()
        missing_paths = []
        
        for param_name, path_str in path_params.items():
            # Skip output paths (they will be created)
            if param_name == "report_path":
                continue
                
            path_obj = Path(path_str)
            if not path_obj.exists():
                missing_paths.append(f"{param_name}: {path_str}")
                
        if missing_paths:
            raise ConfigError(
                f"Required paths do not exist:\n" + "\n".join(missing_paths)
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns:
            Configuration as dictionary
        """
        return self.get_all_parameters()

    def from_dict(self, config_dict: Dict[str, Any]) -> None:
        """
        Load configuration from dictionary.
        
        Args:
            config_dict: Configuration dictionary
        """
        self.reset_to_defaults()
        self.update_config(config_dict)

    def __str__(self) -> str:
        """String representation of configuration."""
        lines = ["Configuration:"]
        for param_name, value in sorted(self._config.items()):
            lines.append(f"  {param_name}: {value}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        """Detailed representation of configuration."""
        return f"ConfigManager({len(self._config)} parameters)"


class ConfigSchema:
    """
    Configuration schema definition.
    
    Defines the structure and constraints for configuration parameters.
    """
    
    @staticmethod
    def get_parameter_schema() -> Dict[str, Dict[str, Any]]:
        """
        Get complete parameter schema.
        
        Returns:
            Dictionary mapping parameter names to their schema definitions
        """
        validator = ConfigValidator()
        schema = {}
        
        all_params = (
            validator.NUMERIC_PARAMS | 
            validator.STRING_PARAMS | 
            validator.PATH_PARAMS
        )
        
        for param_name in all_params:
            schema[param_name] = validator.get_parameter_info(param_name)
            
        return schema

    @staticmethod
    def get_required_parameters() -> set:
        """Get set of required parameter names."""
        return ConfigValidator.REQUIRED_PARAMS.copy()

    @staticmethod
    def get_optional_parameters() -> set:
        """Get set of optional parameter names."""
        validator = ConfigValidator()
        all_params = (
            validator.NUMERIC_PARAMS | 
            validator.STRING_PARAMS | 
            validator.PATH_PARAMS
        )
        return all_params - validator.REQUIRED_PARAMS
