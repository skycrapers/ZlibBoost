"""
Cell model for standard cell definitions.

This module defines the Cell class for managing standard cell information
including pins, timing arcs, and logical functions.
"""

from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass, field

from zlibboost.core.exceptions import ValidationError
from .timing_arc import TimingArc

if TYPE_CHECKING:
    from zlibboost.arc_generation.logic_analyzer import LogicFunctionAnalyzer


# Pin category constants
class PinCategory:
    """Pin category constants for consistent categorization."""
    # Clock related
    CLOCK = 'clock'              # Clock pins (use with is_negative for edge polarity)
    
    # Enable related
    ENABLE = 'enable'            # Enable pins (use with is_negative for active level)
    
    # Scan chain related
    SCAN_ENABLE = 'scan_enable'  # Scan enable pins
    SCAN_IN = 'scan_in'          # Scan input pins
    
    # Data related
    DATA = 'data'                # Data pins
    
    # Asynchronous control
    ASYNC = 'async'              # Asynchronous pins
    RESET = 'reset'              # Reset pins (typically active low)
    SET = 'set'                  # Set pins (typically active low)
    
    # Synchronous control
    SYNC = 'sync'                # Synchronous pins
    

    # SPECIAL
    INTERNAL = 'internal'        # Internal pins

# All valid categories for validation
VALID_PIN_CATEGORIES = {
    PinCategory.CLOCK,
    PinCategory.ENABLE,
    PinCategory.SCAN_ENABLE,
    PinCategory.SCAN_IN,
    PinCategory.DATA,
    PinCategory.ASYNC,
    PinCategory.RESET,
    PinCategory.SET,
    PinCategory.SYNC,
    PinCategory.INTERNAL
}


