"""
函数命令处理器

处理 define_function TCL命令，负责：
- 解析逻辑函数定义
- 验证函数语法
"""

from typing import Dict
import re

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from .base_handler import BaseCommandHandler


class FunctionHandler(BaseCommandHandler):
    """逻辑函数定义命令处理器
    
    处理 define_function TCL命令，用于定义单元的逻辑函数
    """

    def __init__(self, library_db: CellLibraryDB):
        """初始化函数处理器
        
        Args:
            library_db: 库数据库实例
        """
        super().__init__(library_db)

    def handle_function(self, *args) -> str:
        """处理 define_function TCL命令
        
        命令格式:
        define_function -function "output1=expression1,output2=expression2" <cell_name> [-next_state_function internal=<function>]
        
        Args:
            *args: TCL命令参数
            
        Returns:
            str: 空字符串（TCL命令返回值）
            
        Raises:
            CommandParseError: 参数解析或验证失败
        """
        try:
            # 解析TCL参数
            params = self.parse_tcl_args(args)
            self.log_command_start("define_function", params)
            
            cell_name = params['name']
            function_def = params.get('function', '')
            next_state_function = params.get('next_state_function', '')
            # 验证参数
            if not cell_name:
                raise CommandParseError("Cell name is required")
            if not function_def:
                raise CommandParseError("Function definition is required")
            # next_state_function is optional
            
            self.validate_cell_exists(cell_name)
            
            functions = self._parse_function_definitions(function_def)
            
            
            cell = self.library_db.get_cell(cell_name)

            # Validate functions first (this will log warnings)
            self._validate_functions(cell_name, functions)

            functions = self._maybe_promote_sequential_functions(cell, functions)

            if next_state_function and next_state_function.strip():
                # Handle both formats: "pin=function" and just "function" (default to "internal")
                if '=' in next_state_function:
                    pin_name, function_expr = next_state_function.split('=', 1)
                    cell.set_next_state_function(pin_name.strip(), function_expr.strip())
                else:
                    # Default pin name to "internal" when only function expression is provided
                    cell.set_next_state_function("internal", next_state_function.strip())
            cell.update_functions(functions)
            self.log_command_success("define_function")
            self.logger.info(f"Added {len(functions)} function(s) to cell '{cell_name}': "
                           f"{list(functions.keys())}")
    
            return ""
            
        except Exception as e:
            self.log_command_error("define_function", e)
            raise CommandParseError(f"Error in define_function: {str(e)}")

    def _parse_function_definitions(self, function_def: str) -> Dict[str, str]:
        """解析函数定义字符串
        
        Args:
            function_def: 函数定义字符串，格式为 "output1=expr1,output2=expr2"
            
        Returns:
            Dict[str, str]: 输出引脚到表达式的映射
            
        Raises:
            CommandParseError: 解析失败
        """
        functions = {}
        
        # 按逗号分割多个函数定义
        for func in function_def.split(','):
            func = func.strip()
            if not func:
                continue
                
            if '=' not in func:
                raise CommandParseError(f"Invalid function definition format: '{func}'. Expected 'output=expression'")
                
            # 分割输出引脚和表达式
            parts = func.split('=', 1)  # 只分割第一个等号
            if len(parts) != 2:
                raise CommandParseError(f"Invalid function definition format: '{func}'")
                
            output_pin = parts[0].strip()
            expression = parts[1].strip()
            
            if not output_pin:
                raise CommandParseError("Output pin name cannot be empty")
            if not expression:
                raise CommandParseError(f"Expression for output '{output_pin}' cannot be empty")
                
            functions[output_pin] = expression
            
        return functions

    def _validate_functions(self, cell_name: str, functions: Dict[str, str]):
        """验证函数定义的有效性
        
        Args:
            cell_name: 单元名称
            functions: 函数定义字典
            
        Raises:
            CommandParseError: 验证失败
        """
        cell = self.library_db.get_cell(cell_name)
        output_pins = set(cell.get_output_pins())
        input_pins = set(cell.get_input_pins())
        internal_pins = set(cell.get_internal_pins())
        all_pins = set(cell.pins.keys())
        
        for output_pin, expression in functions.items():
            if output_pin not in all_pins:
                raise CommandParseError(f"Pin '{output_pin}' not found in cell '{cell_name}'")
            if output_pin not in output_pins:
                self.logger.warning(f"Pin '{output_pin}' is not defined as output in cell '{cell_name}'")
            
            self._validate_expression_syntax(expression, input_pins, internal_pins, cell_name, output_pin)

    def _validate_expression_syntax(self, expression: str, input_pins: set, 
                                  internal_pins: set, cell_name: str, output_pin: str):
        """验证布尔表达式语法
        
        Args:
            expression: 布尔表达式
            input_pins: 输入引脚集合
            internal_pins: 内部引脚集合
            cell_name: 单元名称
            output_pin: 输出引脚名称
            
        Raises:
            CommandParseError: 语法错误
        """
        # 提取表达式中的标识符（引脚名称）
        identifiers = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', expression)
        
        for identifier in identifiers:
            # 跳过布尔运算符和常量
            if identifier.lower() in ['and', 'or', 'not', 'xor', 'true', 'false']:
                continue
            
            # 检查引脚是否存在
            if identifier not in input_pins and identifier not in internal_pins:
                self.logger.warning(f"Pin '{identifier}' in expression for '{output_pin}' "
                                  f"is not an input pin in cell '{cell_name}'")

        # 检查基本的括号匹配
        if expression.count('(') != expression.count(')'):
            raise CommandParseError(f"Unmatched parentheses in expression for '{output_pin}': {expression}")


    def handle_command(self, *args) -> str:
        """实现基类的抽象方法"""
        return self.handle_function(*args)

    def _maybe_promote_sequential_functions(self, cell, functions: Dict[str, str]) -> Dict[str, str]:
        """
        当单元具备时钟和数据引脚但缺乏内部状态建模时，将输出函数提升为 next_state 表达式，
        以便顺序弧能够识别真正的时钟触发路径。
        """
        # 仅在存在时钟引脚且尚未定义内部状态时处理
        if not cell.get_clock_pins():
            return functions
        # 若 data 分类缺失，退化为“除时钟外的全部输入”以保持 legacy 行为
        data_pins = set(cell.get_data_pins())
        if not data_pins:
            fallback_inputs = set(cell.get_input_pins()) - set(cell.get_clock_pins())
            if not fallback_inputs:
                return functions
            data_pins = fallback_inputs

        def uses_data(expr: str) -> bool:
            tokens = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', expr)
            return any(token in data_pins for token in tokens)

        # 选择第一个依赖数据引脚的输出作为主状态线程
        primary_output = None
        for output_pin, expr in functions.items():
            if uses_data(expr):
                primary_output = output_pin
                break

        if not primary_output:
            return functions

        existing_internal = cell.get_internal_pins()
        if existing_internal:
            state_pin = existing_internal[0]
        else:
            state_pin = f"{primary_output}_state"
            if state_pin in cell.pins:
                state_pin = f"internal_{primary_output}"
            primary_expr = functions[primary_output]
            cell.set_next_state_function(state_pin, primary_expr)

        # 更新主输出映射到内部状态
        functions[primary_output] = state_pin

        # 其余输出表达式中，出现数据引脚的地方替换为状态引脚
        for output_pin, expr in list(functions.items()):
            if output_pin == primary_output:
                continue
            new_expr = expr
            for data_pin in data_pins:
                new_expr = re.sub(rf'\b{re.escape(data_pin)}\b', state_pin, new_expr)
            functions[output_pin] = new_expr
        return functions
