"""
基础命令处理器模块

提供所有TCL命令处理器的基础功能，包括：
- 通用的参数解析
- 错误处理
- 日志记录
- 数据库访问接口
"""

from typing import Dict, List, Any
from abc import ABC, abstractmethod

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.core.logger import LogManager


class BaseCommandHandler(ABC):
    """TCL命令处理器基类
    
    所有具体的命令处理器都应该继承这个基类，
    提供统一的接口和通用功能。
    """

    def __init__(self, library_db: CellLibraryDB):
        """初始化命令处理器
        
        Args:
            library_db: 库数据库实例
        """
        self.library_db = library_db
        self.logger = LogManager().get_logger(self.__class__.__name__)

    def parse_tcl_args(self, args: tuple) -> Dict[str, Any]:
        """解析TCL命令参数为字典
        
        Args:
            args: TCL命令参数元组
            
        Returns:
            Dict: 包含命名参数和位置参数的字典
            命名参数以'-'开头，位置参数按顺序排列在末尾
        """
        params = {}
        current_key = None

        # 最后一个参数用作位置参数
        if args:
            params["name"] = args[-1]
            args = args[:-1]

        # 处理其余参数
        for arg in args:
            if str(arg).startswith("-"):
                current_key = arg.lstrip("-")
                params[current_key] = []
            else:
                if current_key:
                    params[current_key].append(arg)

        # 转换单值列表
        for k, v in params.items():
            if isinstance(v, list) and len(v) == 1:
                params[k] = v[0]
                
        return params

    def parse_number_list(self, text: str) -> List[float]:
        """解析TCL数字列表
        
        Args:
            text: TCL格式的数字列表字符串
            
        Returns:
            List[float]: 解析后的数字列表
        """
        # 清理输入文本，移除不必要的字符和多余空格
        text = text.strip("{}[] \t\n")
        # 按空格和/或逗号分割
        numbers = [x.strip(" ,") for x in text.split() if x.strip(" ,")]
        return [float(x) for x in numbers]

    def parse_pin_list(self, text: str) -> List[str]:
        """解析TCL引脚列表
        
        Args:
            text: TCL格式的引脚列表字符串
            
        Returns:
            List[str]: 解析后的引脚列表
        """
        return [x.strip() for x in text.strip("{}").split()]

    def validate_cell_exists(self, cell_name: str):
        """验证单元是否存在
        
        Args:
            cell_name: 单元名称
            
        Raises:
            CommandParseError: 如果单元不存在
        """
        if not self.library_db.has_cell(cell_name):
            raise CommandParseError(f"Cell {cell_name} not found")

    def validate_template_exists(self, template_name: str):
        """验证模板是否存在
        
        Args:
            template_name: 模板名称
            
        Raises:
            CommandParseError: 如果模板不存在
        """
        if template_name and template_name not in self.library_db.templates:
            raise CommandParseError(f"Template '{template_name}' not found")

    def validate_parameters(self, params: Dict[str, Any], allowed_params: set, command_name: str):
        """验证参数是否在允许范围内
        
        Args:
            params: 解析的参数字典
            allowed_params: 允许的参数集合
            command_name: 命令名称（用于错误消息）
            
        Raises:
            CommandParseError: 参数验证失败
        """
        # 检查是否有不被允许的参数
        invalid_params = set(params.keys()) - allowed_params
        if invalid_params:
            raise CommandParseError(
                f"Invalid parameters for {command_name}: {', '.join(sorted(invalid_params))}. "
                f"Allowed parameters: {', '.join(sorted(allowed_params))}"
            )

    @abstractmethod
    def handle_command(self, *args) -> str:
        """处理TCL命令的抽象方法
        
        每个具体的命令处理器都必须实现这个方法
        
        Args:
            *args: TCL命令参数
            
        Returns:
            str: 命令执行结果
        """
        pass

    def log_command_start(self, command_name: str, params: Dict[str, Any]):
        """记录命令开始执行
        
        Args:
            command_name: 命令名称
            params: 解析后的参数
        """
        self.logger.debug(f"Executing {command_name} with params: {params}")

    def log_command_success(self, command_name: str, result: Any = None):
        """记录命令执行成功
        
        Args:
            command_name: 命令名称
            result: 执行结果
        """
        self.logger.debug(f"Successfully executed {command_name}")

    def log_command_error(self, command_name: str, error: Exception):
        """记录命令执行错误
        
        Args:
            command_name: 命令名称
            error: 错误信息
        """
        self.logger.error(f"Error executing {command_name}: {str(error)}")