@dataclass
class PinInfo:
    """
    Information about a cell pin.
    
    Attributes:
        name: Pin name
        direction: Pin direction ('input', 'output', 'inout')
        position: Position in vector string (0-based index)
        categories: Set of pin categories (e.g., 'clock', 'data', 'enable', 'reset')
        is_negative: Whether this is a negative/inverted pin
        capacitance: Input capacitance (for input pins)
        max_capacitance: Maximum load capacitance (for output pins)
        function: Logical function (for output pins)
        metadata: Additional pin metadata
    """
    name: str
    direction: str
    position: Optional[int] = None
    categories: Set[str] = field(default_factory=set)
    is_negative: bool = False
    capacitance: Optional[float] = None
    max_capacitance: Optional[float] = None
    function: Optional['LogicFunctionAnalyzer'] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate pin information after initialization."""
        if not self.name:
            raise ValidationError("Pin name cannot be empty")
        
        valid_directions = {'input', 'output', 'inout', 'internal'}
        if self.direction not in valid_directions:
            raise ValidationError(
                f"Invalid pin direction '{self.direction}'. "
                f"Must be one of: {valid_directions}"
            )
        

    
    def has_category(self, category: str) -> bool:
        """Check if pin has a specific category."""
        return category in self.categories
    
    def add_category(self, category: str) -> None:
        """Add a category to this pin.
        
        Args:
            category: Category to add (should be one of PinCategory constants)
            
        Raises:
            ValidationError: If category is invalid
        """
        if category not in VALID_PIN_CATEGORIES:
            raise ValidationError(
                f"Invalid pin category '{category}'. "
                f"Valid categories are: {sorted(VALID_PIN_CATEGORIES)}"
            )
        self.categories.add(category)
    
    def remove_category(self, category: str) -> None:
        """Remove a category from this pin."""
        self.categories.discard(category)
    
    def is_clock(self) -> bool:
        """Check if this is a clock pin."""
        return PinCategory.CLOCK in self.categories
    
    def is_data(self) -> bool:
        """Check if this is a data pin."""
        return PinCategory.DATA in self.categories
    
    def is_enable(self) -> bool:
        """Check if this is an enable pin."""
        return PinCategory.ENABLE in self.categories
    
    def is_reset(self) -> bool:
        """Check if this is a reset pin."""
        return PinCategory.RESET in self.categories
    
    def is_set(self) -> bool:
        """Check if this is a set pin."""
        return PinCategory.SET in self.categories
    
    def is_scan(self) -> bool:
        """Check if this is a scan-related pin."""
        return PinCategory.SCAN_ENABLE in self.categories or PinCategory.SCAN_IN in self.categories
    
    def is_async(self) -> bool:
        """Check if this is an asynchronous pin."""
        return PinCategory.ASYNC in self.categories

    def is_internal(self) -> bool:
        """Check if this is an internal pin."""
        return PinCategory.INTERNAL in self.categories


@dataclass
class Cell:
    """
    Represents a standard cell with pins, timing arcs, and functions.
    
    A cell defines the interface and behavior of a standard cell,
    including pin definitions, timing relationships, and logical functions.
    
    Attributes:
        name: Cell name
        pins: Dictionary mapping pin names to PinInfo objects
        pin_order: Ordered list of pin names for vector consistency
        timing_arcs: List of TimingArc objects
        delay_template: Name of delay template
        power_template: Name of power template
        constraint_template: Name of constraint template
        next_state_function: Name of next state function
        metadata: Additional cell metadata
        
    Note:
        Logical functions are stored in PinInfo.function for output pins.
        Use get_functions() to retrieve all functions or get_function(pin_name)
        for a specific pin's function.
    """
    name: str
    pins: Dict[str, PinInfo] = field(default_factory=dict)
    pin_order: List[str] = field(default_factory=list)  # Explicit pin ordering for vectors
    timing_arcs: List[TimingArc] = field(default_factory=list)
    delay_template: Optional[str] = None
    power_template: Optional[str] = None
    constraint_template: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate cell data after initialization."""
        self._validate()
    
    def _validate(self) -> None:
        """
        Validate cell data for consistency and correctness.
        
        Raises:
            ValidationError: If cell data is invalid
        """
        if not self.name:
            raise ValidationError("Cell name cannot be empty")
        
        # Validate that all pin references exist
        all_pin_names = set(self.pins.keys())
        
        # Validate pin_order contains only valid pins
        if self.pin_order:
            invalid_pins_in_order = [p for p in self.pin_order if p and p not in all_pin_names]
            if invalid_pins_in_order:
                raise ValidationError(f"Pin order contains unknown pins: {invalid_pins_in_order}")
        
        # Validate timing arcs reference valid pins
        for arc in self.timing_arcs:
            if arc.pin not in all_pin_names and arc.pin != '-':
                raise ValidationError(f"Timing arc references unknown pin: {arc.pin}")
            
            if arc.related_pin != '-' and arc.related_pin not in all_pin_names:
                raise ValidationError(f"Timing arc references unknown related pin: {arc.related_pin}")
    
    def add_pin(self, pin_info: PinInfo) -> None:
        """
        Add a pin to the cell.
        
        Args:
            pin_info: PinInfo object to add
            
        Raises:
            ValidationError: If pin already exists
        """
        if pin_info.name in self.pins:
            raise ValidationError(f"Pin '{pin_info.name}' already exists in cell")
        
        self.pins[pin_info.name] = pin_info
        
        # Add to pin_order for consistent vector ordering
        if pin_info.name not in self.pin_order:
            self.pin_order.append(pin_info.name)
            # Update position if not set
            if pin_info.position is None:
                pin_info.position = len(self.pin_order) - 1
    
    def get_pin_order(self) -> List[str]:
        """Get the canonical pin ordering for vectors.
        
        Returns a list of pin names in the order they appear in vectors.
        If pin_order is not explicitly set, returns pins in sorted order.
        """
        if self.pin_order:
            return self.pin_order.copy()
        else:
            # Fallback to sorted order
            return sorted(self.pins.keys())
    
    def set_pin_positions(self) -> None:
        """Update all PinInfo objects with their positions based on pin_order."""
        pin_order = self.get_pin_order()
        for idx, pin_name in enumerate(pin_order):
            if pin_name in self.pins:
                self.pins[pin_name].position = idx
    
    def add_timing_arc(self, timing_arc: TimingArc) -> None:
        """
        Add a timing arc to the cell.
        
        Args:
            timing_arc: TimingArc object to add
        """
        if hasattr(timing_arc, "normalize_conditions"):
            timing_arc.normalize_conditions(self)
        self.timing_arcs.append(timing_arc)
    
    def has_any_manual_arcs(self) -> bool:
        """
        Check if the cell has any manually defined timing arcs.
        
        Returns:
            bool: True if the cell has any manual arcs, False otherwise
        """
        return any(
            arc.metadata.get('source') == 'manual' 
            for arc in self.timing_arcs
        )
    
    def should_allow_auto_generation(self) -> bool:
        """
        Check if automatic arc generation should be allowed for this cell.
        
        Auto generation is only allowed if the cell has no manually defined arcs.
        This implements the cell-level conflict detection strategy where a cell
        is either fully manual or fully automatic.
        
        Returns:
            bool: True if auto generation is allowed, False if manual arcs exist
        """
        return not self.has_any_manual_arcs()
    
    def get_manual_arc_count(self) -> int:
        """
        Get the number of manually defined timing arcs.
        
        Returns:
            int: Number of manual arcs
        """
        return sum(
            1 for arc in self.timing_arcs 
            if arc.metadata.get('source') == 'manual'
        )
    
    def get_auto_arc_count(self) -> int:
        """
        Get the number of automatically generated timing arcs.
        
        Returns:
            int: Number of auto arcs
        """
        return sum(
            1 for arc in self.timing_arcs 
            if arc.metadata.get('source') == 'auto'
        )
    
    def get_arc_generation_summary(self) -> Dict[str, Any]:
        """
        Get a summary of arc generation for this cell.
        
        Returns:
            Dict containing arc statistics and generation status
        """
        manual_count = self.get_manual_arc_count()
        auto_count = self.get_auto_arc_count()
        total_count = len(self.timing_arcs)
        unknown_count = total_count - manual_count - auto_count
        
        return {
            'total_arcs': total_count,
            'manual_arcs': manual_count,
            'auto_arcs': auto_count,
            'unknown_source_arcs': unknown_count,
            'has_manual_arcs': manual_count > 0,
            'allows_auto_generation': manual_count == 0,
            'generation_mode': 'manual' if manual_count > 0 else 'auto'
        }
    
    def get_timing_arcs_for_pin(self, pin_name: str) -> List[TimingArc]:
        """
        Get all timing arcs for a specific pin.
        
        Args:
            pin_name: Name of the pin
            
        Returns:
            List of TimingArc objects for the pin
        """
        return [arc for arc in self.timing_arcs if arc.pin == pin_name]
    
    def get_timing_arcs_from_pin(self, pin_name: str) -> List[TimingArc]:
        """
        Get all timing arcs from a specific related pin.
        
        Args:
            pin_name: Name of the related pin
            
        Returns:
            List of TimingArc objects from the pin
        """
        return [arc for arc in self.timing_arcs if arc.related_pin == pin_name]
    
    def get_constraint_arcs(self) -> List[TimingArc]:
        """Get all constraint timing arcs."""
        return [arc for arc in self.timing_arcs if arc.is_constraint_arc]
    
    def get_delay_arcs(self) -> List[TimingArc]:
        """Get all delay timing arcs."""
        return [arc for arc in self.timing_arcs if arc.is_delay_arc]
    
    def get_power_arcs(self) -> List[TimingArc]:
        """Get all power timing arcs."""
        return [arc for arc in self.timing_arcs if arc.is_power_arc]
    
    def get_hidden_arcs(self) -> List[TimingArc]:
        """Get all hidden power arcs."""
        return [arc for arc in self.timing_arcs if arc.is_hidden_arc]
    
    @property
    def is_sequential(self) -> bool:
        """Check if cell is sequential (has clock pins or enable pins that act as clocks)."""

        if any(pin.is_clock() or pin.is_enable() for pin in self.pins.values()):
            return True
        return False
    
    @property
    def is_combinational(self) -> bool:
        """Check if cell is purely combinational."""
        return not self.is_sequential
    
    @property 
    def is_latch(self) -> bool:
        """Check if cell is a latch."""
        return any(pin.is_enable() for pin in self.pins.values())
    
    @property
    def has_async_pins(self) -> bool:
        """Check if cell has asynchronous pins."""
        return any(pin.is_async() or pin.is_reset() or pin.is_set() 
                  for pin in self.pins.values())
    
    def get_pins_by_category(self, category: str) -> List[str]:
        """Get all pins that have a specific category.
        
        Args:
            category: Category to search for
            
        Returns:
            List of pin names with the specified category
        """
        return [name for name, pin in self.pins.items() if pin.has_category(category)]
    
    def get_clock_pins(self) -> List[str]:
        """Get all clock pins."""
        return self.get_pins_by_category(PinCategory.CLOCK)

    def get_clock_positive_pins(self) -> List[str]:
        """Get all positive edge triggered clock pins."""
        return [name for name, pin in self.pins.items()
                if pin.is_clock() and not pin.is_negative]

    def get_clock_negative_pins(self) -> List[str]:
        """Get all negative edge triggered clock pins."""
        return self.get_negative_pins(PinCategory.CLOCK)

    def get_negative_pins(self, category: str) -> List[str]:
        """Get all negative pins of a specific category."""
        return [name for name, pin in self.pins.items() 
                if pin.has_category(category) and pin.is_negative]
    
    def get_enable_pins(self) -> List[str]:
        """Get all enable pins."""
        return self.get_pins_by_category(PinCategory.ENABLE)
    
    def get_data_pins(self) -> List[str]:
        """Get all data pins."""
        return self.get_pins_by_category(PinCategory.DATA)
    
    def get_async_pins(self) -> List[str]:
        """Get all asynchronous pins."""
        return self.get_pins_by_category(PinCategory.ASYNC)
    
    def get_sync_pins(self) -> List[str]:
        """Get all synchronous pins."""
        return self.get_pins_by_category(PinCategory.SYNC)
    
    def get_reset_pins(self) -> List[str]:
        """Get all reset pins."""
        return self.get_pins_by_category(PinCategory.RESET)
    
    def get_set_pins(self) -> List[str]:
        """Get all set pins."""
        return self.get_pins_by_category(PinCategory.SET)
    
    def get_scan_pins(self) -> List[str]:
        """Get all scan-related pins."""
        return [name for name, pin in self.pins.items() if pin.is_scan()]
    
    def get_scan_enable_pins(self) -> List[str]:
        """Get all scan enable pins."""
        return self.get_pins_by_category(PinCategory.SCAN_ENABLE)
    
    def get_scan_in_pins(self) -> List[str]:
        """Get all scan input pins."""
        return self.get_pins_by_category(PinCategory.SCAN_IN)
    
    def get_input_pins(self) -> List[str]:
        """Get all input pins."""
        return [name for name, pin in self.pins.items() if pin.direction == 'input']
    
    def get_output_pins(self) -> List[str]:
        """Get all output pins."""
        return [name for name, pin in self.pins.items() if pin.direction == 'output']

    def get_outpositive_pins(self) -> List[str]:
        """Get all output pins with positive (non-inverted) logic.

        This helper derives polarity from ``PinInfo.is_negative``. Prefer
        accessing ``PinInfo`` directly for new code to avoid relying on the
        legacy "outpositive" terminology.
        """
        return [name for name, pin in self.pins.items()
                if pin.direction == 'output' and not pin.is_negative]

    def get_outnegative_pins(self) -> List[str]:
        """Get all output pins with negative (inverted) logic.

        See :meth:`get_outpositive_pins` for migration notes.
        """
        return [name for name, pin in self.pins.items()
                if pin.direction == 'output' and pin.is_negative]

    def get_internal_pins(self) -> List[str]:
        """Get all internal pins."""
        return self.get_pins_by_category(PinCategory.INTERNAL)
    
    # Function-related convenience methods
    def get_function(self, pin_name: str) -> Optional['LogicFunctionAnalyzer']:
        """
        Get the logical function analyzer for a specific output pin.
        
        Args:
            pin_name: Name of the output pin
            
        Returns:
            The logical function analyzer, or None if not defined
            
        Raises:
            ValidationError: If pin doesn't exist or is not an output pin
        """
        if pin_name not in self.pins:
            raise ValidationError(f"Pin '{pin_name}' not found in cell '{self.name}'")
        
        pin = self.pins[pin_name]
        if pin.direction not in {'output', 'inout', 'internal'}:
            raise ValidationError(f"Pin '{pin_name}' is not an output pin")
        
        return pin.function
    
    def get_function_as_string(self, pin_name: str) -> Optional[str]:
        """
        Get the logical function string for a specific output pin.
        
        Args:
            pin_name: Name of the output pin
            
        Returns:
            The logical function string, or None if not defined
            
        Raises:
            ValidationError: If pin doesn't exist or is not an output pin
        """
        analyzer = self.get_function(pin_name)
        return analyzer.original_expr if analyzer else None
    
    def set_function(self, pin_name: str, function: str) -> None:
        """
        Set the logical function for a specific output pin.
        
        Args:
            pin_name: Name of the output pin
            function: Logical function string
            
        Raises:
            ValidationError: If pin doesn't exist or is not an output pin
        """
        from zlibboost.arc_generation.logic_analyzer import LogicFunctionAnalyzer

        if pin_name not in self.pins:
            raise ValidationError(f"Pin '{pin_name}' not found in cell '{self.name}'")
        
        pin = self.pins[pin_name]
        if pin.direction not in {'output', 'inout', 'internal'}:
            raise ValidationError(f"Pin '{pin_name}' is not an output pin")
        
        pin.function = LogicFunctionAnalyzer(function)
    
    def get_functions(self) -> Dict[str, 'LogicFunctionAnalyzer']:
        """
        Get all logical function analyzers for output pins.
        
        Returns:
            Dictionary mapping output pin names to their logical function analyzers.
            Only includes pins that have functions defined.
        """
        functions = {}
        for pin_name, pin in self.pins.items():
            if pin.direction in {'output', 'inout', 'internal'} and pin.function:
                functions[pin_name] = pin.function
        return functions
    
    def get_functions_as_strings(self) -> Dict[str, str]:
        """
        Get all logical functions for output pins as strings.
        
        Returns:
            Dictionary mapping output pin names to their logical function strings.
            Only includes pins that have functions defined.
        """
        functions = {}
        for pin_name, pin in self.pins.items():
            if pin.direction in {'output', 'inout', 'internal'} and pin.function:
                functions[pin_name] = pin.function.original_expr
        return functions
    
    def update_functions(self, functions: Dict[str, str]) -> None:
        """
        Update multiple logical functions at once.
        
        Args:
            functions: Dictionary mapping pin names to function strings
            
        Raises:
            ValidationError: If any pin doesn't exist or is not an output pin
        """
        for pin_name, function in functions.items():
            self.set_function(pin_name, function)
    
    def set_next_state_function(self, pin_name: str, function: str) -> None:
        """Set the next state function for the cell."""
        from zlibboost.arc_generation.logic_analyzer import LogicFunctionAnalyzer
        
        # Only add the pin if it doesn't already exist
        if pin_name not in self.pins:
            self.add_pin(PinInfo(name=pin_name, direction='internal', categories={PinCategory.INTERNAL}))
            self.set_function(pin_name, function)
        else:
            # Pin exists - check if it's an internal pin
            existing_pin = self.pins[pin_name]
            if existing_pin.direction == 'internal' or existing_pin.has_category(PinCategory.INTERNAL):
                # Pin is internal, just update the function
                self.set_function(pin_name, function)
            else:
                raise ValidationError(f"Error: the pin {pin_name} already exists, but it is not an internal pin")

    
    def __str__(self) -> str:
        """String representation of cell."""
        return (
            f"Cell(name='{self.name}', pins={len(self.pins)}, "
            f"timing_arcs={len(self.timing_arcs)}"
        )

    def __repr__(self) -> str:
        """Detailed string representation of cell."""
        return (
            f"Cell(name='{self.name}', pins={list(self.pins.keys())}, "
            f"timing_arcs={len(self.timing_arcs)}, "
            f"is_sequential={self.is_sequential}"
        )
