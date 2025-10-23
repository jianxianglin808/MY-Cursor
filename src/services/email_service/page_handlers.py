#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
页面处理器 - 负责各种页面的具体处理逻辑
从 auto_register_engine.py 拆分出来的页面处理功能
"""

import time
import random
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime
from .page_detector import PageState

class PageHandler:
    """页面处理器基类"""
    
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        """
        初始化页面处理器
        
        Args:
            log_callback: 日志回调函数
        """
        self.log_callback = log_callback
        self.stop_check_callback = None  # 停止检查回调
        self.logger = logging.getLogger(__name__)
        
        # 简化等待时间配置 - 使用随机范围避免检测
        self.wait_times = {
            "PAGE_LOAD": (0.8, 1.5),           # 页面加载等待范围
            "INPUT_DELAY": (0.15, 0.35),       # 输入延迟范围
            "CLICK_DELAY": (0.2, 0.5),         # 点击延迟范围
            "SHORT_DELAY": (0.1, 0.3),         # 短延迟范围
            "FORM_SUBMIT": (0.8, 1.5),         # 表单提交等待范围
            "ELEMENT_CHECK_EARLY": (1.0, 1.5), # 元素检查间隔（早期）
            "ELEMENT_CHECK_MID": (0.5, 0.9),   # 元素检查间隔（中期）
            "ELEMENT_CHECK_LATE": (0.2, 0.4),  # 元素检查间隔（后期）
            "URL_CHECK_FAST": (1.5, 2.0),      # URL检查快速模式
            "URL_CHECK_NORMAL": (0.8, 1.5),    # URL检查正常模式
            "URL_CHECK_SLOW": (0.5,0.7),      # URL检查慢速模式
            "ELEMENT_TIMEOUT": (0.05, 0.15),   # 元素查找超时范围
            "MOUSE_MOVE_DELAY_FAST": (0.008, 0.018),    # 鼠标移动延迟（快速）
            "MOUSE_MOVE_DELAY_SLOW": (0.018, 0.045),    # 鼠标移动延迟（慢速）
            "MOUSE_ARRIVE_PAUSE": (0.02, 0.05),         # 鼠标到达后停顿
            "AFTER_CLICK_DELAY": (0.05, 0.08),          # 点击后延迟
            "VERIFICATION_INPUT_NORMAL": (0.35, 0.75),  # 验证码输入正常
            "VERIFICATION_INPUT_FAST": (0.15, 0.35),    # 验证码输入快速
            "VERIFICATION_INPUT_THINK": (0.6, 1.2),     # 验证码输入思考
        }
        
        # 通用按钮选择器(避免重复定义)
        self._init_common_selectors()
    
    def _init_common_selectors(self):
        """初始化通用按钮选择器"""
        self.continue_selectors = ["text=Continue", "button[type='submit']", "text=继续"]
        self.email_code_selectors = [
            "text=Email sign-in code",
            "text=使用邮箱验证码继续",
            "text=使用邮箱验证码登录",
            "text=邮箱登录验证码"
        ]
        self.submit_selectors = self.continue_selectors
        self.by_myself_selectors = ["text=By Myself", "text=独自使用"]
        # 扩展按钮选择器：支持多种结束按钮文本
        self.start_trial_selectors = [
            "text=开始试用",
            "text=订阅",
            "text=Start trial",
            "text=Subscribe",
            "text=继续",
            "text=Continue",
            "button:has-text('开始试用')",
            "button:has-text('Start using')",
            "button:has-text('订阅')",
            "button:has-text('Subscribe')",
            "button[type='submit']"
        ]
    
    def _log_progress(self, message: str):
        """记录进度 - 亮色显示重要信息"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    
    def _smart_wait(self, operation_type: str):
        """智能等待 - 根据操作类型使用合适的等待时间"""
        if operation_type in self.wait_times:
            wait_range = self.wait_times[operation_type]
            # 使用随机时间避免固定模式
            wait_time = random.uniform(wait_range[0], wait_range[1])
            time.sleep(wait_time)
        else:
            # 如果操作类型未定义,使用默认短延迟
            default_range = self.wait_times["SHORT_DELAY"]
            wait_time = random.uniform(default_range[0], default_range[1])
            time.sleep(wait_time)
    
    def _wait_for_element(self, tab, selectors: list, element_name: str, max_wait: int = 60, silent_timeout: bool = False) -> bool:
        """动态等待元素加载 - 使用自适应间隔避免固定模式
        
        Args:
            silent_timeout: 超时时是否静默(不输出日志)，用于可选验证检测
        """
        start_time = time.time()
        check_count = 0
        
        while (time.time() - start_time) < max_wait:
            # 检查停止信号
            if self.stop_check_callback and self.stop_check_callback():
                self._log_progress("🛑 检测到停止信号")
                return False
            
            check_count += 1
            
            for selector in selectors:
                # 使用动态超时值避免固定模式
                timeout = random.uniform(*self.wait_times["ELEMENT_TIMEOUT"])
                element = tab.ele(selector, timeout=timeout)
                if element:
                    self._log_progress(f"✅ {element_name}已就绪")
                    return True
            
            # 自适应检查间隔：早期频繁，后期放慢
            if check_count < 3:
                interval = random.uniform(*self.wait_times["ELEMENT_CHECK_EARLY"])
            elif check_count < 8:
                interval = random.uniform(*self.wait_times["ELEMENT_CHECK_MID"])
            else:
                # 后期偶尔快速检查，避免完全规律
                if random.random() < 0.2:  # 20%概率快速检查
                    interval = random.uniform(*self.wait_times["URL_CHECK_FAST"])
                else:
                    interval = random.uniform(*self.wait_times["ELEMENT_CHECK_LATE"])
            
            time.sleep(interval)
        
        if not silent_timeout:
            self._log_progress(f"⚠️ {element_name}加载超时({max_wait}秒)")
        return False
    
    def _fast_input(self, element, text: str):
        """快速一次性输入 - 除验证码外的通用输入方式"""
        try:
            element.clear()  # 先清空
            element.input(text)  # 一次性输入
            time.sleep(random.uniform(0.1, 0.2))  # 输入完成后短暂等待
        except Exception as e:
            # 如果快速输入失败，重试一次
            try:
                element.clear()
                element.input(text)
                time.sleep(random.uniform(0.1, 0.2))
            except:
                self.logger.warning(f"快速输入失败: {str(e)}")
    
    def _humanlike_input_for_verification(self, element, text: str):
        """验证码专用的人性化输入 - 逐字符输入with随机延迟和思考停顿"""
        try:
            element.clear()  # 先清空
            for i, char in enumerate(text):
                element.input(char)
                
                # 验证码输入间隔 - 使用配置的多样化延迟模拟真人
                if i < len(text) - 1:  # 最后一个字符后不延迟
                    # 15%概率出现思考停顿
                    if random.random() < 0.15:
                        delay = random.uniform(*self.wait_times["VERIFICATION_INPUT_THINK"])
                    # 25%概率快速输入
                    elif random.random() < 0.25:
                        delay = random.uniform(*self.wait_times["VERIFICATION_INPUT_FAST"])
                    # 60%概率正常输入
                    else:
                        delay = random.uniform(*self.wait_times["VERIFICATION_INPUT_NORMAL"])
                    
                    time.sleep(delay)
                        
        except Exception as e:
            # 如果人性化输入失败，回退到直接输入
            element.clear()
            element.input(text)
    
    def _humanlike_input(self, element, text: str, min_delay: float = 0.05, max_delay: float = 0.08):
        """兼容性方法 - 默认使用快速输入"""
        self._fast_input(element, text)
    
    def _fill_input_field_fast(self, tab, selectors: list, value: str, field_name: str) -> bool:
        """输入框填写函数 - 使用动态超时避免固定模式"""
        # 检查是否是无头模式
        is_headless = False
        try:
            is_headless = tab.run_js("return window.outerWidth === 0 || !window.outerWidth;")
        except:
            pass
        
        for selector in selectors:
            try:
                # 无头模式使用更长的超时时间
                timeout = random.uniform(1.0, 2.0) if is_headless else random.uniform(0.25, 0.65)
                element = tab.ele(selector, timeout=timeout)
                if element:
                    # 快速填写，无等待
                    self._fast_input(element, value)
                    return True
                        
            except Exception as e:
                self.logger.debug(f"填写{field_name}尝试失败 ({selector})")
                continue
        
        self.logger.debug(f"⚠️ 无法填写{field_name} (无头模式: {is_headless})")
        return False
    
    def _find_and_click_button(self, tab, selectors: list, button_name: str, silent: bool = False, quick_mode: bool = False) -> bool:
        """
        通用的查找并点击按钮函数 - 极简版本，完全模拟真人行为
        
        真人行为：找到按钮 → 点击 → 结束（不重试、不验证）
        
        Args:
            tab: 浏览器标签页
            selectors: 选择器列表
            button_name: 按钮名称
            silent: 静默模式，不输出日志（用于保险性重试）
            quick_mode: 快速模式，用于重试时（超时时间极短）
        """
        # 快速模式：极短超时（0.02秒），正常模式：动态超时
        timeout = 0.02 if quick_mode else random.uniform(0.25, 0.7)
        
        for selector in selectors:
            try:
                btn = tab.ele(selector, timeout=timeout)
                
                if btn:
                    # 快速模式跳过反应时间
                    if not quick_mode:
                        time.sleep(random.uniform(0.1, 0.25))
                    
                    if not silent:
                        self._log_progress(f"👆 点击{button_name}")
                    
                    # 直接点击，不重试（真人就点一次）
                    # 快速模式下跳过鼠标移动动画
                    self._simulate_click_with_mouse_move(tab, btn, quick_mode=quick_mode)
                    return True
                    
            except Exception as e:
                # 静默处理异常，尝试下一个selector
                self.logger.debug(f"选择器 {selector} 失败: {str(e)}")
                continue
        
        # 未找到按钮时，只在非静默模式下输出日志
        if not silent:
            self._log_progress(f"⚠️ 未找到{button_name}")
        return False

    def _simulate_click_with_mouse_move(self, tab, element, quick_mode: bool = False):
        """模拟鼠标移动到元素位置然后点击，使用贝塞尔曲线和动态参数增加真实性
        
        Args:
            quick_mode: 快速模式，跳过鼠标移动动画直接点击
        """
        try:
            # 快速模式：直接点击，不模拟鼠标移动
            if quick_mode:
                element.click()
                return
            # 获取元素的边界框信息
            rect_info = element.run_js("""
                var rect = this.getBoundingClientRect();
                return {
                    left: rect.left,
                    top: rect.top,
                    width: rect.width,
                    height: rect.height
                };
            """)

            if rect_info:
                # 计算元素中心点坐标（扩大随机偏移范围，不总是点击正中心）
                offset_x = random.uniform(-8, 8)
                offset_y = random.uniform(-8, 8)
                center_x = rect_info['left'] + rect_info['width'] / 2 + offset_x
                center_y = rect_info['top'] + rect_info['height'] / 2 + offset_y

                # 扩大轨迹点数范围，更接近真人鼠标移动
                num_points = random.randint(8, 15)
                
                # 起始点范围增加多样性（不同距离模拟不同的鼠标起始位置）
                distance_range = random.choice([
                    (-100, 100),   # 近距离
                    (-200, 200),   # 中距离
                    (-300, 150)    # 远距离（不对称）
                ])
                start_x = center_x + random.randint(*distance_range)
                start_y = center_y + random.randint(-120, 100)  # 不对称范围更自然
                
                # 控制点随机性增强
                control_offset_1 = random.randint(-50, 50)
                control_offset_2 = random.randint(-40, 40)
                control1_x = (start_x + center_x) / 2 + control_offset_1
                control1_y = (start_y + center_y) / 2 + random.randint(-50, 50)
                control2_x = (start_x + center_x) / 2 + control_offset_2
                control2_y = (start_y + center_y) / 2 + random.randint(-40, 40)
                
                # 生成曲线路径点（带加速度变化）
                for i in range(num_points):
                    t = i / num_points
                    # 三次贝塞尔曲线公式
                    x = (1-t)**3 * start_x + 3*(1-t)**2*t * control1_x + 3*(1-t)*t**2 * control2_x + t**3 * center_x
                    y = (1-t)**3 * start_y + 3*(1-t)**2*t * control1_y + 3*(1-t)*t**2 * control2_y + t**3 * center_y
                    
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
                    
                    # 模拟加速度变化：开始加速→匀速→减速
                    if i < num_points / 3:
                        # 开始阶段：加速
                        delay = random.uniform(0.015, 0.035)
                    elif i < num_points * 2 / 3:
                        # 中间阶段：匀速（快）
                        delay = random.uniform(*self.wait_times["MOUSE_MOVE_DELAY_FAST"])
                    else:
                        # 接近目标：减速
                        delay = random.uniform(*self.wait_times["MOUSE_MOVE_DELAY_SLOW"])
                    
                    time.sleep(delay)

                # 最后移动到精确位置
                tab.run_js(f"""
                    var event = new MouseEvent('mousemove', {{
                        view: window,
                        bubbles: true,
                        cancelable: true,
                        clientX: {center_x},
                        clientY: {center_y}
                    }});
                    document.dispatchEvent(event);
                """)

                # 到达后停顿时间增加变化（70%正常，20%稍长，10%极短）
                pause_choice = random.random()
                if pause_choice < 0.7:
                    pause_time = random.uniform(*self.wait_times["MOUSE_ARRIVE_PAUSE"])
                elif pause_choice < 0.9:
                    pause_time = random.uniform(0.15, 0.35)  # 稍长停顿
                else:
                    pause_time = random.uniform(0.05, 0.08)  # 极短停顿
                
                time.sleep(pause_time)
                element.click()

                # 点击后停留时间也要变化
                after_click_choice = random.random()
                if after_click_choice < 0.6:
                    after_delay = random.uniform(*self.wait_times["AFTER_CLICK_DELAY"])
                elif after_click_choice < 0.85:
                    after_delay = random.uniform(0.12, 0.25)
                else:
                    after_delay = random.uniform(0.02, 0.05)
                
                time.sleep(after_delay)
            else:
                # 如果无法获取位置信息，直接点击
                element.click()

        except Exception as e:
            # 如果是元素失效错误，直接向上抛出让上层重试
            if "已失效" in str(e) or "stale" in str(e).lower():
                self.logger.debug(f"元素失效错误: {str(e)}")
                raise
            
            # 其他错误尝试直接点击
            try:
                element.click()
            except Exception as click_error:
                # 简化错误提示，不显示技术细节
                error_msg = str(click_error)
                # 只记录到日志，不显示给用户
                self.logger.warning(f"点击失败: {error_msg}")
                # 向上抛出，让上层处理
                raise
    
    def _humanlike_click(self, tab, element):
        """人性化点击 - 与_simulate_click_with_mouse_move相同"""
        self._simulate_click_with_mouse_move(tab, element)
    
    def _smart_wait_for_url_change(self, tab, initial_url, timeout=60.0):
        """智能等待URL变化 - 使用自适应间隔避免固定轮询模式"""
        start_time = time.time()
        check_count = 0
        
        while (time.time() - start_time) < timeout:
            if tab.url != initial_url:
                return True
            
            check_count += 1
            
            # 自适应检查间隔：模拟真人从耐心到急躁的心理变化
            if check_count < 2:
                # 前期：刚点击，预期需要时间，耐心等待
                interval = random.uniform(*self.wait_times["URL_CHECK_SLOW"])
            elif check_count < 5:
                # 中期：开始关注是否跳转
                interval = random.uniform(*self.wait_times["URL_CHECK_NORMAL"])
            else:
                # 后期：不耐烦了，频繁检查
                if random.random() < 0.25:  # 25%概率非常急切
                    interval = random.uniform(*self.wait_times["URL_CHECK_FAST"])
                else:
                    interval = random.uniform(*self.wait_times["URL_CHECK_NORMAL"])
            
            time.sleep(interval)
        
        return False
    
    def _wait_for_url_change_with_verification(self, tab, initial_url: str, max_wait: int = 60, retry_on_magic_code: bool = False, operation_callback=None) -> bool:
        """
        等待URL跳转并处理人机验证 - 使用动态间隔避免固定轮询
        
        Args:
            tab: 浏览器标签页
            initial_url: 初始URL
            max_wait: 最长等待时间（秒）
            retry_on_magic_code: 已废弃，保留仅用于兼容性
            operation_callback: 已废弃，保留仅用于兼容性
            
        Returns:
            bool: 是否成功跳转
        """
        try:
            from .verification_handler import VerificationHandler
            verification_handler = VerificationHandler(self.log_callback)
            
            start_time = time.time()
            check_count = 0
            verification_handled = False  # 标记验证是否已处理
            
            while (time.time() - start_time) < max_wait:
                check_count += 1
                
                # 检查停止信号
                if self.stop_check_callback and self.stop_check_callback():
                    self._log_progress("🛑 检测到停止信号")
                    return False
                
                # 先检查URL是否已跳转
                current_url = tab.url
                if current_url != initial_url:
                    return True
                
                # 检测是否有验证（只检测和处理一次）
                if not verification_handled:
                    verification_type = verification_handler.detect_verification(tab)
                    if verification_type != VerificationHandler.TYPE_UNKNOWN:
                        # 直接处理验证，不再重复检测
                        verification_handler._handle_verification_direct(tab, verification_type)
                        verification_handled = True  # 标记已处理，后续循环不再检测
                
                # 检查间隔：降低检测频率
                if check_count < 3:
                    # 前期：正常检查（1.5-2.0秒）
                    interval = random.uniform(1.5, 2.0)
                elif check_count < 8:
                    # 中期：稍快检查（1.0-1.5秒）
                    interval = random.uniform(1.0, 1.5)
                else:
                    # 后期：快速检查（0.8-1.2秒）
                    interval = random.uniform(0.8, 1.2)
                
                time.sleep(interval)
            
            # 超时后检查是否已跳转
            if tab.url != initial_url:
                return True
            else:
                self._log_progress(f"⚠️ 等待超时但页面未跳转")
                return False
                
        except Exception as e:
            self._log_progress(f"⚠️ 验证处理异常: {str(e)}")
            return False

    def _handle_captcha_verification_quick(self, tab, silent=False) -> bool:
        """
        简化版验证码处理：只使用DrissionPage深度处理，没有hcaptcha-inner就跳过
        
        Args:
            tab: 浏览器标签页对象
            silent: 静默模式，不输出详细日志（用于循环调用场景）
            
        Returns:
            bool: 是否成功处理验证码
        """
        # 定义通用的复选框选择器
        CHECKBOX_SELECTORS = [
            '#checkbox',
            'div#checkbox', 
            'div[role="checkbox"]',
            'div[aria-checked]',
            '[role="checkbox"]',
            '.h-captcha-checkbox',
            '[data-hcaptcha-widget-id]',
            'div.check',
            'div.checkbox-container',
            '[class*="captcha"][class*="checkbox"]'
        ]
        
        def try_click_checkbox_in_context(context, context_name=""):
            """尝试在给定上下文中查找并点击复选框"""
            # 最精准定位：优先使用最常见的选择器
            try:
                # 首先尝试最常见的#checkbox
                checkbox = context.ele('#checkbox', timeout=0.05)
                if checkbox:
                    if not silent:
                        self._log_progress("✅ 找到复选框: #checkbox")
                    is_checked = (checkbox.attr('aria-checked') == 'true' or 
                                checkbox.attr('checked') == 'true')
                    if not is_checked:
                        initial_url = tab.url
                        self._humanlike_click(tab, checkbox)
                        if not silent:
                            self._log_progress("✅ 已点击 hCaptcha 复选框")
                        
                        # 智能等待URL变化，简化日志
                        if self._smart_wait_for_url_change(tab, initial_url, timeout=30.0):
                            return True
                        
                        if not silent:
                            self._log_progress("ℹ️ URL未变化，但复选框已点击")
                        return True
                    else:
                        if not silent:
                            self._log_progress("ℹ️ 复选框已经选中")
                        return True
            except:
                pass  # #checkbox找不到时直接返回False
            return False
        
        def process_iframe_deeply(frame, max_depth=2, iframe_index=1, depth_level=0):
            """深度处理iframe，支持多层嵌套（优化：减少深度）"""
            depth_prefix = "  " * depth_level  # 缩进显示层级
            
            # 先在当前层查找复选框
            if try_click_checkbox_in_context(frame, f"iframe#{iframe_index}-depth{depth_level}"):
                # 简化层级显示，只在深层且非静默模式时显示
                if depth_level > 0 and not silent:
                    self._log_progress(f"{depth_prefix}✅ 在第{depth_level}层找到并点击复选框")
                return True
            
            # 递归查找嵌套iframe，最多2层（减少深度提升速度）
            if max_depth > 0:
                try:
                    nested_iframes = frame.eles('tag:iframe', timeout=0.2)  # 减少超时
                    # 精简日志：静默模式下不输出
                    if len(nested_iframes) > 1 and not silent:
                        self.logger.debug(f"{depth_prefix}🔍 第{depth_level}层有 {len(nested_iframes)} 个嵌套iframe")
                    
                    for j, nested_iframe in enumerate(nested_iframes):
                        try:
                            nested_frame = frame.get_frame(nested_iframe)
                            if process_iframe_deeply(nested_frame, max_depth - 1, iframe_index, depth_level + 1):
                                return True
                        except:
                            continue
                except:
                    pass
            return False

        # 使用DrissionPage的iframe处理：查找所有hCaptcha相关iframe
        try:
            all_iframes = tab.eles('tag:iframe', timeout=0.3)
            
            if len(all_iframes) == 0:
                return True  # 没有iframe，直接返回
            
            # 查找所有hCaptcha相关的iframe（不限于hcaptcha-inner）
            hcaptcha_iframes = []
            
            for iframe in all_iframes:
                src = iframe.attr('src') or ''
                title = iframe.attr('title') or ''
                iframe_id = iframe.attr('id') or ''
                
                # 扩大检测范围：包含hcaptcha相关的所有iframe
                if any(keyword in src.lower() for keyword in ['hcaptcha', 'checkbox', 'captcha']) or \
                   any(keyword in title.lower() for keyword in ['hcaptcha', 'checkbox', 'captcha']) or \
                   any(keyword in iframe_id.lower() for keyword in ['hcaptcha', 'checkbox', 'captcha']):
                    hcaptcha_iframes.append(iframe)
            
            # 如果没有找到任何hCaptcha iframe，认为不需要处理
            if not hcaptcha_iframes:
                return True
            
            # 精简日志：只在非静默模式下输出
            if not silent:
                self.logger.info(f"✅ 找到 {len(hcaptcha_iframes)} 个 hCaptcha iframe")
            
            # 处理找到的 hCaptcha iframe
            for i, iframe in enumerate(hcaptcha_iframes):
                try:
                    src = iframe.attr('src') or ''
                    if not silent:
                        self.logger.info(f"🔄 [{i+1}/{len(hcaptcha_iframes)}] 处理: {src[:60]}...")
                    frame = tab.get_frame(iframe)
                    if process_iframe_deeply(frame, iframe_index=i+1):
                        if not silent:
                            self._log_progress("✅ hCaptcha验证完成")
                        return True
                except Exception as iframe_err:
                    self._log_progress(f"⚠️ 处理第 {i+1} 个 iframe 出错: {str(iframe_err)}")
                    continue
            
            # 如果所有iframe都处理失败，但不阻塞流程
            return True

        except Exception as e:
            return True  # 异常时不阻塞流程



