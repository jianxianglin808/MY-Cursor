#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
邮箱提取器
"""

import logging
import re
import time
import requests
from typing import Optional, Tuple

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSION_AVAILABLE = True
except ImportError:
    DRISSION_AVAILABLE = False


class EmailExtractor:
    """邮箱提取器，从Cursor Dashboard获取真实邮箱"""
    
    def __init__(self, config=None):
        self.logger = logging.getLogger(__name__)
        self.config = config
    
    def _get_request_proxies(self) -> dict:
        """
        根据配置决定是否使用代理
        
        Returns:
            dict: 代理配置字典
                - {} 表示强制直连，不使用任何代理
                - {'http': 'xxx', 'https': 'xxx'} 表示使用指定代理
        
        Note:
            requests库中 proxies=None 会使用环境变量代理，
            而 proxies={} 才是真正的强制直连
        """
        if self.config and hasattr(self.config, 'get_use_proxy'):
            if not self.config.get_use_proxy():
                # 明确指定不使用代理 - 返回空字典强制直连
                self.logger.info("🌐 代理配置：禁用代理，强制直连")
                return {}
        
        # 启用代理 - 尝试获取系统代理
        try:
            import urllib.request
            proxy_handler = urllib.request.getproxies()
            if proxy_handler:
                self.logger.info(f"🌐 代理配置：使用系统代理 {proxy_handler}")
                return proxy_handler
            else:
                # 没有系统代理，返回空字典强制直连
                self.logger.info("🌐 代理配置：启用代理但未检测到系统代理，强制直连")
                return {}
        except Exception as e:
            self.logger.info(f"🌐 代理配置：获取系统代理失败 {str(e)}，强制直连")
            # 🔥 修复：获取失败时也返回{}而不是None，避免使用环境变量代理
            return {}
    
    def extract_real_email(self, user_id: str, access_token: str) -> Tuple[bool, str, Optional[str]]:
        """
        提取真实邮箱 - 优先使用API方式，备用Dashboard方式
        
        Args:
            user_id: 用户ID
            access_token: 访问令牌
            
        Returns:
            Tuple[bool, str, Optional[str]]: (是否成功, 消息, 真实邮箱)
        """
        self.logger.info(f"开始提取真实邮箱: {user_id}")
        
        # 🥇 方法1：优先使用API获取用户信息（最快最可靠）
        success, email = self._extract_email_via_api(user_id, access_token)
        if success and email:
            self.logger.info(f"✅ API方式成功获取邮箱: {email}")
            return True, "通过API成功获取真实邮箱", email
        
        # 🥈 方法2：如果API失败，回退到Dashboard浏览器方式
        if DRISSION_AVAILABLE:
            self.logger.info("⚠️ API方式失败，尝试Dashboard浏览器方式...")
            return self._extract_email_via_dashboard(user_id, access_token)
        else:
            return False, "API获取失败且DrissionPage未安装，无法提取真实邮箱", None
    
    def _extract_email_via_api(self, user_id: str, access_token: str) -> Tuple[bool, Optional[str]]:
        """通过API获取真实邮箱 - 最优方法，支持JWT格式"""
        try:
            # 🔥 使用CommonUtils通用方法获取headers
            from ...utils.common_utils import CommonUtils
            headers = CommonUtils.get_api_headers(user_id, access_token)
            
            url = "https://cursor.com/api/auth/me"
            self.logger.debug(f"调用API获取用户信息: {url}")
            
            # 根据配置决定是否使用代理
            proxies = self._get_request_proxies()
            
            response = requests.get(url, headers=headers, timeout=15, proxies=proxies)
            
            if response.status_code == 200:
                user_data = response.json()
                email = user_data.get('email')
                
                if email and '@' in email:
                    self.logger.info(f"API成功返回邮箱: {email}")
                    return True, email
                else:
                    self.logger.warning(f"API返回数据中无有效邮箱: {user_data}")
                    return False, None
            else:
                self.logger.error(f"API请求失败，状态码: {response.status_code}, 响应: {response.text[:200]}")
                return False, None
                
        except Exception as e:
            self.logger.error(f"API获取邮箱失败: {str(e)}")
            return False, None
    
    def _extract_email_via_dashboard(self, user_id: str, access_token: str) -> Tuple[bool, str, Optional[str]]:
        """通过Dashboard浏览器方式获取邮箱（备用方案）"""
        page = None
        try:
            self.logger.info("使用Dashboard浏览器方式提取邮箱...")
            
            # 创建浏览器配置
            co = ChromiumOptions()
            co.headless(True)  # 无头模式
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-extensions')
            co.set_argument('--disable-web-security')
            co.set_argument('--allow-running-insecure-content')
            co.auto_port()  # 自动分配端口
            
            # 根据配置决定是否使用代理
            proxies = self._get_request_proxies()
            if proxies == {}:
                # 明确禁用代理 - 使用Chrome标准参数
                co.set_argument('--no-proxy-server')
            elif proxies:
                # 使用系统代理
                if 'http' in proxies:
                    co.set_argument(f'--proxy-server={proxies["http"]}')
                elif 'https' in proxies:
                    co.set_argument(f'--proxy-server={proxies["https"]}')
            
            # 创建页面
            page = ChromiumPage(addr_or_opts=co)
            
            # 先导航到cursor.com设置Cookie
            self.logger.info("导航到cursor.com...")
            page.get("https://cursor.com")
            
            # 设置认证Cookie
            if "%3A%3A" in user_id:
                cookie_value = user_id
            else:
                cookie_value = f"{user_id}%3A%3A{access_token}"
            
            cookie = {
                'name': 'WorkosCursorSessionToken',
                'value': cookie_value,
                'domain': '.cursor.com',
                'path': '/',
                'secure': True,
                'httpOnly': False,
                'sameSite': 'Lax'
            }
            
            page.set.cookies(cookie)
            self.logger.info(f"Cookie设置完成: {cookie_value[:50]}...")
            
            # 导航到Dashboard
            page.get("https://cursor.com/dashboard")
            time.sleep(3)
            
            # 等待页面完全加载
            max_wait = 10
            for i in range(max_wait):
                if "Your Analytics" in page.html or "@" in page.html:
                    self.logger.info(f"页面加载完成，第{i+1}次检查发现用户信息")
                    break
                time.sleep(1)
            
            # 提取邮箱信息
            email = self._extract_email_from_page(page)
            
            if email:
                self.logger.info(f"Dashboard方式成功提取邮箱: {email}")
                return True, "Dashboard方式成功提取邮箱", email
            else:
                self.logger.warning("Dashboard方式未能从页面中提取到邮箱")
                return False, "Dashboard方式未能提取到邮箱", None
                
        except Exception as e:
            error_msg = f"Dashboard方式提取邮箱出错: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg, None
        finally:
            if page:
                try:
                    page.quit()
                except:
                    pass
    
    def _extract_email_from_page(self, page) -> Optional[str]:
        """从页面中提取邮箱"""
        try:
            # 方法1: 使用正则表达式搜索页面文本
            page_text = page.html
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            emails = re.findall(email_pattern, page_text)
            
            # 过滤掉明显的公司邮箱
            exclude_domains = ['cursor.com', 'anysphere.inc', 'example.com']
            real_emails = []
            
            for email in emails:
                domain = email.split('@')[1].lower()
                if domain not in exclude_domains:
                    real_emails.append(email)
            
            if real_emails:
                # 返回第一个真实邮箱
                return real_emails[0]
            
            # 方法2: 尝试查找特定的邮箱显示元素
            try:
                # 查找可能包含用户邮箱的元素
                email_selectors = [
                    'p[class*="truncate"]',  # 根据之前的发现，邮箱在truncate类的p元素中
                    '[class*="font-medium"]',
                    '[class*="text-sm"]',
                    'p:contains("@")',
                    'div:contains("@")',
                    'span:contains("@")'
                ]
                
                for selector in email_selectors:
                    try:
                        elements = page.eles(selector, timeout=1)
                        for element in elements:
                            text = element.text.strip()
                            if '@' in text and '.' in text:
                                # 验证是否是有效邮箱格式
                                if re.match(email_pattern, text):
                                    domain = text.split('@')[1].lower()
                                    if domain not in exclude_domains:
                                        self.logger.info(f"从元素 {selector} 中找到邮箱: {text}")
                                        return text
                    except:
                        continue
                        
            except Exception as e:
                self.logger.warning(f"查找邮箱元素时出错: {str(e)}")
            
            return None
            
        except Exception as e:
            self.logger.error(f"提取邮箱失败: {str(e)}")
            return None
    
    def open_dashboard_with_auth(self, user_id: str, access_token: str, email: str = None) -> bool:
        """
        使用认证信息打开Dashboard
        
        Args:
            user_id: 用户ID
            access_token: 访问令牌
            email: 邮箱（用于日志）
            
        Returns:
            bool: 是否成功打开
        """
        # 方案1：直接使用系统默认浏览器
        try:
            self.logger.info(f"为账号 {email or user_id} 打开Dashboard（使用默认浏览器）")
            
            dashboard_url = "https://cursor.com/dashboard"
            
            # 尝试通过URL参数传递token（虽然可能不会被接受）
            import webbrowser
            webbrowser.open(dashboard_url)
            
            self.logger.info("已在默认浏览器中打开Dashboard页面")
            self.logger.info("提示：由于安全限制，您可能需要手动登录")
            
            # 将token复制到剪贴板，方便用户使用
            try:
                from ...utils.common_utils import CommonUtils
                if "%3A%3A" in user_id:
                    token = user_id
                else:
                    token = f"{user_id}%3A%3A{access_token}"
                success = CommonUtils.copy_to_clipboard(token)
                if success:
                    self.logger.info("已将Token复制到剪贴板，方便登录使用")
            except Exception as e:
                self.logger.debug(f"复制Token失败: {str(e)}")
            
            return True
            
        except Exception as e:
            # 🔥 修复：删除第二次尝试打开的逻辑，避免关闭浏览器后继续尝试
            self.logger.error(f"打开浏览器失败: {str(e)}")
            return False
