"""
弧命令解析器

处理 define_arc 和 define_leakage TCL命令，负责：
- 解析时序弧定义参数
- 解析泄漏功耗定义参数
- 创建TimingArc并添加到Cell

"""

from typing import Dict, Any, Optional
from datetime import datetime
from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.timing_arc import TimingType, TimingArc
from .base_handler import BaseCommandHandler


class ArcHandler(BaseCommandHandler):
    """时序弧定义命令解析器

    处理 define_arc 和 define_leakage TCL命令，直接创建TimingArc并添加到Cell。
    """

    def __init__(self, library_db: CellLibraryDB):
        super().__init__(library_db)

    def handle_arc(self, *args) -> str:
        """解析 define_arc TCL命令

        命令格式:
        define_arc -pin <pin:R/F> -related_pin <related_pin:R/F> -timing_type <timing_type>
                  -condition <condition> <cell_name>
        """
        try:
            params = self.parse_tcl_args(args)
            self.log_command_start("define_arc", params)

            cell_name = params['name']
            pin_spec = params.get('pin')
            related_pin_spec = params.get('related_pin', '-')
            timing_type = params.get('timing_type') or params.get('type')  # 支持两种参数名
            condition = params.get('condition', '')

            # 基本验证
            if not timing_type:
                raise CommandParseError("Timing type is required")
            
            cell = self.library_db.get_cell(cell_name)
            self._validate_timing_type(timing_type)
            
            # 解析引脚和转换
            pin, pin_transition = self._parse_pin_spec(pin_spec)
            related_pin, related_transition = self._parse_pin_spec(related_pin_spec)
            condition_dict = self._parse_condition(condition, cell) if condition else {}
            
            # 验证引脚存在
            if pin != '-' and pin not in cell.pins:
                raise CommandParseError(f"Pin '{pin}' not found in cell '{cell_name}'")
            if related_pin != '-' and related_pin not in cell.pins:
                raise CommandParseError(f"Related pin '{related_pin}' not found in cell '{cell_name}'")

            # 确定表类型和引脚方向
            pin_direction = cell.pins[pin].direction if pin != '-' and pin in cell.pins else 'output'
            table_type = self._determine_table_type(timing_type, pin_transition)
            
            # 直接创建并验证TimingArc - 只使用condition_dict
            timing_arc = TimingArc.create_validated_arc(
                cell=cell,
                pin=pin,
                pin_direction=pin_direction,
                pin_transition=pin_transition,
                related_pin=related_pin,
                related_transition=related_transition,
                timing_type=timing_type,
                table_type=table_type,
                condition=condition,
                condition_dict=condition_dict,
                metadata={'source': 'manual', 'timestamp': datetime.now().isoformat()}
            )
            
            # 直接添加到Cell
            cell.add_timing_arc(timing_arc)
            self.log_command_success("define_arc")
            return ""

        except Exception as e:
            self.log_command_error("define_arc", e)
            raise CommandParseError(f"Error in define_arc: {str(e)}")

    def handle_leakage(self, *args) -> str:
        """解析 define_leakage TCL命令

        命令格式:
        define_leakage -condition <condition> <cell_name>
        """
        try:
            params = self.parse_tcl_args(args)
            self.log_command_start("define_leakage", params)

            cell_name = params['name']
            condition = params.get('condition', '')

            if not condition:
                raise CommandParseError("Condition is required for leakage definition")

            self.validate_cell_exists(cell_name)

            # 直接创建泄漏功耗TimingArc
            cell = self.library_db.get_cell(cell_name)
            condition_dict = self._parse_condition(condition, cell) if condition else {}
            
            timing_arc = TimingArc.create_validated_arc(
                cell=cell,
                pin='-',
                pin_direction='-',
                pin_transition='-',
                related_pin='-',
                related_transition='-',
                timing_type='leakage_power',
                table_type='leakage_power',
                condition=condition,
                condition_dict=condition_dict,
                metadata={'source': 'manual', 'timestamp': datetime.now().isoformat()}
            )
            
            # 直接添加到Cell
            cell.add_timing_arc(timing_arc)
            self.log_command_success("define_leakage")
            return ""

        except Exception as e:
            self.log_command_error("define_leakage", e)
            raise CommandParseError(f"Error in define_leakage: {str(e)}")

    def _validate_timing_type(self, timing_type: str) -> None:
        """验证时序类型"""
        valid_types = {t.value for t in TimingType}
        if timing_type not in valid_types:
            raise CommandParseError(f"Invalid timing type '{timing_type}'")

    def _parse_pin_spec(self, pin_spec: str) -> tuple:
        """解析引脚规格 'pin:R' -> ('pin', 'rise')"""
        if not pin_spec or pin_spec == '-':
            return '-', '-'
        
        if ':' not in pin_spec:
            raise CommandParseError(f"Invalid pin format '{pin_spec}'. Expected 'pin:R' or 'pin:F'")
        
        pin, transition = pin_spec.split(':', 1)
        if transition == 'R':
            return pin, 'rise'
        elif transition == 'F':
            return pin, 'fall'
        else:
            raise CommandParseError(f"Invalid transition '{transition}'. Use 'R' or 'F'")

    def _parse_condition(self, condition: str, cell) -> dict:
        """解析条件 '!EN*SEL' -> {'EN': '0', 'SEL': '1'}"""
        if not condition:
            return {}
        
        # 验证基本格式：只允许字母、数字、下划线、*、!
        if not all(c.isalnum() or c in '_*!' for c in condition):
            raise CommandParseError(f"Invalid characters in condition '{condition}'. Only letters, digits, underscore, '*', and '!' allowed")
        
        # 不允许空的term或连续的*
        if '**' in condition or condition.startswith('*') or condition.endswith('*'):
            raise CommandParseError(f"Invalid condition format '{condition}'. No empty terms or leading/trailing '*'")
        
        condition_dict = {}
        for term in condition.split('*'):
            term = term.strip()
            if not term:
                raise CommandParseError(f"Empty term in condition '{condition}'")
            
            if term.startswith('!'):
                pin_name = term[1:]
                value = '0'
                if not pin_name:
                    raise CommandParseError(f"Invalid negation '!' without pin name in condition '{condition}'")
            else:
                pin_name = term
                value = '1'
            
            # 检查重复定义
            if pin_name in condition_dict:
                raise CommandParseError(f"Pin '{pin_name}' defined multiple times in condition '{condition}'")
            
            # 验证引脚存在
            if pin_name not in cell.pins:
                raise CommandParseError(f"Pin '{pin_name}' in condition not found in cell")
            
            condition_dict[pin_name] = value
        
        return condition_dict
    
    def _determine_table_type(self, timing_type: str, pin_transition: str) -> str:
        """确定表类型"""
        if timing_type == 'leakage_power':
            return 'leakage_power'
        elif timing_type == 'hidden':
            # Hidden弧使用特殊的表类型
            return f'cell_{pin_transition}' if pin_transition != '-' else 'cell_rise'
        elif timing_type in ['combinational', 'rising_edge', 'falling_edge', 'async']:
            # 对于这些类型，如果pin_transition是'-'，使用默认的rise
            transition = pin_transition if pin_transition != '-' else 'rise'
            return f'cell_{transition}'
        elif timing_type.startswith(('setup_', 'hold_', 'recovery_', 'removal_')):
            transition = pin_transition if pin_transition != '-' else 'rise'
            return f'{transition}_constraint'
        elif timing_type == 'min_pulse_width':
            # 最小脉宽约束
            transition = pin_transition if pin_transition != '-' else 'rise'
            return f'{transition}_constraint'
        else:
            transition = pin_transition if pin_transition != '-' else 'rise'
            return f'cell_{transition}'

    def handle_command(self, *_args) -> str:
        """实现基类的抽象方法"""
        raise NotImplementedError("Use handle_arc or handle_leakage instead")