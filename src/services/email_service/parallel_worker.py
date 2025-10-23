#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
并行工作器 - 负责并行注册任务的执行
从 auto_register_engine.py 拆分出来的并行注册功能

并发模型：浏览器实例 + 标签页
- 最多5个浏览器实例（进程级并发）
- 每个实例最多10个标签页（标签页级并发）
- 最大并发数: 5 × 10 = 50
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Dict, List, Callable, Optional

from .browser_manager import BrowserManager

# 北京时区（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


@dataclass
class ParallelRegisterTask:
    """并行注册任务数据结构"""
    task_id: int
    total_tasks: int
    thread_id: str
    browser_instance_id: int  # 浏览器实例ID (1-5)
    tab_id: int  # 标签页ID (1-10)


def execute_parallel_registration_task_with_browser(
    task_id: int, 
    total_tasks: int, 
    browser_instance_id: int,
    tab_id: int,
    shared_browser,
    shared_tab,
    account_config, 
    account_manager, 
    register_config, 
    register_mode: str,
    log_callback, 
    shared_stop
) -> Dict:
    """
    使用共享浏览器和标签页执行注册任务
    
    Args:
        task_id: 任务ID
        total_tasks: 总任务数
        browser_instance_id: 浏览器实例ID (1-5)
        tab_id: 标签页ID (1-10)
        shared_browser: 共享的浏览器实例
        shared_tab: 共享的标签页
        account_config: 账号配置
        account_manager: 账号管理器
        register_config: 注册配置
        register_mode: 注册模式（password/email_code）
        log_callback: 日志回调
        shared_stop: 共享停止标志
    """
    def log(msg):
        if log_callback:
            log_callback(f"[实例{browser_instance_id}-标签{tab_id}] {msg}")
    
    try:
        if shared_stop():
            return {'task_id': task_id, 'success': False, 'email': '', 'error': '用户取消'}
        
        log(f"🚀 任务 {task_id}/{total_tasks} 开始")
        
        # 创建注册引擎，但不初始化浏览器
        from .auto_register_engine import AutoRegisterEngine
        
        engine = AutoRegisterEngine(account_config, account_manager, register_config)
        engine.set_progress_callback(log)
        engine.set_register_mode(register_mode)
        
        # 使用共享的浏览器和标签页
        engine.browser = shared_browser
        engine.tab = shared_tab
        
        # 执行注册流程（不包含浏览器初始化）
        success = engine._execute_register_flow()
        
        return {
            'task_id': task_id,
            'success': success,
            'email': engine.current_email or '',
            'timestamp': datetime.now(BEIJING_TZ).isoformat()
        }
        
    except Exception as e:
        log(f"❌ 任务异常: {str(e)}")
        return {
            'task_id': task_id,
            'success': False,
            'email': '',
            'error': str(e),
            'timestamp': datetime.now(BEIJING_TZ).isoformat()
        }


def execute_parallel_registration_task(task_id: int, total_tasks: int, account_config, account_manager, register_config, headless_mode: bool, log_callback, shared_stop) -> Dict:
    """
    并行注册单个任务（线程函数） - 传统模式（每任务一个浏览器）
    
    Args:
        task_id: 任务ID
        total_tasks: 总任务数
        account_config: 账号配置
        account_manager: 账号管理器
        register_config: 注册配置
        headless_mode: 无头模式
        log_callback: 日志回调
        shared_stop: 共享停止标志
    """
    def log(msg):
        if log_callback:
            log_callback(f"[Worker-{task_id}] {msg}")
    
    try:
        # 错开启动（避免验证码冲突）
        stagger_delay = (task_id - 1) * 3
        if stagger_delay > 0:
            log(f"⏳ 任务 {task_id}/{total_tasks} 等待 {stagger_delay} 秒后启动")
            for _ in range(int(stagger_delay * 10)):
                if shared_stop():
                    log(f"🛑 任务 {task_id} 在等待期间收到停止信号")
                    return {'task_id': task_id, 'success': False, 'email': '', 'error': '用户取消'}
                time.sleep(0.1)
        
        log(f"🚀 开始注册任务 {task_id}/{total_tasks}")
        
        # 创建独立的注册引擎
        from .auto_register_engine import AutoRegisterEngine
        
        engine = AutoRegisterEngine(account_config, account_manager, register_config)
        engine.set_headless_mode(headless_mode)
        engine.set_progress_callback(log)
        
        # 执行注册
        success = engine.register_account()
        
        return {
            'task_id': task_id,
            'success': success,
            'email': engine.current_email or '',
            'timestamp': datetime.now(BEIJING_TZ).isoformat()
        }
        
    except Exception as e:
        log(f"❌ 任务异常: {str(e)}")
        return {
            'task_id': task_id,
            'success': False,
            'email': '',
            'error': str(e),
            'timestamp': datetime.now(BEIJING_TZ).isoformat()
        }


