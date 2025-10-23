#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Session Token转换器 - 集成到项目中的转换逻辑
使用纯API调用方案，快速、稳定、资源消耗低
"""

import base64
import hashlib
import logging
import secrets
import time
import uuid
import requests
from typing import Optional, Dict, Any, Tuple


class SessionTokenConverter:
    """Session Token转换器 - 将web类型token转换为session类型"""
    
    def __init__(self, config=None):
        self.logger = logging.getLogger(__name__)
        self.config = config
    
    def _get_request_proxies(self) -> Optional[dict]:
        """根据配置决定是否使用代理"""
        if self.config and hasattr(self.config, 'get_use_proxy'):
            if not self.config.get_use_proxy():
                # 明确指定不使用代理
                return {}
        
        # 使用系统代理
        try:
            import urllib.request
            proxy_handler = urllib.request.getproxies()
            if proxy_handler:
                return proxy_handler
        except Exception as e:
            self.logger.warning(f"获取系统代理失败: {str(e)}")
        
        return None
    
    def _generate_pkce_challenge(self) -> Tuple[str, str]:
        """生成PKCE challenge"""
        code_verifier = secrets.token_urlsafe(32)
        sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(sha256_hash).rstrip(b'=').decode('utf-8')
        return code_verifier, code_challenge
    
    def _convert_via_api(self, workos_token: str) -> Optional[Dict[str, Any]]:
        """
        纯API方式转换token（参考获取asscessToken.py）
        不使用浏览器，直接调用Cursor官方API
        """
        try:
            # 生成PKCE参数
            request_uuid = str(uuid.uuid4())
            code_verifier, code_challenge = self._generate_pkce_challenge()
            
            # 调用登录回调API
            self.logger.info("调用 loginDeepCallbackControl API...")
            callback_url = "https://cursor.com/api/auth/loginDeepCallbackControl"
            
            callback_data = {
                "uuid": request_uuid,
                "challenge": code_challenge
            }
            
            # Cookie 直接使用完整的 workos_token
            callback_headers = {
                "Content-Type": "application/json",
                "Cookie": f"WorkosCursorSessionToken={workos_token}"
            }
            
            # 获取代理配置
            proxies = self._get_request_proxies()
            
            callback_response = requests.post(
                callback_url,
                json=callback_data,
                headers=callback_headers,
                timeout=10,
                proxies=proxies
            )
            
            self.logger.info(f"loginDeepCallbackControl 响应状态: {callback_response.status_code}")
            
            if callback_response.status_code != 200:
                self.logger.error(f"loginDeepCallbackControl 失败: {callback_response.status_code}")
                return None
            
            self.logger.info("✅ loginDeepCallbackControl 调用成功")
            
            # 轮询获取token
            self.logger.info("开始轮询获取 access_token...")
            result = self._poll_for_session_token(request_uuid, code_verifier, max_attempts=40)
            
            if result and result.get('access_token'):
                access_token = result['access_token']
                refresh_token = result.get('refresh_token', '')
                
                self.logger.info("✅ Token 转换成功")
                self.logger.info(f"📋 Access Token 长度: {len(access_token)}")
                self.logger.info(f"📋 Refresh Token 长度: {len(refresh_token)}")
                
                return result
            else:
                self.logger.error("❌ 轮询超时或未获取到 token")
                return None
            
        except Exception as e:
            self.logger.error(f"API 调用失败: {str(e)}")
            return None
    
    def _poll_for_session_token(self, request_uuid: str, code_verifier: str, max_attempts: int = 40) -> Optional[Dict[str, Any]]:
        """
        轮询获取session token
        默认40次*0.5秒=20秒（API方式）
        """
        polling_url = "https://api2.cursor.sh/auth/poll"
        
        # 记录非 404 的响应次数
        non_404_count = 0
        
        proxies = self._get_request_proxies()
        
        for attempt in range(max_attempts):
            try:
                # 动态生成traceparent
                trace_id = secrets.token_hex(16)
                parent_id = secrets.token_hex(8)
                traceparent = f"00-{trace_id}-{parent_id}-00"
                
                headers = {
                    "Host": "api2.cursor.sh",
                    "Origin": "vscode-file://vscode-app",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Cursor/1.2.2 Chrome/132.0.6834.210 Electron/34.5.1 Safari/537.36",
                    "accept": "*/*",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-site": "cross-site",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-dest": "empty",
                    "accept-language": "zh-CN",
                    "traceparent": traceparent,
                    "x-ghost-mode": "true",
                    "x-new-onboarding-completed": "false",
                }
                
                params = {
                    "uuid": request_uuid,
                    "verifier": code_verifier
                }
                
                response = requests.get(polling_url, headers=headers, params=params, timeout=10, proxies=proxies)
                
                if response.status_code == 200:
                    data = response.json()
                    if "accessToken" in data and "refreshToken" in data:
                        self.logger.info(f"✅ 轮询成功！第 {attempt + 1} 次尝试")
                        return {
                            "access_token": data["accessToken"],
                            "refresh_token": data["refreshToken"],
                            "user_id": data.get("userId", ""),
                            "token_type": "session"
                        }
                    else:
                        self.logger.warning(f"⚠️ 轮询第 {attempt + 1} 次: 200 但缺少 token 字段, 响应: {data}")
                elif response.status_code == 404:
                    # 404 是正常的（表示还没准备好）
                    if attempt % 10 == 0:  # 每 10 次输出一次
                        self.logger.debug(f"轮询第 {attempt + 1} 次: 等待中（404）...")
                else:
                    non_404_count += 1
                    self.logger.warning(
                        f"⚠️ 轮询第 {attempt + 1} 次: 状态码 {response.status_code}, 内容: {response.text[:200]}")
                
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.warning(f"轮询第 {attempt + 1} 次异常: {e}")
                time.sleep(0.5)
        
        self.logger.error(f"❌ 轮询超时！尝试了 {max_attempts} 次，非404响应: {non_404_count} 次")
        return None
    
    def batch_convert_with_browser_reuse(self, accounts: list, config=None, progress_callback=None, stop_flag=None) -> Dict[str, Any]:
        """
        批量转换方法 - 使用纯API方式转换
        
        Args:
            accounts: 账号列表
            config: 配置对象
            progress_callback: 进度回调 (current, total, email, status)
            stop_flag: 停止标志函数
            
        Returns:
            Dict: 转换结果统计
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor
        
        results = {'total': 0, 'converted': 0, 'failed': 0, 'skipped': 0, 'failed_accounts': []}
        results_lock = threading.Lock()
        
        # 筛选需要转换的账号
        pending_accounts = []
        for account in accounts:
            token = account.get('access_token', '')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            # 判断是否需要转换
            token_len = len(token) if token else 0
            
            if not token:
                results['skipped'] += 1
            elif token_len in [413, 424]:
                results['skipped'] += 1
            elif workos_token:
                needs_conversion = True
                pending_accounts.append(account)
            else:
                results['skipped'] += 1
        
        self.logger.info(f"📊 扫描完成: 总数{len(accounts)}, 需转换{len(pending_accounts)}, 已有效{results['skipped']}")
        
        if not pending_accounts:
            return results
        
        results['total'] = len(pending_accounts)
        
        # 使用线程池并发处理（默认20个并发）
        max_workers = min(20, len(pending_accounts))
        
        self.logger.info(f"🚀 启动 {max_workers} 个并发线程，使用API方式转换")
        
        processed_count = {'value': 0}
        processed_lock = threading.Lock()
        
        def worker_convert_account(account):
            """工作线程 - 使用纯API方式转换"""
            if stop_flag and hasattr(stop_flag, '__call__') and stop_flag():
                return
            
            email = account.get('email', '未知')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            try:
                # 验证token
                if not workos_token:
                    self.logger.error(f"❌ [{email}] 缺少WorkosCursorSessionToken")
                    with results_lock:
                        results['failed'] += 1
                        results['failed_accounts'].append(email)
                    with processed_lock:
                        processed_count['value'] += 1
                        current = processed_count['value']
                    if progress_callback:
                        progress_callback(current, len(pending_accounts), email, "跳过(无token)")
                    return
                
                if '::' not in workos_token and '%3A%3A' not in workos_token:
                    self.logger.error(f"❌ [{email}] WorkosCursorSessionToken格式错误")
                    with results_lock:
                        results['failed'] += 1
                        results['failed_accounts'].append(email)
                    with processed_lock:
                        processed_count['value'] += 1
                        current = processed_count['value']
                    if progress_callback:
                        progress_callback(current, len(pending_accounts), email, "格式错误")
                    return
                
                # 使用纯API方式转换
                self.logger.info(f"🔄 [{email}] 开始API转换...")
                result = self._convert_via_api(workos_token)
                
                if result and result.get('access_token'):
                    # API转换成功
                    access_token = result['access_token']
                    refresh_token = result.get('refresh_token', '')
                    
                    account['access_token'] = access_token
                    account['refresh_token'] = refresh_token
                    account['token_type'] = 'session'
                    
                    # 立即保存
                    saved = False
                    if self.config:
                        try:
                            saved = self._save_single_account(account, self.config)
                        except Exception as save_error:
                            self.logger.error(f"❌ [{email}] 保存失败: {str(save_error)}")
                    
                    with results_lock:
                        results['converted'] += 1
                    
                    with processed_lock:
                        processed_count['value'] += 1
                        current = processed_count['value']
                    
                    if progress_callback:
                        progress_callback(current, len(pending_accounts), email, "成功(API)")
                    
                    self.logger.info(f"✅ [{email}] API转换成功 (token长度:{len(access_token)})")
                else:
                    # API失败，记录失败
                    self.logger.warning(f"⚠️ [{email}] API转换失败")
                    
                    with results_lock:
                        results['failed'] += 1
                        results['failed_accounts'].append(email)
                    
                    with processed_lock:
                        processed_count['value'] += 1
                        current = processed_count['value']
                    
                    if progress_callback:
                        progress_callback(current, len(pending_accounts), email, "失败")
                    
            except Exception as e:
                self.logger.error(f"❌ [{email}] 转换异常: {str(e)}")
                with results_lock:
                    results['failed'] += 1
                    results['failed_accounts'].append(email)
                with processed_lock:
                    processed_count['value'] += 1
        
        # 使用线程池并发执行
        executor = ThreadPoolExecutor(max_workers=max_workers)
        
        try:
            futures = [executor.submit(worker_convert_account, account) for account in pending_accounts]
            
            # 等待所有任务完成
            for future in futures:
                if stop_flag and hasattr(stop_flag, '__call__') and stop_flag():
                    self.logger.warning("🛑 收到停止信号，取消剩余任务...")
                    break
                
                try:
                    future.result(timeout=30)  # 每个任务最多30秒
                except Exception as e:
                    self.logger.error(f"任务执行异常: {str(e)}")
        
        finally:
            executor.shutdown(wait=False)
        
        self.logger.info(f"🎉 任务结束: 成功{results['converted']}个, 失败{results['failed']}个, 跳过{results['skipped']}个")
        
        return results
    
    def _save_single_account(self, account: dict, config):
        """立即保存单个转换成功的账号"""
        try:
            token = account.get('access_token', '')
            token_type = account.get('token_type', '')
            email = account.get('email', '')
            user_id = account.get('user_id', '')
            
            # 验证数据有效性
            if not token or token_type != 'session':
                return False
            
            # 加载所有账号
            all_accounts = config.load_accounts()
            
            # 查找并更新对应账号
            for i, acc in enumerate(all_accounts):
                if (email and acc.get('email') == email) or (user_id and acc.get('user_id') == user_id):
                    all_accounts[i].update({
                        'access_token': account.get('access_token'),
                        'refresh_token': account.get('refresh_token'),
                        'token_type': 'session',
                        'WorkosCursorSessionToken': account.get('WorkosCursorSessionToken')
                    })
                    # 立即保存
                    config.save_accounts(all_accounts)
                    self.logger.debug(f"✅ 立即保存账号: {email} (token长度:{len(token)})")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"立即保存账号失败: {str(e)}")
            return False
    
    def convert_workos_to_session_jwt(self, workos_token: str, user_id: str = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        单个账号转换 - 使用纯API方式
        
        Args:
            workos_token: 完整的WorkosCursorSessionToken
            user_id: 用户ID（可选，未使用）
            
        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (是否成功, access_token, refresh_token)
        """
        try:
            self.logger.info("🔄 开始Token转换流程（API方式）...")
            
            # 直接调用API转换
            result = self._convert_via_api(workos_token)
            
            if result and result.get('access_token'):
                access_token = result['access_token']
                refresh_token = result.get('refresh_token', '')
                self.logger.info(f"🎉 转换成功！Token长度: {len(access_token)}")
                return True, access_token, refresh_token
            else:
                self.logger.error("❌ API转换失败")
                return False, None, None
                
        except Exception as e:
            self.logger.error(f"❌ 转换失败: {str(e)}")
            return False, None, None
    
    def batch_convert_accounts(self, accounts: list, config=None, progress_callback=None, stop_flag=None) -> Dict[str, Any]:
        """
        统一的批量转换方法 - 使用纯API方式
        
        Args:
            accounts: 账号列表
            config: 配置对象
            progress_callback: 进度回调 (current, total, email, status)
            stop_flag: 停止标志函数
            
        Returns:
            Dict: 转换结果统计
        """
        return self.batch_convert_with_browser_reuse(
            accounts=accounts,
            config=config,
            progress_callback=progress_callback,
            stop_flag=stop_flag
        )
