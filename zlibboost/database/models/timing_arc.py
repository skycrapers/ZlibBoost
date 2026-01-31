"""
TimingArc model for timing arcs in cell characterization.

This module defines the TimingArc class for managing timing arcs
that represent timing relationships between cell pins.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .cell import Cell
from dataclasses import dataclass, field
from enum import Enum

from zlibboost.core.exceptions import ValidationError



class TimingType(Enum):
    """Enumeration of timing arc types."""
    COMBINATIONAL = "combinational"
    RISING_EDGE = "rising_edge"
    FALLING_EDGE = "falling_edge"
    SETUP_RISING = "setup_rising"
    SETUP_FALLING = "setup_falling"
    HOLD_RISING = "hold_rising"
    HOLD_FALLING = "hold_falling"
    RECOVERY_RISING = "recovery_rising"
    RECOVERY_FALLING = "recovery_falling"
    REMOVAL_RISING = "removal_rising"
    REMOVAL_FALLING = "removal_falling"
    MIN_PULSE_WIDTH = "min_pulse_width"
    ASYNC = "async"
    HIDDEN = "hidden"
    LEAKAGE_POWER = "leakage_power"


class TableType(Enum):
    """Enumeration of timing table types."""
    CELL_RISE = "cell_rise"
    CELL_FALL = "cell_fall"
    RISE_TRANSITION = "rise_transition"
    FALL_TRANSITION = "fall_transition"
    RISE_CONSTRAINT = "rise_constraint"
    FALL_CONSTRAINT = "fall_constraint"
    RISE_POWER = "rise_power"
    FALL_POWER = "fall_power"
    LEAKAGE_POWER = "leakage_power"


class PinDirection(Enum):
    """Enumeration of pin directions."""
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"


class TransitionDirection(Enum):
    """Enumeration of transition directions."""
    RISE = "rise"
    FALL = "fall"


ALL_TIMING_TYPES = {e.value for e in TimingType}
ALL_TABLE_TYPES = {e.value for e in TableType}
ALL_PIN_DIRECTIONS = {e.value for e in PinDirection}
ALL_TRANSITION_DIRECTIONS = {e.value for e in TransitionDirection}
@dataclass
class TimingArc:
    """
    Represents a timing arc between two pins in a cell.

    A timing arc defines the timing relationship between an input pin
    (or clock pin) and an output pin, including delay, transition time,
    constraint information, and simulation results.

    Attributes:
        pin: Output pin name
        pin_direction: Direction of the output pin
        pin_transition: Output transition direction ('rise' or 'fall')
        related_pin: Input/clock pin name ('-' for hidden arcs)
        related_transition: Related pin transition direction
        timing_type: Type of timing arc
        table_type: Type of timing table
        condition: Timing condition expression (auto-generated from condition_dict)
        condition_dict: Timing condition as dictionary {pin_name: value}
        metadata: Additional arc metadata

        # Simulation result fields
        delay_values: 2D table for delay values (cell_rise/cell_fall)
        transition_values: 2D table for transition time values (rise_transition/fall_transition)
        power_values: 2D table for power values (rise_power/fall_power)
        constraint_values: 2D table for constraint values (setup/hold/recovery/removal)
        leakage_power: Single leakage power value for leakage arcs
        input_capacitance: Input capacitance value

        # Simulation metadata
        simulation_metadata: Additional simulation information (PVT conditions, etc.)
        is_simulated: Flag indicating if this arc has been simulated
    """
    pin: str
    pin_direction: str
    pin_transition: str
    related_pin: str
    related_transition: str
    timing_type: str
    table_type: str

    condition: str
    condition_dict: Dict[str, str] = field(default_factory=dict)
    output_condition_dict: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Simulation result fields
    delay_values: Optional[List[List[float]]] = None
    transition_values: Optional[List[List[float]]] = None
    power_values: Optional[List[List[float]]] = None
    constraint_values: Optional[List[List[float]]] = None
    mpw_values: Optional[List[float]] = None
    leakage_power: Optional[float] = None
    input_capacitance: Optional[float] = None

    # Simulation metadata
    simulation_metadata: Dict[str, Any] = field(default_factory=dict)
    is_simulated: bool = False
    
    def __post_init__(self):
        self._validate()



    def reconstruct_condition(self):
        """从condition_dict重构condition字符串

        Returns:
            str: condition字符串，如 "A*!B"
        """
        if not self.condition_dict:
            self.condition = ""
            return
        
        # Sort pins alphabetically for consistent output
        sorted_pins = sorted(self.condition_dict.keys())
        terms = []
        
        for pin in sorted_pins:
            value = self.condition_dict[pin]
            if value == "1":
                terms.append(pin)
            elif value == "0":
                terms.append(f"!{pin}")
        
        self.condition = "*".join(terms)

    def get_condition_inputs(self, cell: "Cell" | None = None) -> Dict[str, str]:
        """
        Return a mapping of input/control pins constrained by this arc.
        """

        inputs, _ = self._partition_conditions(cell)
        return inputs

    def get_condition_outputs(self, cell: "Cell" | None = None) -> Dict[str, str]:
        """
        Return a mapping of output pins constrained by this arc.
        """

        _, outputs = self._partition_conditions(cell)
        return outputs

    def condition_string(
        self,
        *,
        cell: "Cell" | None = None,
        include_outputs: bool = False,
        include_internal: bool = True,
    ) -> str:
        """
        Construct a condition string, optionally including output pins.

        Args:
            cell: Optional cell context used to classify output pins.
            include_outputs: When True, append output-pin constraints.
            include_internal: When False, omit internal state pins even if outputs
                should be included. This primarily keeps serialization output
                aligned with Liberty expectations where when-conditions are
                expressed using externally visible pins.
        """

        inputs, outputs = self._partition_conditions(cell)
        components = dict(inputs)
        if include_outputs:
            merged_outputs = outputs
            if not include_internal:
                internal_pins: set[str] = set()
                if cell is not None:
                    try:
                        internal_pins.update(cell.get_internal_pins())
                    except Exception:  # pragma: no cover - defensive guard
                        pass
                else:
                    # Fallback heuristic for legacy-generated names when cell context
                    # is unavailable. This keeps behaviour stable in older tests.
                    internal_pins = {pin for pin in outputs if pin.endswith("_state")}

                if internal_pins:
                    merged_outputs = {
                        pin: value
                        for pin, value in outputs.items()
                        if pin not in internal_pins
                    }
            components.update(merged_outputs)

        if not components:
            return ""

        terms: List[str] = []
        for pin in sorted(components.keys()):
            value = components[pin]
            if value == "1":
                terms.append(pin)
            elif value == "0":
                terms.append(f"!{pin}")
            else:
                terms.append(f"{pin}={value}")
        return "*".join(terms)

    def _normalize_conditions(self, cell: "Cell" | None) -> None:
        if cell is None:
            self.condition_dict = {
                pin: self._normalize_condition_value(value)
                for pin, value in (self.condition_dict or {}).items()
            }
            self.output_condition_dict = {
                pin: self._normalize_condition_value(value)
                for pin, value in (self.output_condition_dict or {}).items()
            }
            return

        inputs, outputs = self._partition_conditions(cell)
        self.condition_dict = inputs
        self.output_condition_dict = outputs

    def normalize_conditions(self, cell: "Cell" | None) -> None:
        """Normalize condition dictionaries and refresh the condition string."""

        self._normalize_conditions(cell)
        if cell is not None:
            # For leakage_power arcs, include output pins in condition string
            # to distinguish different output states (e.g., Q=0 vs Q=1)
            include_outputs = self.timing_type == 'leakage_power'
            self.condition = self.condition_string(
                cell=cell,
                include_outputs=include_outputs,
                include_internal=False  # Exclude internal state pins from condition
            )
        else:
            self.reconstruct_condition()

    def _partition_conditions(
        self,
        cell: "Cell" | None,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        raw_conditions = getattr(self, "condition_dict", None)
        condition_dict = dict(raw_conditions) if raw_conditions else {}

        # Merge pre-existing output conditions to the lookup table
        outputs: Dict[str, str] = {
            pin: self._normalize_condition_value(value)
            for pin, value in (self.output_condition_dict or {}).items()
        }
        inputs: Dict[str, str] = {}

        if not condition_dict:
            return inputs, outputs

        output_pins: set[str] = set(outputs.keys())
        if cell is not None:
            try:
                output_pins.update(cell.get_output_pins())
                # 内部状态引脚在仿真中不可直接驱动，按输出约束处理，避免被误判成输入条件
                output_pins.update(cell.get_internal_pins())
            except Exception:  # pragma: no cover - defensive
                pass
        else:
            if (
                self.pin
                and self.pin != "-"
                and self.pin_direction in {"output", "inout"}
            ):
                output_pins.add(self.pin)

        for pin, value in condition_dict.items():
            normalized = self._normalize_condition_value(value)
            if pin in output_pins:
                outputs[pin] = normalized
            else:
                inputs[pin] = normalized

        return inputs, outputs

    @staticmethod
    def _normalize_condition_value(value: Any) -> str:
        if isinstance(value, str):
            if value in {"0", "1"}:
                return value
            if value.lower() in {"true", "high"}:
                return "1"
            if value.lower() in {"false", "low"}:
                return "0"
        if value in (1, True):
            return "1"
        if value in (0, False):
            return "0"
        return str(value)

    def set_delay_values(self, values: List[List[float]]) -> None:
        """设置延迟值表

        Args:
            values: 2D延迟值表，对应index_1 x index_2的查找表
        """
        self.delay_values = values
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_transition_values(self, values: List[List[float]]) -> None:
        """设置转换时间值表

        Args:
            values: 2D转换时间值表，对应index_1 x index_2的查找表
        """
        self.transition_values = values
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_power_values(self, values: List[List[float]]) -> None:
        """设置功耗值表

        Args:
            values: 2D功耗值表，对应index_1 x index_2的查找表
        """
        self.power_values = values
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_constraint_values(self, values: List[List[float]]) -> None:
        """设置约束值表

        Args:
            values: 2D约束值表，对应index_1 x index_2的查找表
        """
        self.constraint_values = values
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_mpw_values(self, values: List[float]) -> None:
        """设置最小脉宽（MPW）一维约束表。

        Args:
            values: 按 index_1 顺序排列的 MPW 数值，通常长度等于约束模板的行数。
        """
        if values is None:
            self.mpw_values = None
            return

        sanitized: List[float] = []
        for raw in values:
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"MPW value '{raw}' is not numeric") from exc
            if number < 0:
                raise ValidationError("MPW values must be non-negative")
            sanitized.append(number)

        self.mpw_values = sanitized
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_leakage_power(self, value: float) -> None:
        """设置泄漏功耗值

        Args:
            value: 泄漏功耗值（单个数值）
        """
        self.leakage_power = value
        self.is_simulated = True
        self._update_simulation_timestamp()

    def set_input_capacitance(self, value: float) -> None:
        """设置输入电容值

        Args:
            value: 输入电容值
        """
        self.input_capacitance = value
        self.is_simulated = True
        self._update_simulation_timestamp()

    def _update_simulation_timestamp(self) -> None:
        """更新仿真时间戳"""
        import time
        self.simulation_metadata['last_simulated'] = time.time()

    def has_simulation_results(self) -> bool:
        """检查是否有仿真结果

        Returns:
            bool: 如果有任何仿真结果则返回True
        """
        return (self.delay_values is not None or
                self.transition_values is not None or
                self.power_values is not None or
                self.constraint_values is not None or
                self.mpw_values is not None or
                self.leakage_power is not None or
                self.input_capacitance is not None)

    def get_simulation_result_summary(self) -> Dict[str, Any]:
        """获取仿真结果摘要

        Returns:
            Dict: 仿真结果摘要信息
        """
        summary: Dict[str, Any] = {
            'is_simulated': self.is_simulated,
            'has_delay_values': self.delay_values is not None,
            'has_transition_values': self.transition_values is not None,
            'has_power_values': self.power_values is not None,
            'has_constraint_values': self.constraint_values is not None,
            'has_leakage_power': self.leakage_power is not None,
            'has_input_capacitance': self.input_capacitance is not None,
        }

        # 添加表格维度信息
        if self.delay_values:
            summary['delay_table_size'] = f"{len(self.delay_values)}x{len(self.delay_values[0]) if self.delay_values[0] else 0}"
        if self.transition_values:
            summary['transition_table_size'] = f"{len(self.transition_values)}x{len(self.transition_values[0]) if self.transition_values[0] else 0}"
        if self.power_values:
            summary['power_table_size'] = f"{len(self.power_values)}x{len(self.power_values[0]) if self.power_values[0] else 0}"
        if self.constraint_values:
            summary['constraint_table_size'] = f"{len(self.constraint_values)}x{len(self.constraint_values[0]) if self.constraint_values[0] else 0}"
        if self.mpw_values:
            summary['mpw_vector_length'] = len(self.mpw_values)

        # 添加仿真元数据
        if self.simulation_metadata:
            summary['simulation_metadata_dict'] = self.simulation_metadata.copy()

        return summary

    @classmethod
    def create_validated_arc(cls, cell: 'Cell', **kwargs) -> 'TimingArc':
        """
        创建并验证 TimingArc。
        
        这是创建 TimingArc 的唯一推荐方式，确保创建时就完成所有验证。
        TimingArc 必须属于某个 Cell，在创建时就应该提供 Cell 进行验证。
        
        Args:
            cell: Cell 对象，TimingArc 必须属于某个 Cell
            **kwargs: TimingArc 的其他参数
            
        Returns:
            TimingArc: 完全验证过的 TimingArc 对象
            
        Raises:
            ValidationError: 如果验证失败
        """
        # 创建 TimingArc 对象
        arc = cls(**kwargs)
        arc.normalize_conditions(cell)

        from .timing_arc_validator import TimingArcValidator
        TimingArcValidator.validate_with_cell(arc, cell)

        return arc
    
    def _validate(self) -> None:
        """
        Basic field validation - only essential checks.
        
        Validates basic data integrity, not business logic.
        Business logic validation is handled by TimingArcValidator.
        
        Raises:
            ValidationError: If basic data is invalid
        """
        # Essential non-empty checks
        if not self.pin:
            raise ValidationError("Pin name cannot be empty")
        
        if not self.timing_type:
            raise ValidationError("Timing type cannot be empty")
        
        if not self.table_type:
            raise ValidationError("Table type cannot be empty")
        
        # Enum value validation
        valid_timing_types = {e.value for e in TimingType}
        if self.timing_type not in valid_timing_types:
            raise ValidationError(
                f"Invalid timing type '{self.timing_type}'. "
                f"Must be one of: {valid_timing_types}"
            )
        
        valid_table_types = {e.value for e in TableType}
        if self.table_type not in valid_table_types:
            raise ValidationError(
                f"Invalid table type '{self.table_type}'. "
                f"Must be one of: {valid_table_types}"
            )
    

    
    @property
    def is_hidden_arc(self) -> bool:
        """Check if this is a hidden power arc."""
        return self.timing_type == TimingType.HIDDEN.value
    
    @property
    def is_constraint_arc(self) -> bool:
        """Check if this is a constraint arc."""
        constraint_types = {
            TimingType.SETUP_RISING.value,
            TimingType.SETUP_FALLING.value,
            TimingType.HOLD_RISING.value,
            TimingType.HOLD_FALLING.value,
            TimingType.RECOVERY_RISING.value,
            TimingType.RECOVERY_FALLING.value,
            TimingType.REMOVAL_RISING.value,
            TimingType.REMOVAL_FALLING.value,
            TimingType.MIN_PULSE_WIDTH.value
        }
        return self.timing_type in constraint_types
    
    @property
    def is_delay_arc(self) -> bool:
        """Check if this is a delay arc."""
        delay_types = {
            TimingType.COMBINATIONAL.value,
            TimingType.RISING_EDGE.value,
            TimingType.FALLING_EDGE.value
        }
        return self.timing_type in delay_types
    
    @property
    def is_power_arc(self) -> bool:
        """Check if this is a power arc."""
        power_table_types = {
            TableType.RISE_POWER.value,
            TableType.FALL_POWER.value
        }
        return self.table_type in power_table_types
    
    @property
    def is_transition_arc(self) -> bool:
        """Check if this is a transition time arc."""
        transition_table_types = {
            TableType.RISE_TRANSITION.value,
            TableType.FALL_TRANSITION.value
        }
        return self.table_type in transition_table_types
    
    def get_arc_key(self) -> str:
        """
        Generate a unique key for this timing arc.
        
        Returns:
            String key that uniquely identifies this arc
        """
        return (
            f"{self.pin}:{self.related_pin}:"
            f"{self.timing_type}:{self.table_type}:"
            f"{self.condition}"
        )

    def __str__(self) -> str:
        """Concise string representation of timing arc (compatible with tests)."""
        # Format the basic arc path
        if self.related_pin == "-":
            path = f"TimingArc({self.pin})"
        else:
            path = f"TimingArc({self.related_pin} -> {self.pin})"
        
        # Add transition information
        trans = ""
        if self.related_transition != "-" and self.pin_transition != "-":
            trans = f" [{self.related_transition}->{self.pin_transition}]"
        elif self.pin_transition != "-":
            trans = f" [{self.pin_transition}]"
        type_table = f" ({self.timing_type}, {self.table_type})"
        condition_str = f" when {self.condition}" if self.condition else ""
        return f"{path}{trans}{type_table}{condition_str}"
    
    def __repr__(self) -> str:
        """Detailed string representation for debugging."""
        return (
            f"TimingArc(pin='{self.pin}', related_pin='{self.related_pin}', "
            f"timing_type='{self.timing_type}', table_type='{self.table_type}', "
            f"condition='{self.condition}', simulated={self.is_simulated})"
        )
    
    def print_details(self) -> str:
        """
        Generate a detailed, formatted string representation.
        
        Returns:
            Formatted multi-line string with all arc information
        """
        lines = []
        
        # Header with arc identification
        header = f"┌─ TimingArc: {self.related_pin} → {self.pin} ─"
        lines.append(header + "─" * (60 - len(header)))
        
        # Basic arc information
        lines.append(f"│ Type: {self.timing_type}")
        lines.append(f"│ Table: {self.table_type}")
        
        # Pin information
        if self.related_pin != "-":
            lines.append(f"│ Related Pin: {self.related_pin} ({self.related_transition})")
        lines.append(f"│ Output Pin: {self.pin} ({self.pin_transition})")
        
        # Condition
        if self.condition:
            lines.append(f"│ Condition: {self.condition}")
        
        # Simulation status
        status_icon = "✓" if self.is_simulated else "✗"
        lines.append(f"│ Simulated: {status_icon} {self.is_simulated}")
        
        # Results summary
        if self.has_simulation_results():
            lines.append("│ Results:")
            if self.delay_values:
                size = f"{len(self.delay_values)}×{len(self.delay_values[0])}"
                lines.append(f"│   └─ Delay: {size} table")
            if self.transition_values:
                size = f"{len(self.transition_values)}×{len(self.transition_values[0])}"
                lines.append(f"│   └─ Transition: {size} table")
            if self.power_values:
                size = f"{len(self.power_values)}×{len(self.power_values[0])}"
                lines.append(f"│   └─ Power: {size} table")
            if self.constraint_values:
                size = f"{len(self.constraint_values)}×{len(self.constraint_values[0])}"
                lines.append(f"│   └─ Constraint: {size} table")
            if self.leakage_power is not None:
                lines.append(f"│   └─ Leakage: {self.leakage_power:.2e} W")
            if self.input_capacitance is not None:
                lines.append(f"│   └─ Input Cap: {self.input_capacitance:.2e} F")
        
        # Metadata
        if self.metadata:
            lines.append("│ Metadata:")
            for key, value in self.metadata.items():
                lines.append(f"│   └─ {key}: {value}")
        
        lines.append("└" + "─" * 59)
        
        return "\n".join(lines)
    
    def print_compact(self) -> str:
        """
        Generate a compact, one-line representation for tables.
        
        Returns:
            Compact string suitable for table display
        """
        # Status icon
        status = "✓" if self.is_simulated else "○"
        
        # Arc path
        if self.related_pin == "-":
            path = f"({self.pin})"
        else:
            path = f"{self.related_pin}→{self.pin}"
        
        # Transitions
        if self.related_transition != "-" and self.pin_transition != "-":
            trans = f"{self.related_transition[0].upper()}{self.pin_transition[0].upper()}"
        elif self.pin_transition != "-":
            trans = f"_{self.pin_transition[0].upper()}"
        else:
            trans = "__"
        
        # Type abbreviation
        type_abbrev = {
            "combinational": "COMB",
            "rising_edge": "RISE",
            "falling_edge": "FALL",
            "setup_rising": "SETUP_R",
            "setup_falling": "SETUP_F",
            "hold_rising": "HOLD_R",
            "hold_falling": "HOLD_F",
            "recovery_rising": "RECOV_R",
            "recovery_falling": "RECOV_F",
            "removal_rising": "REMOV_R",
            "removal_falling": "REMOV_F",
            "min_pulse_width": "MPW",
            "hidden": "HIDDEN",
            "leakage_power": "LEAK"
        }.get(self.timing_type, self.timing_type[:8].upper())
        
        # Condition
        cond = f" ({self.condition})" if self.condition else ""
        
        return f"{status} {path:<12} {trans} {type_abbrev:<8}{cond}"
