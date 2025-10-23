#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
人类行为模拟模块
借鉴cursor-ideal项目的真实行为模拟
关键：字符级输入、鼠标移动、随机延迟
"""

import logging
import random
import time


class HumanBehaviorSimulator:
    """人类行为模拟器"""
    
    def __init__(self, log_callback=None):
        """
        初始化行为模拟器
        
        Args:
            log_callback: 日志回调函数
        """
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
    
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.debug(message)  # 行为模拟日志使用debug级别
        if self.log_callback:
            self.log_callback(message)
    
    def humanlike_input(self, element, text: str, 
                       min_delay: float = 0.15, 
                       max_delay: float = 0.35):
        """
        模拟人类输入 - 字符级输入，随机延迟
        
        Args:
            element: 输入元素
            text: 要输入的文本
            min_delay: 最小字符间延迟
            max_delay: 最大字符间延迟
        """
        try:
            for i, char in enumerate(text):
                # 输入单个字符
                element.input(char)
                
                # 字符间随机延迟
                char_delay = random.uniform(min_delay, max_delay)
                time.sleep(char_delay)
                
                # 空格后额外停顿（更真实）
                if char == ' ':
                    time.sleep(random.uniform(0.15, 0.30))
                
                # 15%概率出现长停顿（模拟思考）
                if random.random() < 0.15:
                    time.sleep(random.uniform(0.4, 0.8))
                    
        except Exception as e:
            self.logger.warning(f"字符级输入失败，使用直接输入: {str(e)}")
            # 降级：直接输入整个字符串
            element.input(text)
    
    def humanlike_mouse_move(self, element):
        """
        模拟鼠标移动到元素
        
        Args:
            element: 目标元素
        """
        try:
            # 确保元素可见（滚动到视图）
            tab = getattr(element, 'tab', None)
            if tab:
                tab.scroll.to_see(element)
            time.sleep(random.uniform(0.05, 0.1))
            
            # 鼠标悬停
            element.hover()
            
            # 短暂停留
            time.sleep(random.uniform(0.02, 0.1))
            
        except Exception as e:
            self.logger.debug(f"鼠标移动失败: {str(e)}")
            # 失败时确保元素可见
            try:
                tab = getattr(element, 'tab', None)
                if tab:
                    tab.scroll.to_see(element)
            except:
                pass
    
    def humanlike_click(self, tab, element):
        """
        模拟人类点击 - 移动 + 停顿 + 点击
        
        Args:
            tab: 浏览器标签页对象
            element: 要点击的元素
        """
        try:
            # 1. 先移动鼠标到元素
            self.humanlike_mouse_move(element)
            
            # 2. 随机停顿（模拟瞄准）
            time.sleep(random.uniform(0.1, 0.4))
            
            # 3. 点击
            element.click()
            
            # 4. 点击后短暂等待
            time.sleep(random.uniform(0.2, 0.5))
            
        except Exception as e:
            self.logger.error(f"人类点击失败: {str(e)}")
            # 降级：直接点击
            try:
                element.click()
            except:
                pass
    
    def smart_wait(self, wait_type: str, wait_times: dict, 
                   condition=None, timeout=None) -> bool:
        """
        智能等待 - 支持随机波动和条件检查
        
        Args:
            wait_type: 等待类型
            wait_times: 等待时间配置字典
            condition: 可选的条件函数
            timeout: 可选的超时时间
            
        Returns:
            bool: 条件是否满足（无条件时返回True）
        """
        # 获取基础等待时间
        wait_time = timeout if timeout is not None else wait_times.get(wait_type, 1.0)
        
        # 添加随机波动（85%-130%）
        if timeout is None:
            randomness = 0.85 + random.random() * 0.45
            wait_time = wait_time * randomness
        
        if not condition:
            # 简单等待
            time.sleep(wait_time)
            return True
        
        # 带条件的等待
        start_time = time.time()
        check_interval = min(0.5, wait_time / 4)
        
        while time.time() - start_time < wait_time:
            if condition():
                return True
            time.sleep(check_interval)
        
        return False
    
    def simulate_page_browse(self, tab, duration: float = None):
        """
        模拟页面浏览行为
        
        Args:
            tab: 浏览器标签页对象
            duration: 浏览时长（秒），如果不提供则随机
        """
        try:
            if duration is None:
                duration = random.uniform(0.5, 2.0)
            
            # 随机选择行为
            behaviors = [
                self._simulate_scroll,
                self._simulate_mouse_movement,
                self._simulate_idle,
            ]
            
            end_time = time.time() + duration
            while time.time() < end_time:
                behavior = random.choice(behaviors)
                behavior(tab)
                time.sleep(random.uniform(0.3, 0.8))
                
        except Exception as e:
            self.logger.debug(f"浏览模拟失败: {str(e)}")
    
    def _simulate_scroll(self, tab):
        """模拟滚动"""
        try:
            scroll_y = random.randint(50, 200)
            tab.run_js(f"window.scrollBy(0, {scroll_y});")
            time.sleep(random.uniform(0.2, 0.5))
        except:
            pass
    
    def _simulate_mouse_movement(self, tab):
        """模拟鼠标移动"""
        try:
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            tab.run_js(f"""
                var event = new MouseEvent('mousemove', {{
                    view: window,
                    bubbles: true,
                    cancelable: true,
                    clientX: {x},
                    clientY: {y}
                }});
                document.dispatchEvent(event);
            """)
            time.sleep(random.uniform(0.1, 0.3))
        except:
            pass
    
    def _simulate_idle(self, tab):
        """模拟空闲"""
        time.sleep(random.uniform(0.5, 1.5))
