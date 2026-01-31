"""
统一TCL解析器

该模块提供了统一的TCL文件解析功能，整合了：
- 配置文件解析 (原ConfigParser功能)
- 表征文件解析 (原CommandDispatcher功能)
- 统一的命令处理架构

重构目标：
- 统一所有TCL文件的解析入口
- 使用相同的命令注册和分发机制
- 提供一致的API接口
"""

from typing import Dict, List, Any, Optional, Union, Set
from pathlib import Path
import json

from zlibboost.core.exceptions import CommandParseError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.core.logger import LogManager
from zlibboost.parsers.unified_dispatcher import UnifiedCommandDispatcher


class UnifiedTclParser:
    """统一TCL解析器
    
    这个类提供了统一的TCL文件解析功能，支持：
    1. 配置文件解析 (set_var命令)
    2. 表征文件解析 (define_*命令)
    3. 混合文件解析 (包含配置和表征命令)
    4. 统一的错误处理和状态管理
    
    替代了原有的ConfigParser和CommandDispatcher，提供统一的解析接口。
    """
    
    def __init__(self,
                 library_db: CellLibraryDB = None,
                 engine_name: str = "unified_parser"):
        """初始化统一TCL解析器

        Args:
            library_db: 可选的库数据库实例
            engine_name: TCL引擎名称
        """
        self.logger = LogManager().get_logger(__name__)

        # 初始化组件
        self.library_db = library_db or CellLibraryDB()

        # 使用统一的命令分发器
        self.dispatcher = UnifiedCommandDispatcher(
            library_db=self.library_db,
            engine_name=engine_name
        )
        
        # 解析历史
        self.parsed_files: List[str] = []
        self.parse_results: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info(f"Unified TCL parser initialized with engine '{engine_name}'")
    
    def parse_config_file(self, filepath: str) -> Dict[str, Any]:
        """解析配置文件
        
        Args:
            filepath: 配置文件路径
            
        Returns:
            Dict[str, Any]: 解析后的配置参数
            
        Raises:
            ConfigError: 配置文件解析错误
        """
        try:
            self.logger.info(f"Parsing config file: {filepath}")
            
            # 使用统一分发器解析文件
            self.dispatcher.parse_file(filepath)
            
            # 获取保留变量结果
            reserved_vars = self.dispatcher.get_reserved_vars()
            
            # 记录解析结果
            self.parsed_files.append(filepath)
            self.parse_results[filepath] = {
                "type": "config",
                "reserved_vars": reserved_vars,
                "stats": self.dispatcher.get_execution_stats()
            }

            self.logger.info(f"Successfully parsed config file: {filepath}, {len(reserved_vars)} variables")
            return reserved_vars
            
        except Exception as e:
            error_msg = f"Error parsing config file {filepath}: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)
    
    def parse_characterization_file(self, filepath: str) -> CellLibraryDB:
        """解析表征文件
        
        Args:
            filepath: 表征文件路径
            
        Returns:
            CellLibraryDB: 解析后的库数据库
            
        Raises:
            CommandParseError: 表征文件解析错误
        """
        try:
            self.logger.info(f"Parsing characterization file: {filepath}")
            
            # 使用统一分发器解析文件
            library_db = self.dispatcher.parse_file(filepath)
            
            # 获取解析结果
            active_cells = self.dispatcher.get_active_cells()
            
            # 记录解析结果
            self.parsed_files.append(filepath)
            self.parse_results[filepath] = {
                "type": "characterization",
                "cells_count": len(library_db.get_all_cell_names()),
                "active_cells": list(active_cells),
                "stats": self.dispatcher.get_execution_stats()
            }
            
            self.logger.info(f"Successfully parsed characterization file: {filepath}, {len(active_cells)} active cells")
            return library_db
            
        except Exception as e:
            error_msg = f"Error parsing characterization file {filepath}: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)
    
    def parse_file(self, filepath: str, file_type: str = "auto") -> Dict[str, Any]:
        """解析TCL文件（自动检测类型或指定类型）
        
        Args:
            filepath: 文件路径
            file_type: 文件类型 ("config", "characterization", "auto")
            
        Returns:
            Dict[str, Any]: 解析结果
            
        Raises:
            CommandParseError: 解析错误
        """
        try:
            filepath = str(Path(filepath).resolve())
            
            if file_type == "auto":
                file_type = self._detect_file_type(filepath)
            
            if file_type == "config":
                reserved_vars = self.parse_config_file(filepath)
                return {
                    "type": "config",
                    "reserved_vars": reserved_vars,
                    "library_db": self.library_db
                }
            elif file_type == "characterization":
                library_db = self.parse_characterization_file(filepath)
                return {
                    "type": "characterization",
                    "library_db": library_db,
                    "reserved_vars": self.dispatcher.get_reserved_vars()
                }
            else:
                raise CommandParseError(f"Unknown file type: {file_type}")
                
        except Exception as e:
            error_msg = f"Error parsing file {filepath}: {str(e)}"
            self.logger.error(error_msg)
            raise CommandParseError(error_msg)
    
    def parse_multiple_files(self, filepaths: List[str]) -> Dict[str, Any]:
        """解析多个TCL文件
        
        Args:
            filepaths: 文件路径列表
            
        Returns:
            Dict[str, Any]: 综合解析结果
        """
        results = {
            "reserved_vars": {},
            "library_db": self.library_db,
            "parsed_files": [],
            "errors": []
        }

        for filepath in filepaths:
            try:
                result = self.parse_file(filepath)
                results["parsed_files"].append(filepath)

                if result["type"] == "config":
                    results["reserved_vars"].update(result["reserved_vars"])
                elif result["type"] == "characterization":
                    # 库数据库会自动累积
                    pass
                    
            except Exception as e:
                error_info = {
                    "file": filepath,
                    "error": str(e)
                }
                results["errors"].append(error_info)
                self.logger.error(f"Failed to parse {filepath}: {str(e)}")
        
        self.logger.info(f"Parsed {len(results['parsed_files'])} files successfully, {len(results['errors'])} errors")
        return results
    
    def _detect_file_type(self, filepath: str) -> str:
        """自动检测文件类型
        
        Args:
            filepath: 文件路径
            
        Returns:
            str: 文件类型 ("config" 或 "characterization")
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 简单的启发式检测
            if "set_var" in content and "define_" not in content:
                return "config"
            elif "define_" in content:
                return "characterization"
            else:
                # 默认为配置文件
                return "config"
                
        except Exception:
            # 如果无法读取文件，默认为配置文件
            return "config"
    

    
    def get_library_db(self) -> CellLibraryDB:
        """获取库数据库"""
        return self.library_db

    def get_active_cells(self) -> Set[str]:
        """获取激活的单元列表"""
        return self.dispatcher.get_active_cells()

    def get_reserved_vars(self) -> Dict[str, Any]:
        """获取程序保留变量"""
        return self.dispatcher.get_reserved_vars()

    def get_parsed_files(self) -> List[str]:
        """获取已解析的文件列表"""
        return self.parsed_files.copy()

    def get_parse_results(self) -> Dict[str, Dict[str, Any]]:
        """获取解析结果详情"""
        return self.parse_results.copy()
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计信息"""
        return {
            "parsed_files_count": len(self.parsed_files),
            "dispatcher_stats": self.dispatcher.get_execution_stats(),
            "reserved_vars_count": len(self.dispatcher.get_reserved_vars()),
            "active_cells_count": len(self.dispatcher.get_active_cells()),
            "library_cells_count": len(self.library_db.get_all_cell_names())
        }
    
    def export_config_to_json(self, filepath: str) -> None:
        """导出配置到JSON文件
        
        Args:
            filepath: 输出文件路径
        """
        config_data = {
            "reserved_vars": self.dispatcher.get_reserved_vars(),
            "parsed_files": self.parsed_files,
            "stats": self.get_execution_stats()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Config exported to: {filepath}")
    
    def reset(self):
        """重置解析器状态"""
        self.dispatcher.reset()
        self.parsed_files.clear()
        self.parse_results.clear()
        self.library_db = CellLibraryDB()
        self.logger.info("Parser state reset")



