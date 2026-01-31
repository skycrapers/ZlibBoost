"""
波形命令处理器

处理 define_driver_waveform TCL命令，负责：
- 解析波形定义参数
- 生成波形数值
- 将波形添加到库数据库

重构自 legacy/frontend/tcl_timing_parser.py 的 _handle_driver_waveform 和 _generate_waveform_values 方法
"""

import os
import numpy as np
from typing import Dict, Any, List

from zlibboost.core.exceptions import CommandParseError, WaveformError
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.waveform import Waveform
from .base_handler import BaseCommandHandler


class WaveformHandler(BaseCommandHandler):
    """驱动波形定义命令处理器
    
    处理 define_driver_waveform TCL命令，用于定义驱动波形。
    波形定义了输入信号的时间特性，包括：
    - 波形类型（线性、指数、混合）
    - 转换时间索引
    - 电压索引
    - 生成的波形数值
    """

    def handle_driver_waveform(self, *args) -> str:
        """处理 define_driver_waveform TCL命令
        
        命令格式:
        define_driver_waveform -type <waveform_type> -index_1 {times} -index_2 {voltages} <waveform_name>
        
        Args:
            *args: TCL命令参数
            
        Returns:
            str: 空字符串（TCL命令返回值）
            
        Raises:
            CommandParseError: 参数解析或验证失败
            WaveformError: 波形生成失败
        """
        try:
            # 解析TCL参数
            params = self.parse_tcl_args(args)
            self.log_command_start("define_driver_waveform", params)
            
            # 解析索引值
            index_1 = self.parse_number_list(params["index_1"])  # 转换时间
            index_2 = self.parse_number_list(params["index_2"])  # 归一化电压
            
            # 从环境变量获取波形类型（在 ZlibBoost.run() 中设置）
            waveform_type = int(os.environ.get('DRIVER_WAVEFORM_TYPE', '1'))
            self.logger.info(f"Waveform type selected: {waveform_type}")
            
            # 验证参数
            self._validate_waveform_params(params["name"], index_1, index_2, waveform_type)
            
            # 直接从 index_1 和 index_2 生成数值
            values = self._generate_waveform_values(index_1, index_2, waveform_type, params["name"])
            
            # 创建波形对象并添加到数据库
            waveform = Waveform(
                name=params["name"],
                waveform_type=params["type"],
                index_1=index_1,
                index_2=index_2,
                values=values
            )
            self.library_db.add_driver_waveform(waveform)
            
            self.log_command_success("define_driver_waveform")
            self.logger.info(f"Added driver waveform '{params['name']}' with type {waveform_type}, "
                           f"shape: {values.shape}")
            
            return ""
            
        except Exception as e:
            self.log_command_error("define_driver_waveform", e)
            raise CommandParseError(f"Error in define_driver_waveform: {str(e)}")

    def _validate_waveform_params(self, name: str, index_1: List[float], 
                                index_2: List[float], waveform_type: int):
        """验证波形参数
        
        Args:
            name: 波形名称
            index_1: 转换时间列表
            index_2: 归一化电压列表
            waveform_type: 波形类型
            
        Raises:
            CommandParseError: 验证失败
        """
        if not name.strip():
            raise CommandParseError("Waveform name cannot be empty")
            
        if not index_1:
            raise CommandParseError("index_1 (transition times) cannot be empty")
        if not index_2:
            raise CommandParseError("index_2 (voltages) cannot be empty")
            
        # 验证转换时间为正数
        if any(t <= 0 for t in index_1):
            raise CommandParseError("Transition times must be positive")
            
        # 验证电压在0-1范围内
        if any(v < 0 or v > 1 for v in index_2):
            raise CommandParseError("Voltage values must be between 0 and 1")
            
        # 验证波形类型
        if waveform_type not in [1, 2, 3]:
            raise CommandParseError(f"Invalid waveform type: {waveform_type}. Must be 1, 2, or 3")

    def _generate_waveform_values(self, index_1: List[float], index_2: List[float], 
                                waveform_type: int, name: str) -> np.ndarray:
        """为每个转换时间点生成波形数值
        
        Args:
            index_1: 转换时间列表（斜率时间）
            index_2: 0到1之间的归一化电压列表
            waveform_type: 1=线性, 2=指数, 3=线性+指数
            name: 波形名称（用于错误报告）
            
        Returns:
            np.ndarray: 生成的波形数值矩阵
            
        Raises:
            WaveformError: 波形生成失败
        """
        try:
            values = []
            for transition_time in index_1:
                times = []
                for v in index_2:
                    if waveform_type == 1:
                        # 线性波形
                        times.append(1.25 * v * transition_time)
                    elif waveform_type == 2:
                        # 指数波形: v = 1 - e^(-t/τ), 其中 τ = transition_time/2
                        if v <= 0:
                            times.append(0)
                        else:
                            times.append(-transition_time/2 * np.log(1 - v))
                    elif waveform_type == 3:
                        # 混合波形（线性+指数）
                        tau = transition_time / 2
                        if v <= 0:
                            times.append(0)
                        else:
                            # 使用牛顿-拉夫逊方法求解
                            t = self._solve_mixed_waveform(v, tau)
                            times.append(t)
                    else:
                        raise CommandParseError(f"Invalid waveform type: {waveform_type}")
                values.append(times)
            return np.array(values)
            
        except Exception as e:
            raise WaveformError(f"Failed to generate waveform values for '{name}': {str(e)}")

    def _solve_mixed_waveform(self, v: float, tau: float) -> float:
        """使用牛顿-拉夫逊方法求解混合波形方程
        
        方程: 0.5 * (1 - e^(-t/τ)) + 0.5 * (0.4 * t / τ) = v
        
        Args:
            v: 目标电压值
            tau: 时间常数
            
        Returns:
            float: 求解的时间值
        """
        def f(t):
            # 混合波形函数
            return 0.5 * (1 - np.exp(-t / tau)) + 0.5 * (0.4 * t / tau) - v

        def df(t):
            # 混合波形函数的导数
            return 0.5 / tau * np.exp(-t / tau) + 0.5 * 0.4 / tau
        
        # 初始猜测值
        t_guess = -tau * np.log(1 - min(v/0.5, 0.99999)) if v < 0.5 else tau
        
        # 牛顿-拉夫逊迭代
        t = t_guess
        for _ in range(10):  # 执行几次迭代（通常很快收敛）
            t_new = t - f(t) / df(t)
            if abs(t_new - t) < 1e-9:  # 检查收敛性
                t = t_new
                break
            t = t_new
        
        return t

    def handle_command(self, *args) -> str:
        """实现基类的抽象方法"""
        return self.handle_driver_waveform(*args)
