#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自动注册引擎 - 重构版本
核心改进：
1. 借鉴cursor-ideal的极简浏览器配置和Turnstile处理
2. 保留原有的完整流程和页面处理器
3. 优化：减少DOM查询频率，只在必要时检测
4. 集成人类行为模拟
"""

import os
import sys
import time
import random
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Callable

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# 导入新模块
from .browser_manager import BrowserManager
from .verification_handler import VerificationHandler
from .human_behavior import HumanBehaviorSimulator

# 导入原有模块（保留）
from .page_detector import PageDetector, PageState
from .page_handlers import (
    NavigationHandler,
    LoginPageHandler,
    PasswordPageHandler, 
    SignupPasswordPageHandler,
    MagicCodePageHandler,
    PhoneVerificationPageHandler,
    UsageSelectionPageHandler,
    ProTrialPageHandler,
    StripePaymentPageHandler,
)
from .card_manager import CardManager
from .parallel_worker import ParallelRegistrationManager


class AutoRegisterEngine:
    """
    自动注册引擎 - 重构版本
    
    支持两种模式：
    1. 注册密码模式：注册页→填邮箱→Turnstile→填密码→Turnstile→验证码→试用→支付→caps验证
    2. 登录模式：登录页→填邮箱→点击验证码继续→Turnstile→验证码→试用→支付→caps验证
    """
    
    def __init__(self, account_config, account_manager, register_config):
        """初始化自动注册引擎"""
        self.account_config = account_config
        self.register_config = register_config
        self.account_manager = account_manager
        self.logger = logging.getLogger(__name__)
        
        # 北京时区（UTC+8）
        self.beijing_tz = timezone(timedelta(hours=8))
        
        # 获取手动验证码模式配置
        self.manual_verify_mode = account_config.get_manual_verify_mode() if hasattr(account_config, 'get_manual_verify_mode') else False
        if self.manual_verify_mode:
            self.logger.info("✍️ 手动验证码模式已启用")
        
        # 登录邮箱管理器
        self.login_email_manager = None
        
        # 浏览器相关
        self.browser = None
        self.tab = None
        
        # 初始化新的管理器
        self.browser_manager = BrowserManager(
            account_config=self.account_config,
            log_callback=None
        )
        self.verification_handler = VerificationHandler(log_callback=None)
        self.behavior = HumanBehaviorSimulator(log_callback=None)
        
        # 初始化原有的检测器和处理器
        self.page_detector = PageDetector(log_callback=None)
        self.card_manager = CardManager(
            register_config=self.register_config,
            log_callback=None
        )
        
        # 页面处理器（按注册流程顺序）
        self.navigation_handler = NavigationHandler(log_callback=None)
        self.login_handler = LoginPageHandler(log_callback=None)
        self.signup_password_handler = SignupPasswordPageHandler(log_callback=None)
        self.password_handler = PasswordPageHandler(log_callback=None)
        self.magic_code_handler = MagicCodePageHandler(log_callback=None)
        self.phone_verification_handler = PhoneVerificationPageHandler(log_callback=None)
        self.usage_selection_handler = UsageSelectionPageHandler(log_callback=None)
        self.pro_trial_handler = ProTrialPageHandler(log_callback=None)
        self.stripe_payment_handler = StripePaymentPageHandler(log_callback=None)
        
        # 🔥 手机验证服务（单例，多次注册共享）
        self.shared_phone_service = None
        
        # 并行注册管理器
        self.parallel_manager = ParallelRegistrationManager(
            account_config=self.account_config,
            account_manager=self.account_manager,
            register_config=self.register_config,
            log_callback=None
        )
    
        # 控制标志
        self._stop_event = threading.Event()
        self._browser_process_pid = None
        
        # 注册状态
        self.current_email = None
        self.current_domain = None
        self.account_info = None
        
        # 进度回调
        self.progress_callback = None
        
        # 配置
        self.register_mode = "password"  # 默认注册密码模式
        self.headless_mode = False
        self.use_temp_mail = False  # 是否使用临时邮箱
        
        # 临时邮箱管理器（按需初始化）
        self.temp_mail_manager = None
        
        # 后处理标志
        self._post_payment_handled = False
    
    def _get_next_domain(self) -> str:
        """
        完全随机域名选择
        每次都随机选择一个域名，确保真正的随机性
        """
        domains = self.register_config.get_domains()
        if not domains:
            raise ValueError("未配置域名列表，请在域名配置中添加")
        
        # 完全随机选择
        domain = random.choice(domains)
        
        self.logger.debug(f"📍 随机选择域名: {domain}")
        return domain
    
    def set_progress_callback(self, callback: Callable[[str], None]):
        """设置进度回调函数"""
        self.progress_callback = callback
        # 更新所有组件的回调
        components = [
            self.browser_manager, self.verification_handler, self.behavior,
            self.page_detector, self.card_manager,
            self.navigation_handler, self.login_handler, self.signup_password_handler,
            self.password_handler, self.magic_code_handler, self.phone_verification_handler,
            self.usage_selection_handler, self.pro_trial_handler, self.stripe_payment_handler,
            self.parallel_manager
        ]
        for component in components:
            if hasattr(component, 'log_callback'):
                component.log_callback = callback
            # 设置停止检查回调
            if hasattr(component, 'stop_check_callback'):
                component.stop_check_callback = self._check_stop_signal
    
    def set_headless_mode(self, headless: bool):
        """设置无头模式"""
        self.headless_mode = headless
        self.parallel_manager.set_headless_mode(headless)
    
    def set_register_mode(self, mode: str):
        """设置注册模式"""
        if mode not in ["email_code", "password"]:
            mode = "password"
        self.register_mode = mode
        mode_name = "账号密码模式" if mode == "password" else "邮箱验证码模式"
        self._log_progress(f"🔧 注册模式: {mode_name}")
    
    def set_temp_mail_mode(self, enabled: bool):
        """设置临时邮箱模式"""
        self.use_temp_mail = enabled
        if enabled:
            self._log_progress("📮 已启用BC1P临时邮箱模式")
            # 初始化临时邮箱管理器
            if self.temp_mail_manager is None:
                from .bc1p_temp_mail_manager import BC1PTempMailManager
                self.temp_mail_manager = BC1PTempMailManager()
        else:
            self._log_progress("📧 使用配置的邮箱模式")
        
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def stop_registration(self):
        """立即停止注册流程"""
        self._log_progress("🛑 立即停止注册...")
        
        # 1. 设置停止标志（最高优先级）
        self._stop_event.set()
        
        # 2. 立即关闭浏览器（不等待）
        try:
            if self.browser:
                self.browser.quit()
                self._log_progress("✅ 浏览器已立即关闭")
        except:
            pass
        finally:
            self.browser = None
            self.tab = None
        
        # 3. 通知并行管理器停止（不阻塞）
        try:
            self.parallel_manager.stop_registration()
        except:
            pass
        
        self._log_progress("✅ 停止命令已完成")
    
    def _force_close_browser(self):
        """强制关闭浏览器（注册完成时调用）"""
        try:
            if self.browser:
                self.browser.quit()
                self.logger.debug("浏览器已关闭")
        except:
            pass
        finally:
            self.browser = None
            self.tab = None
    
    def _check_stop_signal(self) -> bool:
        """检查停止信号"""
        return self._stop_event.is_set()
    
    def _check_browser_alive(self) -> bool:
        """检查浏览器是否活跃"""
        try:
            if not self.browser or not self.tab:
                return False
            _ = self.tab.url
            return True
        except Exception:
            return False
    
    # ========== 手动模式等待方法 ==========
    
    def _wait_for_manual_email_input(self, timeout: int = 60, wait_turnstile: bool = False) -> bool:
        """
        手动输入邮箱模式：弹窗获取邮箱 → 调用自动化流程
        
        Args:
            timeout: 超时时间（秒）
            wait_turnstile: 是否等待Turnstile验证完成（注册密码模式需要）
        """
        try:
            # 步骤1: 弹窗让用户输入邮箱
            self._log_progress("📧 请在弹窗中输入邮箱地址")
            user_email = self._get_email_from_dialog()
            
            if not user_email:
                self._log_progress("❌ 未输入邮箱，取消注册")
                return False
            
            # 更新account_info中的邮箱
            self.account_info['email'] = user_email
            self._log_progress(f"✅ 邮箱: {user_email}")
            
            # 步骤2: 直接使用现有的登录页面处理函数（自动填写、点击、验证）
            return self.login_handler.handle_login_page(self.tab, self.account_info, check_turnstile=wait_turnstile)
            
        except Exception as e:
            self.logger.error(f"手动输入邮箱流程失败: {str(e)}")
            return False
    
    def _get_email_from_dialog(self) -> str:
        """通过回调在主线程弹窗获取邮箱"""
        try:
            # 使用进度回调发送特殊信号，让主线程弹出对话框
            if self.progress_callback:
                # 发送特殊信号
                self.progress_callback("__REQUEST_EMAIL_INPUT__")
                
                # 等待account_info中的email被更新（最多60秒）
                start_time = time.time()
                initial_email = self.account_info.get('email', 'manual@pending.com')
                
                while (time.time() - start_time) < 60:
                    current_email = self.account_info.get('email', '')
                    # 如果邮箱被更新且不是占位邮箱
                    if current_email and current_email != initial_email and '@' in current_email:
                        self.logger.info(f"获取到用户输入的邮箱: {current_email}")
                        return current_email
                    time.sleep(0.5)
                
                self.logger.warning("等待邮箱输入超时")
                return ""
            else:
                self.logger.error("没有进度回调，无法请求邮箱输入")
                return ""
            
        except Exception as e:
            self.logger.error(f"获取邮箱失败: {str(e)}")
            return ""
    
    def _wait_for_manual_verification_code(self, timeout: int = 60) -> bool:
        """等待用户手动输入验证码"""
        try:
            from .page_detector import PageState
            
            self.logger.info("等待用户手动输入验证码...")
            start_time = time.time()
            initial_url = self.tab.url
            
            while time.time() - start_time < timeout:
                current_url = self.tab.url
                current_state = self.page_detector.analyze_current_page(self.tab)
                
                # 检查URL是否发生实质性变化（离开验证码页面）
                if current_url != initial_url:
                    self.logger.info(f"URL已变化: {initial_url} -> {current_url}")
                    # 检查是否已经到达后续页面
                    if 'settings' in current_url.lower() or 'trial' in current_url.lower() or 'usage' in current_url.lower():
                        self.logger.info("检测到验证码验证成功，已跳转")
                        return True
                    
                    # 给页面一点时间加载
                    time.sleep(2.0)
                    # 再次检查状态
                    current_state = self.page_detector.analyze_current_page(self.tab)
                    if current_state != PageState.MAGIC_CODE and current_state != PageState.UNKNOWN:
                        self.logger.info(f"检测到页面状态变化: {current_state}")
                        return True
                
                # 短暂等待
                time.sleep(1.0)
            
            self.logger.warning("等待手动输入验证码超时")
            return False
            
        except Exception as e:
            self.logger.error(f"等待手动输入验证码异常: {str(e)}")
            return False
    
    # ========== 账号生成 ==========
    
    def _generate_account_info(self) -> Dict:
        """生成账号信息（支持域名转发、IMAP和BC1P临时邮箱三种方式）"""
        # 如果启用了临时邮箱模式，使用BC1P临时邮箱
        if self.use_temp_mail:
            return self._generate_bc1p_temp_account()
        
        # 获取邮箱配置
        email_config = self.register_config.get_email_config()
        email_type = email_config.get('email_type', 'domain_forward')
        
        if email_type == 'imap':
            # 使用2925 IMAP邮箱生成子邮箱
            return self._generate_2925_sub_account()
        else:
            # 使用域名转发模式（验证码转发到临时邮箱/QQ/163）
            return self._generate_domain_forward_account()
    
    def _generate_bc1p_temp_account(self) -> Dict:
        """生成BC1P临时邮箱账号"""
        # 确保临时邮箱管理器已初始化
        if self.temp_mail_manager is None:
            from .bc1p_temp_mail_manager import BC1PTempMailManager
            self.temp_mail_manager = BC1PTempMailManager()
        
        # 生成临时邮箱地址
        email = self.temp_mail_manager.generate_email()
        
        username = email.split('@')[0]
        domain = email.split('@')[1] if '@' in email else ''
        
        self._log_progress(f"📧 注册邮箱: {email} (BC1P临时邮箱)")
        
        return {
            "email": email,
            "username": username,
            "domain": domain,
            "first_name": username[:6],
            "last_name": username[6:] if len(username) > 6 else "User",
            "full_name": username,
            "password": "CursorAuto123!",
            "use_bc1p_temp_mail": True,  # 标记使用BC1P临时邮箱
        }
    
    def _generate_domain_forward_account(self) -> Dict:
        """生成域名邮箱（验证码转发到临时邮箱/QQ/163）"""
        # 手动模式：跳过生成，使用占位邮箱
        if self.manual_verify_mode:
            self._log_progress(f"✍️ 手动模式：等待用户输入邮箱")
            email = "manual@pending.com"  # 占位邮箱，稍后会被替换
            username = "manual"
            
            return {
                'email': email,
                'username': username,
                'password': '',  # 手动模式下密码由程序生成
                'domain': 'pending.com',
                'first_name': 'Manual',
                'last_name': 'User',
                'full_name': 'Manual User'
            }
        
        # 自动模式：正常生成
        # 选择域名（使用智能轮换）
        domain = self._get_next_domain()
        
        # 生成邮箱（4-6位字母 + 4-6位数字）
        import string
        letter_count = random.randint(4, 6)
        letters = ''.join(random.choice(string.ascii_lowercase) for _ in range(letter_count))
        digit_count = random.randint(4, 6)
        digits = ''.join(random.choice(string.digits) for _ in range(digit_count))
        email = f"{letters}{digits}@{domain}"
        
        username = email.split('@')[0]
        
        self._log_progress(f"📧 注册邮箱: {email}")
        
        return {
            "email": email,
            "username": username,
            "domain": domain,
            "first_name": username[:6],
            "last_name": username[6:] if len(username) > 6 else "User",
            "full_name": username,
            "password": "CursorAuto123!",
        }
    
    def _generate_2925_sub_account(self) -> Dict:
        """生成2925子邮箱账号"""
        from .imap_email_manager import ImapEmailManager
        
        imap_manager = ImapEmailManager(config_manager=self.register_config)
        
        # 生成随机名字
        import string
        firstname = ''.join(random.choice(string.ascii_lowercase) for _ in range(6))
        
        # 生成子邮箱
        sub_email, message = imap_manager.generate_sub_account(firstname=firstname)
        
        if not sub_email:
            self.logger.error(f"生成子邮箱失败: {message}")
            raise ValueError(f"生成子邮箱失败: {message}")
        
        self._log_progress(f"📧 注册邮箱: {sub_email} ")
        
        username = sub_email.split('@')[0]
        domain = sub_email.split('@')[1] if '@' in sub_email else ''
        
        return {
            "email": sub_email,
            "username": username,
            "domain": domain,
            "first_name": firstname,
            "last_name": "User",
            "full_name": firstname,
            "password": "CursorAuto123!",
        }
    
    # ========== 核心注册流程 ==========
    
    def register_account(self) -> bool:
        """执行单个账号注册（串行模式）"""
        start_time = time.time()
        self._stop_event.clear()
        self._post_payment_handled = False
        
        # 🔥 重置验证码页面进入计数器（每个账号独立计数）
        self.magic_code_handler.entry_count = 0
        
        # 清空上次的卡片状态
        self.card_manager.clear_current_card()
        
        try:
            # 1. 初始化浏览器
            if not self._init_browser():
                return False
            
            # 2. 执行注册流程
            success = self._execute_register_flow()
            
            # 3. 记录结果
            elapsed = time.time() - start_time 
            return success
            
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"注册异常: {str(e)}")
            self._log_progress(f"💥 注册异常 用时: {elapsed:.1f}秒")
            return False
        finally:
            # 统一标记银行卡状态
            try:
                # 只要分配了银行卡，就必须标记状态
                has_card = self.card_manager.current_card_info is not None
                card_marked = self.card_manager.is_card_marked_used()
                
                if has_card and not card_marked:
                    self._log_progress("⚠️ 已分配银行卡但注册失败，标记为问题卡")
                    self.card_manager.mark_card_as_problematic()
            except Exception as e:
                self.logger.error(f"卡片状态处理失败: {str(e)}")
            
            # 强制关闭浏览器
            try:
                self._force_close_browser()
            except Exception as e:
                self.logger.error(f"关闭浏览器失败: {str(e)}")
    
    def _execute_register_flow(self) -> bool:
        """执行注册流程（不包含浏览器初始化）- 供并行注册调用"""
        try:
            # 1. 生成账号信息
            account_info = self._generate_account_info()
            account_info['register_mode'] = self.register_mode  # 添加注册模式信息
            self.current_email = account_info['email']
            self.account_info = account_info
            
            # 2. 根据模式执行不同流程
            if self.register_mode == "password":
                return self._execute_password_mode_flow(account_info)
            else:
                return self._execute_email_code_mode_flow(account_info)
                
        except Exception as e:
            self.logger.error(f"注册流程异常: {str(e)}")
            return False
    
    def _init_browser(self) -> bool:
        """初始化浏览器"""
        try:
            self.browser, self.tab = self.browser_manager.create_browser_instance(
                headless_mode=self.headless_mode
            )
            return True
        except Exception as e:
            self._log_progress("❌ 浏览器初始化失败，请检查配置")
            self.logger.error(f"浏览器初始化失败: {str(e)}")
            return False
    
    # ========== 注册密码模式流程 ==========
    
    def _execute_password_mode_flow(self, account_info: Dict) -> bool:
        """
        注册密码模式：注册页→填邮箱→Turnstile→填密码→Turnstile→验证码→试用→支付
        """
        try:
            self._log_progress("📊 开始注册密码流程")
            
            # 第1轮：导航到登录页
            self._log_progress("🚀 导航到登录页")
            if not self.navigation_handler.navigate_to_login_page(self.tab):
                return False
            
            # 第2轮：点击Sign up链接
            self._log_progress("🚀 [第1轮] 导航到注册页面")
            if not self.navigation_handler.click_signup_link(self.tab):
                return False
            
            # 第3轮：填写邮箱 → Turnstile
            self._log_progress("🚀 [第2轮] 填写邮箱")
            if self.manual_verify_mode:
                # 手动模式：弹窗输入邮箱，程序自动填写并等待Turnstile验证
                if not self._wait_for_manual_email_input(wait_turnstile=True):
                    self._log_progress("❌ 邮箱输入或人机验证失败")
                    return False
                self._log_progress("✅ 邮箱已填写并通过人机验证")
            else:
                if not self.login_handler.handle_login_page(self.tab, account_info, check_turnstile=True):
                    return False
                self._log_progress("✅ 邮箱填写完成")
            
            # 第4轮：填写密码 → Turnstile（无论手动还是自动模式，密码都由程序填写）
            self._log_progress("🚀 [第3轮] 填写密码")
            if not self.signup_password_handler.handle_signup_password_page(self.tab, account_info):
                return False
            self._log_progress("✅ 密码填写完成")
            
            # 第5轮：输入验证码
            self._log_progress("🚀 [第4轮] 输入验证码")
            if self.manual_verify_mode:
                # 手动模式：等待用户在浏览器中手动输入验证码
                self._log_progress("✍️ 请在浏览器中手动输入验证码 (60秒超时)")
                if not self._wait_for_manual_verification_code():
                    self._log_progress("❌ 等待手动输入验证码超时")
                    return False
                self._log_progress("✅ 验证码已完成")
            else:
                # 设置人工处理回调
                self.magic_code_handler.manual_intervention_callback = self._request_manual_intervention
                if not self.magic_code_handler.handle_magic_code_page(self.tab, account_info, self.register_config):
                    return False
            # 注：handle_magic_code_page已包含动态等待页面跳转，不需要额外等待
            
            # 第6-8轮：试用+支付
            return self._handle_post_verification_flow(account_info)
            
        except Exception as e:
            self.logger.error(f"注册密码模式流程异常: {str(e)}")
            return False
    
    # ========== 邮箱验证码模式流程 ==========
    
    def _execute_email_code_mode_flow(self, account_info: Dict) -> bool:
        """
        登录模式：登录页→填邮箱→点击验证码继续→Turnstile→验证码→试用→支付
        """
        try:
            self._log_progress("📊 开始验证码注册流程")
            
            # 第1轮：导航到登录页
            self._log_progress("🚀 [第1轮] 导航到登录页")
            if not self.navigation_handler.navigate_to_login_page(self.tab):
                return False
            
            # 第2轮：填写邮箱（验证码登录模式不需要等待Turnstile）
            self._log_progress("🚀 [第2轮] 填写邮箱")
            if self.manual_verify_mode:
                # 手动模式：弹窗输入邮箱，程序自动填写
                if not self._wait_for_manual_email_input(wait_turnstile=False):
                    self._log_progress("❌ 邮箱输入失败")
                    return False
                self._log_progress("✅ 邮箱已填写")
            else:
                if not self.login_handler.handle_login_page(self.tab, account_info, check_turnstile=False):
                    return False
                self._log_progress("✅ 邮箱填写完成")
            
            # 第3轮：点击验证码继续 → Turnstile（无论手动还是自动模式，都由程序点击）
            self._log_progress("🚀 [第3轮] 点击验证码继续")
            if not self.password_handler.handle_password_page(self.tab, account_info, register_config=self.register_config):
                return False
            self._log_progress("✅ 已请求验证码")
            
            # 第4轮：输入验证码
            self._log_progress("🚀 [第4轮] 输入验证码")
            if self.manual_verify_mode:
                # 手动模式：等待用户在浏览器中手动输入验证码
                self._log_progress("✍️ 请在浏览器中手动输入验证码 (60秒超时)")
                if not self._wait_for_manual_verification_code():
                    self._log_progress("❌ 等待手动输入验证码超时")
                    return False
                self._log_progress("✅ 验证码已完成")
            else:
                # 设置人工处理回调
                self.magic_code_handler.manual_intervention_callback = self._request_manual_intervention
                if not self.magic_code_handler.handle_magic_code_page(self.tab, account_info, self.register_config):
                    return False
            # 注：handle_magic_code_page已包含动态等待页面跳转，不需要额外等待
            
            # 第5-7轮：试用+支付
            return self._handle_post_verification_flow(account_info)
            
        except Exception as e:
            self.logger.error(f"邮箱验证码模式流程异常: {str(e)}")
            return False
    
    # ========== 后续流程处理 ==========
    
    def _handle_post_verification_flow(self, account_info: Dict) -> bool:
        """
        处理验证码后的固定流程：
        手机号验证(可选) → Pro试用 → 支付
        """
        try:
            # 检查是否跳过绑卡（配置开关 或 无头模式）
            skip_card_binding = self.register_config.get_skip_card_binding()
            is_headless = self.headless_mode if hasattr(self, 'headless_mode') else False
            
            if skip_card_binding or is_headless:
                if is_headless:
                    self._log_progress("⚡ 无头模式自动跳过绑卡流程")
                else:
                    self._log_progress("⚡ 已开启跳过绑卡")
                
                # 🔥 检查是否启用了手机验证
                phone_config = self.register_config.get_phone_verification_config() if hasattr(self.register_config, 'get_phone_verification_config') else None
                phone_enabled = phone_config and phone_config.get('enabled', False)
                
                if phone_enabled:
                    self._log_progress("🔍 已启用手机验证，等待页面跳转...")
                else:
                    self._log_progress("🔍 未启用手机验证，等待页面跳转...")
                
                max_wait_for_phone = 30  # 最多等待30秒
                
                for wait_attempt in range(max_wait_for_phone):
                    # 检查停止信号
                    if self._check_stop_signal():
                        return False
                    
                    time.sleep(1)
                    
                    current_state = self.page_detector.analyze_current_page(self.tab)
                    current_url = self.tab.url
                    
                    # 🔥 关键：检查是否到达手机验证页面（URL包含radar-challenge/send）
                    if current_state == PageState.PHONE_VERIFICATION or '/radar-challenge/send' in current_url:
                        self._log_progress("📱 检测到手机号验证页面")
                        # 传递人工处理回调和register_config
                        self.phone_verification_handler.manual_intervention_callback = self._request_manual_intervention
                        if not self.phone_verification_handler.handle_phone_verification_page(self.tab, account_info, self.register_config):
                            self._log_progress("❌ 手机号验证失败")
                            return False
                        
                        # 🔥 手机验证完成后，固定等待2-3秒让页面跳转
                        wait_time = random.uniform(2.0, 3.0)
                        time.sleep(wait_time)
                        self._log_progress("✅ 配置已更新")
                        
                        # 提取token并保存
                        self._try_extract_token(account_info)
                        
                        # 继续后面的逻辑
                        break
                    
                    # 🔥 检查是否到达最终页面（trial、agents、settings等）
                    if any(keyword in current_url.lower() for keyword in ['trial', 'agents', 'settings', 'dashboard']):
                        if phone_enabled:
                            self.logger.debug("✅ 已到达最终页面（未遇到手机验证）")
                        else:
                            self.logger.debug("✅ 已到达最终页面")
                        # 🔥 到达最终页面后立即提取token并保存
                        time.sleep(1)  # 等待cookie设置
                        self._try_extract_token(account_info)
                        break
                    
                    # 每5秒输出一次等待日志
                    if wait_attempt % 5 == 0 and wait_attempt > 0:
                        self._log_progress(f"⏳ 等待页面加载... ({wait_attempt}/30秒)")
                        self.logger.debug(f"当前URL: {current_url[:100]}...")
                        self.logger.debug(f"当前状态: {current_state}")
                
                # 🔥 检查token是否已保存
                if account_info.get('saved_to_pool', False):
                    self._log_progress("✅ 账号已保存")
                    # 🔥 刷新UI和订阅状态
                    self._handle_post_payment_success()
                    return True
                else:
                    self._log_progress("❌ Token提取失败，账号未保存")
                    return False
            
            # 固定流程：手机号验证(可选) → Pro试用 → 支付
            phone_config = self.register_config.get_phone_verification_config() if hasattr(self.register_config, 'get_phone_verification_config') else None
            phone_enabled = phone_config and phone_config.get('enabled', False)
            
            # 步骤1: 等待并处理手机号验证（如果启用）
            if phone_enabled:
                self._log_progress("🚀 [第4.5轮] 等待手机号验证页面...")
                if not self._wait_and_handle_phone_verification(account_info):
                    return False
            else:
                self.logger.debug("手机验证未启用，跳过")
            
            # 步骤2: 等待并处理Pro试用页面
            self._log_progress("🚀 [第5轮] 等待Pro试用页面...")
            if not self._wait_and_handle_pro_trial(account_info):
                return False
            
            # 步骤3: 等待并处理支付页面
            self._log_progress("🚀 [终] 等待支付页面...")
            if not self._wait_and_handle_payment(account_info):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"后续流程处理失败: {str(e)}")
            return False
    
    # ========== 辅助方法 ==========
    
    def _request_manual_intervention(self, tab, message: str, wait_time: int = 30) -> bool:
        """人工干预处理（支付页面等）"""
        try:
            initial_url = tab.url
            self._log_progress(f"⏸️ {message}")
            
            # 等待页面变化
            for i in range(wait_time):
                if self._check_stop_signal():
                    return False
            
                current_url = tab.url
                if current_url != initial_url:
                    self._log_progress("✅ 检测到页面变化")
                    return True

                if i % 10 == 0 and i > 0:
                    self._log_progress(f"⏳ 等待中... ({i}秒)")

                time.sleep(1)

            return True
            
        except Exception as e:
            self.logger.error(f"人工干预失败: {str(e)}")
            return False
    
    def _wait_and_handle_phone_verification(self, account_info: Dict) -> bool:
        """等待并处理手机号验证页面"""
        try:
            max_wait = 30
            for i in range(max_wait * 2):
                if self._check_stop_signal() or not self._check_browser_alive():
                    return False
                
                current_state = self.page_detector.analyze_current_page(self.tab)
                if current_state == PageState.PHONE_VERIFICATION:
                    self._log_progress("📱 检测到手机号验证页面")
                    self.phone_verification_handler.manual_intervention_callback = self._request_manual_intervention
                    if self.phone_verification_handler.handle_phone_verification_page(self.tab, account_info, self.register_config):
                        self._log_progress("✅ 手机号验证完成")
                        self._try_extract_token(account_info)
                        return True
                    else:
                        return False
                
                # 跳过了手机验证
                if current_state in [PageState.PRO_TRIAL, PageState.STRIPE_PAYMENT, PageState.AGENTS]:
                    self.logger.debug("未遇到手机验证页面，直接进入下一步")
                    return True
                
                time.sleep(0.5)
            
            self._log_progress("⏰ 等待手机号验证页面超时")
            return False
        except Exception as e:
            self.logger.error(f"处理手机号验证失败: {str(e)}")
            return False
    
    def _wait_and_handle_pro_trial(self, account_info: Dict) -> bool:
        """等待并处理Pro试用页面"""
        try:
            max_wait = 30
            for i in range(max_wait * 2):
                if self._check_stop_signal() or not self._check_browser_alive():
                    return False
                
                current_state = self.page_detector.analyze_current_page(self.tab)
                if current_state == PageState.PRO_TRIAL:
                    self._log_progress("🎯 检测到Pro试用页面")
                    if self.pro_trial_handler.handle_pro_trial_page(self.tab, account_info):
                        self._log_progress("✅ Pro试用页面处理完成")
                        time.sleep(random.uniform(1.0, 2.0))
                        return True
                    else:
                        return False
                
                # 跳过了试用页面
                if current_state in [PageState.STRIPE_PAYMENT, PageState.AGENTS]:
                    self.logger.debug("未遇到试用页面，直接进入下一步")
                    return True
                
                time.sleep(0.5)
            
            self._log_progress("⏰ 等待Pro试用页面超时")
            return False
        except Exception as e:
            self.logger.error(f"处理Pro试用页面失败: {str(e)}")
            return False
    
    def _wait_and_handle_payment(self, account_info: Dict) -> bool:
        """等待并处理支付页面"""
        try:
            max_wait = 30
            for i in range(max_wait * 2):
                if self._check_stop_signal() or not self._check_browser_alive():
                    return False
                
                current_state = self.page_detector.analyze_current_page(self.tab)
                if current_state == PageState.STRIPE_PAYMENT:
                    self._log_progress("💳 检测到支付页面")
                    
                    self._try_extract_token(account_info)
                    
                    self.stripe_payment_handler.manual_intervention_callback = self._request_manual_intervention
                    if self.stripe_payment_handler.handle_stripe_payment_page(self.tab, account_info, self.card_manager):
                        if not account_info.get('saved_to_pool', False):
                            self._try_extract_token(account_info)
                        
                        self._handle_post_payment_success()
                        return True
                    else:
                        return False
                
                # 直接到达agents页面
                if current_state == PageState.AGENTS:
                    self._log_progress("✅ 已到达agents页面")
                    self._try_extract_token(account_info)
                    self._save_account_to_pool(account_info, "注册成功")
                    self._handle_post_payment_success()
                    return True
                
                time.sleep(0.5)
            
            self._log_progress("⏰ 等待支付页面超时")
            return False
        except Exception as e:
            self.logger.error(f"处理支付页面失败: {str(e)}")
            return False
    
    def _try_extract_token(self, account_info: Dict) -> bool:
        """尝试提取session token"""
        try:
            if account_info.get('token_extracted', False):
                return True
                
            cookies = self.tab.cookies()
            workos_token = None
            
            for cookie in cookies:
                if cookie.get('name') == 'WorkosCursorSessionToken':
                    workos_token = cookie.get('value', '')
                    break
            
            if workos_token:
                import urllib.parse
                decoded_token = urllib.parse.unquote(workos_token)
                
                if decoded_token.startswith('user_') and ('::' in decoded_token or '%3A%3A' in decoded_token):
                    account_info['WorkosCursorSessionToken'] = decoded_token
                    account_info['token_extracted'] = True
                    
                    # 提取user_id
                    if '::' in decoded_token:
                        user_id = decoded_token.split('::', 1)[0]
                    else:
                        user_id = decoded_token.split('%3A%3A', 1)[0]
                    
                    account_info['user_id'] = user_id
                    # 使用北京时间（UTC+8）
                    account_info['register_time'] = datetime.now(self.beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
                    
                    # 保存账号
                    if not account_info.get('saved_to_pool', False):
                            self._save_account_to_pool(account_info, "Token获取成功")
                            account_info['saved_to_pool'] = True
                    
                    return True
            
            return False
                
        except Exception as e:
            self.logger.error(f"token提取失败: {str(e)}")
            return False
    
    def _save_account_to_pool(self, account_info: Dict, status: str):
        """保存账号到账号池"""
        try:
            # 处理创建时间
            if 'register_time' in account_info and account_info['register_time']:
                created_time = account_info['register_time']
                if len(created_time) > 16:
                    created_time = created_time[:16]
            else:
                # 使用北京时间（UTC+8）
                created_time = datetime.now(self.beijing_tz).strftime('%Y-%m-%d %H:%M')
            
            workos_token = account_info.get('WorkosCursorSessionToken', '')
            user_id = account_info.get('user_id', '')
            
            email = account_info.get('email', '未知')
            
            if not workos_token or not user_id:
                self._log_progress("⚠️ 缺少必要信息，跳过保存")
                return
            
            # 提取临时token（长度应该是408的web token）
            access_token = ""
            if '::' in workos_token:
                parts = workos_token.split('::', 1)
                if len(parts) == 2 and parts[1].startswith('eyJ'):
                    access_token = parts[1]
                    self.logger.debug(f"✅ 提取临时token成功，长度: {len(access_token)}")
            elif '%3A%3A' in workos_token:
                # 处理URL编码的情况
                parts = workos_token.split('%3A%3A', 1)
                if len(parts) == 2 and parts[1].startswith('eyJ'):
                    access_token = parts[1]
                    self.logger.debug(f"✅ 提取临时token成功（URL编码），长度: {len(access_token)}")
            
            if not access_token:
                self.logger.warning(f"⚠️ 无法从WorkosCursorSessionToken提取临时token")
                access_token = "pending_jwt_conversion"
            
            # 🔥 修正：根据注册模式决定是否保存密码
            # 邮箱验证码模式（email_code）：不保存密码
            # 账号密码模式（password）：保存密码
            password_to_save = ""
            if self.register_mode == "password":
                password_to_save = account_info.get('password', '')
            
            account_data = {
                'email': email,
                'created_at': created_time,
                'subscription_status': "未知",
                'status': status,
                'password': password_to_save,  # 根据模式保存
                'access_token': access_token,
                'refresh_token': access_token,
                'user_id': user_id,
                'WorkosCursorSessionToken': workos_token,
                'token_type': "pending_conversion",
                'domain': account_info['domain'],
                'full_name': account_info['full_name']
            }
            
            success = self.account_config.add_account(account_data)
            if success:
                self._log_progress("💾 账号已保存")
                # 启动异步转换（后台进行，不阻塞注册流程）
                self.logger.info(f"🔄 启动异步Token转换: {email}")
                self.logger.info(f"   临时Token长度: {len(access_token)}")
                self.logger.debug(f"   WorkosCursorSessionToken前50字符: {workos_token[:50]}...")
                self._start_async_token_conversion(workos_token, user_id, account_info)
            else:
                self._log_progress("❌ 账号保存失败")
                self.logger.error(f"账号保存失败，邮箱: {account_info.get('email', '')}")
            
        except Exception as e:
            self.logger.error(f"保存账号失败: {str(e)}")
    
    def _start_async_token_conversion(self, workos_token: str, user_id: str, account_info: dict):
        """异步转换token"""
        email = account_info.get('email', '未知')
        
        def async_convert():
            try:
                self.logger.info(f"🔄 异步转换线程启动: {email}")
                time.sleep(0.3)
                
                from ...utils.session_token_converter import SessionTokenConverter
                converter = SessionTokenConverter(self.account_config)
                
                self.logger.info(f"🔄 开始调用convert_workos_to_session_jwt: {email}")
                success, session_access_token, session_refresh_token = converter.convert_workos_to_session_jwt(
                    workos_token, user_id
                )
                
                if success and session_access_token:
                    self.logger.info(f"✅ Token转换成功: {email}, 新Token长度: {len(session_access_token)}")
                    
                    # 更新账号
                    all_accounts = self.account_config.load_accounts()
                    for i, acc in enumerate(all_accounts):
                        if acc.get('email') == email:
                            all_accounts[i]['access_token'] = session_access_token
                            all_accounts[i]['refresh_token'] = (
                                session_refresh_token or session_access_token
                            )
                            all_accounts[i]['token_type'] = "session"
                            self.logger.info(f"✅ 账号数据已更新: {email}")
                            break
                    
                    self.account_config.save_accounts(all_accounts)
                    self.logger.info(f"✅ {email} 后台转换完成并已保存")
                else:
                    self.logger.error(f"❌ Token转换失败: {email}")
                
                # 🔥 优化：只增量更新这个账号，不刷新整个表格
                if hasattr(self.account_manager, 'update_single_account_in_table'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(500, lambda: self.account_manager.update_single_account_in_table(email))
                elif hasattr(self.account_manager, '_debounced_refresh_ui'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(500, self.account_manager._debounced_refresh_ui)
                elif hasattr(self.account_manager, 'load_accounts'):
                    # 兼容旧版本
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(500, self.account_manager.load_accounts)
                    
            except Exception as e:
                self.logger.error(f"❌ 后台转换异常: {email} - {str(e)}")
                import traceback
                self.logger.error(f"详细错误:\n{traceback.format_exc()}")
        
        thread = threading.Thread(target=async_convert, daemon=True)
        thread.start()
    
    def _handle_post_payment_success(self):
        """绑卡完成后的处理"""
        try:
            if getattr(self, '_post_payment_handled', False):
                return
            self._post_payment_handled = True
            
            # 标记银行卡为已使用
            if hasattr(self.card_manager, 'current_card_info') and self.card_manager.current_card_info:
                self.card_manager.mark_card_as_used()
                self.logger.info("✅ 银行卡已标记")
            
            # 🔥 刷新当前账号订阅状态（只刷新这一个账号）
            if hasattr(self.account_manager, 'start_concurrent_refresh'):
                accounts = self.account_config.load_accounts()
                target_account = None
                for acc in accounts:
                    if acc.get('email') == self.current_email:
                        target_account = acc
                        break
                
                if target_account:
                    # 🔥 关键：标记为注册刷新，告诉UI只增量更新
                    target_account['_is_registration_refresh'] = True
                    self.account_manager.start_concurrent_refresh([target_account])
                    self.logger.info("✅ 已启动订阅刷新（仅当前账号）")
            
        except Exception as e:
            self.logger.error(f"后处理失败: {str(e)}")
    
    # ========== 批量注册 ==========
    
    def batch_register(self, count: int = 1) -> List[Dict]:
        """批量注册"""
        if self.parallel_manager.parallel_enabled and count > 1:
            return self.parallel_manager.parallel_batch_register(count)
        else:
            return self._serial_batch_register(count)
    
    def _serial_batch_register(self, count: int) -> List[Dict]:
        """串行批量注册"""
        results = []
        batch_start_time = time.time()
        
        self._log_progress(f"🚀 开始批量注册 {count} 个账号...")
        
        for i in range(count):
            if self._check_stop_signal():
                self._log_progress(f"🛑 已停止，完成 {i}/{count} 个")
                break
            
            # 输出当前进度（注册开始）
            self._log_progress(f"📊 总进度: {i+1}/{count}")
            
            success = self.register_account()
            
            results.append({
                'index': i + 1,
                'email': self.current_email,
                'success': success,
                'timestamp': datetime.now(self.beijing_tz).isoformat()
            })
            
            if success:
                self._log_progress(f"📊  第 {i+1}/{count} 个账号注册成功: {self.current_email}")
            else:
                self._log_progress(f"❌ 第 {i+1}/{count} 个账号注册失败")
            
            # 间隔（拆分等待，每0.2秒检查停止信号）
            if i < count - 1:
                delay = random.uniform(1, 2)
                self._log_progress(f"⏳ 等待 {delay:.1f} 秒...")
                
                # 拆分等待时间，频繁检查停止信号
                steps = int(delay / 0.2)
                for _ in range(steps):
                    if self._check_stop_signal():
                        self._log_progress(f"🛑 检测到停止信号，终止批量注册")
                        break
                    time.sleep(0.2)
        
        # 统计
        total_time = time.time() - batch_start_time
        success_count = sum(1 for r in results if r.get('success', False))
        avg_time = total_time / len(results) if results else 0
        
        self._log_progress(f"📊  批量注册完成 {success_count}/{count}, 平均: {avg_time:.1f}秒/个")
            
        return results
    
    def enable_parallel_mode(self, enabled: bool = True, max_workers: int = 3):
        """启用并行模式"""
        self.parallel_manager.enable_parallel_mode(enabled, max_workers)
    
    # ========== 一键登录功能 ==========
    
    def quick_login_with_email(self, email: str) -> bool:
        """
        使用指定邮箱进行一键登录
        
        流程：登录页→填邮箱→点击验证码继续→Turnstile→验证码→Dashboard获取token
        
        Args:
            email: 指定的邮箱地址
            
        Returns:
            bool: 是否登录成功
        """
        try:
            self._log_progress(f"🔑 开始一键登录: {email}")
            
            # 初始化浏览器
            if not self._init_browser():
                return False
            
            # 创建账号信息（用于流程）
            username = email.split('@')[0]
            domain = email.split('@')[1] if '@' in email else ''
            
            account_info = {
                'email': email,
                'username': username,
                'domain': domain,
                'first_name': username[:6],
                'last_name': 'User',
                'full_name': username,
                'register_mode': 'email_code'  # 使用验证码模式
            }
            
            self.account_info = account_info
            self.current_email = email
            
            # 第1步：导航到登录页
            self._log_progress("🚀 导航到登录页")
            if not self.navigation_handler.navigate_to_login_page(self.tab):
                return False
            
            # 第2步：填写邮箱
            self._log_progress("📧 填写邮箱")
            if not self.login_handler.handle_login_page(self.tab, account_info, check_turnstile=False):
                return False
            
            # 第3步：点击验证码继续 → Turnstile（一键登录模式，不需要返回）
            self._log_progress("🔑 点击使用验证码继续")
            # 标记为一键登录模式，防止执行返回操作
            account_info['quick_login_mode'] = True
            if not self.password_handler.handle_password_page(self.tab, account_info, register_config=self.register_config):
                return False
            
            # 第4步：输入验证码（initial_url在验证码页面就绪后记录）
            self._log_progress("🔐 输入验证码")
            self.magic_code_handler.manual_intervention_callback = self._request_manual_intervention
            if not self.magic_code_handler.handle_magic_code_page(self.tab, account_info, self.register_config):
                return False
            
            # 第5步：等待页面跳转并提取Token
            self._log_progress("✅ 验证码完成，等待页面跳转...")
            
            # 记录当前URL（验证码页面完成后）
            initial_url = self.tab.url
            
            # 等待页面变化并提取Token（最多30秒）
            token_extracted = False
            for attempt in range(30):
                time.sleep(1)
                
                current_url = self.tab.url
                
                # 只要URL变化了就尝试提取
                if current_url != initial_url:
                    self._log_progress(f"✅ 检测到页面跳转")
                    
                    # 等待1-2秒确保cookie设置完成
                    time.sleep(random.uniform(1.0, 2.0))
                    
                    # 尝试提取token
                    if self._try_extract_token(account_info):
                        self._log_progress("✅ Token已获取")
                        token_extracted = True
                        break
                    else:
                        # Token还没设置，继续等待
                        self.logger.debug(f"尝试 {attempt+1}: Token尚未设置，继续等待...")
                
                if attempt % 5 == 0:
                    self._log_progress(f"⏳ 等待页面跳转和Token... ({attempt}/30秒)")
            
            if token_extracted:
                # 保存账号并启动异步转换
                if not account_info.get('saved_to_pool', False):
                    self._save_account_to_pool(account_info, "一键登录成功")
                    account_info['saved_to_pool'] = True
                
                self._log_progress("✅ 账号已保存，后台转换Token中...")
                # 🔥 刷新UI和订阅状态
                self._handle_post_payment_success()
                return True
            else:
                self._log_progress("⚠️ Token提取失败（超时30秒）")
                return False
            
        except Exception as e:
            self.logger.error(f"一键登录失败: {str(e)}")
            self._log_progress(f"❌ 一键登录失败: {str(e)}")
            return False
        finally:
            # 关闭浏览器
            self._force_close_browser()
    
    # ========== 兼容原有代码的辅助方法 ==========
    
    def _select_random_domain(self) -> str:
        """选择随机域名"""
        domains = self.register_config.get_domains()
        if not domains:
            raise ValueError("未配置域名列表")
        return random.choice(domains)
    
    @property
    def email_manager(self):
        """获取email_manager（兼容性）"""
        return getattr(self.register_config, 'email_manager', None)