class NavigationHandler(PageHandler):
    """页面导航处理器"""
    
    def navigate_to_login_page(self, tab) -> bool:
        """导航到登录页面并等待加载"""
        try:
            login_url = "https://authenticator.cursor.sh/"
            self._log_progress(f"🌐 导航到登录页...")
            
            # 使用JS导航，不阻塞，无需后台线程
            try:
                tab.run_js(f"window.location.href = '{login_url}';")
            except Exception as js_err:
                # JS导航失败，回退到普通导航
                self.logger.warning(f"JS导航失败，使用普通导航: {js_err}")
                try:
                    tab.get(login_url, timeout=5)
                except:
                    pass
            
            # 使用统一的元素等待方法（最多等60秒）
            from .page_detector import PageDetector
            detector = PageDetector()
            
            # 使用PageDetector中定义的邮箱输入框选择器
            if self._wait_for_element(tab, detector.email_input_selectors, "登录页", max_wait=60):
                return True
            
            # 超时后依然返回True，因为可能只是元素定位有问题，尝试继续
            self._log_progress("⚠️ 登录页加载超时，但继续尝试")
            return True
            
        except Exception as e:
            self.logger.error(f"导航失败: {str(e)}")
            return False
    
    def click_signup_link(self, tab) -> bool:
        """点击注册链接并等待注册页加载"""
        try:
            self._log_progress("📍 点击Sign up链接...")
            # 动态等待Sign up链接加载
            signup_selectors = ["xpath://a[contains(@href, '/sign-up')]", "a[href*='sign-up']", "text=Sign up"]
            if not self._wait_for_element(tab, signup_selectors, "Sign up链接", max_wait=60):
                self._log_progress("⚠️ Sign up链接加载超时,尝试继续")
            
            # 查找并点击注册链接
            signup_link = tab.ele("xpath://a[contains(@href, '/sign-up')]", timeout=0.5)
            if not signup_link:
                self._log_progress("❌ 未找到Sign up链接")
                return False
            
            signup_link.click()
            time.sleep(0.3)  # 点击后短暂等待
            
            # 使用统一的元素等待方法（最多等60秒）
            first_name_selectors = [
                "@placeholder=Your first name",
                "@placeholder=您的名字",
                "input[placeholder*='first name']",
                "input[placeholder*='名字']"
            ]
            
            if self._wait_for_element(tab, first_name_selectors, "注册页", max_wait=60):
                return True
            
            # 超时后依然返回True，因为可能只是元素定位有问题，尝试继续
            self._log_progress("⚠️ 注册页加载超时，但继续尝试")
            return True
            
        except Exception as e:
            self.logger.error(f"点击注册链接失败: {str(e)}")
            return False