class RegisterWorker:
    """简化的Worker类（已废弃，保留兼容性）"""
    
    def execute_single_registration(self, task: ParallelRegisterTask) -> Dict:
        """兼容旧代码，直接调用简化的函数"""
        return execute_parallel_registration_task(
            task.task_id, task.total_tasks,
            self.account_config, self.account_manager, self.register_config,
            self.headless_mode, self.progress_callback, lambda: self._should_stop
        )


class ParallelRegistrationManager:
    """并行注册管理器 - 支持浏览器实例+标签页的多层并发"""
    
    def __init__(self, account_config, account_manager, register_config, log_callback=None):
        """
        初始化并行注册管理器
        
        Args:
            account_config: 账号配置管理器
            account_manager: 账号管理器
            register_config: 注册配置管理器
            log_callback: 日志回调函数
        """
        self.account_config = account_config
        self.account_manager = account_manager
        self.register_config = register_config
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        
        # 并行注册配置
        self.parallel_enabled = False
        self.max_parallel_workers = 3  # 默认最大并行数量（传统模式）
        self._parallel_results_lock = threading.Lock()  # 结果收集锁
        self._parallel_progress_lock = threading.Lock()  # 进度报告锁
        self._card_allocation_lock = threading.Lock()  # 银行卡分配锁
        
        # 多层并发配置
        self.multi_level_enabled = False  # 是否启用多层并发
        self.max_browser_instances = 5  # 最多5个浏览器实例
        self.max_tabs_per_instance = 10  # 每个实例最多10个标签页
        
        # 无头模式配置
        self.headless_mode = False
        
        # 注册模式配置
        self.register_mode = "email_code"  # 默认邮箱验证码模式
        
        # 控制标志
        self._should_stop = False
    
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def enable_parallel_mode(self, enabled: bool = True, max_workers: int = 3):
        """
        启用/禁用并行注册模式（传统模式）
        
        Args:
            enabled: 是否启用并行模式
            max_workers: 最大并行工作线程数
        """
        self.parallel_enabled = enabled
        self.max_parallel_workers = max_workers
        self._log_progress(f"🔄 并行注册模式: {'启用' if enabled else '禁用'}, 最大并行数: {max_workers}")
    
    def enable_multi_level_parallel(self, enabled: bool = True, max_instances: int = 5, max_tabs: int = 10):
        """
        启用/禁用多层并发模式（浏览器实例+标签页）
        
        Args:
            enabled: 是否启用多层并发
            max_instances: 最多浏览器实例数（1-5）
            max_tabs: 每实例最多标签页数（1-10）
        """
        self.multi_level_enabled = enabled
        self.max_browser_instances = min(max(1, max_instances), 5)
        self.max_tabs_per_instance = min(max(1, max_tabs), 10)
        
        max_concurrent = self.max_browser_instances * self.max_tabs_per_instance
        self._log_progress(
            f"🔄 多层并发: {'启用' if enabled else '禁用'}, "
            f"实例数: {self.max_browser_instances}, "
            f"标签页/实例: {self.max_tabs_per_instance}, "
            f"最大并发: {max_concurrent}"
        )
    
    def set_headless_mode(self, headless: bool):
        """设置无头模式"""
        self.headless_mode = headless
        mode_text = "无头模式 (后台运行)" if headless else "可视模式 (显示界面)"
        self._log_progress(f"🔧 已设置: {mode_text}")
    
    def set_register_mode(self, mode: str):
        """设置注册模式"""
        self.register_mode = mode
        mode_name = "账号密码模式" if mode == "password" else "邮箱验证码模式"
        self._log_progress(f"🔧 注册模式: {mode_name}")
    
    def _parallel_progress_callback(self, message: str):
        """线程安全的进度回调"""
        with self._parallel_progress_lock:
            if self.log_callback:
                self.log_callback(message)
    
    def _format_time_duration(self, total_seconds: float) -> str:
        """格式化时间显示"""
        if total_seconds >= 3600:  # 超过1小时
            return f"{int(total_seconds // 3600)}时{int((total_seconds % 3600) // 60)}分{int(total_seconds % 60)}秒"
        elif total_seconds >= 60:  # 超过1分钟
            return f"{int(total_seconds // 60)}分{int(total_seconds % 60)}秒"
        else:
            return f"{total_seconds:.1f}秒"
    
    def parallel_batch_register(self, count: int = 1) -> List[Dict]:
        """
        并行批量注册账号
        
        Args:
            count: 注册数量
            
        Returns:
            List[Dict]: 注册结果列表
        """
        # 判断使用哪种并发模式
        if self.multi_level_enabled:
            return self._multi_level_parallel_register(count)
        else:
            return self._traditional_parallel_register(count)
    
    def _multi_level_parallel_register(self, count: int) -> List[Dict]:
        """
        多层并发注册（浏览器实例+标签页）
        
        Args:
            count: 注册数量
            
        Returns:
            List[Dict]: 注册结果列表
        """
        results = []
        batch_start_time = time.time()
        
        # 计算实际使用的实例数和标签页数
        max_concurrent = self.max_browser_instances * self.max_tabs_per_instance
        actual_concurrent = min(count, max_concurrent)
        
        # 计算实际需要的实例数
        actual_instances = min(
            self.max_browser_instances,
            (count + self.max_tabs_per_instance - 1) // self.max_tabs_per_instance
        )
        
        self._log_progress(
            f"🚀 开始多层并发注册 {count} 个账号\n"
            f"   实例数: {actual_instances}, 标签页/实例: {self.max_tabs_per_instance}, "
            f"并发数: {actual_concurrent}"
        )
        
        # 创建浏览器实例
        browser_instances = []
        try:
            browser_manager = BrowserManager(self.account_config, self._parallel_progress_callback)
            
            for instance_id in range(1, actual_instances + 1):
                if self._should_stop:
                    break
                
                self._log_progress(f"🌐 创建浏览器实例 {instance_id}/{actual_instances}")
                browser, first_tab = browser_manager.create_browser_instance(
                    headless_mode=self.headless_mode
                )
                
                # 创建标签页
                tabs = [first_tab]
                for tab_id in range(2, self.max_tabs_per_instance + 1):
                    if self._should_stop:
                        break
                    new_tab = browser.new_tab()
                    tabs.append(new_tab)
                
                browser_instances.append({
                    'instance_id': instance_id,
                    'browser': browser,
                    'tabs': tabs
                })
                
                self._log_progress(f"✅ 实例 {instance_id} 已就绪 ({len(tabs)} 个标签页)")
            
            # 创建任务分配
            tasks = []
            task_id = 1
            for instance_idx, instance_info in enumerate(browser_instances):
                instance_id = instance_info['instance_id']
                browser = instance_info['browser']
                tabs = instance_info['tabs']
                
                for tab_idx, tab in enumerate(tabs):
                    if task_id > count:
                        break
                    
                    tasks.append({
                        'task_id': task_id,
                        'instance_id': instance_id,
                        'tab_id': tab_idx + 1,
                        'browser': browser,
                        'tab': tab
                    })
                    task_id += 1
            
            self._log_progress(f"📋 任务分配完成，共 {len(tasks)} 个任务")
            
            # 使用线程池执行任务
            shared_stop = lambda: self._should_stop
            
            with ThreadPoolExecutor(
                max_workers=len(tasks),
                thread_name_prefix="MultiLevel"
            ) as executor:
                future_to_task = {}
                
                # 提交所有任务
                for task in tasks:
                    if self._should_stop:
                        break
                    
                    future = executor.submit(
                        execute_parallel_registration_task_with_browser,
                        task['task_id'], count,
                        task['instance_id'], task['tab_id'],
                        task['browser'], task['tab'],
                        self.account_config, self.account_manager, self.register_config,
                        self.register_mode,
                        self._parallel_progress_callback, shared_stop
                    )
                    future_to_task[future] = task['task_id']
                
                # 收集结果
                completed_tasks = 0
                for future in as_completed(future_to_task):
                    if self._should_stop:
                        self._log_progress("🛑 正在停止...")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    
                    try:
                        result = future.result()
                        with self._parallel_results_lock:
                            results.append(result)
                            completed_tasks += 1
                        
                        success_emoji = "✅" if result.get('success') else "❌"
                        task_id = result.get('task_id', '?')
                        self._log_progress(
                            f"{success_emoji} 任务 {task_id}/{count} "
                            f"{'成功' if result.get('success') else '失败'}"
                        )
                        self._log_progress(f"📊 总进度: {completed_tasks}/{count}")
                        
                    except Exception as e:
                        self.logger.error(f"任务执行异常: {str(e)}")
                        task_id = future_to_task.get(future, '?')
                        error_result = {
                            'task_id': task_id,
                            'success': False,
                            'email': '',
                            'error': str(e),
                            'timestamp': datetime.now(BEIJING_TZ).isoformat()
                        }
                        with self._parallel_results_lock:
                            results.append(error_result)
                            completed_tasks += 1
        
        finally:
            # 关闭所有浏览器实例
            self._log_progress("🧹 清理浏览器实例...")
            for instance_info in browser_instances:
                try:
                    instance_info['browser'].quit()
                except:
                    pass
            self._log_progress("✅ 浏览器已关闭")
        
        # 统计结果
        results.sort(key=lambda x: x.get('task_id', 0))
        completed_count = len(results)
        success_count = sum(1 for r in results if r.get('success', False))
        
        batch_end_time = time.time()
        total_time = batch_end_time - batch_start_time
        time_str = self._format_time_duration(total_time)
        
        self._log_progress(
            f"🏁 多层并发完成 - 总计: {completed_count}/{count}, "
            f"成功: {success_count}/{completed_count}"
        )
        self._log_progress(f"⏱️ 总用时: {time_str}")
        
        return results
    
    def _traditional_parallel_register(self, count: int) -> List[Dict]:
        """
        传统并行注册（每任务一个浏览器）
        
        Args:
            count: 注册数量
            
        Returns:
            List[Dict]: 注册结果列表
        """
        results = []
        
        # 记录批量注册开始时间
        batch_start_time = time.time()
        self._log_progress(f"🚀 开始并行批量注册 {count} 个账号，并行数: {self.max_parallel_workers}")
        
        # 确保count是整数
        count = int(count) if isinstance(count, str) else count
        
        # 创建任务列表
        tasks = [
            ParallelRegisterTask(
                task_id=i + 1,
                total_tasks=count,
                thread_id=f"thread_{i + 1}",
                browser_instance_id=0,
                tab_id=0
            )
            for i in range(count)
        ]
        
        # 创建共享停止标志
        shared_stop = lambda: self._should_stop
        
        # 简化的并行注册：直接提交任务函数
        with ThreadPoolExecutor(max_workers=self.max_parallel_workers, thread_name_prefix="CursorReg") as executor:
            future_to_task_id = {}
            
            # 提交所有任务
            for i, task in enumerate(tasks):
                if self._should_stop:
                    self._log_progress("🛑 用户请求停止，取消剩余任务")
                    break
                
                # 直接提交任务函数
                future = executor.submit(
                    execute_parallel_registration_task,
                    task.task_id, task.total_tasks,
                    self.account_config, self.account_manager, self.register_config,
                    self.headless_mode, self._parallel_progress_callback, shared_stop
                )
                future_to_task_id[future] = task.task_id
                
                # 预估完成时间（只显示一次）
                if i == 0:
                    estimated_time = 3 * (count - 1) + 50  # 错开时间 + 平均注册时间
                    self._log_progress(f"📊 预计总完成时间: {estimated_time//60}分{estimated_time%60}秒")
            
            self._log_progress(f"🚀 所有任务已提交，共 {len(future_to_task_id)} 个并行任务正在执行...")
            
            # 收集结果
            completed_tasks = 0
            for future in as_completed(future_to_task_id):
                if self._should_stop:
                    self._log_progress("🛑 正在停止所有并行任务...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    self._log_progress("✅ 已停止注册")
                    break
                
                try:
                    result = future.result()
                    with self._parallel_results_lock:
                        results.append(result)
                        completed_tasks += 1
                    
                    # 报告进度
                    success_emoji = "✅" if result.get('success') else "❌"
                    task_id = result.get('task_id', '?')
                    self._log_progress(f"{success_emoji} 任务 {task_id}/{count} {'注册成功' if result.get('success') else '注册失败'}")
                    self._log_progress(f"📊 总进度: {completed_tasks}/{count}")
                    
                except Exception as e:
                    self.logger.error(f"任务执行异常: {str(e)}")
                    task_id = future_to_task_id.get(future, '?')
                    error_result = {
                        'task_id': task_id,
                        'success': False,
                        'email': '',
                        'error': str(e),
                        'timestamp': datetime.now(BEIJING_TZ).isoformat()
                    }
                    with self._parallel_results_lock:
                        results.append(error_result)
                        completed_tasks += 1
        
        # 按task_id排序结果
        results.sort(key=lambda x: x.get('task_id', 0))
        
        # 最终状态报告
        completed_count = len(results)
        success_count = sum(1 for r in results if r.get('success', False))
        
        # 计算并行批量注册总时间
        batch_end_time = time.time()
        total_time = batch_end_time - batch_start_time
        avg_time_per_account = total_time / completed_count if completed_count > 0 else 0
        time_str = self._format_time_duration(total_time)
        
        if self._should_stop:
            self._log_progress(f"🏁 并行注册已停止 - 完成: {completed_count}/{count}, 成功: {success_count}/{completed_count}")
            if completed_count > 0:
                self._log_progress(f"⏱️ 并行总用时: {time_str}, 平均每账号: {avg_time_per_account:.1f}秒")
            self._log_progress("✅ 已停止注册")
            return results  # 提前返回，不计算效率
        else:
            self._log_progress(f"🏁 并行批量注册完成 - 总计: {completed_count}/{count}, 成功: {success_count}/{completed_count}")
        
        self._log_progress(f"⏱️ 并行总用时: {time_str}, 平均每账号: {avg_time_per_account:.1f}秒")
        
        # 并行效率对比
        estimated_serial_time = avg_time_per_account * count if completed_count > 0 else 0
        if estimated_serial_time > 0:
            efficiency_ratio = estimated_serial_time / total_time if total_time > 0 else 1
            self._log_progress(f"🚀 并行效率: {efficiency_ratio:.1f}x 加速（相比串行）")
        
        return results
    
    def stop_registration(self):
        """停止并行注册"""
        self._should_stop = True
        self._log_progress("🛑 发出并行注册停止信号")
