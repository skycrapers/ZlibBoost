"""
ZlibBoost - 标准单元库表征框架

ZlibBoost 是一个开源的标准单元库表征框架，支持从 TCL 配置文件生成 SPICE 网表，
执行多线程仿真，并将结果转换为 Liberty 格式的库文件。

主要功能：
- TCL 配置文件解析与命令处理
- SPICE 网表自动生成
- 多仿真器支持 (HSPICE, Spectre, NgSpice)
- 多线程并行仿真执行
- 时序弧自动推断与验证
- Liberty/JSON 格式输出
- 结果分析与优化

版本: 2.0.0
许可证: BSD 3-Clause License with Commercial Use Restriction
"""

__version__ = "2.0.0"
__author__ = "ZlibBoost Team"
__license__ = "BSD 3-Clause License with Commercial Use Restriction"

# 导入主要模块
from . import core
from . import database
from . import parsers
from . import simulation
from . import output
from . import cli
from . import commands
from . import arc_generation

# 导入常用类和函数
from .core.exceptions import ZlibBoostError
from .core.logger import LogManager
from .database import Cell, TimingArc, Template, CellLibraryDB
from .parsers import UnifiedParser, TclEngine

__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    "__license__",

    # 主要模块
    "core",
    "database",
    "parsers",
    "simulation",
    "output",
    "cli",
    "commands",
    "arc_generation",

    # 核心类
    "ZlibBoostError",
    "LogManager",
    "Cell",
    "TimingArc",
    "Template",
    "CellLibraryDB",
    "UnifiedParser",
    "TclEngine",
]