class LoginPageHandler(PageHandler):
    """登录页面处理器"""
    
    def handle_login_page(self, tab, account_info: Dict, check_turnstile: bool = False) -> bool:
        """
        处理登录页面
        
        Args:
            tab: 浏览器标签页
            account_info: 账号信息
            check_turnstile: 是否检查Turnstile验证（注册密码模式需要，登录模式不需要）
        """
        try:
            self._log_progress("📧 处理登录页面")
            
            # 查找并输入邮箱(使用PageDetector中的选择器)
            from .page_detector import PageDetector
            detector = PageDetector()
            
            # 先等待邮箱输入框加载（最多等待10秒）
            if not self._wait_for_element(tab, detector.email_input_selectors, "邮箱输入框", max_wait=60):
                self._log_progress("❌ 邮箱输入框加载超时")
                return False
            
            # 查找并输入邮箱
            email_input_found = False
            for selector in detector.email_input_selectors:
                email_input = tab.ele(selector, timeout=1.0)
                if email_input:
                    # 使用快速输入
                    self._fast_input(email_input, account_info['email'])
                    self._log_progress(f"✅ 已输入邮箱: {account_info['email']}")
                    email_input_found = True
                    break
            
            if not email_input_found:
                self._log_progress("❌ 无法找到邮箱输入框")
                return False
            
            # 输入完邮箱后短暂延迟，模拟人类反应时间
            time.sleep(random.uniform(0.3, 0.6))
            
            # 点击Continue按钮（使用统一的重试机制）
            continue_clicked = self._find_and_click_button(tab, self.continue_selectors, "Continue按钮")
            if not continue_clicked:
                return False
            
            # 根据参数决定是否检查Turnstile
            if check_turnstile:
                self._log_progress("⏳ 检查人机验证...")
                initial_url = tab.url
                return self._wait_for_url_change_with_verification(tab, initial_url, max_wait=60)
            
            return True
                
        except Exception as e:
            self.logger.error(f"处理登录页面失败: {str(e)}")
            return False
    


class PasswordPageHandler(PageHandler):
    """密码页面处理器（仅登录模式使用）"""
    
    def __init__(self, log_callback=None):
        """初始化密码页面处理器"""
        super().__init__(log_callback)
        self.email_handler = None  # 初始化邮箱处理器属性
    
    def handle_password_page(self, tab, account_info: Dict, register_mode: str = "email_code", register_config=None) -> bool:
        """处理密码页面 - 点击使用验证码继续"""
        try:
            self._log_progress("🔑 处理密码页面")
            # 动态等待邮箱验证码按钮加载
            if not self._wait_for_element(tab, self.email_code_selectors, "邮箱验证码按钮", max_wait=60):
                self._log_progress("⚠️ 未找到邮箱验证码按钮,尝试继续")
            return self._handle_email_code_login(tab, account_info, register_config=register_config)
                
        except Exception as e:
            self.logger.error(f"处理密码页面失败: {str(e)}")
            return False
    
    def _handle_email_code_login(self, tab, account_info: Dict, is_retry: bool = False, retry_start_time: float = None, register_config=None) -> bool:
        """选择邮箱验证码登录(邮箱验证码模式)
        
        Args:
            is_retry: 已废弃，保留仅用于兼容性
            retry_start_time: 已废弃，保留仅用于兼容性
            register_config: 注册配置（用于初始化邮箱处理器）
        """
        try:
            # 🔥 优化：提前初始化邮箱验证码处理器（用于清空邮箱）
            if not self.email_handler and register_config:
                try:
                    from .email_verification_handler import EmailVerificationHandler
                    self.email_handler = EmailVerificationHandler(account_info['email'], register_config, account_info)
                    self.logger.debug("✅ 邮箱验证码处理器已初始化")
                except ImportError:
                    self.logger.warning("⚠️ 邮箱验证码处理器导入失败")
            
            # 直接查找并点击"Email sign-in code"按钮
            clicked = self._find_and_click_button(tab, self.email_code_selectors, "Email sign-in code按钮")
            if clicked:
                # 记录点击时间
                click_time = time.time()
                account_info['click_registration_time'] = click_time
                self.logger.info(f"✅ 点击邮箱验证码按钮，记录时间: {click_time}")
                
                # 等待并处理人机验证
                self._log_progress("⏳ 检查人机验证...")
                initial_url = tab.url
                return self._wait_for_url_change_with_verification(tab, initial_url, max_wait=60)
            else:
                self._log_progress("⚠️ 未找到邮箱验证码按钮")
                return False
                
        except Exception as e:
            self.logger.error(f"邮箱验证码登录处理失败: {str(e)}")
            return False


