"""
Waveform model for driver waveforms.

This module defines the Waveform class for managing driver waveforms
used in timing characterization simulations.
"""

from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
import numpy as np

from zlibboost.core.exceptions import ValidationError


@dataclass
class Waveform:
    """
    Represents a driver waveform with timing and amplitude information.
    
    Driver waveforms define the input stimulus patterns used in timing
    characterization, including delay waveforms and constraint waveforms.
    
    Attributes:
        name: Waveform name (e.g., 'delay_waveform', 'constraint_waveform')
        waveform_type: Type of waveform ('delay', 'constraint')
        index_1: First dimension index values (input transition time)
        index_2: Second dimension index values (output load capacitance)
        values: 2D array of waveform values
        metadata: Additional waveform metadata
    """
    name: str
    waveform_type: str
    index_1: List[float]
    index_2: List[float]
    values: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate waveform data after initialization."""
        self._validate()
    
    def _validate(self) -> None:
        """
        Validate waveform data for consistency and correctness.
        
        Raises:
            ValidationError: If waveform data is invalid
        """
        if not self.name:
            raise ValidationError("Waveform name cannot be empty")
        
        if not self.waveform_type:
            raise ValidationError("Waveform type cannot be empty")
        
        valid_types = {'delay', 'constraint'}
        if self.waveform_type not in valid_types:
            raise ValidationError(
                f"Invalid waveform type '{self.waveform_type}'. "
                f"Must be one of: {valid_types}"
            )
        
        if not self.index_1:
            raise ValidationError("index_1 cannot be empty")
        
        if not self.index_2:
            raise ValidationError("index_2 cannot be empty")
        
        # Validate index values are numeric and sorted
        try:
            index_1_array = np.array(self.index_1, dtype=float)
            index_2_array = np.array(self.index_2, dtype=float)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Index values must be numeric: {e}")
        
        if not np.all(index_1_array[:-1] <= index_1_array[1:]):
            raise ValidationError("index_1 values must be in non-decreasing order")
        
        if not np.all(index_2_array[:-1] <= index_2_array[1:]):
            raise ValidationError("index_2 values must be in non-decreasing order")
        
        # Validate values array
        if not isinstance(self.values, np.ndarray):
            try:
                self.values = np.array(self.values, dtype=float)
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Waveform values must be numeric: {e}")
        
        expected_shape = (len(self.index_1), len(self.index_2))
        if self.values.shape != expected_shape:
            raise ValidationError(
                f"Waveform values shape {self.values.shape} does not match "
                f"expected shape {expected_shape}"
            )
        
        # Check for invalid values (NaN, inf)
        if np.any(np.isnan(self.values)):
            raise ValidationError("Waveform values cannot contain NaN")
        
        if np.any(np.isinf(self.values)):
            raise ValidationError("Waveform values cannot contain infinity")
    
    @property
    def dimensions(self) -> tuple[int, int]:
        """Get waveform dimensions as (rows, columns)."""
        return len(self.index_1), len(self.index_2)
    
    @property
    def is_square(self) -> bool:
        """Check if waveform has square dimensions."""
        return len(self.index_1) == len(self.index_2)
    
    @property
    def value_range(self) -> tuple[float, float]:
        """Get the range of waveform values."""
        return float(np.min(self.values)), float(np.max(self.values))
    
    def get_value(self, index_1_idx: int, index_2_idx: int) -> float:
        """
        Get waveform value at specific indices.
        
        Args:
            index_1_idx: Index for first dimension
            index_2_idx: Index for second dimension
            
        Returns:
            Waveform value at specified indices
            
        Raises:
            IndexError: If indices are out of bounds
        """
        try:
            return float(self.values[index_1_idx, index_2_idx])
        except IndexError as e:
            raise IndexError(
                f"Index ({index_1_idx}, {index_2_idx}) is out of bounds "
                f"for waveform with shape {self.values.shape}"
            ) from e
    
    def interpolate_value(self, index_1_val: float, index_2_val: float) -> float:
        """
        Interpolate waveform value for given index values.
        
        Args:
            index_1_val: Value for first dimension
            index_2_val: Value for second dimension
            
        Returns:
            Interpolated waveform value
            
        Raises:
            ValueError: If values are out of range
        """
        # Find interpolation indices for both dimensions
        i1_lower, i1_upper, w1 = self._interpolate_indices(index_1_val, self.index_1)
        i2_lower, i2_upper, w2 = self._interpolate_indices(index_2_val, self.index_2)
        
        # Bilinear interpolation
        v00 = self.values[i1_lower, i2_lower]
        v01 = self.values[i1_lower, i2_upper]
        v10 = self.values[i1_upper, i2_lower]
        v11 = self.values[i1_upper, i2_upper]
        
        # Interpolate along index_2 first
        v0 = v00 * (1 - w2) + v01 * w2
        v1 = v10 * (1 - w2) + v11 * w2
        
        # Then interpolate along index_1
        result = v0 * (1 - w1) + v1 * w1
        
        return float(result)
    
    def _interpolate_indices(self, value: float, indices: List[float]) -> tuple[int, int, float]:
        """
        Find interpolation indices and weight for a given value.
        
        Args:
            value: Value to interpolate
            indices: List of index values
            
        Returns:
            Tuple of (lower_index, upper_index, weight)
        """
        indices_array = np.array(indices)
        
        # Check bounds
        if value < indices_array[0] or value > indices_array[-1]:
            raise ValueError(
                f"Value {value} is out of range [{indices_array[0]}, {indices_array[-1]}]"
            )
        
        # Find interpolation indices
        upper_idx = np.searchsorted(indices_array, value, side='right')
        
        if upper_idx == 0:
            return 0, 0, 0.0
        elif upper_idx == len(indices_array):
            return len(indices_array) - 1, len(indices_array) - 1, 0.0
        else:
            lower_idx = upper_idx - 1
            lower_val = indices_array[lower_idx]
            upper_val = indices_array[upper_idx]
            weight = (value - lower_val) / (upper_val - lower_val)
            return lower_idx, upper_idx, weight
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert waveform to dictionary representation."""
        return {
            'name': self.name,
            'type': self.waveform_type,
            'index_1': self.index_1.copy(),
            'index_2': self.index_2.copy(),
            'values': self.values.tolist(),
            'dimensions': self.dimensions,
            'value_range': self.value_range,
            'metadata': self.metadata.copy()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Waveform':
        """
        Create Waveform instance from dictionary.
        
        Args:
            data: Dictionary containing waveform data
            
        Returns:
            Waveform instance
            
        Raises:
            ValidationError: If required fields are missing
        """
        required_fields = {'name', 'type', 'index_1', 'index_2', 'values'}
        missing_fields = required_fields - set(data.keys())
        if missing_fields:
            raise ValidationError(f"Missing required fields: {missing_fields}")
        
        return cls(
            name=data['name'],
            waveform_type=data['type'],
            index_1=list(data['index_1']),
            index_2=list(data['index_2']),
            values=np.array(data['values']),
            metadata=data.get('metadata', {})
        )
    
    def __str__(self) -> str:
        """String representation of waveform."""
        return (
            f"Waveform(name='{self.name}', type='{self.waveform_type}', "
            f"dimensions={self.dimensions})"
        )
    
    def __repr__(self) -> str:
        """Detailed string representation of waveform."""
        return (
            f"Waveform(name='{self.name}', waveform_type='{self.waveform_type}', "
            f"index_1={self.index_1}, index_2={self.index_2}, "
            f"values_shape={self.values.shape}, metadata={self.metadata})"
        )
