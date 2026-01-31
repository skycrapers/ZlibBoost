"""
统一TCL命令分发器

该模块提供了统一的TCL命令分发功能，支持：
- 所有类型的TCL命令分发
- 统一的错误处理
- 命令执行状态跟踪
- 可扩展的处理器架构

重构自原有的CommandDispatcher，现在支持配置命令和表征命令的统一分发。
"""

from typing import Dict, List, Any, Set, Optional
from pathlib import Path
import os

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.core.logger import LogManager
from zlibboost.parsers.tcl_engine import TclEngine
from zlibboost.parsers.command_registry import CommandRegistry, CommandType, CommandInfo
from zlibboost.parsers.command_callbacks import CommandCallbacks


class UnifiedCommandDispatcher:
    """统一TCL命令分发器
    
    这个类是所有TCL命令分发的统一入口，负责：
    1. 使用统一的TCL引擎
    2. 通过命令注册中心管理所有命令
    3. 统一分发配置命令和表征命令
    4. 提供统一的错误处理和状态管理
    
    重构自原有的CommandDispatcher，现在支持更广泛的命令类型。
    """

    def __init__(self, library_db: CellLibraryDB = None, engine_name: str = "unified_dispatcher"):
        """初始化统一命令分发器

        Args:
            library_db: 可选的库数据库实例，如果不提供则创建新实例
            engine_name: TCL引擎名称
        """
        self.logger = LogManager().get_logger(__name__)

        # 使用统一的TCL引擎
        self.tcl_engine = TclEngine(engine_name)
        self.library_db = library_db or CellLibraryDB()

        # 使用统一的命令注册中心
        self.command_registry = CommandRegistry()

        # 使用统一的命令回调
        self.command_callbacks = CommandCallbacks(self.library_db)

        # 执行状态跟踪
        self.execution_stats = {
            "commands_executed": 0,
            "errors_encountered": 0,
            "files_processed": 0
        }

        # 注册所有支持的命令
        self._register_all_commands()

        self.logger.info(f"Unified command dispatcher initialized with engine '{engine_name}'")

    def _register_all_commands(self):
        """注册所有支持的TCL命令"""
        
        # 注册标准TCL命令
        self._register_standard_commands()
        
        # 注册配置命令
        self._register_config_commands()
        
        # 注册表征命令
        self._register_characterization_commands()
        
        # 将所有命令注册到TCL引擎
        self._bind_commands_to_tcl_engine()

    def _register_standard_commands(self):
        """注册标准TCL命令"""
        self.command_registry.register_command(
            name="set",
            handler=self.command_callbacks.handle_set,
            command_type=CommandType.STANDARD,
            description="Standard TCL set command",
            required_args=2,
            optional_args=0
        )

    def _register_config_commands(self):
        """注册配置命令"""
        self.command_registry.register_command(
            name="set_var",
            handler=self.command_callbacks.handle_set_var,
            command_type=CommandType.CONFIG,
            description="Set configuration variable",
            required_args=1,
            optional_args=1
        )

    def _register_characterization_commands(self):
        """注册表征命令"""
        characterization_commands = [
            ("define_driver_waveform", self.command_callbacks.handle_driver_waveform, "Define driver waveform"),
            ("define_template", self.command_callbacks.handle_template, "Define timing template"),
            ("define_cell", self.command_callbacks.handle_cell, "Define cell characterization"),
            ("define_function", self.command_callbacks.handle_function, "Define cell logic function"),
            ("define_arc", self.command_callbacks.handle_arc, "Define timing arc"),
            ("define_leakage", self.command_callbacks.handle_leakage, "Define leakage power"),
            ("ALAPI_active_cell", self.command_callbacks.handle_active_cell, "Check if cell is active")
        ]

        for cmd_name, handler, description in characterization_commands:
            self.command_registry.register_command(
                name=cmd_name,
                handler=handler,
                command_type=CommandType.CHARACTERIZATION,
                description=description,
                required_args=0,  # 这些命令参数数量可变
                optional_args=float('inf')
            )

    def _bind_commands_to_tcl_engine(self):
        """将注册的命令绑定到TCL引擎"""
        all_commands = self.command_registry.get_all_commands()
        
        for cmd_name, cmd_info in all_commands.items():
            # 创建包装函数来处理命令分发
            def create_wrapper(command_name: str, command_info: CommandInfo):
                def wrapper(*args):
                    return self._dispatch_command(command_name, command_info, args)
                return wrapper
            
            wrapper_func = create_wrapper(cmd_name, cmd_info)
            self.tcl_engine.register_command_function(cmd_name, wrapper_func)
        
        self.logger.debug(f"Bound {len(all_commands)} commands to TCL engine")

    def _dispatch_command(self, command_name: str, command_info: CommandInfo, args: tuple) -> Any:
        """分发命令到相应的处理器
        
        Args:
            command_name: 命令名称
            command_info: 命令信息
            args: 命令参数
            
        Returns:
            Any: 命令执行结果
            
        Raises:
            CommandParseError: 命令执行错误
        """
        try:
            # 验证参数
            if not command_info.validate_args(args):
                raise CommandParseError(
                    f"Invalid arguments for command '{command_name}': "
                    f"expected {command_info.required_args}-{command_info.required_args + command_info.optional_args} args, "
                    f"got {len(args)}"
                )
            
            # 执行命令
            self.logger.debug(f"Dispatching {command_info.command_type.value} command: {command_name}")
            result = command_info.handler(*args)
            
            # 更新统计信息
            self.execution_stats["commands_executed"] += 1
            
            return result
            
        except Exception as e:
            self.execution_stats["errors_encountered"] += 1
            error_msg = f"Error executing command '{command_name}': {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)



    def parse_file(self, filepath: str) -> CellLibraryDB:
        """解析TCL文件
        
        Args:
            filepath: 文件路径
            
        Returns:
            CellLibraryDB: 解析后的库数据库
            
        Raises:
            CommandParseError: 解析错误
        """
        try:
            self.logger.info(f"Parsing file: {filepath}")
            
            # 使用统一的TCL引擎解析文件
            self.tcl_engine.source_file(filepath)
            
            # 更新统计信息
            self.execution_stats["files_processed"] += 1
            
            self.logger.info(f"Successfully parsed file: {filepath}")
            return self.library_db
            
        except Exception as e:
            error_msg = f"Error parsing file {filepath}: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)

    def get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计信息"""
        return {
            **self.execution_stats,
            "callback_stats": self.command_callbacks.get_statistics(),
            "registered_commands": self.command_registry.get_command_info()
        }

    def get_active_cells(self) -> Set[str]:
        """获取激活的单元列表"""
        return self.command_callbacks.get_active_cells()

    def get_reserved_vars(self) -> Dict[str, Any]:
        """获取程序保留变量"""
        return self.command_callbacks.get_reserved_vars()

    def reset(self):
        """重置分发器状态"""
        self.command_callbacks.reset_state()
        self.library_db = CellLibraryDB()
        self.tcl_engine.reset()
        self.execution_stats = {
            "commands_executed": 0,
            "errors_encountered": 0,
            "files_processed": 0
        }
        # 重新绑定命令
        self._bind_commands_to_tcl_engine()
        self.logger.info("Dispatcher state reset")
