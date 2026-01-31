"""
统一的TCL解析引擎

提供统一的TCL解析服务，支持：
- 配置文件解析
- 时序库文件解析
- 自定义命令注册
- 解析状态管理

这个模块解决了原始架构中TCL解析器重复的问题，
提供了一个统一的、可扩展的TCL解析框架。
"""

import tkinter as tk
from typing import Dict, List, Any, Callable, Optional
from pathlib import Path
import os
from abc import ABC, abstractmethod

from zlibboost.core.exceptions import CommandParseError
from zlibboost.core.logger import LogManager


class TclCommandHandler(ABC):
    """TCL命令处理器接口"""
    
    @abstractmethod
    def handle_command(self, *args) -> str:
        """处理TCL命令
        
        Args:
            *args: TCL命令参数
            
        Returns:
            str: 命令执行结果
        """
        pass


class TclEngine:
    """统一的TCL解析引擎
    
    这个类提供了一个统一的TCL解析框架，可以被不同的解析器使用：
    - ConfigParser: 配置文件解析
    - TimingParser: 时序库文件解析
    - 其他需要TCL解析的模块
    """

    def __init__(self, engine_name: str = "default"):
        """初始化TCL引擎
        
        Args:
            engine_name: 引擎名称，用于日志和调试
        """
        self.engine_name = engine_name
        self.logger = LogManager().get_logger(f"{__name__}.{engine_name}")
        
        # 创建TCL解释器
        self._tcl = tk.Tcl()
        
        # 命令处理器注册表
        self._command_handlers: Dict[str, TclCommandHandler] = {}
        self._command_functions: Dict[str, Callable] = {}
        
        # 解析状态
        self._current_file: Optional[Path] = None
        self._variables: Dict[str, Any] = {}
        
        self.logger.info(f"TCL engine '{engine_name}' initialized")

    def register_command_handler(self, command_name: str, handler: TclCommandHandler):
        """注册命令处理器
        
        Args:
            command_name: TCL命令名称
            handler: 命令处理器实例
        """
        self._command_handlers[command_name] = handler
        
        # 创建包装函数
        def wrapper(*args):
            try:
                return handler.handle_command(*args)
            except Exception as e:
                self.logger.error(f"Error in command '{command_name}': {str(e)}")
                raise
        
        self._tcl.createcommand(command_name, wrapper)
        self.logger.debug(f"Registered command handler: {command_name}")

    def register_command_function(self, command_name: str, function: Callable):
        """注册命令函数
        
        Args:
            command_name: TCL命令名称
            function: 处理函数
        """
        self._command_functions[command_name] = function
        
        # 创建包装函数
        def wrapper(*args):
            try:
                return function(*args)
            except Exception as e:
                self.logger.error(f"Error in command '{command_name}': {str(e)}")
                raise
        
        self._tcl.createcommand(command_name, wrapper)
        self.logger.debug(f"Registered command function: {command_name}")

    def set_variable(self, name: str, value: Any):
        """设置TCL变量
        
        Args:
            name: 变量名
            value: 变量值
        """
        self._variables[name] = value
        self._tcl.setvar(name, str(value))
        self.logger.debug(f"Set variable: {name} = {value}")

    def get_variable(self, name: str, default: Any = None) -> Any:
        """获取TCL变量
        
        Args:
            name: 变量名
            default: 默认值
            
        Returns:
            Any: 变量值
        """
        try:
            return self._tcl.getvar(name)
        except tk.TclError:
            return default

    def evaluate(self, script: str) -> str:
        """执行TCL脚本
        
        Args:
            script: TCL脚本内容
            
        Returns:
            str: 执行结果
            
        Raises:
            CommandParseError: TCL执行错误
        """
        try:
            result = self._tcl.eval(script)
            self.logger.debug(f"Evaluated script: {script[:100]}...")
            return result
        except tk.TclError as e:
            error_msg = f"TCL evaluation error: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)

    def source_file(self, filepath: str) -> str:
        """执行TCL文件
        
        Args:
            filepath: 文件路径
            
        Returns:
            str: 执行结果
            
        Raises:
            CommandParseError: 文件不存在或执行错误
        """
        filepath = Path(filepath).resolve()
        if not filepath.exists():
            raise CommandParseError(f"File not found: {filepath}")
        
        self._current_file = filepath
        original_dir = os.getcwd()
        
        try:
            # 切换到文件所在目录以支持相对路径
            os.chdir(filepath.parent)
            self.logger.info(f"Sourcing TCL file: {filepath.name}")
            
            result = self._tcl.eval(f"source {filepath.name}")
            
            self.logger.info(f"Successfully sourced file: {filepath.name}")
            return result
            
        except tk.TclError as e:
            error_msg = f"TCL file execution error in {filepath.name}: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)
        finally:
            os.chdir(original_dir)
            self._current_file = None

    def get_current_file(self) -> Optional[Path]:
        """获取当前正在解析的文件"""
        return self._current_file

    def reset(self):
        """重置TCL引擎状态"""
        # 重新创建TCL解释器
        self._tcl = tk.Tcl()
        
        # 清空状态
        self._variables.clear()
        self._current_file = None
        
        # 重新注册命令
        for command_name, handler in self._command_handlers.items():
            def wrapper(*args, h=handler):
                return h.handle_command(*args)
            self._tcl.createcommand(command_name, wrapper)
            
        for command_name, function in self._command_functions.items():
            def wrapper(*args, f=function):
                return f(*args)
            self._tcl.createcommand(command_name, wrapper)
        
        self.logger.info(f"TCL engine '{self.engine_name}' reset")

    def get_registered_commands(self) -> List[str]:
        """获取已注册的命令列表"""
        return list(self._command_handlers.keys()) + list(self._command_functions.keys())

    def unregister_command(self, command_name: str):
        """注销命令
        
        Args:
            command_name: 命令名称
        """
        if command_name in self._command_handlers:
            del self._command_handlers[command_name]
        if command_name in self._command_functions:
            del self._command_functions[command_name]
        
        # 从TCL解释器中删除命令
        try:
            self._tcl.eval(f"rename {command_name} {{}}")
        except tk.TclError:
            pass  # 命令可能不存在
        
        self.logger.debug(f"Unregistered command: {command_name}")

    def __del__(self):
        """析构函数"""
        if hasattr(self, '_tcl'):
            try:
                self._tcl.eval("exit")
            except:
                pass
