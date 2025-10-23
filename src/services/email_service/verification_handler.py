#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
验证处理模块 - Cloudflare Turnstile自动处理
借鉴cursor-ideal项目的专业实现
"""

import logging
import random
import time
from typing import Optional


class VerificationHandler:
    """验证处理类，自动检测和处理Cloudflare Turnstile验证"""
    
    # 验证类型
    TYPE_TURNSTILE = "turnstile"
    TYPE_UNKNOWN = "unknown"
    
    def __init__(self, log_callback=None):
        """
        初始化验证处理器
        
        Args:
            log_callback: 日志回调函数
        """
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        self._error = None
    
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def detect_verification(self, tab) -> str:
        """
        检测页面是否包含验证挑战，并返回验证类型
        使用多种特征组合进行精确检测
        
        Args:
            tab: 浏览器标签页对象
            
        Returns:
            str: 验证类型，如果没有验证则返回TYPE_UNKNOWN
        """
        try:
            # 获取页面的HTML
            full_html = tab.run_js("return document.documentElement.outerHTML;")

            # 1. 检测到可能被激活的Turnstile（当前为inert），增加等待重试机制
            if "you are human" in full_html.lower() and '<div inert="" aria-hidden="true"' in full_html:
                self.logger.debug("检测到可能被激活的Turnstile验证（当前为inert），将等待最多3秒...")
                timeout = 3  # 3秒超时
                poll_interval = 1  # 1秒轮询间隔
                start_time = time.time()

                while time.time() - start_time < timeout:
                    time.sleep(poll_interval)
                    self.logger.debug("重新检查验证状态...")
                    full_html = tab.run_js("return document.documentElement.outerHTML;")

                    # 如果inert div消失，说明验证已激活
                    if '<div inert="" aria-hidden="true"' not in full_html:
                        self.logger.info("Turnstile验证已激活，继续进行检测。")
                        break  # 退出循环，继续下面的检测逻辑
                else:  # while循环正常结束（未被break）
                    self.logger.debug("等待超时，Turnstile验证未激活。跳过处理。")
                    return self.TYPE_UNKNOWN

            # 1.1 检测隐藏的Turnstile验证
            # 使用更通用的特征组合，避免依赖特定ID
            hidden_turnstile_pattern = (
                    'Verify your email' in full_html and
                    'id="cf-turnstile-script"' in full_html and  # 包含turnstile脚本ID
                    'challenges.cloudflare.com/turnstile/v0/api.js' in full_html and  # 包含API引用
                    'position: absolute' in full_html and  # 使用绝对定位
                    'left: -100' in full_html and  # 使用左偏移（不限定具体值）
                    'visibility: hidden' in full_html and
                    'siteKey' in full_html  # 包含siteKey配置
            )

            # 检查是否同时包含BotCheckClient或BotCheckTokenInput组件
            has_bot_check_components = (
                    'BotCheckClient' in full_html or
                    'BotCheckTokenInput' in full_html
            )

            # 综合判断：必须满足隐藏模式特征，且不存在明显的需要验证文本
            if hidden_turnstile_pattern and has_bot_check_components:
                self.logger.debug("检测到隐藏的Turnstile验证，无需用户交互")
                return self.TYPE_UNKNOWN

            # 1.2 检测明确展示的Turnstile验证（在sign-up页面）
            is_signup_page = 'Sign up' in full_html and '/sign-up' in tab.url
            explicit_turnstile_pattern = (
                    is_signup_page and
                    'id="cf-turnstile-script"' in full_html and  # 包含turnstile脚本ID
                    'challenges.cloudflare.com/turnstile/v0/api.js' in full_html and  # 包含API引用
                    'id="cf-turnstile"' in full_html and  # Turnstile容器ID
                    'we need to be sure you are human' in full_html and  # 人机验证提示文本
                    'display:flex' in full_html and  # 显示样式
                    'siteKey' in full_html  # 包含siteKey配置
            )

            if explicit_turnstile_pattern:
                self.logger.info("检测到明确展示的Turnstile验证，需要用户交互")
                return self.TYPE_TURNSTILE

            # 2. 快速检测需要验证的特征
            # 检查是否包含关键特征
            need_verification_features = [
                # 特征1: Windows测试文件中的特定文本
                'Before continuing, we need to be sure you are human.' in full_html,
                # 特征2: 验证页面的挑战平台脚本
                'cdn-cgi/challenge-platform' in full_html,
                # 特征3: 验证页面的turnstile API
                'challenges.cloudflare.com/turnstile/v0/api.js' in full_html and not '<div inert="" aria-hidden="true"' in full_html,
                # 特征4: 验证页面的特定文本
                (
                        '请确认您是真人' in full_html or
                        '确认您是真人' in full_html or
                        '验证您是真人' in full_html or  # 增加新的中文匹配
                        'verify you are human' in full_html
                ) and not '<div inert="" aria-hidden="true"' in full_html,
                # 特征5: 验证页面的特定元素
                (
                        'cf-turnstile' in full_html or
                        'data-sitekey' in full_html or
                        'name="cf-turnstile-response"' in full_html  # 增加对turnstile响应输入框的检测
                ) and not '<div inert="" aria-hidden="true"' in full_html
            ]

            # 如果满足任一特征，则认为需要验证
            if any(need_verification_features):
                self.logger.info(f"检测到需要Turnstile验证")
                return self.TYPE_TURNSTILE

            self.logger.debug("未检测到需要验证的特征")
            return self.TYPE_UNKNOWN

        except Exception as e:
            self.logger.error(f"检测Turnstile验证时出错: {str(e)}")
            return self.TYPE_UNKNOWN
    
    def check_and_handle_verification(self, tab) -> bool:
        """
        检查并自动处理验证
        
        Args:
            tab: 浏览器标签页对象
            
        Returns:
            bool: 是否成功处理（或无需处理）
        """
        verification_type = self.detect_verification(tab)
        
        if verification_type == self.TYPE_UNKNOWN:
            self.logger.info("无需处理验证")
            return True
        
        return self._handle_verification_direct(tab, verification_type)
    
    def _handle_verification_direct(self, tab, verification_type) -> bool:
        """
        直接处理验证（不再重复检测）
        
        Args:
            tab: 浏览器标签页对象
            verification_type: 已检测到的验证类型
            
        Returns:
            bool: 是否成功处理
        """
        try:
            # 检测到验证，模拟人类反应时间（1-1.5秒）
            self._log_progress("🤔 检测到人机验证，正在处理...")
            time.sleep(random.uniform(1.0, 1.5))
            
            # 获取验证框位置
            click_info = self._get_click_info(tab)
            
            if click_info:
                # 模拟真实点击
                success = self._simulate_human_click(tab, click_info)
                
                if success:
                    self._log_progress("✅ 验证处理成功")
                    # 点击后等待验证完成（1.5-2秒）
                    time.sleep(random.uniform(1.5, 2.0))
                    return True
                else:
                    return True  # 即使失败也继续
            else:
                return True  # 未找到验证框也继续
                
        except Exception as e:
            self.logger.error(f"验证处理异常: {str(e)}")
            return True  # 异常时也继续流程
    
    def _get_click_info(self, tab):
        """
        获取验证元素的点击信息
        使用JavaScript精确定位验证框位置
        
        Args:
            tab: 浏览器标签页对象
            
        Returns:
            dict: 包含点击坐标的字典，如果未找到则返回None
        """
        try:
            # 注入脚本获取点击信息
            result = tab.run_js("""
                function getClickInfo() {
                    // 优先选择器，用于直接定位目标
                    const prioritySelectors = [
                        '#cf-turnstile iframe',                     // Turnstile iframe
                        '.cf-turnstile iframe',                    // Turnstile iframe
                        'iframe[src*="challenges.cloudflare.com"]', // Cloudflare挑战iframe
                        '#cf-turnstile',                           // Turnstile容器
                        '.cf-turnstile',                           // Turnstile容器
                    ];

                    // 复选框相关的选择器
                    const checkboxSelectors = [
                        'input[type="checkbox"]',                  // 常规复选框
                        '[role="checkbox"]',                       // 带有checkbox角色的元素
                    ];

                    let targetElement = null;

                    // 1. 尝试使用优先选择器查找目标元素（通常是iframe或容器）
                    for (const selector of prioritySelectors) {
                        const element = document.querySelector(selector);
                        if (element) {
                            const rect = element.getBoundingClientRect();
                            const style = getComputedStyle(element);
                            if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                                targetElement = element;
                                break;
                            }
                        }
                    }

                    // 2. 如果没找到，尝试在整个文档中查找可见的复选框
                    if (!targetElement) {
                        for (const selector of checkboxSelectors) {
                             const elements = document.querySelectorAll(selector);
                             for (const element of elements) {
                                const rect = element.getBoundingClientRect();
                                const style = getComputedStyle(element);
                                if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                                    // 检查父元素是否与turnstile相关，增加准确性
                                    if (element.closest('.cf-turnstile, #cf-turnstile')) {
                                        targetElement = element;
                                        break;
                                    }
                                }
                             }
                             if (targetElement) break;
                        }
                    }
                    
                    // 3. 如果找到了目标元素，计算点击位置
                    if (targetElement) {
                        const rect = targetElement.getBoundingClientRect();
                        let clickX, clickY;

                        const isCheckbox = checkboxSelectors.some(sel => targetElement.matches(sel));

                        if (isCheckbox) {
                            // 如果是复选框，其可点击区域总是在左侧。
                            // 不信任rect.width，因为它可能被CSS拉伸到100%。
                            // 我们点击距离左边缘一个小的固定偏移量。
                            clickX = rect.left + 15; // 15px的固定偏移量
                            clickY = rect.top + rect.height / 2;
                        } else {
                            // 对于非复选框的容器元素，尝试在其内部查找实际的复选框
                            const checkboxInside = targetElement.querySelector('input[type="checkbox"], [role="checkbox"]');
                            if (checkboxInside) {
                                const checkboxRect = checkboxInside.getBoundingClientRect();
                                // 点击复选框的中心
                                clickX = checkboxRect.left + checkboxRect.width / 2;
                                clickY = checkboxRect.top + checkboxRect.height / 2;
                            } else {
                                // 如果在容器内找不到复选框，则回退到原有的猜测逻辑
                                // 这对于iframe或复选框在shadow DOM内的情况可能是必须的
                                clickX = rect.left + rect.width * 0.2;
                                clickY = rect.top + rect.height / 2;
                            }
                        }
                        
                        return {
                            found: true,
                            selector: targetElement.tagName + (targetElement.id ? '#' + targetElement.id : '') + (targetElement.className ? '.' + targetElement.className.split(' ').join('.') : ''),
                            position: {
                                top: rect.top,
                                left: rect.left,
                                width: rect.width,
                                height: rect.height
                            },
                            clickPoint: {
                                x: clickX,
                                y: clickY
                            },
                            isCheckbox: isCheckbox
                        };
                    }
                    
                    return { found: false };
                }
                
                return getClickInfo();
            """)

            if result and result.get('found', False):
                self.logger.info(f"成功定位验证元素: {result.get('selector')} 位置: {result.get('position')}")
                self.logger.info(
                    f"推荐点击位置: X={result.get('clickPoint', {}).get('x')}, Y={result.get('clickPoint', {}).get('y')}")
                return result  # 返回结果对象
            else:
                self.logger.warning("未能定位验证元素")
                return None  # 未找到验证框时返回None

        except Exception as e:
            self.logger.error(f"获取点击信息时出错: {str(e)}")
            return None  # 发生错误时返回None
    
    def _simulate_human_click(self, tab, click_info: dict) -> bool:
        """
        模拟真实的人类点击
        
        Args:
            tab: 浏览器标签页对象
            click_info: 点击信息
            
        Returns:
            bool: 是否点击成功
        """
        try:
            click_point = click_info.get('clickPoint', {})
            x = click_point.get('x')
            y = click_point.get('y')
            
            if x is None or y is None:
                self.logger.warning("缺少点击坐标")
                return False
            
            self.logger.info(f"在坐标 ({x}, {y}) 模拟点击...")
            
            # 使用DrissionPage的actions API模拟真实点击
            tab.actions.move_to((x, y)).click()
            
            # 短暂延迟
            time.sleep(random.uniform(0.5, 1.0))
            
            return True
            
        except Exception as e:
            self.logger.error(f"模拟点击失败: {str(e)}")
            return False
    
    def get_last_error(self) -> Optional[str]:
        """获取最近的错误信息"""
        return self._error
