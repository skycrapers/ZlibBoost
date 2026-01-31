"""
统一TCL命令注册中心

该模块提供了统一的TCL命令注册和管理功能，支持：
- 标准TCL命令 (set等)
- 配置命令 (set_var)
- 表征命令 (define_cell, define_template等)

重构目标：
- 统一所有TCL命令的注册机制
- 分离命令解析和处理逻辑
- 提供可扩展的命令框架
"""

from typing import Dict, List, Any, Callable, Optional, Set
from enum import Enum
from abc import ABC, abstractmethod
import inspect

from zlibboost.core.exceptions import CommandParseError
from zlibboost.core.logger import LogManager


class CommandType(Enum):
    """TCL命令类型枚举"""
    STANDARD = "standard"           # 标准TCL命令 (set等)
    CONFIG = "config"              # 配置命令 (set_var)
    CHARACTERIZATION = "characterization"  # 表征命令 (define_*)


class CommandHandler(ABC):
    """命令处理器接口"""
    
    @abstractmethod
    def handle(self, *args, **kwargs) -> Any:
        """处理命令
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 处理结果
        """
        pass
    
    @property
    @abstractmethod
    def command_type(self) -> CommandType:
        """返回命令类型"""
        pass


class CommandInfo:
    """命令信息类"""
    
    def __init__(self, 
                 name: str,
                 handler: Callable,
                 command_type: CommandType,
                 description: str = "",
                 required_args: int = 0,
                 optional_args: int = 0):
        """初始化命令信息
        
        Args:
            name: 命令名称
            handler: 命令处理函数
            command_type: 命令类型
            description: 命令描述
            required_args: 必需参数数量
            optional_args: 可选参数数量
        """
        self.name = name
        self.handler = handler
        self.command_type = command_type
        self.description = description
        self.required_args = required_args
        self.optional_args = optional_args
        
        # 自动分析函数签名
        self._analyze_signature()
    
    def _analyze_signature(self):
        """分析函数签名以确定参数信息"""
        try:
            sig = inspect.signature(self.handler)
            params = list(sig.parameters.values())
            
            # 排除self参数
            if params and params[0].name == 'self':
                params = params[1:]
            
            # 计算必需和可选参数
            required = 0
            optional = 0
            
            for param in params:
                if param.kind == param.VAR_POSITIONAL:  # *args
                    optional = float('inf')
                    break
                elif param.default == param.empty:
                    required += 1
                else:
                    optional += 1
            
            # 只有在没有手动设置时才使用自动分析结果
            if self.required_args == 0 and self.optional_args == 0:
                self.required_args = required
                self.optional_args = optional
                
        except Exception:
            # 如果分析失败，保持默认值
            pass
    
    def validate_args(self, args: tuple) -> bool:
        """验证参数数量
        
        Args:
            args: 参数元组
            
        Returns:
            bool: 参数是否有效
        """
        arg_count = len(args)
        min_args = self.required_args
        max_args = self.required_args + self.optional_args
        
        if self.optional_args == float('inf'):
            return arg_count >= min_args
        else:
            return min_args <= arg_count <= max_args


