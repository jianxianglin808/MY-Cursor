#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
页面状态检测器 - 优化版本
核心改进：
1. 优先使用URL检测（快速，不触发自动化检测）
2. 必要时才使用DOM元素检测
3. 保留原有的所有选择器和检测逻辑
"""

import logging
import urllib.parse
from enum import Enum
from typing import Optional


class PageState(Enum):
    """页面状态枚举 - 智能注册流程状态管理"""
    LOGIN = "login"                   # 登录模式邮箱输入页面
    SIGNUP_FIRST_LEVEL = "signup_first_level"  # 注册模式第一级页面（邮箱+姓名输入）
    PASSWORD = "password"             # 登录模式密码输入页面  
    SIGNUP_PASSWORD = "signup_password" # 注册模式密码创建页面
    MAGIC_CODE = "magic_code"         # 验证码输入页面
    PHONE_VERIFICATION = "phone_verification" # 手机号验证页面 (radar-challenge)
    USAGE_SELECTION = "usage_selection" # 使用方式选择页面 (How are you planning to use Cursor?)
    PRO_TRIAL = "pro_trial"          # 试用选择页面 (Try Cursor Pro, On Us)
    PRO_TRIAL_OLD = "pro_trial_old"  # 试用页面 (Claim your free Pro trial)
    STRIPE_PAYMENT = "stripe_payment" # 支付页面
    BANK_VERIFICATION = "bank_verification" # 银行验证页面 (hCaptcha复选框)
    AGENTS = "agents"                 # Agents页面（成功）
    UNKNOWN = "unknown"              # 未知状态


class PageDetector:
    """
    页面状态检测器 - 优化版本
    优先URL检测，减少DOM查询
    """
    
    def __init__(self, log_callback=None):
        """初始化页面检测器"""
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        self.last_url = None
        
        # 保留原有的选择器配置
        self._init_selectors()
    
    def _init_selectors(self):
        """初始化选择器配置（保留原有逻辑）"""
        # 邮箱输入选择器
        self.email_input_selectors = [
            "@placeholder=Your email address",
            "@placeholder=您的邮箱地址",
        ]
        
        # 注册第一级选择器
        self.signup_first_level_selectors = [
            "@placeholder=Your email address",
            "@placeholder=您的邮箱地址",
            "@placeholder=您的名字",
            "@placeholder=您的姓氏",
            "@placeholder=Your first name",
            "@placeholder=Your last name"
        ]
        
        # 密码页面选择器
        self.password_selectors = [
            "@placeholder=您的密码",
            "@placeholder=输入密码",
            "@placeholder=Your password",
            "text=使用邮箱验证码登录"
        ]
        
        # 注册密码选择器
        self.signup_password_selectors = [
            "@placeholder=创建密码",
            "@placeholder=Create password",
            "text=创建密码",
            "text=使用邮箱验证码继续"
        ]
        
        # 验证码页面选择器
        self.verification_selectors = [
            "text=验证您的邮箱",
            "text=查看您的邮箱",
            "text=Verify your email",
            "text=Check your email",
        ]
        
        # 使用方式选择选择器
        self.usage_selection_selectors = [
            "text=How are you planning to use Cursor?",
            "text=您打算如何使用Cursor？"
        ]
        
        # Pro试用选择器
        self.pro_trial_selectors = [
            "text=Try Cursor Pro, On Us",
            "text=Get 2 free weeks"
        ]
        
        # Pro试用旧版选择器（更新为新界面）
        self.pro_trial_old_selectors = [
            "text=Claim your free Pro trial",
            "text=Continue with free trial",
            "text=Skip for now"
        ]
        
        # 支付页面选择器
        self.stripe_payment_selectors = [
            "text=输入付款详情",
            "text=支付方式",
            "text=美国银行账户",
            "text=Cash App Pay"
        ]
    
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.debug(message)
        if self.log_callback:
            self.log_callback(message)
    
    def analyze_current_page(self, tab, processed_pages=None) -> PageState:
        """
        分析当前页面状态
        优化：优先使用URL检测，减少DOM查询
        
        Args:
            tab: 浏览器标签页
            processed_pages: 已处理的页面（未使用，保留兼容性）
            
        Returns:
            PageState: 当前页面状态
        """
        try:
            current_url = tab.url
            
            # 记录URL变化
            if self.last_url != current_url:
                self.logger.debug(f"URL变化: {current_url}")
                self.last_url = current_url
            
            # 🔥 第一优先级：URL快速检测（不查询DOM）
            url_state = self._detect_by_url(current_url)
            if url_state != PageState.UNKNOWN:
                return url_state
            
            # 🔥 第二优先级：必要的DOM检测
            # 只检测URL无法区分的页面
            dom_state = self._detect_by_dom(tab, current_url)
            return dom_state
            
        except Exception as e:
            self.logger.error(f"页面分析异常: {str(e)}")
            return PageState.UNKNOWN
    
    def _detect_by_url(self, current_url: str) -> PageState:
        """
        通过URL进行快速检测
        不查询DOM，极快
        """
        parsed_url = urllib.parse.urlparse(current_url)
        path = parsed_url.path
        netloc = parsed_url.netloc
        
        # 检查agents页面
        if "cursor.com" in netloc and "/agents" in path:
            return PageState.AGENTS
        
        # 检查Pro试用页面（通过URL路径）
        if "cursor.com" in netloc and ("/trial" in path or "/cn/trial" in path):
            return PageState.PRO_TRIAL
        
        # 检查支付页面
        if "checkout.stripe.com" in current_url or "js.stripe.com" in current_url:
            return PageState.STRIPE_PAYMENT
        
        # 检查authenticator.cursor.sh
        if "authenticator.cursor.sh" in netloc:
            # 手机号验证页面（只检测 /radar-challenge/send，不包括 /verify）
            if "/radar-challenge/send" in path:
                return PageState.PHONE_VERIFICATION
            
            # radar-challenge/verify 是验证码输入页面，不是手机号输入页面
            if "/radar-challenge/verify" in path:
                return PageState.MAGIC_CODE
            
            # 验证码页面
            if "/magic-code" in path:
                return PageState.MAGIC_CODE
            
            # 密码页面（需要在DOM检测中区分注册/登录）
            if "/password" in path:
                # 暂时返回UNKNOWN，让DOM检测区分
                return PageState.UNKNOWN
            
            # 注册页面
            if "/sign-up" in path and "/password" not in path:
                return PageState.SIGNUP_FIRST_LEVEL
            
            # 登录页面
            if "?client_id" in current_url and "/sign-up" not in path:
                return PageState.LOGIN
        
        return PageState.UNKNOWN
    
    def _detect_by_dom(self, tab, current_url: str) -> PageState:
        """
        通过DOM进行检测（仅在URL无法判断时使用）
        保留原有的检测逻辑
        """
        # 使用适中的超时，平衡速度和准确性
        quick_timeout = 0.5
        
        # 密码页面检测
        if "/password" in current_url:
            # 检测是否是注册密码页面
            for selector in self.signup_password_selectors[:2]:  # 只检查核心选择器
                if tab.ele(selector, timeout=quick_timeout):
                    return PageState.SIGNUP_PASSWORD
            # 否则是登录密码页面
            return PageState.PASSWORD
        
        # # 使用方式选择页面（已合并到Pro试用页面）
        # if tab.ele(self.usage_selection_selectors[0], timeout=quick_timeout):
        #     return PageState.USAGE_SELECTION
        
        # # Pro试用新版（已禁用）
        # if tab.ele(self.pro_trial_selectors[0], timeout=quick_timeout):
        #     return PageState.PRO_TRIAL
        
        # Pro试用页面
        if tab.ele(self.pro_trial_old_selectors[0], timeout=quick_timeout):
            return PageState.PRO_TRIAL
        
        # 验证码页面
        if tab.ele(self.verification_selectors[0], timeout=quick_timeout):
            return PageState.MAGIC_CODE
        
        # 登录/注册页面（检查是否有姓名输入框）
        if tab.ele("@placeholder=Your first name", timeout=quick_timeout) or \
           tab.ele("@placeholder=您的名字", timeout=quick_timeout):
            return PageState.SIGNUP_FIRST_LEVEL
        
        if tab.ele("@placeholder=Your email address", timeout=quick_timeout):
            return PageState.LOGIN
        
        return PageState.UNKNOWN
    
    def wait_for_page_state(self, tab, expected_state: PageState,
                           max_wait_time: float = 60.0,
                           check_interval: float = 0.5) -> bool:
        """等待页面跳转到预期状态"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            current_state = self.analyze_current_page(tab)
            
            if current_state == expected_state:
                self.logger.debug(f"✅ 已处于预期页面: {expected_state.value}")
                return True
            
            time.sleep(check_interval)
        
        return False
    
    # ========== 兼容性方法（保留旧接口）==========
    
    def detect_specific_page(self, tab, expected_page: str) -> bool:
        """检测特定页面（兼容旧代码）"""
        try:
            page_state_map = {
                "login": PageState.LOGIN,
                "signup_first_level": PageState.SIGNUP_FIRST_LEVEL,
                "password": PageState.PASSWORD,
                "signup_password": PageState.SIGNUP_PASSWORD,
                "magic_code": PageState.MAGIC_CODE,
                "usage_selection": PageState.USAGE_SELECTION,
                "pro_trial": PageState.PRO_TRIAL,
                "pro_trial_old": PageState.PRO_TRIAL_OLD,
                "stripe_payment": PageState.STRIPE_PAYMENT,
            }
            
            expected_state = page_state_map.get(expected_page)
            if not expected_state:
                return False
            
            current_state = self.analyze_current_page(tab)
            return current_state == expected_state
            
        except Exception as e:
            self.logger.error(f"页面检测异常: {str(e)}")
            return False