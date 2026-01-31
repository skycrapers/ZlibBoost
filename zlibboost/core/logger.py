"""
ZlibBoost 日志管理器

提供集中化的日志管理功能，支持控制台和文件输出，
以及不同模块的独立日志记录。
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class LogManager:
    """Centralized logging management for zlibboost."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.root_logger = logging.getLogger('zlibboost')
            self.root_logger.setLevel(logging.INFO)
            self.formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            self._loggers: Dict[str, logging.Logger] = {}
    
    def setup(self, 
              log_level: int = logging.INFO, 
              log_file: Optional[str] = None,
              console: bool = True,
              format_string: Optional[str] = None) -> None:
        """
        Setup global logging configuration.
        
        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (optional)
            console: Whether to output to console
            format_string: Custom format string (optional)
        """
        self.root_logger.setLevel(log_level)
        
        # Update formatter if custom format provided
        if format_string:
            self.formatter = logging.Formatter(format_string)
        
        # Clear existing handlers
        self.root_logger.handlers.clear()
        
        # Console handler
        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(self.formatter)
            console_handler.setLevel(log_level)
            self.root_logger.addHandler(console_handler)
        
        # File handler
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(self.formatter)
            file_handler.setLevel(log_level)
            self.root_logger.addHandler(file_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a logger instance for a specific module.
        
        Args:
            name: Logger name (usually module name)
            
        Returns:
            Logger instance
        """
        full_name = f'zlibboost.{name}'
        if full_name not in self._loggers:
            self._loggers[full_name] = logging.getLogger(full_name)
        return self._loggers[full_name]
    
    def set_level(self, level: int) -> None:
        """Set logging level for all loggers."""
        self.root_logger.setLevel(level)
        for handler in self.root_logger.handlers:
            handler.setLevel(level)
    
    def add_file_handler(self, log_file: str, level: int = logging.INFO) -> None:
        """Add an additional file handler."""
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(self.formatter)
        file_handler.setLevel(level)
        self.root_logger.addHandler(file_handler)
    
    def log_performance(self, operation: str, duration: float, **kwargs) -> None:
        """Log performance metrics."""
        perf_logger = self.get_logger('performance')
        extra_info = ' '.join([f'{k}={v}' for k, v in kwargs.items()])
        perf_logger.info(f"PERF: {operation} took {duration:.3f}s {extra_info}")
    
    def log_memory_usage(self, operation: str, memory_mb: float) -> None:
        """Log memory usage."""
        mem_logger = self.get_logger('memory')
        mem_logger.info(f"MEM: {operation} used {memory_mb:.2f}MB")
    
    def create_session_log(self, session_id: str) -> str:
        """Create a session-specific log file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/session_{session_id}_{timestamp}.log"
        self.add_file_handler(log_file)
        return log_file


# 全局日志管理器实例
log_manager = LogManager()


def get_logger(name: str) -> logging.Logger:
    """
    便捷函数：获取日志记录器
    
    Args:
        name: 模块名称
        
    Returns:
        Logger instance
    """
    return log_manager.get_logger(name)


def setup_logging(**kwargs) -> None:
    """
    便捷函数：设置日志配置
    
    Args:
        **kwargs: 传递给 LogManager.setup() 的参数
    """
    log_manager.setup(**kwargs)


# 预定义的日志级别常量
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


__all__ = [
    'LogManager',
    'log_manager',
    'get_logger',
    'setup_logging',
    'LOG_LEVELS',
]