class CommandRegistry:
    """统一TCL命令注册中心
    
    这个类管理所有TCL命令的注册、查找和分发：
    1. 支持多种命令类型
    2. 提供命令验证功能
    3. 支持命令别名
    4. 提供命令信息查询
    """
    
    def __init__(self):
        """初始化命令注册中心"""
        self.logger = LogManager().get_logger(__name__)
        
        # 命令注册表：命令名 -> CommandInfo
        self._commands: Dict[str, CommandInfo] = {}
        
        # 命令别名：别名 -> 真实命令名
        self._aliases: Dict[str, str] = {}
        
        # 按类型分组的命令
        self._commands_by_type: Dict[CommandType, Set[str]] = {
            CommandType.STANDARD: set(),
            CommandType.CONFIG: set(),
            CommandType.CHARACTERIZATION: set()
        }
        
        self.logger.info("Command registry initialized")
    
    def register_command(self,
                        name: str,
                        handler: Callable,
                        command_type: CommandType,
                        description: str = "",
                        required_args: int = 0,
                        optional_args: int = 0,
                        aliases: List[str] = None) -> None:
        """注册TCL命令
        
        Args:
            name: 命令名称
            handler: 命令处理函数
            command_type: 命令类型
            description: 命令描述
            required_args: 必需参数数量
            optional_args: 可选参数数量
            aliases: 命令别名列表
            
        Raises:
            CommandParseError: 命令已存在或注册失败
        """
        if name in self._commands:
            raise CommandParseError(f"Command '{name}' already registered")
        
        # 创建命令信息
        cmd_info = CommandInfo(
            name=name,
            handler=handler,
            command_type=command_type,
            description=description,
            required_args=required_args,
            optional_args=optional_args
        )
        
        # 注册命令
        self._commands[name] = cmd_info
        self._commands_by_type[command_type].add(name)
        
        # 注册别名
        if aliases:
            for alias in aliases:
                if alias in self._commands or alias in self._aliases:
                    raise CommandParseError(f"Alias '{alias}' already exists")
                self._aliases[alias] = name
        
        self.logger.debug(f"Registered {command_type.value} command: {name}")
    
    def get_command(self, name: str) -> Optional[CommandInfo]:
        """获取命令信息
        
        Args:
            name: 命令名称或别名
            
        Returns:
            CommandInfo: 命令信息，如果不存在返回None
        """
        # 检查别名
        if name in self._aliases:
            name = self._aliases[name]
        
        return self._commands.get(name)
    
    def has_command(self, name: str) -> bool:
        """检查命令是否存在
        
        Args:
            name: 命令名称或别名
            
        Returns:
            bool: 命令是否存在
        """
        return name in self._commands or name in self._aliases
    
    def get_commands_by_type(self, command_type: CommandType) -> List[str]:
        """获取指定类型的所有命令
        
        Args:
            command_type: 命令类型
            
        Returns:
            List[str]: 命令名称列表
        """
        return list(self._commands_by_type[command_type])
    
    def get_all_commands(self) -> Dict[str, CommandInfo]:
        """获取所有注册的命令
        
        Returns:
            Dict[str, CommandInfo]: 所有命令信息
        """
        return self._commands.copy()
    
    def unregister_command(self, name: str) -> bool:
        """注销命令
        
        Args:
            name: 命令名称
            
        Returns:
            bool: 是否成功注销
        """
        if name not in self._commands:
            return False
        
        cmd_info = self._commands[name]
        
        # 移除命令
        del self._commands[name]
        self._commands_by_type[cmd_info.command_type].discard(name)
        
        # 移除相关别名
        aliases_to_remove = [alias for alias, cmd in self._aliases.items() if cmd == name]
        for alias in aliases_to_remove:
            del self._aliases[alias]
        
        self.logger.debug(f"Unregistered command: {name}")
        return True
    
    def clear_commands(self, command_type: Optional[CommandType] = None) -> None:
        """清除命令
        
        Args:
            command_type: 要清除的命令类型，None表示清除所有
        """
        if command_type is None:
            # 清除所有命令
            self._commands.clear()
            self._aliases.clear()
            for cmd_set in self._commands_by_type.values():
                cmd_set.clear()
            self.logger.info("Cleared all commands")
        else:
            # 清除指定类型的命令
            commands_to_remove = list(self._commands_by_type[command_type])
            for cmd_name in commands_to_remove:
                self.unregister_command(cmd_name)
            self.logger.info(f"Cleared {command_type.value} commands")
    
    def get_command_info(self) -> Dict[str, Any]:
        """获取注册中心统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            "total_commands": len(self._commands),
            "total_aliases": len(self._aliases),
            "commands_by_type": {
                cmd_type.value: len(cmd_set) 
                for cmd_type, cmd_set in self._commands_by_type.items()
            }
        }
