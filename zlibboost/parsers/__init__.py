"""
Parser modules for ZlibBoost.

This package contains unified parsers for various file formats used in the
ZlibBoost timing characterization tool:
- unified_parser: Unified TCL parser
- tcl_engine: Unified TCL parsing engine
- command_registry: Unified command registration center
- command_callbacks: Independent command callback functions
- unified_dispatcher: Unified command dispatcher
"""

# 统一架构
from .unified_parser import UnifiedTclParser
from .tcl_engine import TclEngine
from .command_registry import CommandRegistry, CommandType
from .command_callbacks import CommandCallbacks
from .unified_dispatcher import UnifiedCommandDispatcher

# 主要接口
TclParser = UnifiedTclParser
UnifiedParser = UnifiedTclParser  # 别名

__all__ = [
    'UnifiedTclParser',
    'UnifiedParser',
    'TclParser',
    'TclEngine',
    'CommandRegistry',
    'CommandType',
    'CommandCallbacks',
    'UnifiedCommandDispatcher',
]