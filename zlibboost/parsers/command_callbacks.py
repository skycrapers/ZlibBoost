"""
统一TCL命令回调函数

该模块提供了所有TCL命令的独立回调函数，实现了处理逻辑与解析逻辑的分离：
- 配置命令回调
- 表征命令回调
- 标准TCL命令回调

重构目标：
- 将命令处理器重构为独立的回调函数
- 确保回调函数可以独立测试和维护
- 提供统一的回调接口
"""

from typing import Dict, List, Any, Set, Optional, Tuple
import re

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.core.logger import LogManager


class CommandCallbacks:
    """统一的TCL命令回调函数集合
    
    这个类包含了所有TCL命令的回调函数，实现了：
    1. 配置命令的处理逻辑
    2. 表征命令的处理逻辑
    3. 标准TCL命令的处理逻辑
    4. 统一的错误处理和日志记录
    """
    
    def __init__(self, library_db: CellLibraryDB):
        """初始化命令回调

        Args:
            library_db: 库数据库实例
        """
        self.logger = LogManager().get_logger(__name__)
        self.library_db = library_db

        # 状态跟踪
        self.active_cells: Set[str] = set()
        self.reserved_vars: Dict[str, Any] = {}  # 程序保留变量

        # 延迟导入命令处理器以避免循环依赖
        self._handlers_cache = {}
    
    def _get_handler(self, handler_name: str):
        """获取命令处理器（延迟导入）"""
        if handler_name not in self._handlers_cache:
            if handler_name == "cell":
                from zlibboost.commands.characterization.cell_handler import CellHandler
                self._handlers_cache[handler_name] = CellHandler(self.library_db)
            elif handler_name == "template":
                from zlibboost.commands.characterization.template_handler import TemplateHandler
                self._handlers_cache[handler_name] = TemplateHandler(self.library_db)
            elif handler_name == "waveform":
                from zlibboost.commands.characterization.waveform_handler import WaveformHandler
                self._handlers_cache[handler_name] = WaveformHandler(self.library_db)
            elif handler_name == "function":
                from zlibboost.commands.characterization.function_handler import FunctionHandler
                self._handlers_cache[handler_name] = FunctionHandler(self.library_db)
            elif handler_name == "arc":
                from zlibboost.commands.characterization.arc_handler import ArcHandler
                self._handlers_cache[handler_name] = ArcHandler(self.library_db)
            else:
                raise CommandParseError(f"Unknown handler: {handler_name}")
        
        return self._handlers_cache[handler_name]
    
    # ==================== 标准TCL命令回调 ====================
    
    def handle_set(self, var_name: str, value: str) -> str:
        """处理标准TCL set命令
        
        Args:
            var_name: 变量名
            value: 变量值
            
        Returns:
            str: 设置的值
        """
        try:
            if var_name == "cells":
                # 解析单元列表并存储激活的单元
                cells = [x.strip(' \t\n"\\') for x in value.strip('{}').split()]
                self.active_cells.update(cells)
                self.logger.debug(f"Added {len(cells)} active cells: {cells}")
            
            return value
            
        except Exception as e:
            self.logger.error(f"Error in set command: {str(e)}")
            raise CommandParseError(f"Error in set command: {str(e)}")
    
    # ==================== 配置命令回调 ====================
    
    def handle_set_var(self, var_name: str, value: str = None) -> str:
        """处理程序保留变量设置命令

        set_var是程序内部保留的变量，与标准TCL的set命令类似，
        但专门用于程序内部的配置和状态管理，不涉及ConfigManager。

        Args:
            var_name: 变量名
            value: 变量值（可选，如果不提供则返回当前值）

        Returns:
            str: 变量值
        """
        try:
            if value is not None:
                # 直接存储到保留变量字典
                self.reserved_vars[var_name] = value
                self.logger.debug(f"Set reserved variable: {var_name} = {value}")
                return value
            else:
                # 获取变量值
                return self.reserved_vars.get(var_name, "")

        except Exception as e:
            self.logger.error(f"Error in set_var command: {str(e)}")
            raise CommandParseError(f"Error setting reserved variable '{var_name}': {str(e)}")
    
    # ==================== 表征命令回调 ====================
    
    def handle_driver_waveform(self, *args) -> str:
        """处理 define_driver_waveform 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("waveform")
            return handler.handle_driver_waveform(*args)
        except Exception as e:
            self.logger.error(f"Error in define_driver_waveform: {str(e)}")
            raise CommandParseError(f"Error in define_driver_waveform: {str(e)}")
    
    def handle_template(self, *args) -> str:
        """处理 define_template 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("template")
            return handler.handle_template(*args)
        except Exception as e:
            self.logger.error(f"Error in define_template: {str(e)}")
            raise CommandParseError(f"Error in define_template: {str(e)}")
    
    def handle_cell(self, *args) -> str:
        """处理 define_cell 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("cell")
            return handler.handle_cell(*args)
        except Exception as e:
            self.logger.error(f"Error in define_cell: {str(e)}")
            raise CommandParseError(f"Error in define_cell: {str(e)}")
    
    def handle_function(self, *args) -> str:
        """处理 define_function 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("function")
            return handler.handle_function(*args)
        except Exception as e:
            self.logger.error(f"Error in define_function: {str(e)}")
            raise CommandParseError(f"Error in define_function: {str(e)}")
    
    def handle_arc(self, *args) -> str:
        """处理 define_arc 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("arc")
            return handler.handle_arc(*args)
        except Exception as e:
            self.logger.error(f"Error in define_arc: {str(e)}")
            raise CommandParseError(f"Error in define_arc: {str(e)}")
    
    def handle_leakage(self, *args) -> str:
        """处理 define_leakage 命令
        
        Args:
            *args: 命令参数
            
        Returns:
            str: 处理结果
        """
        try:
            handler = self._get_handler("arc")
            return handler.handle_leakage(*args)
        except Exception as e:
            self.logger.error(f"Error in define_leakage: {str(e)}")
            raise CommandParseError(f"Error in define_leakage: {str(e)}")
    
    def handle_active_cell(self, cell_name: str) -> str:
        """处理 ALAPI_active_cell 命令
        
        Args:
            cell_name: 单元名称
            
        Returns:
            str: "1" 如果单元激活，否则 "0"
        """
        try:
            result = "1" if cell_name in self.active_cells else "0"
            self.logger.debug(f"Active cell check for '{cell_name}': {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error in ALAPI_active_cell: {str(e)}")
            raise CommandParseError(f"Error in ALAPI_active_cell: {str(e)}")
    
    # ==================== 状态管理方法 ====================
    
    def get_active_cells(self) -> Set[str]:
        """获取激活的单元列表"""
        return self.active_cells.copy()
    
    def get_reserved_vars(self) -> Dict[str, Any]:
        """获取程序保留变量"""
        return self.reserved_vars.copy()

    def reset_state(self):
        """重置回调状态"""
        self.active_cells.clear()
        self.reserved_vars.clear()
        self._handlers_cache.clear()
        self.logger.debug("Command callbacks state reset")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "active_cells_count": len(self.active_cells),
            "reserved_vars_count": len(self.reserved_vars),
            "cached_handlers": list(self._handlers_cache.keys())
        }
