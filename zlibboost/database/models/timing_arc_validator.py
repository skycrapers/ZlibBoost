"""
Timing Arc Validator - 统一的验证架构

这个模块提供了基于最终状态的验证逻辑，避免重复验证和外部依赖。
"""

from typing import Dict, Optional
from zlibboost.core.exceptions import ValidationError


class TimingArcValidator:
    """统一的时序弧验证器，基于最终状态进行验证。"""
    
    @classmethod
    def validate_semantics(cls, 
                          pin: str,
                          pin_transition: str,
                          related_pin: str, 
                          related_transition: Optional[str],
                          timing_type: str,
                          condition_dict: Dict[str, str]) -> None:
        """
        验证时序弧的语义正确性。
        
        这是核心验证方法，基于 TimingArc 的最终状态进行验证，
        不依赖 vector 字符串或 pin_order。
        
        Args:
            pin: 输出引脚名
            pin_transition: 输出引脚转换方向 
            related_pin: 相关引脚名
            related_transition: 相关引脚转换方向
            timing_type: 时序类型
            condition_dict: 静态条件字典
            
        Raises:
            ValidationError: 如果验证失败
        """
        # 构建 transitions 字典
        transitions = {}
        if pin != '-' and pin_transition in ['rise', 'fall']:
            transitions[pin] = pin_transition
        if related_pin != '-' and related_transition in ['rise', 'fall']:
            transitions[related_pin] = related_transition
        
        # 验证引脚不能同时有转换和静态条件
        transition_pins = set(transitions.keys())
        condition_pins = set(condition_dict.keys())
        overlap = transition_pins & condition_pins
        if overlap:
            raise ValidationError(
                f"Pins cannot have both transition and static condition: {overlap}"
            )
        
        # 验证静态条件值
        cls._validate_condition_values(condition_dict)
        
        # 验证基于时序类型的转换要求
        cls._validate_timing_type_transitions(timing_type, pin, related_pin, transitions)
    
    @classmethod
    def _validate_condition_values(cls, condition_dict: Dict[str, str]) -> None:
        """验证静态条件值的有效性。"""
        valid_values = {'0', '1'}
        for pin_name, value in condition_dict.items():
            if value not in valid_values:
                raise ValidationError(
                    f"Invalid logic value '{value}' for pin '{pin_name}'. "
                    f"Must be one of: {valid_values}"
                )
    
    @classmethod
    def _validate_timing_type_transitions(cls, timing_type: str, pin: str, 
                                        related_pin: str, transitions: Dict[str, str]) -> None:
        """验证基于时序类型的转换要求。"""
        
        if timing_type == "combinational":
            # 组合逻辑：输出引脚和输入引脚必须都有转换
            if pin not in transitions:
                raise ValidationError(f"Combinational arc: output pin '{pin}' must have transition")
            if related_pin != '-' and related_pin not in transitions:
                raise ValidationError(f"Combinational arc: input pin '{related_pin}' must have transition")
            
            # 只有这两个引脚应该有转换
            expected_pins = {pin}
            if related_pin != '-':
                expected_pins.add(related_pin)
            extra_transitions = set(transitions.keys()) - expected_pins
            if extra_transitions:
                raise ValidationError(f"Combinational arc: unexpected transitions on pins: {extra_transitions}")
        
        elif timing_type == "hidden":
            # 隐藏弧：只有输入引脚有转换
            if pin not in transitions:
                raise ValidationError(f"Hidden arc: input pin '{pin}' must have transition")
            if len(transitions) != 1:
                raise ValidationError(f"Hidden arc: must have exactly 1 transition, found {len(transitions)}")
        
        elif timing_type in ["rising_edge", "falling_edge"]:
            # 边沿触发：输出和时钟引脚都必须有转换
            if pin not in transitions:
                raise ValidationError(f"{timing_type} arc: output pin '{pin}' must have transition")
            if related_pin != '-' and related_pin not in transitions:
                raise ValidationError(f"{timing_type} arc: clock pin '{related_pin}' must have transition")
            
            # 验证时钟转换方向
            if related_pin != '-' and related_pin in transitions:
                expected_dir = 'rise' if timing_type == "rising_edge" else 'fall'
                if transitions[related_pin] != expected_dir:
                    raise ValidationError(
                        f"{timing_type} arc: clock pin '{related_pin}' must have {expected_dir} transition"
                    )
        
        elif timing_type in ["setup_rising", "setup_falling", "hold_rising", "hold_falling",
                             "recovery_rising", "recovery_falling", "removal_rising", "removal_falling"]:
            # 约束弧：数据和时钟引脚都必须有转换
            if pin not in transitions:
                raise ValidationError(f"{timing_type} arc: data pin '{pin}' must have transition")
            if related_pin != '-' and related_pin not in transitions:
                raise ValidationError(f"{timing_type} arc: clock pin '{related_pin}' must have transition")
            
            # 验证时钟转换方向
            if related_pin != '-' and related_pin in transitions:
                if timing_type.endswith("_rising"):
                    expected_dir = 'rise'
                elif timing_type.endswith("_falling"):
                    expected_dir = 'fall'
                else:
                    expected_dir = None
                
                if expected_dir and transitions[related_pin] != expected_dir:
                    raise ValidationError(
                        f"{timing_type} arc: clock pin '{related_pin}' must have {expected_dir} transition"
                    )
        
        elif timing_type == "min_pulse_width":
            # 最小脉宽：只有时钟引脚有转换
            if related_pin == '-':
                raise ValidationError("Min pulse width arc must have related_pin (clock)")
            if related_pin not in transitions:
                raise ValidationError(f"Min pulse width arc: clock pin '{related_pin}' must have transition")
            if len(transitions) != 1:
                raise ValidationError(f"Min pulse width arc: must have exactly 1 transition, found {len(transitions)}")
        
        elif timing_type == "async":
            # 异步弧：输出和控制引脚都必须有转换
            if pin not in transitions:
                raise ValidationError(f"Async arc: output pin '{pin}' must have transition")
            if related_pin != '-' and related_pin not in transitions:
                raise ValidationError(f"Async arc: control pin '{related_pin}' must have transition")
    
    @classmethod
    def validate_with_cell(cls, arc, cell) -> None:
        """
        验证时序弧与单元的集成。
        
        Args:
            arc: TimingArc 对象
            cell: Cell 对象
            
        Raises:
            ValidationError: 如果验证失败
        """
        # 验证引脚存在性
        all_pin_names = set(cell.pins.keys())
        
        if arc.pin not in all_pin_names and arc.pin != '-':
            raise ValidationError(f"Pin '{arc.pin}' not found in cell '{cell.name}'")
        
        if arc.related_pin != '-' and arc.related_pin not in all_pin_names:
            raise ValidationError(f"Related pin '{arc.related_pin}' not found in cell '{cell.name}'")
        
        # 验证引脚方向的业务逻辑合理性
        cls._validate_pin_directions(arc, cell)
        
        # 完整的业务逻辑验证
        cls.validate_complete_arc(arc)
    
    @classmethod
    def validate_complete_arc(cls, arc) -> None:
        """
        验证 TimingArc 的完整业务逻辑。
        
        包括字段验证和语义验证。
        
        Args:
            arc: TimingArc 对象
            
        Raises:
            ValidationError: 如果验证失败
        """
        # 验证字段完整性
        cls._validate_arc_fields(arc)
        
        # 验证 timing_type 和 related_pin 的一致性
        cls._validate_timing_type_consistency(arc)
        
        # 验证语义
        cls.validate_semantics(
            arc.pin, arc.pin_transition,
            arc.related_pin, arc.related_transition,
            arc.timing_type, arc.condition_dict or {}
        )
    
    @classmethod
    def _validate_arc_fields(cls, arc) -> None:
        """验证 TimingArc 字段的完整性。"""
        # 验证 pin_direction
        if not arc.pin_direction:
            raise ValidationError("Pin direction cannot be empty")
        
        from .timing_arc import PinDirection, TransitionDirection, TableType
        
        valid_pin_directions = {e.value for e in PinDirection}
        # Allow '-' for leakage power arcs
        if arc.table_type == TableType.LEAKAGE_POWER.value:
            valid_pin_directions.add('-')
        
        if arc.pin_direction not in valid_pin_directions:
            raise ValidationError(
                f"Invalid pin direction '{arc.pin_direction}'. "
                f"Must be one of: {valid_pin_directions}"
            )
        
        # 验证 pin_transition
        if not arc.pin_transition:
            raise ValidationError("Output transition cannot be empty")
        
        valid_transitions = {e.value for e in TransitionDirection}
        # Allow '-' for leakage power arcs
        if arc.table_type == TableType.LEAKAGE_POWER.value:
            valid_transitions.add('-')
        
        if arc.pin_transition not in valid_transitions:
            raise ValidationError(
                f"Invalid output transition '{arc.pin_transition}'. "
                f"Must be one of: {valid_transitions}"
            )
        
        # 验证 related_pin 和 related_transition
        if not arc.related_pin:
            raise ValidationError("Related pin cannot be empty (use '-' for hidden arcs)")
        
        if not arc.related_transition:
            raise ValidationError("Related transition cannot be empty (use '-' for hidden arcs)")
        
        if arc.related_pin != '-' and arc.related_transition not in valid_transitions:
            if arc.related_transition != '-':  # Allow '-' for hidden arcs
                raise ValidationError(
                    f"Invalid related transition '{arc.related_transition}'. "
                    f"Must be one of: {valid_transitions} or '-'"
                )
    
    @classmethod
    def _validate_timing_type_consistency(cls, arc) -> None:
        """验证 timing_type 和 related_pin 的一致性。"""
        from .timing_arc import TimingType
        
        # Timing types that should NOT have related_pin
        no_related_pin_types = {
            TimingType.HIDDEN.value,
            TimingType.LEAKAGE_POWER.value
        }
        
        if arc.timing_type in no_related_pin_types:
            if arc.related_pin != '-':
                raise ValidationError(f"{arc.timing_type} arc should not have related_pin (use '-')")
        else:
            # All other types require related_pin
            if arc.related_pin == '-':
                raise ValidationError(f"Timing type '{arc.timing_type}' requires related_pin")
    
    @classmethod
    def _validate_pin_directions(cls, arc, cell) -> None:
        """验证引脚方向的业务逻辑合理性。
        
        Args:
            arc: TimingArc 对象
            cell: Cell 对象
            
        Raises:
            ValidationError: 如果引脚方向不合理
        """
        from .timing_arc import TimingType
        
        # 获取引脚信息
        pin_info = cell.pins.get(arc.pin) if arc.pin != '-' else None
        related_pin_info = cell.pins.get(arc.related_pin) if arc.related_pin != '-' else None
        
        # 特殊情况：隐藏弧和泄漏功耗弧
        if arc.timing_type in [TimingType.HIDDEN.value, TimingType.LEAKAGE_POWER.value]:
            return  # 这些弧有特殊的引脚要求，不应用常规方向验证
        
        # 验证输出引脚方向
        if pin_info and arc.timing_type in [
            TimingType.COMBINATIONAL.value, 
            TimingType.RISING_EDGE.value, 
            TimingType.FALLING_EDGE.value
        ]:
            # 延迟弧：pin应该是输出引脚
            if pin_info.direction not in ['output', 'inout']:
                raise ValidationError(
                    f"Delay arc pin '{arc.pin}' should be output pin, "
                    f"but found '{pin_info.direction}' pin"
                )
        
        # 验证related_pin方向
        if related_pin_info:
            # 大多数情况下，related_pin应该是输入引脚
            if arc.timing_type in [
                TimingType.COMBINATIONAL.value,
                TimingType.RISING_EDGE.value,
                TimingType.FALLING_EDGE.value,
                TimingType.SETUP_RISING.value,
                TimingType.SETUP_FALLING.value,
                TimingType.HOLD_RISING.value,
                TimingType.HOLD_FALLING.value,
                TimingType.RECOVERY_RISING.value,
                TimingType.RECOVERY_FALLING.value,
                TimingType.REMOVAL_RISING.value,
                TimingType.REMOVAL_FALLING.value,
                TimingType.MIN_PULSE_WIDTH.value
            ]:
                # related_pin应该是输入引脚或双向引脚
                if related_pin_info.direction not in ['input', 'inout']:
                    raise ValidationError(
                        f"Timing arc related_pin '{arc.related_pin}' should be input pin, "
                        f"but found '{related_pin_info.direction}' pin"
                    )
        
        # 约束弧的特殊验证：pin应该是数据引脚，related_pin应该是时钟引脚
        if arc.timing_type in [
            TimingType.SETUP_RISING.value,
            TimingType.SETUP_FALLING.value,
            TimingType.HOLD_RISING.value,
            TimingType.HOLD_FALLING.value
        ]:
            # pin应该是输入引脚（数据引脚）
            if pin_info and pin_info.direction not in ['input', 'inout']:
                raise ValidationError(
                    f"Constraint arc data pin '{arc.pin}' should be input pin, "
                    f"but found '{pin_info.direction}' pin"
                )