class SignupPasswordPageHandler(PageHandler):
    """注册密码设置页面处理器"""
    
    def handle_signup_password_page(self, tab, account_info: Dict) -> bool:
        """处理注册密码设置页面(账号密码模式)"""
        try:
            return self._fill_and_submit_password(tab, account_info)
                
        except Exception as e:
            self.logger.error(f"处理密码设置页面失败: {str(e)}")
            return False
    
    def _fill_and_submit_password(self, tab, account_info: Dict) -> bool:
        """填写并提交密码的核心逻辑"""
        try:
            self._log_progress("🔑 处理密码设置页面")
            
            # 等待密码输入框加载
            password_selectors = ["@name=password", "input[type='password']", "input[name='password']"]
            if not self._wait_for_element(tab, password_selectors, "密码输入框", max_wait=60):
                self._log_progress("❌ 密码输入框加载超时")
                return False
            
            # 生成随机密码(符合复杂度要求)
            import string
            
            # 生成12位包含大小写字母、数字和特殊字符的密码
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            password = ''.join(random.choices(chars, k=12))
            
            # 确保密码包含各种字符类型
            password = (
                random.choice(string.ascii_lowercase) +
                random.choice(string.ascii_uppercase) +
                random.choice(string.digits) +
                random.choice("!@#$%^&*") +
                password[4:]
            )
            
            # 输入密码
            try:
                password_input = tab.ele("@name=password", timeout=0.5)
                if password_input:
                    # 使用人性化输入，更安全
                    self._fast_input(password_input, password)
                    self._log_progress("📝 已输入密码")
                    
                    # 保存密码到账号信息中
                    account_info['password'] = password
                    account_info['first_name'] = "User"
                    account_info['last_name'] = "Default"
                    account_info['full_name'] = "User Default"
                else:
                    self._log_progress("⚠️ 未找到密码输入框")
                    return False
            except Exception as e:
                self.logger.error(f"输入密码失败: {str(e)}")
                return False
            
            # 提交密码
            try:
                submit_clicked = False
                for selector in self.submit_selectors:
                    submit_btn = tab.ele(selector, timeout=0.02)  # 极速查找
                    if submit_btn:
                        self._simulate_click_with_mouse_move(tab, submit_btn)
                        submit_clicked = True
                        self._log_progress("📝 已提交密码设置")
                        break
                
                if not submit_clicked:
                    self._log_progress("⚠️ 未找到提交按钮")
                    return False
                
                # 等待并处理人机验证
                self._log_progress("⏳ 检查人机验证...")
                initial_url = tab.url
                return self._wait_for_url_change_with_verification(tab, initial_url, max_wait=60)
                    
            except Exception as e:
                self.logger.error(f"提交密码失败: {str(e)}")
                return False
                
        except Exception as e:
            self.logger.error(f"填写并提交密码失败: {str(e)}")
            return False


class MagicCodePageHandler(PageHandler):
    """验证码页面处理器"""
    
    def __init__(self, log_callback=None):
        super().__init__(log_callback)
        self.email_handler = None
        self.manual_intervention_callback = None  # 人工处理回调
        self.entry_count = 0  # 记录进入验证码页面的次数
    
    
    def handle_magic_code_page(self, tab, account_info: Dict, register_config=None) -> bool:
        """处理验证码输入页面"""
        try:
            # 动态等待验证码输入框加载
            code_input_selectors = ["@data-index=0", "input:nth-child(1)", "input[type='text']"]
            if not self._wait_for_element(tab, code_input_selectors, "验证码输入框", max_wait=60):
                self._log_progress("❌ 验证码输入框加载超时")
                return False
            
            # 🔥 记录进入次数（用于调试）
            self.entry_count += 1
            self.logger.debug(f"📍 第 {self.entry_count} 次进入验证码页面")
            
            # 定位所有验证码输入框
            input_boxes = []
            for i in range(6):
                input_box = tab.ele(f"@data-index={i}", timeout=0.5)
                if not input_box:
                    input_box = tab.ele(f"input:nth-child({i+1})", timeout=0.5)
                
                if input_box:
                    input_boxes.append(input_box)
                else:
                    break
            
            if not input_boxes:
                self._log_progress("⚠️ 未找到验证码输入框")
                return False
            
            # 初始化邮箱验证码处理器
            if not self.email_handler and register_config:
                try:
                    from .email_verification_handler import EmailVerificationHandler
                    self.email_handler = EmailVerificationHandler(account_info['email'], register_config, account_info)
                except ImportError:
                    self._log_progress("⚠️ 邮箱验证码处理器导入失败")
                    return False
            
            # 🔥 优化：提前异步初始化phone_service（在等待验证码的同时进行）
            self._async_init_phone_service(register_config, account_info)
            
            # 获取验证码（静默等待）
            time.sleep(random.uniform(0.5, 1))
            verification_code = None
            if self.email_handler:
                # 从account_info中获取之前记录的点击时间（跨Handler共享）
                registration_time = account_info.get('click_registration_time', None)
                if registration_time:
                    from datetime import datetime
                    self.logger.info(f"🕐 使用之前记录的点击时间: {registration_time} ({datetime.fromtimestamp(registration_time).strftime('%Y-%m-%d %H:%M:%S')})")
                else:
                    registration_time = time.time()
                    from datetime import datetime
                    self.logger.info(f"🕐 使用当前时间: {registration_time} ({datetime.fromtimestamp(registration_time).strftime('%Y-%m-%d %H:%M:%S')})")
                
                # 判断是否为验证码注册模式
                is_email_code_mode = account_info.get('register_mode', 'email_code') == 'email_code'
                verification_code = self.email_handler.get_verification_code(
                    max_retries=40, 
                    retry_interval=2, 
                    registration_time=registration_time,
                    is_email_code_mode=is_email_code_mode
                )
            
            if verification_code:
                self._log_progress(f"✅ 获取到验证码: {verification_code}")
                
                # 输入验证码（静默输入）
                for i, digit in enumerate(verification_code):
                    if i < len(input_boxes):
                        try:
                            input_boxes[i].clear()
                            input_boxes[i].input(digit)
                            
                            if i < len(verification_code) - 1:
                                time.sleep(random.uniform(0.1, 0.2))
                                
                        except Exception as e:
                            self.logger.error(f"输入第{i+1}位验证码失败: {str(e)}")
                            return False
                
                self._log_progress("✅ 验证码输入完成")
                
                # 🔥 验证码输入完成后，只清空临时邮箱（IMAP邮箱不清空）
                if self.email_handler and hasattr(self.email_handler, 'temp_mail_username'):
                    try:
                        temp_email = f"{self.email_handler.temp_mail_username}{self.email_handler.temp_mail_extension}"
                        temp_pin = self.email_handler.temp_mail_pin if hasattr(self.email_handler, 'temp_mail_pin') else ""
                        
                        # 先获取邮件列表以获取真实的first_id
                        if temp_pin:
                            mail_list_url = f"https://tempmail.plus/api/mails?email={temp_email}&limit=1&epin={temp_pin}"
                        else:
                            mail_list_url = f"https://tempmail.plus/api/mails?email={temp_email}&limit=1"
                        
                        response = self.email_handler.session.get(mail_list_url, timeout=5)
                        if response.status_code == 200:
                            mail_data = response.json()
                            first_id = mail_data.get("first_id")
                            if first_id and first_id > 0:
                                self.logger.info("✅ 验证码输入完成后，清空临时邮箱所有邮件")
                                self.email_handler._cleanup_tempmail_plus(temp_email, str(first_id), temp_pin)
                            else:
                                self.logger.debug("临时邮箱中暂无邮件，跳过清空")
                        else:
                            self.logger.debug(f"获取邮件列表失败: HTTP {response.status_code}")
                    except Exception as e:
                        self.logger.debug(f"清空临时邮箱失败: {str(e)}")
                
                # 验证码输入完成后立即返回True，让主流程检测下一个页面
                self._log_progress("✅ 验证码处理完成，继续后续流程")
                return True
            else:
                self._log_progress("❌ 无法获取验证码，请求人工处理")
                # 请求人工处理（给10秒时间手动输入）
                if self.manual_intervention_callback:
                    return self.manual_intervention_callback(tab, "无法自动获取验证码，请手动输入验证码", 60)
                else:
                    self._log_progress("❌ 无人工处理回调，验证码输入失败")
                    return False
            
        except Exception as e:
            self.logger.error(f"处理验证码页面失败: {str(e)}")
            return False
    
    def _async_init_phone_service(self, register_config, account_info):
        """
        异步初始化phone_service（在等待验证码的同时进行）
        这样可以节省时间，避免到手机号页面才开始初始化
        """
        try:
            import threading
            
            def init_phone_service():
                try:
                    # 检查配置
                    if not register_config:
                        return
                    
                    phone_config = register_config.get_phone_verification_config() if hasattr(register_config, 'get_phone_verification_config') else None
                    if not phone_config or not phone_config.get('enabled', False):
                        self.logger.debug("手机验证未启用，跳过phone_service初始化")
                        return
                    
                    # 检查是否已有全局单例
                    if PhoneVerificationPageHandler._global_phone_service:
                        self.logger.debug("♻️ 全局phone_service单例已存在，无需初始化")
                        # 🔥 提前获取手机号（避免后续堵塞）
                        try:
                            phone_service = PhoneVerificationPageHandler._global_phone_service
                            current_uid = phone_config.get('uid', None)
                            phone = phone_service.get_or_reuse_phone(uid=current_uid)
                            if phone:
                                country_code = phone_service.current_country_code or '+86'
                                account_info['_prefetched_phone'] = phone
                                account_info['_prefetched_country_code'] = country_code
                                self.logger.debug(f"✅ 已提前获取手机号: {country_code} {phone}")
                        except Exception as phone_err:
                            self.logger.debug(f"提前获取手机号失败: {str(phone_err)}")
                        # 将account_info标记为已准备好phone_service
                        account_info['_phone_service_ready'] = True
                        return
                    
                    # 初始化phone_service
                    from .phone_verification_service import PhoneVerificationService
                    
                    username = phone_config.get('username', '')
                    password = phone_config.get('password', '')
                    project_id = phone_config.get('project_id', '')
                    api_server = phone_config.get('api_server', None)
                    author = phone_config.get('author', None)
                    
                    # 提取项目ID
                    current_uid = phone_config.get('uid', None)
                    if current_uid and '-' in current_uid:
                        extracted_project_id = current_uid.split('-')[0]
                        if extracted_project_id:
                            project_id = extracted_project_id
                    
                    if not username or not password or not project_id:
                        self.logger.debug("phone_service配置不完整，跳过初始化")
                        return
                    
                    self.logger.info("🚀 后台初始化phone_service中...")
                    
                    phone_service = PhoneVerificationService(
                        username=username,
                        password=password,
                        project_id=project_id,
                        api_server=api_server,
                        author=author,
                        log_callback=self.log_callback
                    )
                    
                    # 设置最大使用次数
                    max_usage_count = phone_config.get('max_usage_count', 3)
                    phone_service.set_max_usage_count(max_usage_count)
                    
                    # 保存到全局单例
                    PhoneVerificationPageHandler._global_phone_service = phone_service
                    
                    # 🔥 提前获取手机号（避免后续堵塞）
                    try:
                        current_uid = phone_config.get('uid', None)
                        phone = phone_service.get_or_reuse_phone(uid=current_uid)
                        if phone:
                            country_code = phone_service.current_country_code or '+86'
                            account_info['_prefetched_phone'] = phone
                            account_info['_prefetched_country_code'] = country_code
                            self.logger.debug(f"✅ 已提前获取手机号: {country_code} {phone}")
                    except Exception as phone_err:
                        self.logger.debug(f"提前获取手机号失败: {str(phone_err)}")
                    
                    # 标记为已准备
                    account_info['_phone_service_ready'] = True
                    
                    self.logger.info("✅ phone_service后台初始化完成")
                    
                except Exception as e:
                    self.logger.debug(f"后台初始化phone_service失败: {str(e)}")
            
            # 在后台线程中初始化
            thread = threading.Thread(target=init_phone_service, daemon=True)
            thread.start()
            
        except Exception as e:
            self.logger.debug(f"启动phone_service后台初始化失败: {str(e)}")


