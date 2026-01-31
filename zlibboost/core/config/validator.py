"""
Configuration validation module for ZlibBoost.

This module provides validation logic for configuration parameters,
including type checking, value range validation, and dependency validation.
"""

from typing import Dict, Any, Set, Optional, Union
from pathlib import Path
from ..exceptions import ConfigError, InvalidValueError


class ConfigValidator:
    """
    Configuration parameter validator.
    
    Validates configuration parameters based on their types, ranges,
    and dependencies. Provides detailed error messages for invalid values.
    """
    
    # Parameter type definitions
    NUMERIC_PARAMS = {
        "delay_inp_rise",
        "delay_inp_fall",
        "delay_out_rise",
        "delay_out_fall",
        "measure_slew_lower_rise",
        "measure_slew_lower_fall",
        "measure_slew_upper_rise",
        "measure_slew_upper_fall",
        "measure_cap_lower_rise",
        "measure_cap_lower_fall",
        "measure_cap_upper_rise",
        "measure_cap_upper_fall",
        "voltage",
        "temp",
        "threads",
        "mpw_search_bound",
        "subtract_hidden_power",
        "driver_waveform",
        "arc_mode",
    }

    STRING_PARAMS = {
        "spice_simulator",
        "vdd_name",
        "gnd_name",
        "vpw_name",
        "vnw_name",
        "gnw_name",  # Added for sky130
        "lib_corner",
        "spicefiles_format",
    }

    PATH_PARAMS = {
        "extsim_deck_dir",
        "template_file",
        "spicefiles",
        "modelfiles",
        "report_path",
    }

    REQUIRED_PARAMS = {
        "spicefiles",
        "extsim_deck_dir",
        "template_file",
        "report_path"
    }
    
    # Valid values for specific parameters
    VALID_SIMULATORS = {"hspice", "spectre", "ngspice"}
    
    # Parameter ranges
    PARAM_RANGES = {
        "voltage": (0.1, 5.0),  # Voltage range in volts
        "temp": (-40, 125),     # Temperature range in Celsius
        "threads": (1, 64),     # Thread count range
        "mpw_search_bound": (1e-12, 100.0),  # MPW search bound (can be in seconds or nanoseconds)
        "subtract_hidden_power": (0, 1),  # Boolean as integer
    }
    
    # Parameters that should be positive
    POSITIVE_PARAMS = {
        "delay_inp_rise", "delay_inp_fall", "delay_out_rise", "delay_out_fall",
        "measure_slew_lower_rise", "measure_slew_lower_fall",
        "measure_slew_upper_rise", "measure_slew_upper_fall",
        "measure_cap_lower_rise", "measure_cap_lower_fall",
        "measure_cap_upper_rise", "measure_cap_upper_fall",
    }

    def __init__(self):
        """Initialize the configuration validator."""
        pass

    def validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate complete configuration dictionary.
        
        Args:
            config: Configuration dictionary to validate
            
        Raises:
            ConfigError: If configuration is invalid
            InvalidValueError: If parameter values are invalid
        """
        if not isinstance(config, dict):
            raise ConfigError("Configuration must be a dictionary")
            
        # Check required parameters
        self._validate_required_params(config)
        
        # Validate individual parameters
        for param_name, value in config.items():
            self.validate_parameter(param_name, value)
            
        # Validate parameter dependencies
        self._validate_dependencies(config)

    def validate_parameter(self, param_name: str, value: Any) -> Any:
        """
        Validate a single configuration parameter.
        
        Args:
            param_name: Name of the parameter
            value: Value to validate
            
        Returns:
            Validated and possibly converted value
            
        Raises:
            InvalidValueError: If parameter value is invalid
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            raise InvalidValueError(f"Parameter '{param_name}' cannot be empty")
            
        # Type-specific validation
        if param_name in self.NUMERIC_PARAMS:
            return self._validate_numeric_param(param_name, value)
        elif param_name in self.STRING_PARAMS:
            return self._validate_string_param(param_name, value)
        elif param_name in self.PATH_PARAMS:
            return self._validate_path_param(param_name, value)
        else:
            # Unknown parameter - keep as string but warn
            return str(value)

    def _validate_required_params(self, config: Dict[str, Any]) -> None:
        """Validate that all required parameters are present."""
        missing_params = self.REQUIRED_PARAMS - set(config.keys())
        if missing_params:
            raise ConfigError(
                f"Missing required configuration parameters: {', '.join(sorted(missing_params))}"
            )

    def _validate_numeric_param(self, param_name: str, value: Any) -> Union[int, float]:
        """Validate numeric parameters."""
        try:
            # Convert to appropriate numeric type
            if isinstance(value, str):
                value = value.strip()
                if "e" in value.lower() or "." in value:
                    numeric_value = float(value)
                else:
                    numeric_value = int(value)
            elif isinstance(value, (int, float)):
                numeric_value = value
            else:
                raise ValueError(f"Cannot convert {type(value)} to number")
                
            # Range validation
            if param_name in self.PARAM_RANGES:
                min_val, max_val = self.PARAM_RANGES[param_name]
                if not (min_val <= numeric_value <= max_val):
                    raise InvalidValueError(
                        f"Parameter '{param_name}' value {numeric_value} is outside valid range [{min_val}, {max_val}]"
                    )
                    
            # Positive value validation
            if param_name in self.POSITIVE_PARAMS and numeric_value <= 0:
                raise InvalidValueError(
                    f"Parameter '{param_name}' must be positive, got {numeric_value}"
                )
                
            return numeric_value
            
        except (ValueError, TypeError) as e:
            raise InvalidValueError(
                f"Invalid numeric value for parameter '{param_name}': {value} ({str(e)})"
            )

    def _validate_string_param(self, param_name: str, value: Any) -> str:
        """Validate string parameters."""
        str_value = str(value).strip()
        
        # Special validation for specific parameters
        if param_name == "spice_simulator":
            if str_value.lower() not in self.VALID_SIMULATORS:
                raise InvalidValueError(
                    f"Invalid simulator '{str_value}'. Valid options: {', '.join(self.VALID_SIMULATORS)}"
                )
            return str_value.lower()
            
        return str_value

    def _validate_path_param(self, param_name: str, value: Any) -> str:
        """Validate path parameters."""
        path_str = str(value).strip().strip("\"'")  # Remove quotes
        
        if not path_str:
            raise InvalidValueError(f"Path parameter '{param_name}' cannot be empty")
            
        # For required paths, check if they exist (except report_path which is output)
        if param_name in self.REQUIRED_PARAMS and param_name != "report_path":
            path_obj = Path(path_str)
            if not path_obj.exists():
                raise InvalidValueError(
                    f"Path for parameter '{param_name}' does not exist: {path_str}"
                )
                
        return path_str

    def _validate_dependencies(self, config: Dict[str, Any]) -> None:
        """Validate parameter dependencies and consistency."""
        # Example: Check slew measurement thresholds
        slew_params = [
            ("measure_slew_lower_rise", "measure_slew_upper_rise"),
            ("measure_slew_lower_fall", "measure_slew_upper_fall"),
        ]
        
        for lower_param, upper_param in slew_params:
            if lower_param in config and upper_param in config:
                lower_val = config[lower_param]
                upper_val = config[upper_param]
                if lower_val >= upper_val:
                    raise InvalidValueError(
                        f"Parameter '{lower_param}' ({lower_val}) must be less than '{upper_param}' ({upper_val})"
                    )
                    
        # Check capacitance measurement thresholds
        cap_params = [
            ("measure_cap_lower_rise", "measure_cap_upper_rise"),
            ("measure_cap_lower_fall", "measure_cap_upper_fall"),
        ]
        
        for lower_param, upper_param in cap_params:
            if lower_param in config and upper_param in config:
                lower_val = config[lower_param]
                upper_val = config[upper_param]
                if lower_val >= upper_val:
                    raise InvalidValueError(
                        f"Parameter '{lower_param}' ({lower_val}) must be less than '{upper_param}' ({upper_val})"
                    )

    def get_parameter_info(self, param_name: str) -> Dict[str, Any]:
        """
        Get information about a parameter.
        
        Args:
            param_name: Name of the parameter
            
        Returns:
            Dictionary with parameter information
        """
        info = {
            "name": param_name,
            "required": param_name in self.REQUIRED_PARAMS,
        }
        
        if param_name in self.NUMERIC_PARAMS:
            info["type"] = "numeric"
            if param_name in self.PARAM_RANGES:
                info["range"] = self.PARAM_RANGES[param_name]
            if param_name in self.POSITIVE_PARAMS:
                info["constraint"] = "positive"
        elif param_name in self.STRING_PARAMS:
            info["type"] = "string"
            if param_name == "spice_simulator":
                info["valid_values"] = list(self.VALID_SIMULATORS)
        elif param_name in self.PATH_PARAMS:
            info["type"] = "path"
        else:
            info["type"] = "unknown"
            
        return info
