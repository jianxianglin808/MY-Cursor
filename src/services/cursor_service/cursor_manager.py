#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cursor管理器 - 处理Cursor数据库操作和账号切换
"""

import sqlite3
import logging
import os
import requests
import time
import uuid
import hashlib
import shutil
import sys
import subprocess
import psutil
import json
import base64
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from ...utils.common_utils import CommonUtils
from .cursor_backup_manager import CursorBackupManager

class CursorManager:
    """Cursor管理器，处理账号切换和数据库操作"""
    
    def __init__(self, config):
        """初始化Cursor管理器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.db_path = config.get('cursor', 'db_path')
        
        # 获取Cursor用户数据路径（使用配置中的路径）
        cursor_data_dir = config.get_cursor_data_dir()
        self.user_data_path = os.path.join(cursor_data_dir, "User")
        
        # 🔥 新增：账号机器码配置目录
        self.account_machine_id_dir = os.path.join(config.config_dir, "account_machine_ids")
        
        # 初始化备份管理器
        self.backup_manager = CursorBackupManager(config)
        
        # 🔥 性能优化：创建XCCursorManager单例，避免重复初始化
        self._xc_manager = None


    def _get_xc_manager(self):
        """获取XCCursorManager单例"""
        if self._xc_manager is None:
            from .xc_cursor_manage import XCCursorManager
            self._xc_manager = XCCursorManager(self.config)
        return self._xc_manager

    def get_current_account(self):
        """获取当前账号 - 使用XCCursorManager单例"""
        try:
            xc_manager = self._get_xc_manager()
            account_info = xc_manager.get_account_info()
            
            if account_info and account_info.get('is_logged_in'):
                return {
                    'email': account_info.get('email'),
                    'access_token': account_info.get('token'),
                    'user_id': account_info.get('user_id'),
                    'status': account_info.get('status'),
                    'is_logged_in': account_info.get('is_logged_in')
                }
            
            # 检查完整性
            if not all([account_info.get('email'), account_info.get('token'), account_info.get('user_id')]):
                missing = []
                if not account_info.get('email'):
                    missing.append('email')
                if not account_info.get('token'):
                    missing.append('token')
                if not account_info.get('user_id'):
                    missing.append('userId')
                self.logger.warning(f"❌ 账号信息不完整，缺少字段: {missing}")
                return None
            
            return account_info
        except Exception as e:
            self.logger.error(f"获取当前账号失败: {str(e)}")
            return None
    
    
    def switch_account(self, account: Dict) -> Tuple[bool, str]:
        """
        切换到指定账号 - 改进版，支持WorkosCursorSessionToken，增加验证步骤
        
        Args:
            account: 账号信息字典
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            self.logger.info("🎯" + "="*50)
            self.logger.info("🎯 开始账号切换流程")
            self.logger.info("🎯" + "="*50)
            
            if not os.path.exists(self.db_path):
                error_msg = f"Cursor数据库文件不存在: {self.db_path}"
                self.logger.error(f"❌ {error_msg}")
                return False, error_msg
            
            # 获取账号信息
            email = account.get('email')
            access_token = account.get('access_token')
            refresh_token = account.get('refresh_token')
            user_id = account.get('user_id')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            self.logger.info(f"📧 目标邮箱: {email}")
            # 认证信息日志已简化
            
            # 🔥 修复：删除错误的拆分逻辑，保留基本的user_id提取
            if not user_id and workos_token and workos_token.startswith('user_'):
                # 只提取user_id，不拆分获取token
                if '::' in workos_token or '%3A%3A' in workos_token:
                    separator = '::' if '::' in workos_token else '%3A%3A'
                    parts = workos_token.split(separator, 1)
                    if len(parts) >= 1:
                        user_id = parts[0].strip()
                        self.logger.info(f"从WorkosCursorSessionToken提取user_id: {user_id}")

            # 最终确保有refresh_token（避免重复逻辑）
            if not refresh_token and access_token:
                refresh_token = access_token
            
            # 验证必要信息
            if not all([email, access_token, user_id]):
                missing = []
                if not email:
                    missing.append('email')
                if not access_token:
                    missing.append('access_token')  
                if not user_id:
                    missing.append('user_id')
                return False, f"账号信息不完整，缺少: {', '.join(missing)}"
            
            # 使用新的XCCursorManager处理账号切换
            xc_manager = self._get_xc_manager()
            success, message = xc_manager.apply_account(email, access_token, refresh_token, user_id)
            
            if success:
                self.logger.info("🎯 数据库更新成功，开始验证切换结果...")
                
                # 🔥 新增：验证切换后的认证状态
                verification_success, verification_message = self._verify_account_switch(account)
                
                if verification_success:
                    self.logger.info(f"✅ 成功切换到账号: {email}，认证状态已验证")
                    self.logger.info("🎯" + "="*50)
                    self.logger.info("🎯 账号切换流程完成")
                    self.logger.info("🎯" + "="*50)
                    return True, f"成功切换到账号: {email}"
                else:
                    self.logger.warning(f"⚠️ 账号切换完成但验证失败: {verification_message}")
                    self.logger.info("🎯" + "="*50)
                    self.logger.info("🎯 账号切换流程完成（验证失败）")
                    self.logger.info("🎯" + "="*50)
                    return True, f"账号切换完成: {email}（验证失败: {verification_message}）"
            else:
                self.logger.error(f"❌ 切换账号失败: {message}")
                return False, f"切换账号失败: {message}"
                
        except Exception as e:
            error_msg = f"切换账号时出错: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def _verify_account_switch(self, account: Dict) -> Tuple[bool, str]:
        """
        验证账号切换是否生效 - 简化版本
        
        Args:
            account: 切换后的账号信息
            
        Returns:
            Tuple[bool, str]: (验证是否成功, 验证消息)
        """
        try:
            self.logger.info("🔍 验证账号切换是否生效...")
            
            # 验证数据库中的认证信息
            current_account = self.get_current_account()
            if not current_account:
                return False, "无法从数据库获取当前账号信息"
            
            expected_email = account.get('email')
            expected_user_id = account.get('user_id')
            
            current_email = current_account.get('email')
            current_user_id = current_account.get('user_id')
            
            # 验证邮箱
            if current_email != expected_email:
                return False, f"邮箱不匹配: 期望 {expected_email}, 实际 {current_email}"
            
            # 验证用户ID
            if current_user_id != expected_user_id:
                return False, f"用户ID不匹配: 期望 {expected_user_id}, 实际 {current_user_id}"
            
            # 验证登录状态
            if not current_account.get('is_logged_in', False):
                return False, "数据库中显示未登录状态"
            
            # 可选：验证API认证状态（快速检查）
            try:
                user_id = account.get('user_id')
                access_token = account.get('access_token')
                
                if user_id and access_token:
                    headers = CommonUtils.get_api_headers(user_id, access_token, account)
                    proxies = self._get_request_proxies()
                    response = self._requests_with_proxy_control(
                        'get',
                        "https://cursor.com/api/auth/stripe",
                        proxies,
                        headers=headers,
                        timeout=3
                    )
                    
                    if response.status_code == 200:
                        self.logger.info("✅ API认证验证通过")
                    elif response.status_code == 401:
                        self.logger.warning("⚠️ API认证失败，可能需要时间生效")
                        
            except Exception as api_error:
                pass
            
            self.logger.info("✅ 账号切换验证通过")
            return True, "认证状态验证成功"
            
        except Exception as e:
            error_msg = f"验证账号切换失败: {str(e)}"
            self.logger.warning(error_msg)
            return False, error_msg
    
    def _start_post_startup_token_refresh(self, account: Dict):
        """
        在Cursor启动后执行Token刷新 - 正确的时序
        在Cursor启动后几秒执行Token刷新操作
        
        Args:
            account: 账号信息
        """
        try:
            import threading
            
            def post_startup_refresh():
                """Cursor启动后的Token刷新"""
                email = account.get('email', '未知')
                self.logger.info(f"🔄 Cursor启动后Token刷新开始 (账号: {email})")
                
                # 🚀 优化：动态等待Cursor完全启动和稳定（关键时序）
                self._wait_for_cursor_stability(max_wait=8)  # 从15秒优化到最多8秒动态等待
                
                try:
                    # 检查认证状态
                    current_account = self.get_current_account()
                    if not current_account or not current_account.get('email'):
                        self.logger.warning("🔧 检测到认证字段丢失，执行Token刷新...")
                        
                        # 执行Token刷新
                        access_token = account.get('access_token')
                        refresh_token = account.get('refresh_token')
                        user_id = account.get('user_id')
                        
                        if all([email, access_token, user_id]):
                            conn = sqlite3.connect(self.db_path)
                            cursor = conn.cursor()
                        
                            token_updates = [
                                ("cursorAuth/cachedEmail", email),
                                ("cursorAuth/accessToken", access_token),  # 直接使用原始token
                                ("cursorAuth/refreshToken", refresh_token),  # 直接使用原始token
                                ("cursorAuth/onboardingDate", time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int(time.time() * 1000) % 1000:03d}Z"),
                            ]
                            
                            for key, value in token_updates:
                                cursor.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))
                                if cursor.rowcount == 0:
                                    cursor.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
                                # 启动后刷新日志已简化
                            
                            conn.commit()
                            conn.close()
                            
                            self.logger.info(f"✅ Cursor启动后Token刷新成功")
                        else:
                            self.logger.error("❌ 账号信息不完整，无法刷新")
                    else:
                        self.logger.info(f"🛡️ 认证状态正常 (账号: {email})")
                        
                except Exception as e:
                    self.logger.error(f"启动后Token刷新异常: {str(e)}")
                
                self.logger.info(f"🔄 Cursor启动后Token刷新结束 (账号: {email})")
            
            # 启动后台刷新线程
            refresh_thread = threading.Thread(target=post_startup_refresh, daemon=True)
            refresh_thread.start()
            
        except Exception as e:
            self.logger.warning(f"启动Cursor后Token刷新失败: {str(e)}")
        
    def get_all_accounts(self):
        """
        获取所有账号列表
        
        Returns:
            List[Dict]: 账号信息列表
        """
        try:
            # 这里应该从数据库或配置文件中获取账号列表
            # 目前返回空列表作为占位符
            # Note: 当前返回空列表，实际实现在其他模块中
            self.logger.info("获取所有账号列表")
            return []
            
        except Exception as e:
            self.logger.error(f"获取账号列表失败: {str(e)}")
            return []
    
    def refresh_account_subscription(self, account: Dict) -> bool:
        """
        刷新指定账号的订阅信息和模型使用量
        同时处理token转换：将WorkosCursorSessionToken转换为session类型JWT
        
        Args:
            account: 账号信息字典
            
        Returns:
            bool: 刷新是否成功
        """
        try:
            email = account.get('email', '未知')
            user_id = account.get('user_id', '')
            access_token = account.get('access_token', '')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            self.logger.info(f"刷新账号 {email} 的订阅信息和使用量")
            
            # 🔥 修复：正确提取完整认证信息
            # 尝试从WorkosCursorSessionToken中提取user_id和access_token
            if workos_token and (not user_id or not access_token):
                try:
                    # WorkosCursorSessionToken格式: user_xxxx::eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
                    if '::' in workos_token:
                        parts = workos_token.split('::', 1)
                        if len(parts) == 2:
                            extracted_user_id = parts[0].strip()
                            extracted_access_token = parts[1].strip()
                            
                            # 如果原来没有这些字段，使用提取的值
                            if not user_id and extracted_user_id:
                                user_id = extracted_user_id
                            if not access_token and extracted_access_token:
                                access_token = extracted_access_token
                            
                            self.logger.info(f"从WorkosCursorSessionToken提取认证信息成功")
                    elif '%3A%3A' in workos_token:
                        parts = workos_token.split('%3A%3A', 1)
                        if len(parts) == 2:
                            extracted_user_id = parts[0].strip()
                            extracted_access_token = parts[1].strip()
                            
                            if not user_id and extracted_user_id:
                                user_id = extracted_user_id
                            if not access_token and extracted_access_token:
                                access_token = extracted_access_token
                            
                            self.logger.info(f"从WorkosCursorSessionToken提取认证信息成功")
                except Exception as e:
                    self.logger.warning(f"从WorkosCursorSessionToken提取认证信息失败: {str(e)}")
            
            if not user_id or not access_token:
                self.logger.error(f"账号 {email} 缺少必要的认证信息，无法刷新")
                return False
            
            # 使用优化后的邮箱提取器：优先API方式，备用Dashboard方式
            email_updated = False  # 标记邮箱是否更新
            email_source = account.get('email_source', '')
            if (email.endswith('@cursor.local') or email == '未知' or 
                email_source in ['jwt_fallback', 'fallback_local', 'manual_required']):
                self.logger.info(f"检测到临时邮箱 {email}，尝试获取真实邮箱...")
                
                # 使用EmailExtractor（优先API，备用Dashboard）
                try:
                    from ..email_service.email_extractor import EmailExtractor
                    email_extractor = EmailExtractor(self.config)
                    success, message, real_email = email_extractor.extract_real_email(user_id, access_token)
                    
                    if success and real_email:
                        old_email = email
                        account["email"] = real_email
                        account["email_source"] = "api_dashboard_refresh"
                        account["needs_manual_email"] = False
                        email_updated = True  # 标记邮箱已更新
                        self.logger.info(f"✅ 成功更新邮箱: {old_email} → {real_email}")
                        
                        # 🔥 重要修复：更新邮箱后立即保存到配置文件
                        try:
                            accounts = self.config.load_accounts()
                            for i, acc in enumerate(accounts):
                                # 使用user_id作为唯一标识符匹配账号
                                if acc.get('user_id') == user_id:
                                    accounts[i] = account
                                    break
                            self.config.save_accounts(accounts)
                            self.logger.info(f"💾 邮箱更新已保存到配置文件: {old_email} → {real_email}")
                        except Exception as save_error:
                            self.logger.error(f"保存邮箱更新失败: {str(save_error)}")
                    else:
                        self.logger.warning(f"⚠️ 获取真实邮箱失败: {message}")
                        # 即使获取失败，也继续刷新订阅信息
                except Exception as e:
                    self.logger.error(f"EmailExtractor调用失败: {str(e)}")
                    # 继续刷新订阅信息
            
            # 🚀 使用新 API：获取使用量汇总（包含账单日期）
            usage_summary = self._get_usage_summary_from_api(user_id, access_token, account)
            
            # 从API获取订阅信息
            subscription_data = self._get_subscription_from_api(user_id, access_token, account)
            
            # 获取详细模型使用量（保留旧方法作为补充）
            usage_data = self._get_model_usage_from_api(user_id, access_token, account)
            
            # 🚀 可选：获取用户详细信息（补充profile数据）
            user_profile = None
            if email_updated or not account.get('user_profile'):  # 邮箱更新时或首次刷新时获取
                user_profile = self._get_user_profile_from_dashboard(user_id, access_token, account)
            
            if subscription_data and isinstance(subscription_data, dict):
                # 解析订阅信息
                membership_type = subscription_data.get("membershipType", "未知")
                individual_membership_type = subscription_data.get("individualMembershipType", membership_type)
                subscription_status = subscription_data.get("subscriptionStatus", "unknown")
                trial_days = subscription_data.get("daysRemainingOnTrial", 0)
                
                # 确定最终的会员类型
                final_membership_type = individual_membership_type or membership_type
                
                # 确定subscription_type（用于用量计算）
                subscription_type = final_membership_type
                if subscription_type and subscription_type.lower() in ['pro', 'cursor pro']:
                    subscription_type = 'Pro'
                elif trial_days > 0:
                    subscription_type = 'Trial'
                elif subscription_type and subscription_type.lower() in ['free', '免费']:
                    subscription_type = 'Free'
                else:
                    subscription_type = subscription_type or 'Unknown'
                
                # 更新账号信息
                account["membershipType"] = membership_type
                account["individualMembershipType"] = individual_membership_type
                account["subscriptionStatus"] = subscription_status
                account["subscription_type"] = subscription_type
                account["trialDaysRemaining"] = trial_days
                account["subscriptionData"] = subscription_data
                account["modelUsageData"] = usage_data
                account["subscriptionUpdatedAt"] = int(time.time())
                
                # 🚀 保存新 API 数据
                if usage_summary:
                    account["usage_summary"] = usage_summary
                    # 从 usage_summary 提取账单日期（用于 Pro 剩余天数计算）
                    if "billingCycleStart" in usage_summary:
                        account["billingCycleStart"] = usage_summary["billingCycleStart"]
                    if "billingCycleEnd" in usage_summary:
                        account["billingCycleEnd"] = usage_summary["billingCycleEnd"]
                
                if user_profile:
                    account["user_profile"] = user_profile
                    # 从 user_profile 补充用户信息
                    if "createdAt" in user_profile:
                        # 将 API 返回的 UTC 时间转换为本地时间（北京时间）
                        try:
                            import re
                            created_at_utc = user_profile["createdAt"]
                            # 去除毫秒部分
                            clean_time = re.sub(r'\.\d+Z?$', '', created_at_utc)
                            # 解析 UTC 时间
                            dt = datetime.fromisoformat(clean_time.replace('Z', '+00:00'))
                            # 转换为本地时间字符串
                            account["created_at"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(dt.timestamp()))
                        except Exception as e:
                            self.logger.warning(f"转换创建时间失败: {e}，使用原始值")
                            account["created_at"] = user_profile["createdAt"]
                    if "workosId" in user_profile:
                        account["workosId"] = user_profile["workosId"]
                
                # 格式化显示信息
                if trial_days > 0:
                    status_info = f"{final_membership_type} (试用剩余{trial_days}天)"
                else:
                    status_info = f"{final_membership_type} ({subscription_status})"
                
                self.logger.info(f"成功刷新账号 {email} 的订阅信息: {status_info}")
                
                # 如果有模型使用量数据，记录总费用
                if usage_data and usage_data.get('totalCostCents', 0) > 0:
                    total_cost = usage_data['totalCostCents'] / 100
                    used_models = len([m for m in usage_data.get('aggregations', []) if m.get('totalCents', 0) > 0])
                    self.logger.info(f"账号 {email} 本月模型使用: {used_models}个模型, 总费用: ${total_cost:.2f}")

                return True
            else:
                self.logger.error(f"无法获取账号 {email} 的订阅信息，API返回为空")
                return False
            
        except Exception as e:
            self.logger.error(f"刷新账号订阅失败: {str(e)}")
            return False
    
    def _get_request_proxies(self) -> Dict[str, str]:
        """
        根据配置决定是否使用代理
        
        Returns:
            Dict[str, str]: 代理配置字典
                - {} 表示强制直连，不使用任何代理
                - {'http': 'xxx', 'https': 'xxx'} 表示使用指定代理
        
        Note:
            requests库中 proxies=None 会使用环境变量代理，
            而 proxies={} 才是真正的强制直连
        """
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
    
    def _requests_with_proxy_control(self, method: str, url: str, proxies: Dict[str, str], **kwargs):
        """
        使用代理控制的requests请求
        
        Args:
            method: 请求方法 ('get', 'post', 'put', 'delete')
            url: 请求URL
            proxies: 代理配置
            **kwargs: 其他requests参数
            
        Returns:
            Response对象
        """
        method_func = getattr(requests, method.lower())
        return method_func(url, proxies=proxies, **kwargs)
    
    def _get_api_headers(self, user_id: str, access_token: str, account: Dict = None) -> Dict[str, str]:
        """生成API请求的通用headers - 🚀 按照CURSOR_API_SUCCESS_GUIDE优化"""
        # 📋 严格按照成功验证的方法设置headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json",
            "Referer": "https://cursor.com/dashboard",
            "Origin": "https://cursor.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors", 
            "Sec-Fetch-Site": "same-origin",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Cookie": f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"
        }
        
        self.logger.info(f"🔑 使用正确的Cookie认证方式: WorkosCursorSessionToken={user_id[:20]}...")
        return headers

    def _get_subscription_from_api(self, user_id: str, access_token: str, account: Dict = None) -> Optional[Dict]:
        """获取订阅信息 - 🚀 使用CURSOR_API_SUCCESS_GUIDE验证的方法"""
        url = "https://cursor.com/api/auth/stripe"
        
        try:
            # ✅ 使用文档验证的正确方法
            headers = self._get_api_headers(user_id, access_token, account)
            self.logger.info(f"🔗 请求订阅信息: {url}")
            
            # 根据配置决定是否使用代理
            proxies = self._get_request_proxies()
            response = self._requests_with_proxy_control('get', url, proxies, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"✅ 成功获取订阅信息: membershipType={data.get('membershipType')}, daysRemaining={data.get('daysRemainingOnTrial')}")
                return data
            else:
                self.logger.error(f"❌ 订阅API失败，状态码: {response.status_code}, 响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 获取订阅信息异常: {str(e)}")
            return None
    
    def _get_usage_summary_from_api(self, user_id: str, access_token: str, account: Dict = None) -> Optional[Dict]:
        """获取使用量汇总 - 使用官方标准接口"""
        url = "https://cursor.com/api/usage-summary"
        
        try:
            headers = self._get_api_headers(user_id, access_token, account)
            self.logger.info(f"🔗 请求使用量汇总: {url}")
            
            proxies = self._get_request_proxies()
            response = self._requests_with_proxy_control('get', url, proxies, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"✅ 成功获取使用量汇总: membershipType={data.get('membershipType')}, limitType={data.get('limitType')}")
                return data
            else:
                self.logger.error(f"❌ usage-summary API失败，状态码: {response.status_code}, 响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 获取使用量汇总异常: {str(e)}")
            return None
    
    def _get_user_profile_from_dashboard(self, user_id: str, access_token: str, account: Dict = None) -> Optional[Dict]:
        """获取用户详细信息 - 使用dashboard接口"""
        url = "https://cursor.com/api/dashboard/get-me"
        
        try:
            headers = self._get_api_headers(user_id, access_token, account)
            self.logger.info(f"🔗 请求用户详细信息: {url}")
            
            proxies = self._get_request_proxies()
            # 注意：这是POST接口，需要空body
            response = self._requests_with_proxy_control('post', url, proxies, headers=headers, json={}, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"✅ 成功获取用户详细信息: email={data.get('email')}, userId={data.get('userId')}")
                return data
            else:
                self.logger.error(f"❌ dashboard/get-me API失败，状态码: {response.status_code}, 响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 获取用户详细信息异常: {str(e)}")
            return None
    
    def _get_model_usage_from_api(self, user_id: str, access_token: str, account: Dict = None) -> Optional[Dict]:
        """获取模型使用量 - 🚀 按照CURSOR_API_SUCCESS_GUIDE的正确方法"""
        try:
            # ✅ 使用文档验证的正确方法和headers
            headers = self._get_api_headers(user_id, access_token, account)
            
            # 📋 按照文档顺序：先获取详细费用，再获取基础使用量
            aggregated_url = "https://cursor.com/api/dashboard/get-aggregated-usage-events"
            usage_url = f"https://cursor.com/api/usage?user={user_id}"
            
            self.logger.info(f"🔗 开始获取模型使用量: {aggregated_url}")
            
            # 1. 获取聚合使用事件（包含详细费用）
            # 构建请求体（关键：必须包含 teamId、startDate、endDate）
            current_time_ms = int(time.time() * 1000)
            start_time_ms = current_time_ms - (30 * 24 * 60 * 60 * 1000)  # 30天前
            
            request_data = {
                "teamId": -1,  # -1 表示个人账号
                "startDate": start_time_ms,
                "endDate": current_time_ms
            }
            
            proxies = self._get_request_proxies()
            aggregated_response = self._requests_with_proxy_control('post', aggregated_url, proxies, headers=headers, json=request_data, timeout=15)
            
            if aggregated_response.status_code == 200:
                aggregated_data = aggregated_response.json()
                self.logger.info(f"✅ 成功获取聚合使用数据: totalCostCents={aggregated_data.get('totalCostCents')}")
                
                # 2. 获取基础使用量统计（补充信息）
                basic_usage = {}
                try:
                    # 使用相同的代理配置
                    usage_response = self._requests_with_proxy_control('get', usage_url, proxies, headers=headers, timeout=15)
                    if usage_response.status_code == 200:
                        basic_usage = usage_response.json()
                        self.logger.info("✅ 成功获取基础使用量信息")
                    else:
                        self.logger.warning(f"⚠️ 基础使用量API失败: {usage_response.status_code}")
                except Exception as e:
                    self.logger.warning(f"⚠️ 基础使用量请求异常: {str(e)}")
                
                # 3. 合并数据并格式化
                formatted_data = self._format_usage_data(aggregated_data, basic_usage)
                if formatted_data and formatted_data.get('totalCostUSD', 0) > 0:
                    self.logger.info(f"🎉 模型使用量获取成功: ${formatted_data.get('totalCostUSD'):.2f}, {len(formatted_data.get('usedModels', []))}个模型")
                return formatted_data
                
            else:
                self.logger.error(f"❌ 聚合使用事件API失败: status={aggregated_response.status_code}, response={aggregated_response.text[:200]}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 获取模型使用量异常: {str(e)}")
            return None
    
    def _format_usage_data(self, aggregated_data: Dict, basic_usage: Dict) -> Dict:
        """
        格式化使用量数据
        
        Args:
            aggregated_data: 聚合使用事件数据
            basic_usage: 基础使用量数据
            
        Returns:
            dict: 格式化后的使用量数据
        """
        try:
            formatted_data = {
                "aggregations": aggregated_data.get("aggregations", []),
                "totalInputTokens": aggregated_data.get("totalInputTokens", "0"),
                "totalOutputTokens": aggregated_data.get("totalOutputTokens", "0"), 
                "totalCacheWriteTokens": aggregated_data.get("totalCacheWriteTokens", "0"),
                "totalCacheReadTokens": aggregated_data.get("totalCacheReadTokens", "0"),
                "totalCostCents": aggregated_data.get("totalCostCents", 0),
                "startOfMonth": basic_usage.get("startOfMonth", ""),
                "usedModels": []
            }
            
            # 解析用过的模型及费用
            used_models = []
            for agg in aggregated_data.get("aggregations", []):
                model_intent = agg.get("modelIntent", "unknown")
                total_cents = agg.get("totalCents", 0)
                input_tokens = int(agg.get("inputTokens", "0"))
                output_tokens = int(agg.get("outputTokens", "0"))
                
                # 获取请求次数 - API不提供准确数据，用token估算
                num_requests_raw = agg.get("numRequests", "0")
                try:
                    num_requests = int(num_requests_raw) if num_requests_raw else 0
                except:
                    num_requests = 0
                
                # 如果API返回的是0，用token数量估算（每次请求平均2万 tokens，更接近实际）
                if num_requests == 0 and (input_tokens > 0 or output_tokens > 0):
                    total_tokens = input_tokens + output_tokens
                    num_requests = max(1, round(total_tokens / 20000))
                    self.logger.info(f"🔍 模型 {model_intent}: 用token估算请求次数={num_requests} (tokens={total_tokens})")
                else:
                    self.logger.info(f"🔍 模型 {model_intent}: API返回请求次数={num_requests}")
                
                if total_cents > 0:  # 只统计有费用的模型
                    model_info = {
                        "name": model_intent,  # 改为name以统一字段名
                        "modelName": model_intent,  # 保留兼容性
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                        "costCents": total_cents,
                        "costInCents": total_cents,  # 添加costInCents字段
                        "costUSD": total_cents / 100,
                        "numRequests": num_requests,  # 添加请求次数字段
                        "cacheWriteTokens": int(agg.get("cacheWriteTokens", "0")),
                        "cacheReadTokens": int(agg.get("cacheReadTokens", "0"))
                    }
                    used_models.append(model_info)
            
            formatted_data["usedModels"] = used_models
            formatted_data["totalUsedModels"] = len(used_models)
            formatted_data["totalCostUSD"] = formatted_data["totalCostCents"] / 100
            
            return formatted_data
            
        except Exception as e:
            self.logger.error(f"格式化使用量数据失败: {str(e)}")
            return {}
    
    def get_model_usage_summary(self, account: Dict) -> str:
        """
        获取模型使用量摘要文本
        
        Args:
            account: 账号信息
            
        Returns:
            str: 使用量摘要
        """
        try:
            usage_data = account.get("modelUsageData", {})
            if not usage_data:
                return "暂无使用量数据"
            
            total_cost = usage_data.get("totalCostUSD", 0)
            used_models = usage_data.get("usedModels", [])
            
            if total_cost == 0:
                return "本月暂无付费使用"
            
            # 构建摘要
            summary_parts = [f"本月总费用: ${total_cost:.2f}"]
            
            if used_models:
                summary_parts.append(f"使用了{len(used_models)}个模型:")
                for model in used_models[:3]:  # 只显示前3个模型
                    model_name = model.get("modelName", "unknown")
                    model_cost = model.get("costUSD", 0)
                    summary_parts.append(f"  • {model_name}: ${model_cost:.2f}")
                
                if len(used_models) > 3:
                    summary_parts.append(f"  • 等{len(used_models)}个模型...")
            
            return "\n".join(summary_parts)
            
        except Exception as e:
            self.logger.error(f"生成使用量摘要失败: {str(e)}")
            return "获取使用量摘要失败"
    
    def get_cursor_processes(self) -> List[psutil.Process]:
        """获取所有运行中的Cursor IDE进程（排除XC-Cursor管理工具）"""
        cursor_processes = []
        try:
            # 🚀 性能优化：只获取pid和name，减少信息获取
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    process_name = proc.info['name']
                    if process_name:
                        process_name_lower = process_name.lower()
                        # 🚀 性能优化：简化匹配逻辑，只匹配最常见的名称
                        if (process_name_lower == 'cursor.exe' or 
                            process_name_lower == 'cursor'):
                            cursor_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.error(f"获取Cursor进程失败: {str(e)}")
        
        return cursor_processes
    
    def get_current_workspaces(self) -> List[str]:
        """获取当前打开的工作区路径"""
        workspaces = []
        try:
            cursor_processes = self.get_cursor_processes()
            for proc in cursor_processes:
                try:
                    cmdline = proc.cmdline()
                    if cmdline and len(cmdline) > 1:
                        # 查找工作区参数（跳过第一个参数，即可执行文件路径）
                        for i, arg in enumerate(cmdline[1:], 1):  # 从第二个参数开始
                            # 跳过非路径参数（如选项参数）
                            if arg.startswith('-') or arg.startswith('--'):
                                continue
                            
                            # 检查是否是有效的目录路径
                            if os.path.exists(arg) and os.path.isdir(arg):
                                # 排除Cursor程序目录、系统目录和扩展目录
                                arg_lower = arg.lower()
                                
                                # 排除Cursor内部目录
                                is_cursor_internal = any([
                                    'cursor' in arg_lower and ('appdata' in arg_lower or 'program' in arg_lower or 'application' in arg_lower),
                                    'resources\\app\\extensions' in arg_lower,
                                    'resources/app/extensions' in arg_lower,
                                    'cursor\\extensions' in arg_lower,
                                    'cursor/extensions' in arg_lower,
                                    'node_modules' in arg_lower,
                                    '.vscode' in arg_lower and 'extensions' in arg_lower,
                                    'html-language-features' in arg_lower,
                                    'htmlservermain' in arg_lower.replace(' ', ''),
                                ])
                                
                                # 排除系统根目录
                                is_system_dir = (
                                    arg_lower in ['c:\\', 'd:\\', 'e:\\', 'f:\\', '/'] or
                                    arg == os.path.expanduser('~') or
                                    arg == os.path.expanduser('~/Desktop') or
                                    arg.endswith(':\\') or arg == '/'
                                )
                                
                                if not is_cursor_internal and not is_system_dir:
                                    # 进一步验证：检查是否是真实的项目目录
                                    # 项目目录通常包含代码文件、配置文件等
                                    is_likely_workspace = self._is_likely_workspace(arg)
                                    if is_likely_workspace:
                                        workspaces.append(arg)
                                        break
                            elif os.path.exists(arg) and os.path.isfile(arg):
                                # 如果是文件，获取其所在目录作为工作区
                                parent_dir = os.path.dirname(arg)
                                if parent_dir and os.path.exists(parent_dir):
                                    parent_lower = parent_dir.lower()
                                    # 排除Cursor内部目录
                                    if not any([
                                        'cursor' in parent_lower and ('appdata' in parent_lower or 'program' in parent_lower),
                                        'resources\\app\\extensions' in parent_lower,
                                        'resources/app/extensions' in parent_lower,
                                    ]):
                                        workspaces.append(parent_dir)
                                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.error(f"获取当前工作区失败: {str(e)}")
        
        return list(set(workspaces))  # 去重
    
    def _is_likely_workspace(self, path: str) -> bool:
        """
        判断路径是否可能是工作区目录
        
        Args:
            path: 要检查的路径
            
        Returns:
            bool: 是否可能是工作区
        """
        try:
            # 检查常见的项目标识文件
            project_indicators = [
                '.git', '.gitignore', 'package.json', 'requirements.txt', 
                'pom.xml', 'build.gradle', 'Cargo.toml', 'go.mod',
                'README.md', 'readme.md', 'LICENSE', 'Makefile',
                '.vscode', '.idea', 'src', 'lib', 'app'
            ]
            
            # 快速检查：只检查前几个标识
            items = os.listdir(path)[:20]  # 只检查前20项，避免大目录性能问题
            for item in items:
                if item in project_indicators:
                    return True
            
            # 如果没有找到项目标识，但目录包含代码文件，也认为是工作区
            code_extensions = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.swift'}
            for item in items:
                if os.path.isfile(os.path.join(path, item)):
                    _, ext = os.path.splitext(item)
                    if ext.lower() in code_extensions:
                        return True
            
            return False
        except:
            # 如果无法访问目录，认为不是工作区
            return False
    
    def close_cursor_processes(self) -> Tuple[bool, str]:
        """关闭所有Cursor进程 - 改进版，确保完全关闭"""
        try:
            cursor_processes = self.get_cursor_processes()
            if not cursor_processes:
                return True, "没有运行中的Cursor进程"
            
            self.logger.info(f"发现 {len(cursor_processes)} 个Cursor进程，开始关闭...")
            closed_count = 0
            
            # 第一轮：优雅关闭
            for proc in cursor_processes:
                try:
                    self.logger.info(f"优雅关闭Cursor进程: PID {proc.pid}")
                    proc.terminate()
                    
                    # 等待进程结束，最多等待8秒（保持原有可靠性）
                    try:
                        proc.wait(timeout=3)
                        closed_count += 1
                    except psutil.TimeoutExpired:
                        self.logger.warning(f"进程 {proc.pid} 未在8秒内关闭，将强制终止")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    self.logger.warning(f"无法关闭进程 {proc.pid}: {str(e)}")
                    continue
            
            # 检查是否还有残留进程，强制杀死
            remaining_processes = self.get_cursor_processes()
            if remaining_processes:
                self.logger.warning(f"发现 {len(remaining_processes)} 个残留进程，强制终止...")
                for proc in remaining_processes:
                    try:
                        self.logger.info(f"强制关闭Cursor进程: PID {proc.pid}")
                        proc.kill()
                        
                        # 等待进程彻底结束
                        try:
                            proc.wait(timeout=3)
                            closed_count += 1
                        except psutil.TimeoutExpired:
                            self.logger.error(f"进程 {proc.pid} 无法强制关闭")
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            # 🚀 优化：智能动态等待进程完全关闭（进一步加速）
            self.logger.info("智能检测进程关闭状态...")
            max_wait_time = 1.5  # 🚀 一键换号优化：从2.5秒减少到1.5秒
            check_interval = 0.15  # 🚀 一键换号优化：更频繁检查，从0.2秒优化到0.15秒
            waited_time = 0
            consecutive_empty_checks = 0
            
            while waited_time < max_wait_time:
                time.sleep(check_interval)
                waited_time += check_interval
                
                # 检查是否还有进程
                remaining_processes = self.get_cursor_processes()
                if not remaining_processes:
                    consecutive_empty_checks += 1
                    # 🚀 优化：连续1次检查没有进程就立即退出（更激进）
                    if consecutive_empty_checks >= 1:
                        self.logger.info(f"✅ 所有Cursor进程已完全关闭 (等待了 {waited_time:.1f}秒)")
                        return True, f"成功关闭 {closed_count} 个Cursor进程"
                else:
                    consecutive_empty_checks = 0  # 重置计数器
                
            
            # 超时后最后检查一次
            final_check = self.get_cursor_processes()
            if final_check:
                self.logger.warning(f"等待超时，仍有 {len(final_check)} 个Cursor进程未关闭")
                return False, f"关闭了 {closed_count} 个进程，但仍有 {len(final_check)} 个进程未能关闭"
            
            self.logger.info(f"✅ 所有Cursor进程已完全关闭")
            return True, f"成功关闭 {closed_count} 个Cursor进程"
            
        except Exception as e:
            error_msg = f"关闭Cursor进程失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def start_cursor_with_workspaces(self, workspaces: List[str] = None) -> Tuple[bool, str]:
        """启动Cursor并打开指定工作区 - 改进版，优化时序控制"""
        try:
            # 优先使用配置文件中的Cursor可执行文件路径
            cursor_exe = self.config.get_cursor_install_path()
            
            # 如果配置的路径不存在或不是exe文件，使用默认检测
            if not cursor_exe or not os.path.exists(cursor_exe) or not cursor_exe.lower().endswith('.exe'):
                possible_paths = [
                    os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "cursor", "Cursor.exe"),
                    os.path.join(os.getenv("PROGRAMFILES", ""), "Cursor", "Cursor.exe"),
                    os.path.join(os.getenv("PROGRAMFILES(X86)", ""), "Cursor", "Cursor.exe"),
                ]
                
                cursor_exe = None
                for path in possible_paths:
                    if os.path.exists(path):
                        cursor_exe = path
                        break
            
            if not cursor_exe:
                return False, "找不到Cursor可执行文件"
            
            self.logger.info(f"找到Cursor可执行文件: {cursor_exe}")
            
            if workspaces and len(workspaces) > 0:
                # 🔥 改进：优化工作区启动时序
                self.logger.info(f"准备启动Cursor并打开 {len(workspaces)} 个工作区")
                
                started_count = 0
                for i, workspace in enumerate(workspaces):
                    if os.path.exists(workspace):
                        self.logger.info(f"启动工作区 {i+1}/{len(workspaces)}: {workspace}")
                        
                        # 启动Cursor实例
                        process = subprocess.Popen([cursor_exe, workspace], 
                                       creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                                       stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                        
                        started_count += 1
                        
                                # 🚀 一键换号优化：进一步减少启动间隔
                        if i < len(workspaces) - 1:  # 最后一个不用等待
                            time.sleep(0.1)  # 从0.3秒优化到0.1秒
                    else:
                        self.logger.warning(f"工作区路径不存在，跳过: {workspace}")
                
                # 🚀 一键换号优化：进一步减少等待时间
                if started_count > 0:
                    success = self._wait_for_cursor_startup(f"{started_count} 个Cursor实例", max_wait=0.5)  # 🚀 从1.0秒优化到0.5秒
                    return True, f"成功启动Cursor并打开 {started_count} 个工作区"
                else:
                    # 所有工作区路径都不存在，只启动Cursor
                    self.logger.warning("所有工作区路径都不存在，启动Cursor（无工作区）")
                    # cursor_exe已经在前面找到了，直接使用
                    process = subprocess.Popen([cursor_exe], 
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                    success = self._wait_for_cursor_startup("Cursor", max_wait=2.5)
                    return True, "成功启动Cursor（工作区路径无效）"
            else:
                # 只启动Cursor
                self.logger.info("启动Cursor（无工作区）")
                process = subprocess.Popen([cursor_exe], 
                               creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                
                # 🚀 一键换号优化：减少单实例等待时间
                success = self._wait_for_cursor_startup("Cursor", max_wait=1.5)  # 从2.5秒优化到1.5秒
                return True, "成功启动Cursor"
                
        except Exception as e:
            error_msg = f"启动Cursor失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def _wait_for_cursor_stability(self, max_wait: float = 8.0) -> bool:
        """
        🚀 优化：动态等待Cursor完全稳定 - 替代固定15秒等待
        
        Args:
            max_wait: 最大等待时间（秒）
            
        Returns:
            bool: 是否达到稳定状态
        """
        try:
            self.logger.info("🔄 动态检测Cursor稳定性...")
            
            check_interval = 0.5
            waited_time = 0
            stable_count = 0
            required_stable_checks = 3  # 连续3次检查稳定才认为真正稳定
            
            # 初始等待2秒让Cursor基本启动
            time.sleep(2.0)
            waited_time += 2.0
            
            last_process_count = len(self.get_cursor_processes())
            
            while waited_time < max_wait:
                current_process_count = len(self.get_cursor_processes())
                
                # 检查进程数是否稳定
                if current_process_count > 0 and current_process_count == last_process_count:
                    stable_count += 1
                    if stable_count >= required_stable_checks:
                        self.logger.info(f"✅ Cursor已稳定运行 {current_process_count} 个进程 (等待了 {waited_time:.1f}秒)")
                        return True
                else:
                    stable_count = 0  # 重置稳定计数
                
                last_process_count = current_process_count
                time.sleep(check_interval)
                waited_time += check_interval
            
            # 超时但有进程运行
            final_processes = self.get_cursor_processes()
            if final_processes:
                self.logger.info(f"⏰ 等待超时但Cursor运行正常 {len(final_processes)} 个进程 (用时 {waited_time:.1f}秒)")
                return True
            else:
                self.logger.warning(f"⚠️ Cursor稳定性检测超时，未发现进程")
                return False
                
        except Exception as e:
            self.logger.warning(f"Cursor稳定性检测失败: {str(e)}")
            return False

    def _wait_for_cursor_startup(self, instance_name: str = "Cursor", max_wait: float = 2.5) -> bool:
        """
        动态等待Cursor启动完成 - 优化版，减少等待时间
        
        Args:
            instance_name: 实例名称（用于日志）
            max_wait: 最大等待时间（秒）
            
        Returns:
            bool: 启动是否成功
        """
        try:
            self.logger.info(f"等待{instance_name}初始化...")
            
            check_interval = 0.25  # 优化：更频繁的检查间隔，提升响应速度
            waited_time = 0
            initial_process_count = 0
            
            # 🚀 性能优化：减少初始等待时间
            time.sleep(0.3)  # 从0.5秒优化到0.3秒
            waited_time += 0.3
            
            while waited_time < max_wait:
                cursor_processes = self.get_cursor_processes()
                current_count = len(cursor_processes)
                
                # 检查是否有进程启动
                if current_count > 0:
                    # 如果进程数稳定，认为启动完成
                    if initial_process_count > 0 and current_count == initial_process_count:
                        # 再等待一个检查周期确认稳定
                        time.sleep(check_interval)
                        final_check = len(self.get_cursor_processes())
                        if final_check == current_count:
                            self.logger.info(f"✅ {instance_name}启动完成，发现 {current_count} 个进程 (等待了 {waited_time:.1f}秒)")
                            return True
                    
                    initial_process_count = current_count
                
                time.sleep(check_interval)
                waited_time += check_interval
            
            # 超时检查
            final_processes = self.get_cursor_processes()
            if final_processes:
                self.logger.info(f"⏰ {instance_name}启动超时但发现 {len(final_processes)} 个进程，可能正在启动中")
                return True
            else:
                self.logger.warning(f"⚠️ 等待超时，未发现{instance_name}进程")
                return False
                
        except Exception as e:
            self.logger.warning(f"等待{instance_name}启动失败: {str(e)}")
            return False
    
    def check_subscription_status(self, account: Dict) -> Tuple[bool, str, int]:
        """
        检查Cursor订阅状态
        
        Args:
            account: 账号信息字典，需要包含认证信息
            
        Returns:
            Tuple[bool, str, int]: (检查成功, 消息, 订阅数量)
        """
        try:
            email = account.get('email', '未知')
            user_id = account.get('user_id', '')
            access_token = account.get('access_token', '')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            self.logger.info(f"开始检查账号订阅状态: {email}")
            
            # 处理认证信息
            if workos_token and not user_id:
                try:
                    # 🔥 修复：删除错误的拆分逻辑，只提取user_id
                    if ('::' in workos_token or '%3A%3A' in workos_token) and workos_token.startswith('user_'):
                        separator = '::' if '::' in workos_token else '%3A%3A'
                        parts = workos_token.split(separator, 1)
                        if len(parts) >= 1:
                            user_id = parts[0].strip()
                    
                    # access_token需要通过PKCE API转换获取，不能直接拆分
                except Exception as e:
                    self.logger.warning(f"解析WorkosCursorSessionToken失败: {str(e)}")
            
            if not user_id or not access_token:
                return False, f"账号 {email} 缺少必要的认证信息", 0
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://cursor.com",
                "Referer": "https://cursor.com/dashboard?tab=billing",
                "Cookie": f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"
            }
            
            # 获取Stripe session
            proxies = self._get_request_proxies()
            stripe_session_response = self._requests_with_proxy_control(
                'get',
                "https://cursor.com/api/stripeSession",
                proxies,
                headers=headers,
                timeout=15
            )
            
            if stripe_session_response.status_code != 200:
                return False, f"无法检查订阅状态: HTTP {stripe_session_response.status_code}", 0
            
            # 处理Cursor API返回的数据（可能是JSON字符串或直接URL）
            response_text = stripe_session_response.text.strip()
            
            try:
                # 尝试作为JSON解析
                if response_text.startswith('"') and response_text.endswith('"'):
                    # 移除首尾引号，获取实际URL
                    stripe_session_url = response_text[1:-1]
                elif response_text.startswith('{"') and response_text.endswith('}'):
                    # JSON对象格式
                    import json
                    data = json.loads(response_text)
                    stripe_session_url = data.get('url', response_text)
                else:
                    # 直接是URL字符串
                    stripe_session_url = response_text
            except Exception:
                # 解析失败，直接使用原文本
                stripe_session_url = response_text
            
            if not stripe_session_url or not stripe_session_url.startswith('https://billing.stripe.com'):
                return False, f"无效的Stripe session URL: {stripe_session_url[:100] if stripe_session_url else '空响应'}", 0
            
            # 提取session ID
            import re
            session_match = re.search(r'/session/([^/?]+)', stripe_session_url)
            if not session_match:
                return False, "无法从URL中提取session ID", 0
            
            stripe_session_id = session_match.group(1)
            
            # 获取订阅信息
            subscriptions_url = f"https://billing.stripe.com/v1/billing_portal/sessions/{stripe_session_id}/subscriptions"
            subscriptions_response = self._requests_with_proxy_control(
                'get',
                subscriptions_url,
                proxies,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": stripe_session_url
                },
                timeout=15
            )
            
            if subscriptions_response.status_code != 200:
                return False, f"获取订阅信息失败: HTTP {subscriptions_response.status_code}", 0
            
            try:
                subscriptions_data = subscriptions_response.json()
            except Exception as e:
                return False, f"订阅信息响应格式错误: {str(e)}", 0
            
            if not isinstance(subscriptions_data, dict):
                return False, f"订阅信息数据格式错误", 0
            
            subscriptions = subscriptions_data.get('data', [])
            active_subscriptions = [sub for sub in subscriptions if sub.get('status') not in ['canceled', 'cancelled']]
            
            subscription_count = len(active_subscriptions)
            self.logger.info(f"找到 {subscription_count} 个活跃订阅")
            
            return True, f"账号 {email} 有 {subscription_count} 个活跃订阅", subscription_count
            
        except Exception as e:
            error_msg = f"检查订阅状态异常: {str(e)}"
            self.logger.error(f"检查订阅状态失败: {error_msg}")
            return False, error_msg, 0

    # 分步骤切换逻辑已简化，统一使用apply_account_cursor_ideal_style
    
    # 备份和恢复功能
    def create_user_data_backup(self, backup_name: str = None) -> Tuple[bool, str]:
        """
        创建用户数据备份（不包括机器码和认证信息）
        
        Args:
            backup_name: 备份名称
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        return self.backup_manager.create_backup(backup_name)
    
    
    def list_user_data_backups(self) -> List[Dict]:
        """
        列出所有用户数据备份
        
        Returns:
            List[Dict]: 备份列表
        """
        return self.backup_manager.list_backups()
    
    def delete_user_data_backup(self, backup_name: str) -> Tuple[bool, str]:
        """
        删除用户数据备份
        
        Args:
            backup_name: 备份名称
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        return self.backup_manager.delete_backup(backup_name)
    
    def get_backup_info(self, backup_name: str) -> Dict[str, str]:
        """
        获取备份详细信息
        
        Args:
            backup_name: 备份名称
            
        Returns:
            Dict[str, str]: 备份信息
        """
        backups = self.list_user_data_backups()
        for backup in backups:
            if backup.get('backup_name') == backup_name:
                backup['size'] = self.backup_manager.get_backup_size(backup_name)
                return backup
        return {}
