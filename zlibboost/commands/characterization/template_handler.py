"""
模板命令处理器

处理 define_template TCL命令，负责：
- 解析模板定义参数
- 验证模板数据
- 将模板添加到库数据库

重构自 legacy/frontend/tcl_timing_parser.py 的 _handle_template 方法
"""

from typing import Dict, Any

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.template import Template
from .base_handler import BaseCommandHandler


class TemplateHandler(BaseCommandHandler):
    """模板定义命令处理器
    
    处理 define_template TCL命令，用于定义时序表模板。
    模板定义了查找表的索引结构，包括：
    - 模板类型（delay、power、constraint等）
    - index_1: 第一个索引维度（通常是输入转换时间）
    - index_2: 第二个索引维度（通常是输出负载）
    """

    def handle_template(self, *args) -> str:
        """处理 define_template TCL命令
        
        命令格式:
        define_template -type <template_type> -index_1 {values} -index_2 {values} <template_name>
        
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
            self.log_command_start("define_template", params)
            
            # 提取必需参数
            template_type = params.get("type")
            template_name = params["name"]  # 模板名称如 delay_template_7x7
            
            # 验证必需参数
            if not template_name:
                raise CommandParseError("Template name is required")
            
            # 解析索引值
            index_1 = self.parse_number_list(params["index_1"])
            index_2 = self.parse_number_list(params["index_2"])
            
            # 验证索引数据
            self._validate_template_data(template_name, template_type, index_1, index_2)
            
            # 创建模板对象并添加到数据库
            template = Template(
                name=template_name,
                template_type=template_type,
                index_1=index_1,
                index_2=index_2
            )
            self.library_db.add_template(template)
            
            self.log_command_success("define_template")
            self.logger.info(f"Added template '{template_name}' with type '{template_type}', "
                           f"index_1: {len(index_1)} values, index_2: {len(index_2)} values")
            
            return ""
            
        except Exception as e:
            self.log_command_error("define_template", e)
            raise CommandParseError(f"Error in define_template: {str(e)}")

    def _validate_template_data(self, template_name: str, template_type: str, 
                              index_1: list, index_2: list):
        """验证模板数据的有效性
        
        Args:
            template_name: 模板名称
            template_type: 模板类型
            index_1: 第一个索引维度
            index_2: 第二个索引维度
            
        Raises:
            CommandParseError: 验证失败
        """
        # 验证模板名称
        if not template_name.strip():
            raise CommandParseError("Template name cannot be empty")
        
        # 验证索引数据
        if not index_1:
            raise CommandParseError("index_1 cannot be empty")
        if not index_2:
            raise CommandParseError("index_2 cannot be empty")
            
        # 验证索引值的单调性（应该是递增的）
        if not self._is_monotonic_increasing(index_1):
            self.logger.warning(f"index_1 values are not monotonic increasing in template '{template_name}'")
        if not self._is_monotonic_increasing(index_2):
            self.logger.warning(f"index_2 values are not monotonic increasing in template '{template_name}'")
            
        # 验证索引值为正数
        if any(x < 0 for x in index_1):
            raise CommandParseError("index_1 values must be non-negative")
        if any(x < 0 for x in index_2):
            raise CommandParseError("index_2 values must be non-negative")
            
        # 验证模板类型（如果提供）
        if template_type:
            valid_types = ['delay', 'power', 'constraint', 'transition']
            if template_type not in valid_types:
                self.logger.warning(f"Unknown template type '{template_type}' in template '{template_name}'")

    def _is_monotonic_increasing(self, values: list) -> bool:
        """检查数值列表是否单调递增
        
        Args:
            values: 数值列表
            
        Returns:
            bool: 如果单调递增返回True
        """
        return all(values[i] <= values[i + 1] for i in range(len(values) - 1))

    def handle_command(self, *args) -> str:
        """实现基类的抽象方法"""
        return self.handle_template(*args)
