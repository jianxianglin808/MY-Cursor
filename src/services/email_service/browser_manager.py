#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
浏览器管理器 - 极简版本
借鉴cursor-ideal项目的最佳实践：
1. 完全依赖DrissionPage内置指纹能力
2. 极简化配置，避免独特指纹
3. 核心反检测参数
"""

import os
import sys
import logging
import platform
from typing import Optional, Callable, Tuple

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# DrissionPage 动态导入
DRISSION_AVAILABLE = None

def _ensure_drission_imported():
    """确保DrissionPage已导入"""
    global DRISSION_AVAILABLE
    if DRISSION_AVAILABLE is None:
        try:
            import DrissionPage
            from DrissionPage import ChromiumPage, ChromiumOptions
            DRISSION_AVAILABLE = True
            globals()['ChromiumPage'] = ChromiumPage
            globals()['ChromiumOptions'] = ChromiumOptions
        except ImportError:
            DRISSION_AVAILABLE = False
            raise ImportError("❌ 缺少DrissionPage依赖，请安装：pip install DrissionPage")
    elif not DRISSION_AVAILABLE:
        raise ImportError("❌ DrissionPage不可用")


class BrowserManager:
    """
    浏览器管理器 - 极简版本
    核心理念：保持配置极简，依赖DrissionPage内置反检测能力
    过度配置会产生独特指纹，更容易被检测
    """
    
    def __init__(self, account_config=None, log_callback: Optional[Callable[[str], None]] = None):
        """
        初始化浏览器管理器
        
        Args:
            account_config: 账号配置管理器
            log_callback: 日志回调函数
        """
        self.account_config = account_config
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        
    def create_browser_instance(self, headless_mode: bool = False) -> Tuple[object, object]:
        """
        创建配置好的浏览器实例
        
        Args:
            headless_mode: 是否启用无头模式（不推荐，会被检测）
            
        Returns:
            tuple: (browser, tab) 浏览器实例和标签页
        """
        import time
        start_time = time.time()
        
        _ensure_drission_imported()
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        co = ChromiumOptions()
        
        # 记录日志
        def log_info(message: str):
            self.logger.info(message)
            if self.log_callback:
                self.log_callback(message)
        
        # 1. 核心反检测配置（最重要！）
        self._apply_core_antidetection(co, log_info)
        
        # 2. 配置浏览器路径
        self._configure_browser_path(co, log_info)
        
        # 3. 配置无头模式（根据参数）
        if headless_mode:
            # 获取UserAgent并替换HeadlessChrome标识
            user_agent = self._get_user_agent_for_headless()
            if not user_agent:
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            # 剔除HeadlessChrome标识（关键！）
            user_agent = user_agent.replace("HeadlessChrome", "Chrome")
            co.set_user_agent(user_agent)
            co.headless(True)
        else:
            co.headless(False)
        
        # 4. 自动端口（避免冲突）
        co.auto_port()
        
        # 注意：无痕模式会自动创建临时文件夹，不需要额外设置user_data_path
        # 设置user_data_path可能会与auto_port()冲突导致地址解析错误
        
        # 5. 默认无痕模式
        self._configure_incognito(co, log_info)
        
        # 7. 代理配置
        self._configure_proxy(co, log_info)
        
        # 创建浏览器（添加重试机制解决并发端口冲突）
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.warning(f"🔄 重试创建浏览器 (第{attempt + 1}次尝试)...")
                    time.sleep(retry_delay)
                    # 重新分配端口避免冲突
                    co.auto_port()
                
                self.logger.debug("🚀 开始创建浏览器实例...")
                browser = ChromiumPage(co)
                
                create_elapsed = time.time() - start_time
                self.logger.debug(f"✅ 浏览器实例创建完成 (用时{create_elapsed:.1f}秒)")
                
                tab = browser.get_tab(1)
                
                # 🔥 隐藏 navigator.webdriver（无头和有头都需要）
                self._hide_webdriver(tab)
                
                total_elapsed = time.time() - start_time
                if attempt > 0:
                    self.logger.info(f"✅ 浏览器就绪 (重试{attempt}次后成功，耗时{total_elapsed:.1f}秒)")
                else:
                    self.logger.info(f"✅ 浏览器就绪 (总耗时{total_elapsed:.1f}秒)")
                
                return browser, tab
                
            except Exception as e:
                error_msg = str(e)
                is_connection_error = "浏览器连接失败" in error_msg or "BrowserConnectError" in error_msg
                
                if is_connection_error and attempt < max_retries - 1:
                    self.logger.warning(f"⚠️ 浏览器连接失败，准备重试 ({attempt + 1}/{max_retries})")
                    continue
                else:
                    self.logger.error(f"创建浏览器失败: {error_msg}")
                    import traceback
                    if self.logger.level <= logging.DEBUG:
                        self.logger.error(f"错误详情: {traceback.format_exc()}")
                    raise
    
    def _apply_core_antidetection(self, co: 'ChromiumOptions', log_info: Callable):
        """
        应用核心反检测参数
        这是cursor-ideal项目的核心优势
        """
        # 🔥 最关键的参数：移除 enable-automation 开关
        # 这是最明显的自动化标志
        co.set_argument('--exclude-switches=enable-automation')
        
        # 辅助参数：让浏览器行为更像普通用户
        co.set_argument('--no-first-run')
        co.set_argument('--no-default-browser-check')
        
        # 🚀 加速启动：禁用不必要的后台服务
        co.set_argument("--disable-background-networking")
        co.set_argument("--disable-component-update")
        co.set_argument("--disable-default-apps")
        co.set_argument("--disable-component-extensions-with-background-pages")
        co.set_argument("--disable-extensions")  # 禁用扩展加速启动
        co.set_argument("--disable-sync")  # 禁用同步加速启动
        co.set_argument("--disable-background-timer-throttling")  # 加速渲染
    
    def _get_user_agent_for_headless(self) -> Optional[str]:
        """获取UserAgent（无头模式专用）"""
        try:
            import time
            from DrissionPage import ChromiumPage, ChromiumOptions
            
            # 创建极简临时浏览器获取UA
            temp_co = ChromiumOptions()
            temp_co.headless(True)
            temp_co.auto_port()
            temp_co.set_argument('--disable-extensions')
            temp_co.set_argument('--disable-sync')
            
            temp_browser = ChromiumPage(temp_co)
            user_agent = temp_browser.run_js("return navigator.userAgent")
            temp_browser.quit()
            
            return user_agent
        except Exception as e:
            self.logger.debug(f"获取user agent失败: {str(e)}")
            return None
    
    def _configure_browser_path(self, co: 'ChromiumOptions', log_info: Callable):
        """配置浏览器路径"""
        if self.account_config:
            browser_path = self.account_config.config_data.get('browser', {}).get('path', '')
            if browser_path and os.path.exists(browser_path):
                co.set_browser_path(browser_path)
                log_info("🌐 使用配置的浏览器")
            else:
                log_info("🌐 使用系统默认浏览器")
    
    def _configure_user_data_dir(self, co, log_info: Callable):
        """配置独立的用户数据文件夹（批量注册时避免冲突）"""
        # 注意：无痕模式下不需要设置user_data_path，会自动使用临时文件夹
        # 只在非无痕模式下设置
        try:
            import tempfile
            import uuid
            
            # 创建临时的用户数据文件夹，使用UUID确保唯一性
            temp_dir = tempfile.gettempdir()
            user_data_dir = os.path.join(temp_dir, f"xc_cursor_chrome_{uuid.uuid4().hex[:8]}")
            
            # 设置用户数据文件夹
            co.set_user_data_path(user_data_dir)
            self.logger.debug(f"📁 使用独立用户数据文件夹: {user_data_dir}")
        except Exception as e:
            self.logger.warning(f"设置用户数据文件夹失败，将使用默认: {str(e)}")
    
    def _configure_incognito(self, co: 'ChromiumOptions', log_info: Callable):
        """配置无痕模式（默认开启）"""
        browser_path = co.browser_path
        
        # 根据浏览器类型使用不同的无痕参数
        if sys.platform == "win32" and browser_path and "msedge.exe" in browser_path.lower():
            co.set_argument('--inprivate')
        else:
            co.set_argument('--incognito')

    
    def _hide_webdriver(self, tab):
        """
        隐藏 navigator.webdriver 属性
        这是最关键的自动化检测点，必须隐藏
        """
        try:
            # 注入JavaScript代码删除 navigator.webdriver
            js_code = """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
            tab.run_js(js_code)
            
            # 验证是否隐藏成功
            webdriver_value = tab.run_js("return navigator.webdriver;")
            if webdriver_value is None or webdriver_value == 'undefined':
                self.logger.debug("✅ navigator.webdriver 已隐藏")
            else:
                self.logger.warning(f"⚠️ navigator.webdriver 隐藏可能失败，当前值: {webdriver_value}")
                
        except Exception as e:
            self.logger.warning(f"⚠️ 隐藏 navigator.webdriver 失败: {str(e)}")
    
    def _configure_proxy(self, co: 'ChromiumOptions', log_info: Callable):
        """配置网络代理"""
        if self.account_config:
            try:
                use_proxy = self.account_config.get_use_proxy()
                if use_proxy:
                    # 启用代理 - 使用系统代理设置
                    try:
                        import urllib.request
                        proxies = urllib.request.getproxies()
                        if proxies:
                            if 'http' in proxies:
                                co.set_argument(f'--proxy-server={proxies["http"]}')
                                log_info(f"🌐 启用HTTP代理")
                            elif 'https' in proxies:
                                co.set_argument(f'--proxy-server={proxies["https"]}')
                                log_info(f"🌐 启用HTTPS代理")
                            else:
                                log_info("🌐 代理已启用但未检测到系统代理")
                        else:
                            log_info("🌐 代理已启用但未检测到系统代理")
                    except Exception as e:
                        log_info(f"⚠️ 代理设置失败: {str(e)}")
                else:
                    # 禁用代理（同时清除环境变量）
                    co.set_argument('--no-proxy-server')
                    # 清除可能存在的代理环境变量
                    import os
                    for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
                        if proxy_var in os.environ:
                            del os.environ[proxy_var]
                    log_info("🌐 已禁用代理（包括环境变量）")
            except Exception as e:
                log_info(f"⚠️ 读取代理配置失败: {str(e)}")