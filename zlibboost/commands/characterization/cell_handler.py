"""
单元命令处理器

处理 define_cell TCL命令，负责：
- 解析单元定义参数
- 验证引脚信息和模板
- 将单元添加到库数据库

"""

from typing import Dict, Any, List

from zlibboost.core.exceptions import CommandParseError
from .base_handler import BaseCommandHandler


class CellHandler(BaseCommandHandler):
    """单元定义命令处理器
    
    处理 define_cell TCL命令，用于定义标准单元。
    单元定义包括：
    - 引脚列表和方向
    - 特殊引脚分类（时钟、数据、复位等）
    - 关联的模板（延迟、功耗、约束）
    """

    def handle_cell(self, *args) -> str:
        """处理 define_cell TCL命令
        
        命令格式:
        define_cell -pinlist {pins} -input {input_pins} -output {output_pins} 
                   -delay <template> -power <template> -constraint <template>
                   [其他特殊引脚参数] <cell_name>
        
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
            self.log_command_start("define_cell", params)
            
            # 验证参数是否在允许范围内
            allowed_params = {
                # 必需参数
                'name', 'pinlist', 'input', 'output',
                # 模板参数
                'delay', 'power', 'constraint',
                # 特殊引脚分类参数
                'clock', 'clocknegative', 'enable', 'enablenegative',
                'scanenable', 'scanin', 'data',
                'sync', 'async', 'reset', 'set'
            }
            self.validate_parameters(params, allowed_params, "define_cell")
            
            cell_name = params['name']
            if not cell_name:
                raise CommandParseError("Cell name is required")
            
            # 解析引脚列表和方向
            pin_list = self.parse_pin_list(params.get('pinlist', ''))
            input_pins = self.parse_pin_list(params.get('input', ''))
            output_pins = self.parse_pin_list(params.get('output', ''))
            
            # 验证引脚信息
            self._validate_pin_info(cell_name, pin_list, input_pins, output_pins)
            
            # 初始化引脚信息
            pins_info = self._build_pins_info(pin_list, input_pins, output_pins)
            
            # 获取模板名称并验证
            delay_template = params.get('delay')
            power_template = params.get('power')
            constraint_template = params.get('constraint')
            self._validate_templates(delay_template, power_template, constraint_template)

            # 构建单元信息
            cell_info = self._build_cell_info(
                pins_info, delay_template, power_template, constraint_template, params
            )
            
            # 创建Cell对象并添加到数据库
            from zlibboost.database.models.cell import Cell, PinInfo, PinCategory

            cell = Cell(name=cell_name)

            # 添加引脚信息
            for pin_name in pin_list:
                direction = "input" if pin_name in input_pins else "output" if pin_name in output_pins else "input"
                pin_info = PinInfo(name=pin_name, direction=direction)    
                cell.add_pin(pin_info)

            # 设置模板信息
            cell.delay_template = delay_template
            cell.power_template = power_template
            cell.constraint_template = constraint_template

            # 设置特殊引脚分类 - 通过PinInfo的categories来管理
            # 时钟引脚
            clock_pins = self.parse_pin_list(params.get('clock', ''))
            for pin_name in clock_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.CLOCK)
                    
            clock_negative_pins = self.parse_pin_list(params.get('clocknegative', ''))
            for pin_name in clock_negative_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.CLOCK)
                    cell.pins[pin_name].is_negative = True
                    
            # 使能引脚
            enable_pins = self.parse_pin_list(params.get('enable', ''))
            for pin_name in enable_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.ENABLE)
                    
            enable_negative_pins = self.parse_pin_list(params.get('enablenegative', ''))
            for pin_name in enable_negative_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.ENABLE)
                    cell.pins[pin_name].is_negative = True
                    
            # 扫描链引脚
            scan_enable_pins = self.parse_pin_list(params.get('scanenable', ''))
            for pin_name in scan_enable_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.SCAN_ENABLE)
                    
            scan_in_pins = self.parse_pin_list(params.get('scanin', ''))
            for pin_name in scan_in_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.SCAN_IN)
                    
            # 数据引脚
            data_pins = self.parse_pin_list(params.get('data', ''))
            for pin_name in data_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.DATA)
                    
            # 同步/异步引脚
            sync_pins = self.parse_pin_list(params.get('sync', ''))
            for pin_name in sync_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.SYNC)
                    
            async_pins = self.parse_pin_list(params.get('async', ''))
            for pin_name in async_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.ASYNC)
                    
            # 复位/置位引脚
            reset_pins = self.parse_pin_list(params.get('reset', ''))
            for pin_name in reset_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.RESET)
                    # Legacy/Liberty convention: reset pins are typically active-low.
                    cell.pins[pin_name].is_negative = True
                    
            set_pins = self.parse_pin_list(params.get('set', ''))
            for pin_name in set_pins:
                if pin_name in cell.pins:
                    cell.pins[pin_name].add_category(PinCategory.SET)
                    # Legacy/Liberty convention: set pins are typically active-low.
                    cell.pins[pin_name].is_negative = True

            # 使用数据库API添加单元
            self.library_db.add_cell(cell)
            
            self.log_command_success("define_cell")
            self.logger.info(f"Added cell '{cell_name}' with {len(pin_list)} pins, "
                           f"{len(input_pins)} inputs, {len(output_pins)} outputs")
            return ""
            
        except Exception as e:
            self.log_command_error("define_cell", e)
            raise CommandParseError(f"Error in define_cell: {str(e)}")

    def _validate_pin_info(self, cell_name: str, pin_list: List[str], 
                          input_pins: List[str], output_pins: List[str]):
        """验证引脚信息
        
        Args:
            cell_name: 单元名称
            pin_list: 所有引脚列表
            input_pins: 输入引脚列表
            output_pins: 输出引脚列表
            
        Raises:
            CommandParseError: 验证失败
        """
        if not pin_list:
            raise CommandParseError(f"Cell '{cell_name}' must have at least one pin")
            
        # 验证输入输出引脚都在引脚列表中
        for pin in input_pins:
            if pin not in pin_list:
                raise CommandParseError(f"Input pin '{pin}' not in pinlist for cell '{cell_name}'")
                
        for pin in output_pins:
            if pin not in pin_list:
                raise CommandParseError(f"Output pin '{pin}' not in pinlist for cell '{cell_name}'")
        
        # 检查引脚重复定义
        overlap = set(input_pins) & set(output_pins)
        if overlap:
            raise CommandParseError(f"Pins cannot be both input and output in cell '{cell_name}': {overlap}")

    def _validate_next_state_function(self, next_state_function: str):
        """验证下一个状态函数
        
        Args:
            next_state_function: 下一个状态函数
        """
        if not next_state_function:
            raise CommandParseError("Next state function is required")
        
    
    def _build_pins_info(self, pin_list: List[str], input_pins: List[str], 
                        output_pins: List[str]) -> Dict[str, Dict[str, str]]:
        """构建引脚信息字典
        
        Args:
            pin_list: 所有引脚列表
            input_pins: 输入引脚列表
            output_pins: 输出引脚列表
            
        Returns:
            Dict: 引脚信息字典
        """
        pins_info = {}
        for pin in pin_list:
            if pin in input_pins:
                pin_direction = 'input'
            elif pin in output_pins:
                pin_direction = 'output'
            else:
                # 默认为输入引脚
                pin_direction = 'input'
                self.logger.warning(f"Pin '{pin}' direction not specified, defaulting to input")
                
            pins_info[pin] = {'direction': pin_direction}
            
        return pins_info

    def _validate_templates(self, delay_template: str, power_template: str, 
                          constraint_template: str):
        """验证模板是否存在
        
        Args:
            delay_template: 延迟模板名称
            power_template: 功耗模板名称
            constraint_template: 约束模板名称
            
        Raises:
            CommandParseError: 模板不存在
        """
        self.validate_template_exists(delay_template)
        self.validate_template_exists(power_template)
        self.validate_template_exists(constraint_template)

    def _build_cell_info(self, pins_info: Dict[str, Dict[str, str]], 
                        delay_template: str, power_template: str, constraint_template: str,
                        params: Dict[str, Any]) -> Dict[str, Any]:
        """构建完整的单元信息
        
        Args:
            pins_info: 引脚信息
            delay_template: 延迟模板
            power_template: 功耗模板
            constraint_template: 约束模板
            params: 解析的参数
            
        Returns:
            Dict: 完整的单元信息
        """
        cell_info = {
            'pins': pins_info,
            'timing_arcs': [],
            'delay_template': delay_template,
            'power_template': power_template,
            'constraint_template': constraint_template,
        }
        
        return cell_info

    def handle_command(self, *args) -> str:
        return self.handle_cell(*args)
