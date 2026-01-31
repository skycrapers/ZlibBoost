"""
ZlibBoost 异常类定义

定义了 ZlibBoost 项目中使用的所有异常类，提供了层次化的异常处理机制。
"""


class ZlibBoostError(Exception):
    """Base exception for all zlibboost errors."""
    pass


class ParserError(ZlibBoostError):
    """Base exception for parsing errors."""
    pass


class SimulationError(ZlibBoostError):
    """Base exception for simulation errors."""
    pass


class ConfigError(ZlibBoostError):
    """Configuration related errors."""
    pass


class UnknownCommandError(ParserError):
    """Raised when an unknown command is encountered."""
    pass


class InvalidValueError(ParserError):
    """Raised when a parameter value is invalid."""
    pass


class TemplateError(ParserError):
    """Raised when there's an error in a template file."""
    pass


class EmptyConfigError(ConfigError):
    """Raised when configuration file is empty or has no valid parameters."""
    pass


class FileAccessError(ZlibBoostError):
    """Raised when there are problems accessing files."""
    pass


class ValidationError(ConfigError):
    """Raised when configuration validation fails."""
    pass


class CommandParseError(ParserError):
    """Raised when there are errors parsing timing files."""
    pass


class TimingTypeError(CommandParseError):
    """Raised when timing type is invalid or unsupported."""
    pass


class TableTypeError(CommandParseError):
    """Raised when table type cannot be determined."""
    pass


class CellNotFoundError(CommandParseError):
    """Raised when referenced cell is not found."""
    pass


class VectorParseError(CommandParseError):
    """Raised when vector parsing fails."""
    pass


class WaveformError(CommandParseError):
    """Raised when waveform generation fails."""
    pass


# 新增的异常类，用于重构后的模块

class DatabaseError(ZlibBoostError):
    """Database related errors."""
    pass


class ModelError(DatabaseError):
    """Data model related errors."""
    pass


class BuilderError(DatabaseError):
    """Model builder related errors."""
    pass


class AnalysisError(ZlibBoostError):
    """Analysis related errors."""
    pass


class OutputError(ZlibBoostError):
    """Output generation related errors."""
    pass


class LibertyError(OutputError):
    """Liberty file generation errors."""
    pass


class JsonError(OutputError):
    """JSON output errors."""
    pass


class ExecutorError(SimulationError):
    """Simulation executor errors."""
    pass


class SchedulerError(SimulationError):
    """Task scheduler errors."""
    pass


class OptimizerError(SimulationError):
    """Optimization errors."""
    pass


class TemplateNotFoundError(DatabaseError):
    """Raised when a template is not found in the database."""
    pass


class WaveformNotFoundError(DatabaseError):
    """Raised when a waveform is not found in the database."""
    pass


class ConfigurationError(ConfigError):
    """Raised when configuration is invalid or incomplete."""
    pass


# 异常类映射，用于向后兼容
EXCEPTION_MAP = {
    'ZlibBoostError': ZlibBoostError,
    'ParserError': ParserError,
    'SimulationError': SimulationError,
    'ConfigError': ConfigError,
    'UnknownCommandError': UnknownCommandError,
    'InvalidValueError': InvalidValueError,
    'TemplateError': TemplateError,
    'EmptyConfigError': EmptyConfigError,
    'FileAccessError': FileAccessError,
    'ValidationError': ValidationError,
    'CommandParseError': CommandParseError,
    'TimingTypeError': TimingTypeError,
    'TableTypeError': TableTypeError,
    'CellNotFoundError': CellNotFoundError,
    'VectorParseError': VectorParseError,
    'WaveformError': WaveformError,
    'DatabaseError': DatabaseError,
    'ModelError': ModelError,
    'BuilderError': BuilderError,
    'AnalysisError': AnalysisError,
    'OutputError': OutputError,
    'LibertyError': LibertyError,
    'JsonError': JsonError,
    'ExecutorError': ExecutorError,
    'SchedulerError': SchedulerError,
    'OptimizerError': OptimizerError,
    'TemplateNotFoundError': TemplateNotFoundError,
    'WaveformNotFoundError': WaveformNotFoundError,
    'ConfigurationError': ConfigurationError,
}


__all__ = list(EXCEPTION_MAP.keys())