class PhoneVerificationPageHandler(PageHandler):
    """手机号验证页面处理器 (radar-challenge)"""
    
    # 🔥 类级别的phone_service单例（全局共享，跨批次重用）
    _global_phone_service = None
    
    def __init__(self, log_callback=None):
        super().__init__(log_callback)
        self.phone_service = None
        self.manual_intervention_callback = None  # 人工处理回调
    
    def handle_phone_verification_page(self, tab, account_info: Dict, register_config=None) -> bool:
        """处理手机号验证页面"""
        try:
            
            # 检查是否配置了接码平台
            if not register_config:
                self._log_progress("⚠️ 未配置注册管理器，无法自动处理手机验证")
                return self._request_manual_intervention(tab, "需要手机号验证，请手动处理")
            
            # 从配置中获取接码平台信息
            phone_config = register_config.get_phone_verification_config() if hasattr(register_config, 'get_phone_verification_config') else None
            
            if not phone_config or not phone_config.get('enabled', False):
                self._log_progress("⚠️ 接码平台未启用，请手动输入手机号")
                return self._request_manual_intervention(tab, "需要手机号验证，接码平台未启用")
            
            # 使用全局接码服务（前面已经初始化好）
            self.phone_service = PhoneVerificationPageHandler._global_phone_service
            if not self.phone_service:
                self._log_progress("❌ 接码服务未初始化")
                return self._request_manual_intervention(tab, "接码服务未初始化")
            
            # 步骤1: 优先使用提前获取的手机号（避免API调用堵塞）
            phone = account_info.get('_prefetched_phone')
            country_code = account_info.get('_prefetched_country_code')
            
            # 如果没有提前获取，现场获取
            if not phone:
                current_uid = phone_config.get('uid', None) if phone_config else None
                phone = self.phone_service.get_or_reuse_phone(uid=current_uid)
                
                if not phone:
                    self._log_progress("❌ 获取手机号失败")
                    return self._request_manual_intervention(tab, "获取手机号失败")
                
                country_code = self.phone_service.current_country_code
            
            # 确保区号有效
            if not country_code or country_code == 'None' or country_code == 'null':
                country_code = '+86'
                self.phone_service.current_country_code = '+86'
            
            # 🔥 显示手机号
            self._log_progress(f"📱 使用手机号: {country_code} {phone}")
            
            # 保存手机号到账号信息
            account_info['phone'] = phone
            account_info['country_code'] = country_code
            
            # 步骤2: 定位并输入手机号（无需等待，直接开始）
            try:
                import time as time_module
                
                # 1. 找到国家代码框 → 立即输入
                country_code_input = None
                try:
                    country_code_input = tab.ele("@placeholder=+1", timeout=0.3)
                    if country_code_input and country_code:
                        country_code_input.click()
                        country_code_input.clear()
                        country_code_input.input(country_code)
                        self.logger.debug(f"✅ 已输入国家代码: {country_code}")
                except:
                    pass
                
                # 2. 找到手机号框 → 立即输入
                phone_input = None
                
                # 如果有区号框，手机号框是第二个tel输入框
                if country_code_input:
                    try:
                        tel_inputs = tab.eles("@type=tel", timeout=0.3)
                        if len(tel_inputs) >= 2:
                            phone_input = tel_inputs[1]
                    except:
                        pass
                
                # 如果没找到，尝试其他选择器
                if not phone_input:
                    phone_selectors = [
                        "@placeholder=(555)555-5555",
                        "@placeholder=555-555-5555",
                        "input[placeholder*='555']",
                        "@type=tel"
                    ]
                    
                    for selector in phone_selectors:
                        try:
                            phone_input = tab.ele(selector, timeout=0.3)
                            if phone_input:
                                break
                        except:
                            continue
                
                if not phone_input:
                    self._log_progress("❌ 未找到手机号输入框")
                    return self._request_manual_intervention(tab, "未找到手机号输入框")
                
                # 输入手机号
                phone_input.click()
                for i, digit in enumerate(phone):
                    phone_input.input(digit)
                    if i < len(phone) - 1:
                        time_module.sleep(random.uniform(0.05, 0.08))
                
                self._log_progress(f"✅ 已输入手机号: {phone}")
                
            except Exception as e:
                self.logger.error(f"输入手机号失败: {str(e)}")
                return False
            
            # 步骤3: 点击"发送验证码"按钮
            send_code_selectors = [
                "text=发送验证码",
                "text=Send code"
            ]
            
            send_btn_clicked = False
            for selector in send_code_selectors:
                try:
                    send_btn = tab.ele(selector, timeout=0.3)
                    if send_btn:
                        self._smart_wait("CLICK_DELAY")
                        self._simulate_click_with_mouse_move(tab, send_btn)
                        self._log_progress("✅ 已点击发送验证码按钮")
                        send_btn_clicked = True
                        break
                except:
                    continue
            
            if not send_btn_clicked:
                self._log_progress("❌ 未找到发送验证码按钮")
                return self._request_manual_intervention(tab, "未找到发送验证码按钮")
            
            # 步骤4: 等待页面跳转到验证码输入页面
            self._log_progress("⏳ 等待页面跳转...")
            self._smart_wait("PAGE_LOAD")
            
            # 记录发送验证码的时间（用于过滤短信）
            import time
            sms_send_time = time.time()
            
            # 步骤5: 等待并获取短信验证码（30秒超时，每秒尝试一次）
            self._log_progress("📨 正在等待短信验证码...")
            
            verification_code = self.phone_service.get_verification_code(
                phone=phone,
                max_retries=30,
                retry_interval=1
            )
            
            if not verification_code:
                self._log_progress("❌ 获取短信验证码超时（30秒）")
                # 🔥 接不到验证码的手机号直接拉黑，永不录用
                if self.phone_service and phone:
                    self.phone_service.blacklist_phone(phone, reason="无法接收验证码")
                    # 清空reusable_phone，下次获取新号码
                    self.phone_service.reusable_phone = None
                    self.phone_service.reusable_country_code = None
                # 🔥 不需要人工处理，直接判定为失败
                return False
            
            # 步骤6: 检查页面是否仍然存活
            try:
                current_url = tab.url
                self.logger.debug(f"获取验证码后的URL: {current_url}")
            except Exception as e:
                self._log_progress("⚠️ 页面连接已断开，可能已自动跳转")
                self.logger.error(f"页面连接检查失败: {str(e)}")
                # 页面可能已经自动验证通过并跳转，返回True
                return True
            
            # 步骤7: 定位6个验证码输入框
            input_boxes = []
            try:
                for i in range(6):
                    try:
                        input_box = tab.ele(f"@data-index={i}", timeout=0.5)
                        if not input_box:
                            input_box = tab.ele(f"input:nth-child({i+1})", timeout=0.5)
                        
                        if input_box:
                            input_boxes.append(input_box)
                        else:
                            break
                    except Exception as ele_error:
                        self.logger.debug(f"定位输入框{i}失败: {str(ele_error)}")
                        break
            except Exception as e:
                self._log_progress("⚠️ 定位输入框时页面已断开，可能已自动验证")
                self.logger.error(f"定位输入框异常: {str(e)}")
                # 页面断开可能是自动验证通过了，返回True
                return True
            
            if not input_boxes:
                self._log_progress("❌ 未找到验证码输入框")
                return self._request_manual_intervention(tab, "未找到验证码输入框")
            
            # 步骤8: 输入验证码
            try:
                for i, digit in enumerate(verification_code):
                    if i < len(input_boxes):
                        input_boxes[i].clear()
                        input_boxes[i].input(digit)
                        # 快速输入，减少延迟
                        if i < len(verification_code) - 1:
                            time.sleep(random.uniform(0.05, 0.1))
                
                self.logger.debug(f"✅ 已输入验证码: {verification_code}")
                
            except Exception as e:
                # 如果是页面断开错误，可能已经自动验证通过
                if "PageDisconnectedError" in str(type(e).__name__) or "断开" in str(e):
                    self._log_progress("⚠️ 输入验证码时页面断开，可能已自动验证")
                    return True
                self.logger.error(f"输入验证码失败: {str(e)}")
                return False
            
            # 步骤9: 等待验证完成
            self.logger.debug("⏳ 等待验证完成...")
            self._smart_wait("PAGE_LOAD")
            
            # 验证成功
            self._log_progress("✅ 手机号验证完成，继续后续流程")
            
            # 步骤10: 记录手机号使用次数
            self.phone_service.record_phone_usage(phone)
            
            return True
            
        except Exception as e:
            self.logger.error(f"处理手机验证页面失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return False
        finally:
            # 清理资源（如果处理器被销毁）
            if hasattr(self, 'phone_service') and self.phone_service:
                try:
                    if hasattr(self.phone_service, 'cleanup'):
                        pass  # 不在这里cleanup，保留给下次重用
                except:
                    pass
    
    def _request_manual_intervention(self, tab, message: str) -> bool:
        """请求人工干预 - 获取手机号失败直接返回False"""
        self._log_progress(f"❌ {message}")
        return False


class UsageSelectionPageHandler(PageHandler):
    """使用方式选择页面处理器"""
    
    def handle_usage_selection_page(self, tab, account_info: Dict) -> bool:
        """处理使用方式选择页面 - 点击By Myself然后Continue"""
        try:
            self._log_progress("🎯 处理使用方式选择页面")
            
            # 动态等待"By Myself"选项加载
            if not self._wait_for_element(tab, self.by_myself_selectors, "使用方式选项", max_wait=60):
                self._log_progress("⚠️ 使用方式选项加载超时,尝试继续")
            
            # 点击"By Myself"选项
            myself_clicked = False
            for selector in self.by_myself_selectors:
                try:
                    option = tab.ele(selector, timeout=0.1)
                    if option:
                        self._simulate_click_with_mouse_move(tab, option)
                        self._log_progress("✅ 已选择 By Myself")
                        myself_clicked = True
                        break
                except:
                    continue
            
            # 同一页面上，Continue按钮肯定已经加载了，短暂等待后直接点击
            time.sleep(random.uniform(0.3, 0.6))
            
            # 点击Continue按钮
            return self._find_and_click_button(tab, self.continue_selectors, "Continue按钮")
                
        except Exception as e:
            self.logger.error(f"处理使用方式选择页面失败: {str(e)}")
            return False


class ProTrialPageHandler(PageHandler):
    """Pro试用页面处理器"""
    
    def __init__(self, log_callback=None):
        super().__init__(log_callback)
        # 统一的试用页面选择器
        self.trial_continue_selectors = [
            "text=Continue",
            "text=Start trial",
            "button:has-text('Continue')",
            "button:has-text('Start trial')",
            "[data-testid='continue-button']",
            "button[type='submit']",
            "text=继续",
            "text=开始试用",
            "button:has-text('继续')",
            "button:has-text('开始试用')"
        ]
    
    def handle_pro_trial_page_new(self, tab, account_info: Dict) -> bool:
        """处理新版Pro试用页面（已禁用）"""
        try:
            self._log_progress("🎯 处理新版Pro试用页面")
            # 动态等待Continue按钮加载
            if not self._wait_for_element(tab, self.continue_selectors, "Continue按钮", max_wait=60):
                self._log_progress("⚠️ Continue按钮加载超时")
                return False
            return self._find_and_click_button(tab, self.continue_selectors, "Continue按钮进入绑卡流程")
                
        except Exception as e:
            self.logger.error(f"处理Pro Trial页面失败: {str(e)}")
            return False
    
    def handle_pro_trial_page(self, tab, account_info: Dict) -> bool:
        """处理Pro试用页面 (Claim your free Pro trial)"""
        try:
            self._log_progress("🎯 处理Pro试用页面")
            
            # 新界面的按钮选择器
            continue_trial_selectors = [
                "text=Continue with free trial",
                "button:has-text('Continue with free trial')"
            ]
            
            skip_selectors = [
                "text=Skip for now",
                "button:has-text('Skip for now')"
            ]
            
            # 动态等待按钮加载
            all_selectors = continue_trial_selectors + skip_selectors
            if not self._wait_for_element(tab, all_selectors, "试用按钮", max_wait=60):
                self._log_progress("⚠️ 试用按钮加载超时")
                return False
            
            # 优先点击"Continue with free trial"启动试用
            continue_clicked = self._find_and_click_button(tab, continue_trial_selectors, "Continue with free trial按钮", silent=True)
            if continue_clicked:
                self._log_progress("✅ 已点击继续试用")
                return True
            
            # 如果没有Continue按钮，点击Skip
            skip_clicked = self._find_and_click_button(tab, skip_selectors, "Skip for now按钮", silent=True)
            if skip_clicked:
                self._log_progress("✅ 已跳过Pro试用")
                return True
            
            return False
                
        except Exception as e:
            self.logger.error(f"处理旧版Pro Trial页面失败: {str(e)}")
            return False


class StripePaymentPageHandler(PageHandler):
    """Stripe支付页面处理器"""
    
    def __init__(self, log_callback=None):
        super().__init__(log_callback)
        self._init_payment_selectors()
        self._init_us_bank_selectors()
        self.manual_intervention_callback = None
        
        # 美国银行账户固定路由号码
        self.US_BANK_ROUTING = "121000358"
    
    def _init_payment_selectors(self):
        """初始化支付相关选择器"""
        # 银行卡选项选择器
        self.card_selectors = ["text=Card", "text=银行卡"]
        
        # 银行卡信息字段选择器
        self.card_field_selectors = {
            'number': ["@placeholder=1234 1234 1234 1234", "@placeholder=卡号"],
            'expiry': ["@placeholder=月份/年份", "@placeholder=MM/YY", "@placeholder=有效期"],
            'cvc': ["@placeholder=CVC", "@placeholder=安全码"],
            'name': ["@placeholder=全名", "@placeholder=Full name"]
        }
        
        # 地址字段选择器
        self.address_field_selectors = {
            'address1': ["@placeholder=地址第1行", "@placeholder=地址第 1 行", "@placeholder=地址"],
            'city': ["@placeholder=城市", "input[placeholder*='City']"],
            'zip': ["@placeholder=邮编", "input[placeholder*='Zip']"]
        }
        
        # 国家选择器
        self.country_selectors = ["text=中国", "text=美国", "text=United States"]
    
    def _init_us_bank_selectors(self):
        """初始化美国银行账户相关选择器"""
        # 美国银行账户选项选择器（使用css:前缀）
        self.us_bank_selectors = [
            'css:button[data-testid="us_bank_account-accordion-item-button"]',
            'css:button[aria-label="US bank account"]',
            'css:button:has-text("US bank account")'
        ]
        
        # 手动输入链接选择器
        self.manual_entry_selectors = ['css:[data-testid="manual-entry-link"]']
        
        # 银行账户信息字段选择器（iframe中）
        self.bank_account_field_selectors = {
            'routing': [
                'css:input[data-testid="manualEntry-routingNumber-input"]',
                'input[name="routingNumber"]'
            ],
            'account': [
                'css:input[data-testid="manualEntry-accountNumber-input"]', 
                'input[name="accountNumber"]'
            ],
            'confirm_account': [
                'css:input[data-testid="manualEntry-confirmAccountNumber-input"]', 
                'input[name="confirmAccountNumber"]'
            ]
        }
        
        # 提交按钮选择器（iframe中）
        self.continue_button_selectors = [
            'css:button[data-testid="continue-button"][form="manual-entry-form"]',
            'css:button[data-testid="continue-button"]',
            'text=继续',
            'text=Continue'
        ]
        
        # Link保存提示按钮（可能在iframe或主窗口）
        self.link_not_now_selectors = [
            'css:button[data-testid="link-not-now-button"]',
            'text=暂不',
            'text=Not now',
            'text=不保存'
        ]
        
        # 返回按钮选择器（可能在iframe或主窗口）- 优先使用text=返回
        self.done_button_selectors = [
            'text=返回到Cursor',
            'css:button[data-testid="done-button"]',
            'text=完成',
            'text=Done'
        ]
        
        # 账单地址字段选择器(主页面) - 支持中英文placeholder（需要css:前缀）
        self.billing_field_selectors = {
            'name': [
                'css:input#billingName', 
                'css:input[name="billingName"]',
                '@placeholder=名称',
                '@placeholder=姓名'
            ],
            'country': [
                'css:select#billingCountry', 
                'css:select[name="billingCountry"]'
            ],
            'address1': [
                'css:input#billingAddressLine1', 
                'css:input[name="billingAddressLine1"]',
                '@placeholder=地址第 1 行',
                '@placeholder=地址第1行'
            ],
            'city': [
                'css:input#billingLocality', 
                'css:input[name="billingLocality"]',
                '@placeholder=城市'
            ],
            'zip': [
                'css:input#billingPostalCode', 
                'css:input[name="billingPostalCode"]',
                '@placeholder=邮编'
            ],
            'state': [
                'css:select#billingAdministrativeArea', 
                'css:select[name="billingAdministrativeArea"]',
                '@placeholder=省/州'
            ]
        }
    
    def handle_stripe_payment_page(self, tab, account_info: Dict, card_manager) -> bool:
        """处理Stripe支付页面"""
        try:
            # 检查是否使用美国银行账户
            use_us_bank = False
            if hasattr(card_manager, 'register_config'):
                use_us_bank = card_manager.register_config.get_use_us_bank()
            
            # 步骤1: 等待支付页面整体加载
            from .page_detector import PageDetector
            detector = PageDetector()
            
            self._log_progress("⏳ 等待支付页面加载...")
            if not self._wait_for_element(tab, detector.stripe_payment_selectors, "支付页面", max_wait=60):
                self._log_progress("⚠️ 支付页面加载超时，请求人工处理")
                if self.manual_intervention_callback:
                    return self.manual_intervention_callback(tab, "支付页面加载超时，请手动填写银行卡信息", 60)
                else:
                    self._log_progress("❌ 无人工处理回调，注册失败")
                    return False
            
            # 根据配置选择绑卡方式
            if use_us_bank:
                self._log_progress("🏦 使用美国银行账户进行绑卡")
                return self._handle_us_bank_payment(tab)
            else:
                self._log_progress("💳 使用银行卡进行绑卡")
                # 获取银行卡信息
                if not card_manager:
                    self._log_progress("❌ 银行卡管理器未初始化")
                    return False
                
                # 🔥 关键修复：使用已分配的银行卡，不要重复分配
                card_info = card_manager.current_card_info
                if not card_info:
                    # 如果没有预先分配，才调用get_next_card_info
                    card_info = card_manager.get_next_card_info()
                    if not card_info:
                        return False
                
                # 点击银行卡选项
                self._click_card_option(tab)

                # 检查是否是无头模式
                is_headless = False
                try:
                    is_headless = tab.run_js("return window.outerWidth === 0 || !window.outerWidth;")
                except:
                    pass
                
                # 无头模式下给更长的等待时间让表单展开
                if is_headless:
                    time.sleep(random.uniform(1.5, 2.5))
                    self.logger.debug("⏳ 无头模式：等待支付表单展开")
                else:
                    # 模拟人类反应时间
                    time.sleep(random.uniform(0.5, 1.0))
                
                # 填写银行卡信息
                self._fill_card_info(tab, card_info)
                
                # 填写地址信息
                self._fill_address_info(tab, card_info)
                
                # 点击提交按钮并等待页面跳转
                return self._click_and_wait_for_next_page(tab, use_us_bank=False)
                        
        except Exception as e:
            self.logger.error(f"处理Stripe支付页面失败: {str(e)}")
            return False
    
    def _click_card_option(self, tab):
        """点击银行卡选项 - 优先使用文本选择器"""
        card_clicked = False
        
        # 检查是否是无头模式（通过浏览器driver属性判断）
        is_headless = False
        try:
            # 无头模式下浏览器可能没有window.outerWidth或值为0
            is_headless = tab.run_js("return window.outerWidth === 0 || !window.outerWidth;")
        except:
            pass
        
        # 滚动到页面顶部
        try:
            tab.run_js("window.scrollTo(0,0)")
        except:
            pass
        
        # 🔥 优先级1：尝试文本选择器（最直接）
        try:
            text_selectors = ["text=Card", "text=银行卡", "text=信用卡", "text=借记卡"]
            for text_selector in text_selectors:
                ele = tab.ele(text_selector, timeout=0.3)
                if ele:
                    try:
                        tab.run_js("arguments[0].scrollIntoView({behavior:'instant',block:'center'});", ele)
                    except:
                        pass
                    try:
                        ele.click()
                        self.logger.debug(f"✅ 成功点击银行卡选项(文本选择器: {text_selector})")
                        card_clicked = True
                        break
                    except Exception:
                        try:
                            tab.run_js("arguments[0].click();", ele)
                            self.logger.debug(f"✅ 成功点击银行卡选项(JS点击: {text_selector})")
                            card_clicked = True
                            break
                        except Exception:
                            pass
            if card_clicked:
                return
        except Exception as e:
            self.logger.debug(f"文本选择器失败: {str(e)}")
        
        # 🔥 优先级2-4：如果文本选择器失败，使用原有选择器
        timeout = 2.5 if is_headless else 0.6
        
        for selector in self.card_selectors:
            try:
                card_option = tab.ele(selector, timeout=timeout)
                if card_option:
                    # 无头模式下额外等待元素完全可见
                    if is_headless:
                        time.sleep(random.uniform(0.5, 1.0))
                        try:
                            tab.run_js("arguments[0].scrollIntoView({behavior:'instant',block:'center'});", card_option)
                        except:
                            pass
                    
                    # 优先级2: 模拟鼠标移动点击
                    try:
                        self._simulate_click_with_mouse_move(tab, card_option)
                        self.logger.debug(f"✅ 成功点击银行卡选项(鼠标移动) (无头模式: {is_headless})")
                        card_clicked = True
                        break
                    except Exception:
                        # 优先级3: JS点击
                        try:
                            tab.run_js("arguments[0].click();", card_option)
                            self.logger.debug(f"✅ 成功点击银行卡选项(JS点击) (无头模式: {is_headless})")
                            card_clicked = True
                            break
                        except Exception:
                            # 优先级4: 直接ele.click()
                            try:
                                card_option.click()
                                self.logger.debug(f"✅ 成功点击银行卡选项(直接点击) (无头模式: {is_headless})")
                                card_clicked = True
                                break
                            except Exception:
                                pass
            except Exception as e:
                self.logger.debug(f"选择器 {selector} 失败: {str(e)}")
                continue
        
        if not card_clicked:
            self.logger.warning(f"⚠️ 未找到银行卡选项 (无头模式: {is_headless})，直接尝试填写")
    
    def _fill_card_info(self, tab, card_info: Dict):
        """填写银行卡信息"""
        
        # 直接遍历选择器字典，避免硬编码
        field_names = {'number': "卡号", 'expiry': "到期日", 'cvc': "CVC", 'name': "持卡人姓名"}
        
        for field_key in self.card_field_selectors.keys():
            if field_key in card_info:
                value = card_info[field_key]
                selectors = self.card_field_selectors[field_key]
                field_name = field_names.get(field_key, field_key)
                self._fill_input_field_fast(tab, selectors, value, field_name)
    
    def _fill_address_info(self, tab, card_info: Dict):
        """填写地址信息"""
        try:
            # 首先选择美国作为国家
            self._select_country_us(tab)
            
            # 生成随机地址
            random_address = self._generate_random_address()
            
            # 直接遍历地址选择器字典，快速填写
            address_field_names = {'address1': "地址", 'city': "城市", 'zip': "邮编"}
            
            for field_key in self.address_field_selectors.keys():
                if field_key in random_address:
                    value = random_address[field_key]
                    selectors = self.address_field_selectors[field_key]
                    field_name = address_field_names.get(field_key, field_key)
                    success = self._fill_input_field_fast(tab, selectors, value, field_name)
                    if success:
                        self._log_progress(f"📝 填写{field_name}: {value}")
                        # 输入邮编后额外等待
                        if field_key == 'zip':
                            time.sleep(random.uniform(1.0, 1.5))  # 邮编输入后随机等待1.5-2.5秒
                            self._log_progress("⏳ 邮编输入完成，等待处理")
                
        except Exception as e:
            self.logger.error(f"填写地址信息失败: {str(e)}")
    
    def _generate_random_address(self) -> Dict[str, str]:
        """生成随机美国地址信息"""
        streets = ["Main St", "Oak Ave", "Park Rd", "Elm St", "First Ave", "Broadway"]
        cities = ["New York", "Los Angeles", "Chicago", "Houston", "Seattle", "Boston"]
        
        return {
            'address1': f"{random.randint(100, 9999)} {random.choice(streets)}",
            'city': random.choice(cities),
            'zip': f"{random.randint(10000, 99999):05d}"
        }
    
    def _select_country_us(self, tab):
        """选择美国作为账单地址国家"""
        try:
            # 使用定义的国家选择器，统一使用
            for selector in self.country_selectors:
                if "中国" in selector or "China" in selector:
                    china_element = tab.ele(selector, timeout=0.2)
                    if china_element:
                        self._simulate_click_with_mouse_move(tab, china_element)
                        break
            
            # 选择美国
            for selector in self.country_selectors:
                if "美国" in selector or "United States" in selector:
                    us_element = tab.ele(selector, timeout=0.2)
                    if us_element:
                        self._simulate_click_with_mouse_move(tab, us_element)
                        return
        except Exception:
            pass  # 静默处理
    
    def _click_and_wait_for_next_page(self, tab, use_us_bank: bool = False) -> bool:
        """点击提交按钮并等待页面跳转
        
        Args:
            tab: 浏览器标签页
            use_us_bank: 是否使用美国银行账户（True=美国银行账户15秒超时判定成功，False=普通银行卡30秒超时判定失败）
        """
        # 查找提交按钮(极速查找)
        # 使用统一的点击方法进行第一次点击
        first_click = self._find_and_click_button(tab, self.start_trial_selectors, "提交按钮（开始使用/订阅）")
        if first_click:
            # 第一次点击后等待1.5-2.5秒
            time.sleep(random.uniform(1.5, 2.0))
            
            # 第二次点击（可能元素已失效，需要重试） - 保险性点击，失败是正常的
            second_click = self._find_and_click_button(tab, self.start_trial_selectors, "提交按钮（开始使用/订阅）", silent=True)
            
            # 无论第二次点击是否成功，都检查页面状态（用户可能手动点击了）
            if second_click or True:  # 即使第二次点击失败也继续检查
                # 等待页面跳转并处理hCaptcha
                self._log_progress("⏳ 等待页面跳转...")
                # 记录当前URL，用于检测页面是否跳转
                initial_url = tab.url
                # 根据绑卡类型设置不同的超时时间
                max_wait = 45 if use_us_bank else 45  # 美国银行账户45秒，普通银行卡45秒
                start_time = time.time()
                check_count = 0
                
                while (time.time() - start_time) < max_wait:
                    check_count += 1
                    
                    # 检查停止信号
                    if self.stop_check_callback and self.stop_check_callback():
                        self._log_progress("🛑 检测到停止信号")
                        return False
                    
                    # 检测浏览器是否已关闭
                    try:
                        current_url = tab.url
                    except Exception as e:
                        self._log_progress("❌ 检测到浏览器已关闭，判定为失败")
                        return False
                    
                    # 检查URL是否已跳转（离开支付页面）
                    if "checkout.stripe.com" not in current_url:
                        self._log_progress("✅ 离开支付界面，绑卡完成")
                        return True
                    
                    # 调用hCaptcha处理逻辑（静默模式，循环中不输出详细日志）
                    try:
                        self._handle_captcha_verification_quick(tab, silent=True)
                    except Exception as e:
                        self.logger.debug(f"hCaptcha处理异常: {str(e)}")
                    
                    # 自适应检查间隔（模拟真人从耐心到不耐烦）
                    if check_count < 3:
                        # 前期：刚提交，耐心等待支付处理
                        interval = random.uniform(*self.wait_times["URL_CHECK_SLOW"])
                    elif check_count < 10:
                        # 中期：开始有点不耐烦
                        interval = random.uniform(*self.wait_times["URL_CHECK_NORMAL"])
                    else:
                        # 后期：很不耐烦，频繁检查（偶尔更快）
                        if random.random() < 0.3:  # 30%概率非常急切
                            interval = random.uniform(*self.wait_times["URL_CHECK_FAST"])
                        else:
                            interval = random.uniform(*self.wait_times["URL_CHECK_NORMAL"])
                    
                    time.sleep(interval)
                
                # 超时后检查是否已离开支付页面
                try:
                    current_url = tab.url
                except Exception as e:
                    self._log_progress("❌ 检测到浏览器已关闭，判定为失败")
                    return False
                
                if "checkout.stripe.com" not in current_url:
                    self._log_progress("✅ 离开支付界面，绑卡完成")
                    return True
                else:
                    # 根据绑卡类型决定超时判定结果
                    if use_us_bank:
                        # 美国银行账户：超时判定为成功
                        self._log_progress("⚠️ 绑卡45秒超时，判定为成功")
                        return True
                    else:
                        # 普通银行卡：超时判定为失败
                        self._log_progress("⚠️ 绑卡45秒超时，判定为失败")
                        return False
        
        # 第一次点击也失败 - 检查是否用户已手动操作
        # 给一点时间看页面是否跳转
        time.sleep(2.0)
        
        # 检测浏览器是否已关闭
        try:
            current_url = tab.url
        except Exception as e:
            self._log_progress("❌ 检测到浏览器已关闭，判定为失败")
            return False
        
        if "checkout.stripe.com" not in current_url:
            self._log_progress("✅ 检测到页面已跳转，继续")
            return True
        
        # 确实没找到按钮且页面没跳转，请求人工处理
        if self.manual_intervention_callback:
            return self.manual_intervention_callback(tab, "未找到支付提交按钮，请手动点击完成支付", 120)
        else:
            return False
    
    def _handle_us_bank_payment(self, tab) -> bool:
        """处理美国银行账户支付流程 - 精简日志版本"""
        try:
            # 1. 点击US bank account选项
            if not self._click_us_bank_option(tab):
                self._log_progress("❌ 选择美国银行账户失败")
                return False
            
            # 2. 生成随机银行账户信息
            account_number = self._generate_us_bank_account_number()
            billing_name = self._generate_random_billing_name()
            
            # 3. 填写银行账户信息(在弹出对话框中)
            if not self._fill_us_bank_account_info(tab, self.US_BANK_ROUTING, account_number):
                self._log_progress("❌ 填写银行账户信息失败")
                return False
            
            # 4. 填写账单地址(在主页面)
            if not self._fill_us_billing_address(tab, billing_name):
                self._log_progress("❌ 填写账单地址失败")
                return False
            
            # 5. 点击最终提交按钮（美国银行账户）
            return self._click_and_wait_for_next_page(tab, use_us_bank=True)
            
        except Exception as e:
            self.logger.error(f"美国银行账户支付流程失败: {str(e)}")
            return False
    
    def _click_us_bank_option(self, tab) -> bool:
        """点击美国银行账户选项 - 增加调试日志"""
        try:
            self._log_progress("🔘 点击美国银行账户选项...")
            time.sleep(random.uniform(0.8, 1.2))
            
            # 1. 点击 "美国银行账户" 选项
            us_bank_accordion = None
            selectors = [
                'text=美国银行账户',
                'css:button[data-testid="us_bank_account-accordion-item-button"]',
                'text=US bank account',
                'css:button[aria-label="US bank account"]',
                'css:button[aria-label="美国银行账户"]'
            ]
            
            for selector in selectors:
                try:
                    us_bank_accordion = tab.ele(selector, timeout=2)
                    if us_bank_accordion:
                        break
                except:
                    continue
            
            if not us_bank_accordion:
                self._log_progress("❌ 未找到美国银行账户选项")
                return False
            
            us_bank_accordion.click()
            self._log_progress("✅ 美国银行账户已点击")
            time.sleep(random.uniform(1.0, 1.3))
            
            # 2. 验证选项展开并点击手动输入
            self._log_progress("🔘 点击手动输入...")
            manual_entry_link = tab.ele('css:[data-testid="manual-entry-link"]', timeout=5)
            if not manual_entry_link:
                self._log_progress("❌ 选项未展开")
                return False
            
            manual_entry_link.click()
            self._log_progress("✅ 手动输入已点击")
            time.sleep(random.uniform(1.0, 1.3))
            return True
                
        except Exception as e:
            self._log_progress(f"❌ 美国银行账户选项失败: {str(e)}")
            return False
    
    def _fill_us_bank_account_info(self, tab, routing_number: str, account_number: str) -> bool:
        """填写银行账户信息(在iframe弹出框中) - 增加调试日志"""
        try:
            self._log_progress("⏳ 等待iframe加载...")
            time.sleep(random.uniform(2.0, 2.5))
            
            # 查找并切换到iframe
            iframe = tab.ele('tag:iframe', timeout=3)
            if iframe:
                frame_tab = tab.get_frame(iframe)
                self._log_progress("✅ 已切换到iframe")
            else:
                frame_tab = tab
                self._log_progress("⚠️ 未找到iframe")
            
            # 填写Routing number
            for selector in self.bank_account_field_selectors['routing']:
                try:
                    routing_input = frame_tab.ele(selector, timeout=1)
                    if routing_input:
                        routing_input.clear()
                        routing_input.input(routing_number)
                        time.sleep(random.uniform(0.3, 0.5))  # 路径号码填写后等待更长时间
                        self._log_progress("✅ 路径号码已填写")
                        break
                except:
                    continue
            
            # 填写Account number
            for selector in self.bank_account_field_selectors['account']:
                try:
                    account_input = frame_tab.ele(selector, timeout=2)
                    if account_input:
                        account_input.clear()
                        account_input.input(account_number)
                        time.sleep(random.uniform(0.3, 0.5))
                        self._log_progress("✅ 账号已填写")
                        break
                except:
                    continue
            
            # 填写确认账号
            for selector in self.bank_account_field_selectors['confirm_account']:
                try:
                    confirm_input = frame_tab.ele(selector, timeout=2)
                    if confirm_input:
                        confirm_input.clear()
                        confirm_input.input(account_number)
                        time.sleep(random.uniform(0.5, 0.8))
                        self._log_progress("✅ 确认账号已填写")
                        break
                except:
                    continue
            
            self._log_progress("✅ 银行账户信息已填写")
            
            # 点击Continue按钮
            self._log_progress("⏳ 等待Continue可点击...")
            time.sleep(random.uniform(0.4, 0.7))
            continue_clicked = False
            for selector in self.continue_button_selectors:
                try:
                    continue_button = frame_tab.ele(selector, timeout=2)
                    if continue_button:
                        is_disabled = continue_button.attr('disabled')
                        if not is_disabled or is_disabled == 'false':
                            continue_button.click()
                            continue_clicked = True
                            self._log_progress("✅ Continue已点击")
                            time.sleep(random.uniform(0.7, 1.0))
                            break
                except:
                    continue
            
            if not continue_clicked:
                self._log_progress("⚠️ 未找到Continue按钮，继续流程")
            
            # 处理Link保存提示（快速检查，可能不存在）
            time.sleep(random.uniform(0.3, 0.5))
            link_found = False
            
            # 快速尝试（只尝试第一个选择器，timeout缩短）
            for frame in [frame_tab, tab]:
                try:
                    not_now_button = frame.ele('css:button[data-testid="link-not-now-button"]', timeout=0.5)
                    if not_now_button:
                        not_now_button.click()
                        self._log_progress("✅ Link提示已处理")
                        time.sleep(random.uniform(0.3, 0.5))
                        link_found = True
                        break
                except:
                    continue
            
            if not link_found:
                self._log_progress("⏭️ 无Link提示，跳过")
            
            # 情况1: 查找并点击返回按钮
            self._log_progress("⏳ 查找返回按钮...")
            
            for frame in [frame_tab, tab]:
                for selector in self.done_button_selectors:
                    try:
                        done_button = frame.ele(selector, timeout=1)
                        if done_button:
                            self._log_progress(f"✅ 找到返回按钮")
                            done_button.click()
                            self._log_progress("✅ 返回按钮已点击，继续流程")
                            time.sleep(random.uniform(1.0, 1.4))
                            return True
                    except:
                        continue
            
            # 情况2: 未找到返回按钮，检查是否有错误提示需要处理
            self._log_progress("🔍 未找到返回按钮，检查是否有错误提示...")
            
            error_close_button = None
            
            # 第1步：在iframe中查找"关闭"按钮
            try:
                error_close_button = frame_tab.ele('xpath://button[contains(text(), "关闭")]', timeout=1)
            except:
                pass
            
            # 第2步：如果没找到，在iframe中查找Button--primary
            if not error_close_button:
                try:
                    error_close_button = frame_tab.ele('css:button[class*="Button--primary"]', timeout=1)
                except:
                    pass
            
            # 第3步：如果还没找到，在主框架中查找"关闭"按钮
            if not error_close_button:
                try:
                    error_close_button = tab.ele('xpath://button[contains(text(), "关闭")]', timeout=1)
                except:
                    pass
            
            if error_close_button:
                self._log_progress("⚠️ 检测到错误提示，点击关闭按钮...")
                error_close_button.click()
                self._log_progress("✅ 已点击关闭按钮")
                time.sleep(1)
                self._log_progress("✅ 银行账户信息填写完成（已处理错误），继续流程")
                return True
            
            # 理论上不会走到这里，因为只会出现返回或关闭两种情况
            self._log_progress("⚠️ 未找到返回按钮或关闭按钮")
            return True
            
        except Exception as e:
            self.logger.error(f"填写银行账户信息失败: {str(e)}")
            return False
    
    def _fill_us_billing_address(self, tab, billing_name: str) -> bool:
        """填写美国账单地址(在主页面) - 极简日志版本"""
        try:
            time.sleep(random.uniform(0.8, 1.2))
            
            # 1. 填写账单持有人姓名
            name_input = tab.ele('css:input#billingName', timeout=5)
            if not name_input:
                name_input = tab.ele('css:input[name="billingName"]', timeout=5)
            
            if not name_input:
                self._log_progress("❌ 未找到姓名输入框")
                return False
            
            name_input.clear()
            name_input.input(billing_name)
            
            # 2. 选择美国作为国家（静默）
            self._select_country_us(tab)
            
            # 3. 生成并填写随机地址（静默）
            random_address = self._generate_random_address()
            
            for field_key in ['address1', 'city', 'zip']:
                if field_key in random_address:
                    value = random_address[field_key]
                    selectors = self.address_field_selectors[field_key]
                    field_name = {'address1': "地址", 'city': "城市", 'zip': "邮编"}[field_key]
                    success = self._fill_input_field_fast(tab, selectors, value, field_name)
                    
                    # 邮编输入后等待
                    if field_key == 'zip' and success:
                        time.sleep(random.uniform(1.0, 1.5))
            
            self._log_progress(f"✅ 账单信息已填写: {billing_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"填写账单地址失败: {str(e)}")
            return False
    
    def _generate_us_bank_account_number(self) -> str:
        """生成随机美国银行账号(12位数字)"""
        return ''.join([str(random.randint(0, 9)) for _ in range(12)])
    
    def _generate_random_billing_name(self) -> str:
        """生成随机账单持有人姓名"""
        first_names = ["John", "Jane", "Mike", "Sarah", "David", "Lisa", "Tom", "Anna", 
                      "Chris", "Emma", "James", "Mary", "Robert", "Patricia"]
        last_names = ["Smith", "Johnson", "Brown", "Davis", "Miller", "Wilson", "Moore",
                     "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris"]
        
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        return f"{first_name} {last_name}"


class BankVerificationPageHandler(PageHandler):
    """银行验证页面处理器 - 处理支付后的hCaptcha复选框验证"""
    
    def handle_bank_verification_page(self, tab, account_info: Dict) -> bool:
        """处理银行验证页面(hCaptcha复选框验证)"""
        try:
            self._log_progress("🏦开始处理hCaptcha复选框...")
            
            # 调用bank-checkbox.py中的验证逻辑（方法已移至PageHandler基类）
            success = self._handle_captcha_verification_quick(tab)
            
            if success:
                self._log_progress("✅ 银行验证完成")
                return True
            else:
                self._log_progress("⚠️ 银行验证处理失败，但继续流程")
                return True  # 即使失败也继续，让用户手动处理
                
        except Exception as e:
            self.logger.error(f"处理银行验证页面失败: {str(e)}")
            return True  # 异常时也继续流程
