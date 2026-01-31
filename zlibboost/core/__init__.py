"""
ZlibBoost 核心模块

包含异常处理、日志管理、配置管理等核心功能。
"""

from .exceptions import *
from .logger import LogManager, get_logger, setup_logging, LOG_LEVELS

__all__ = [
    # 异常类
    'ZlibBoostError',
    'ParserError',
    'SimulationError',
    'ConfigError',
    'UnknownCommandError',
    'InvalidValueError',
    'TemplateError',
    'EmptyConfigError',
    'FileAccessError',
    'ValidationError',
    'CommandParseError',
    'TimingTypeError',
    'TableTypeError',
    'CellNotFoundError',
    'VectorParseError',
    'WaveformError',
    'DatabaseError',
    'ModelError',
    'BuilderError',
    'AnalysisError',
    'OutputError',
    'LibertyError',
    'JsonError',
    'ExecutorError',
    'SchedulerError',
    'OptimizerError',

    # 日志管理
    'LogManager',
    'get_logger',
    'setup_logging',
    'LOG_LEVELS',
]