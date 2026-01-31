"""
Template model for timing library templates.

This module defines the Template class for managing timing templates
used in delay, power, and constraint characterization.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import numpy as np

from zlibboost.core.exceptions import ValidationError


@dataclass
class Template:
    """
    Represents a timing template with index dimensions and metadata.
    
    Templates define the lookup table structure for timing characterization,
    including delay templates, power templates, and constraint templates.
    
    Attributes:
        name: Template name (e.g., 'delay_template_7x7')
        template_type: Type of template ('delay', 'power', 'constraint')
        index_1: First dimension index values (input transition time or constraint)
        index_2: Second dimension index values (output load capacitance)
        metadata: Additional template metadata
    """
    name: str
    template_type: str
    index_1: List[float]
    index_2: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate template data after initialization."""
        self._validate()
    
    def _validate(self) -> None:
        """
        Validate template data for consistency and correctness.
        
        Raises:
            ValidationError: If template data is invalid
        """
        if not self.name:
            raise ValidationError("Template name cannot be empty")
        
        if not self.template_type:
            raise ValidationError("Template type cannot be empty")
        
        valid_types = {'delay', 'power', 'constraint'}
        if self.template_type not in valid_types:
            raise ValidationError(
                f"Invalid template type '{self.template_type}'. "
                f"Must be one of: {valid_types}"
            )
        
        if not self.index_1:
            raise ValidationError("index_1 cannot be empty")
        
        if not self.index_2:
            if not self.metadata.get("allow_empty_index_2"):
                raise ValidationError("index_2 cannot be empty")
        else:
            try:
                index_2_array = np.array(self.index_2, dtype=float)
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Index values must be numeric: {e}")

            if not np.all(index_2_array[:-1] <= index_2_array[1:]):
                raise ValidationError("index_2 values must be in non-decreasing order")

            if np.any(index_2_array < 0):
                raise ValidationError("index_2 values cannot be negative")

        # Validate index values are numeric and sorted
        try:
            index_1_array = np.array(self.index_1, dtype=float)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Index values must be numeric: {e}")

        if not np.all(index_1_array[:-1] <= index_1_array[1:]):
            raise ValidationError("index_1 values must be in non-decreasing order")

        if np.any(index_1_array < 0):
            raise ValidationError("index_1 values cannot be negative")
    
    @property
    def dimensions(self) -> tuple[int, int]:
        """Get template dimensions as (rows, columns)."""
        return len(self.index_1), len(self.index_2)
    
    @property
    def is_square(self) -> bool:
        """Check if template has square dimensions."""
        return len(self.index_1) == len(self.index_2)
    
    def get_index_range(self, dimension: int) -> tuple[float, float]:
        """
        Get the range of index values for a given dimension.
        
        Args:
            dimension: 1 for index_1, 2 for index_2
            
        Returns:
            Tuple of (min_value, max_value)
            
        Raises:
            ValueError: If dimension is not 1 or 2
        """
        if dimension == 1:
            return min(self.index_1), max(self.index_1)
        elif dimension == 2:
            return min(self.index_2), max(self.index_2)
        else:
            raise ValueError("Dimension must be 1 or 2")
    
    def interpolate_indices(self, value: float, dimension: int) -> tuple[int, int, float]:
        """
        Find interpolation indices and weight for a given value.
        
        Args:
            value: Value to interpolate
            dimension: 1 for index_1, 2 for index_2
            
        Returns:
            Tuple of (lower_index, upper_index, weight)
            where weight is the interpolation weight (0.0 to 1.0)
            
        Raises:
            ValueError: If dimension is invalid or value is out of range
        """
        if dimension == 1:
            indices = self.index_1
        elif dimension == 2:
            indices = self.index_2
        else:
            raise ValueError("Dimension must be 1 or 2")
        
        indices_array = np.array(indices)
        
        # Check bounds
        if value < indices_array[0] or value > indices_array[-1]:
            raise ValueError(
                f"Value {value} is out of range [{indices_array[0]}, {indices_array[-1]}]"
            )
        
        # Find interpolation indices
        upper_idx = np.searchsorted(indices_array, value, side='right')
        
        if upper_idx == 0:
            # Value equals first index
            return 0, 0, 0.0
        elif upper_idx == len(indices_array):
            # Value equals last index
            return len(indices_array) - 1, len(indices_array) - 1, 0.0
        else:
            # Interpolation needed
            lower_idx = upper_idx - 1
            lower_val = indices_array[lower_idx]
            upper_val = indices_array[upper_idx]
            weight = (value - lower_val) / (upper_val - lower_val)
            return lower_idx, upper_idx, weight
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary representation."""
        return {
            'name': self.name,
            'type': self.template_type,
            'index_1': self.index_1.copy(),
            'index_2': self.index_2.copy(),
            'dimensions': self.dimensions,
            'metadata': self.metadata.copy()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Template':
        """
        Create Template instance from dictionary.
        
        Args:
            data: Dictionary containing template data
            
        Returns:
            Template instance
            
        Raises:
            ValidationError: If required fields are missing
        """
        required_fields = {'name', 'type', 'index_1', 'index_2'}
        missing_fields = required_fields - set(data.keys())
        if missing_fields:
            raise ValidationError(f"Missing required fields: {missing_fields}")
        
        return cls(
            name=data['name'],
            template_type=data['type'],
            index_1=list(data['index_1']),
            index_2=list(data['index_2']),
            metadata=data.get('metadata', {})
        )
    
    def __str__(self) -> str:
        """String representation of template."""
        return (
            f"Template(name='{self.name}', type='{self.template_type}', "
            f"dimensions={self.dimensions})"
        )
    
    def __repr__(self) -> str:
        """Detailed string representation of template."""
        return (
            f"Template(name='{self.name}', template_type='{self.template_type}', "
            f"index_1={self.index_1}, index_2={self.index_2}, "
            f"metadata={self.metadata})"
        )
