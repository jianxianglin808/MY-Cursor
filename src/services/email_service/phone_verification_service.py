#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
手机号验证服务 - 豪猪接码平台集成
用于自动获取手机号、接收验证码和拉黑号码
"""

import time
import logging
import requests
import json
import os
from pathlib import Path
from typing import Optional, Dict


class PhoneVerificationService:
    """手机号验证服务类"""
    
    # 默认服务器地址(可配置)
    DEFAULT_API_SERVERS = [
        "https://api.haozhuma.com",
        "https://api.haozhuyun.com"
    ]
    
    # 开发者账号列表（轮询使用）
    AUTHOR_ACCOUNTS = [
        "Aethxz247XCGL"
    ]
    
    def __init__(self, username: str, password: str, project_id: str, 
                 api_server: str = None, author: str = None, log_callback=None):
        """
        初始化手机验证服务
        
        Args:
            username: API账号
            password: API密码
            project_id: 项目ID（sid）
            api_server: API服务器地址（可选，默认使用第一个）
            author: 开发者账号（可选，不指定则轮询使用多个账号）
            log_callback: 日志回调函数
        """
        self.username = username
        self.password = password
        self.project_id = project_id
        self.api_server = api_server or self.DEFAULT_API_SERVERS[0]
        self.author = author  # 如果指定了author，使用指定的；否则轮询
        self.log_callback = log_callback
        
        # 轮询索引（用于在多个author账号间轮换）
        self._author_index = 0
        
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # 令牌（登录后获取）
        self.token = None
        
        # 当前使用的手机号和区号
        self.current_phone = None
        self.current_country_code = '+86'  # 默认中国区号
        
        # 手机号使用次数记录文件（持久化，跨批次、跨重启都生效）
        config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'config')
        self.phone_usage_file = Path(config_dir) / 'phone_usage_record.json'
        self.phone_usage_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 最大使用次数（从外部传入，默认3次）
        self.max_usage_count = 3
        
        # 当前可重用的手机号
        self.reusable_phone = None
        self.reusable_country_code = None
        
        # 记录当前project_id，用于检测对接码是否变化
        self.last_project_id = project_id
        
        self.logger.info(f"初始化手机验证服务: API服务器={self.api_server}, 项目ID={self.project_id}")
        self.logger.info(f"手机号使用策略: 每个号码可使用{self.max_usage_count}次后拉黑（持久化记录，跨批次、跨重启生效）")
    
    def __del__(self):
        """析构函数：清理资源"""
        try:
            if hasattr(self, 'session') and self.session:
                self.session.close()
        except:
            pass
    
    def cleanup(self):
        """手动清理资源"""
        try:
            if self.session:
                self.session.close()
                self.logger.debug("✅ 已关闭HTTP会话")
        except Exception as e:
            self.logger.debug(f"清理资源失败: {str(e)}")
    
    def _log_progress(self, message: str):
        """记录进度日志"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def _make_request(self, api: str, params: Dict, method: str = 'GET') -> Optional[Dict]:
        """
        发起API请求
        
        Args:
            api: API名称
            params: 请求参数
            method: 请求方法（GET或POST）
            
        Returns:
            返回API响应的JSON数据，失败返回None
        """
        try:
            url = f"{self.api_server}/sms/"
            params['api'] = api
            
            self.logger.debug(f"请求API: {api}, 参数: {params}")
            
            if method.upper() == 'POST':
                response = self.session.post(url, data=params, timeout=10)
            else:
                response = self.session.get(url, params=params, timeout=10)
            
            self.logger.debug(f"响应状态码: {response.status_code}")
            
            if response.status_code != 200:
                self.logger.error(f"API请求失败: HTTP {response.status_code}")
                self.logger.error(f"响应内容: {response.text}")
                return None
            
            result = response.json()
            self.logger.debug(f"API响应: {result}")
            return result
            
        except requests.RequestException as e:
            self.logger.error(f"网络请求失败: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"API请求异常: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def login(self) -> bool:
        """
        登录获取令牌
        
        Returns:
            成功返回True，失败返回False
        """
        try:
            params = {
                'user': self.username,
                'pass': self.password
            }
            
            result = self._make_request('login', params)
            
            if not result:
                self._log_progress("❌ 登录接码平台失败：无响应")
                return False
            
            code = result.get('code')
            if code in [0, '0', 200, '200']:
                self.token = result.get('token')
                self.logger.debug(f"获取到令牌: {self.token}")
                return True
            else:
                msg = result.get('msg', '未知错误')
                self._log_progress(f"❌ 登录接码平台失败: {msg}")
                return False
                
        except Exception as e:
            self.logger.error(f"登录失败: {str(e)}")
            return False
    
    def set_max_usage_count(self, count: int):
        """设置最大使用次数"""
        self.max_usage_count = count
        self.logger.info(f"手机号最大使用次数设置为: {count}")
    
    def occupy_phone(self, phone: str) -> bool:
        """
        占用指定号码（用于重用号码）
        
        Args:
            phone: 要占用的手机号
            
        Returns:
            成功返回True，失败返回False
        """
        try:
            # 确保已登录
            if not self.token:
                if not self.login():
                    return False
            
            self.logger.debug(f"♻️ 正在占用号码: {phone}...")
            
            params = {
                'token': self.token,
                'sid': self.project_id,
                'phone': phone
            }
            
            # 添加开发者账号参数
            if self.author:
                current_author = self.author
            else:
                current_author = self.AUTHOR_ACCOUNTS[self._author_index]
                self._author_index = (self._author_index + 1) % len(self.AUTHOR_ACCOUNTS)
            params['author'] = current_author
            
            result = self._make_request('getPhone', params)
            
            if not result:
                self._log_progress("❌ 占用号码失败：无响应")
                return False
            
            code = result.get('code')
            if code in [0, '0', 200, '200']:
                # 更新当前号码信息
                country_qu = result.get('country_qu')
                
                # 处理区号
                if not country_qu or country_qu == 'None':
                    if phone and str(phone).startswith('1') and len(str(phone)) == 11:
                        country_qu = '+86'
                    else:
                        country_qu = '+86'
                    self.logger.warning(f"占用号码API未返回区号，设置为: {country_qu}")
                
                self.current_phone = phone
                self.current_country_code = country_qu
                
                # 确保区号一定有值
                if not self.current_country_code:
                    self.current_country_code = '+86'
                    self.logger.error(f"区号仍为空，强制设置为: +86")
                
                self.logger.debug(f"✅ 成功占用号码: {phone} 区号:{country_qu} (author={current_author})")
                return True
            else:
                msg = result.get('msg', '未知错误')
                self._log_progress(f"❌ 占用号码失败: {msg}")
                return False
                
        except Exception as e:
            self.logger.error(f"占用号码失败: {str(e)}")
            return False
    
    def get_or_reuse_phone(self, isp: int = None, province: str = None, 
                           ascription: int = None, uid: str = None, max_retries: int = 3) -> Optional[str]:
        """
        获取或重用手机号（智能判断，支持跨批次、跨重启）
        
        Args:
            isp: 运营商（1=移动，2=联通，3=电信，可选）
            province: 省份代码（可选，如44=广东）
            ascription: 号码类型（1=虚拟号，2=实卡，可选）
            uid: 对接码ID（可选，指定使用哪个对接码）
            max_retries: 最大重试次数
            
        Returns:
            成功返回手机号，失败返回None
        """
        # 检测对接码是否变化（project_id变化意味着更换了对接码平台）
        if self.project_id != self.last_project_id:
            self.logger.info(f"🔄 检测到对接码变化: {self.last_project_id} -> {self.project_id}")
            self.logger.info(f"♻️ 清空旧平台缓存的手机号: {self.reusable_phone}")
            self.reusable_phone = None
            self.reusable_country_code = None
            self.last_project_id = self.project_id
        
        # 检查是否有可重用的号码
        if self.reusable_phone:
            usage_record = self._load_phone_usage_record()
            existing = usage_record.get(str(self.reusable_phone), 0)
            
            # 兼容新旧格式
            if isinstance(existing, dict):
                current_count = existing.get("count", 0)
                is_blacklisted = existing.get("blacklisted", False)
            else:
                current_count = existing
                is_blacklisted = False
            
            # 如果已拉黑，不再重用
            if is_blacklisted:
                self.logger.warning(f"⚠️ 缓存的号码 {self.reusable_phone} 已被拉黑，获取新号码")
                self.reusable_phone = None
                self.reusable_country_code = None
            elif current_count < self.max_usage_count:
                # 号码还可以继续使用，调用占用API
                self.logger.debug(f"♻️ 重用手机号: {self.reusable_phone} (已使用{current_count}/{self.max_usage_count}次)")
                
                # 调用占用API重新占用这个号码
                if self.occupy_phone(self.reusable_phone):
                    # 占用成功后，确保区号被正确设置
                    if not self.current_country_code or self.current_country_code == 'None':
                        # 如果占用API也没返回区号，使用缓存的区号
                        if self.reusable_country_code:
                            self.current_country_code = self.reusable_country_code
                            self.logger.info(f"使用缓存的区号: {self.reusable_country_code}")
                        else:
                            self.current_country_code = '+86'
                            self.logger.warning(f"无缓存区号，使用默认值: +86")
                    return self.reusable_phone
                else:
                    # 占用失败，可能号码已被释放或拉黑，获取新号码
                    self._log_progress("⚠️ 占用号码失败，获取新号码")
                    self.reusable_phone = None
                    self.reusable_country_code = None
            else:
                # 号码已达上限，清空缓存
                self._log_progress(f"🚫 手机号 {self.reusable_phone} 已达使用上限，获取新号码")
                self.reusable_phone = None
                self.reusable_country_code = None
        
        # 获取新号码
        phone = self.get_phone(isp, province, ascription, uid, max_retries)
        if phone:
            # 缓存新号码供重用
            self.reusable_phone = phone
            self.reusable_country_code = self.current_country_code
        
        return phone
    
    def get_phone(self, isp: int = None, province: str = None, 
                  ascription: int = None, uid: str = None, max_retries: int = 3) -> Optional[str]:
        """
        获取手机号
        
        Args:
            isp: 运营商（1=移动，2=联通，3=电信，可选）
            province: 省份代码（可选，如44=广东）
            ascription: 号码类型（1=虚拟号，2=实卡，可选）
            uid: 对接码ID（可选，指定使用哪个对接码）
            max_retries: 最大重试次数
            
        Returns:
            成功返回手机号，失败返回None
        """
        try:
            # 确保已登录
            if not self.token:
                if not self.login():
                    return None
            
            self.logger.debug("📱 正在获取手机号...")
            
            params = {
                'token': self.token,
                'sid': self.project_id
            }
            
            # 添加可选参数
            if isp is not None:
                params['isp'] = isp
            if province is not None:
                params['Province'] = province
            if ascription is not None:
                params['ascription'] = ascription
            if uid is not None:
                params['uid'] = uid
            
            # 添加开发者账号参数（获取50%分成）
            # 如果指定了author，使用指定的；否则轮询使用
            if self.author:
                current_author = self.author
            else:
                # 轮询使用多个author账号
                current_author = self.AUTHOR_ACCOUNTS[self._author_index]
                self._author_index = (self._author_index + 1) % len(self.AUTHOR_ACCOUNTS)
            
            params['author'] = current_author
            self.logger.debug(f"使用开发者账号: {current_author}")
            
            # 尝试获取手机号（可能需要重试）
            for attempt in range(max_retries):
                result = self._make_request('getPhone', params)
                
                if not result:
                    if attempt < max_retries - 1:
                        self.logger.debug(f"获取手机号失败，{2}秒后重试...")
                        time.sleep(2)
                        continue
                    else:
                        self._log_progress("❌ 获取手机号失败：无响应")
                        return None
                
                code = result.get('code')
                if code in [0, '0', 200, '200']:
                    phone = result.get('phone')
                    sp = result.get('sp', '')  # 运营商
                    phone_gsd = result.get('phone_gsd', '')  # 归属地
                    country_qu = result.get('country_qu')  # 国家区号
                    
                    # 如果API没返回区号或返回None，根据手机号智能判断
                    if not country_qu or country_qu == 'None':
                        # 中国手机号：1开头，11位
                        if phone and str(phone).startswith('1') and len(str(phone)) == 11:
                            country_qu = '+86'
                            self.logger.warning(f"API未返回区号，根据手机号判断为中国号码: {country_qu}")
                        else:
                            country_qu = '+86'  # 默认中国
                            self.logger.warning(f"API未返回区号，使用默认值: {country_qu}")
                    
                    self.current_phone = phone
                    self.current_country_code = country_qu  # 保存区号
                    self._log_progress(f"✅ 获取到手机号: {phone} ({sp} {phone_gsd}) 区号:{country_qu}")
                    
                    # 确保区号一定有值
                    if not self.current_country_code:
                        self.current_country_code = '+86'
                        self.logger.error(f"区号仍为空，强制设置为: +86")
                    
                    return phone
                else:
                    msg = result.get('msg', '未知错误')
                    self._log_progress(f"❌ 获取手机号失败: {msg}")
                    
                    # 如果是token失效，尝试重新登录
                    if 'token' in msg.lower() or '令牌' in msg:
                        self.logger.info("Token可能失效，尝试重新登录...")
                        if self.login():
                            params['token'] = self.token
                            continue
                    
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    return None
            
            return None
            
        except Exception as e:
            self.logger.error(f"获取手机号失败: {str(e)}")
            return None
    
    def get_verification_code(self, phone: str = None, max_retries: int = 20, 
                             retry_interval: int = 5) -> Optional[str]:
        """
        获取验证码
        
        Args:
            phone: 手机号（可选，默认使用当前手机号）
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            
        Returns:
            成功返回验证码，失败返回None
        """
        try:
            # 使用指定手机号或当前手机号
            target_phone = phone or self.current_phone
            if not target_phone:
                self.logger.error("未指定手机号且没有当前手机号")
                return None
            
            # 确保已登录
            if not self.token:
                if not self.login():
                    return None
            
            self.logger.debug(f"📨 正在获取验证码（手机号: {target_phone}）...")
            
            params = {
                'token': self.token,
                'sid': self.project_id,
                'phone': target_phone
            }
            
            # 循环获取验证码
            for attempt in range(max_retries):
                self.logger.debug(f"等待验证码... ({(attempt + 1) * retry_interval}/{max_retries * retry_interval}秒)")
                
                result = self._make_request('getMessage', params)
                
                if not result:
                    if attempt < max_retries - 1:
                        time.sleep(retry_interval)
                        continue
                    else:
                        self._log_progress("❌ 获取验证码失败：无响应")
                        return None
                
                code = result.get('code')
                if code in [0, '0', 200, '200']:
                    yzm = result.get('yzm')  # 系统识别的验证码
                    sms = result.get('sms', '')  # 完整短信内容
                    
                    if yzm:
                        self._log_progress(f"✅ 获取到验证码: {yzm}")
                        self.logger.debug(f"完整短信: {sms}")
                        return yzm
                    else:
                        self.logger.debug("验证码字段为空，继续等待...")
                else:
                    msg = result.get('msg', '未知错误')
                    
                    # 如果是"暂无短信"，继续等待
                    if '暂无' in msg or '未收到' in msg or 'no' in msg.lower():
                        self.logger.debug(f"暂无短信，继续等待... ({msg})")
                    else:
                        self.logger.warning(f"获取验证码返回错误: {msg}")
                        
                        # token失效，尝试重新登录
                        if 'token' in msg.lower() or '令牌' in msg:
                            self.logger.info("Token可能失效，尝试重新登录...")
                            if self.login():
                                params['token'] = self.token
                
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
            
            self._log_progress(f"❌ 获取验证码超时（等待{max_retries * retry_interval}秒）")
            return None
            
        except Exception as e:
            self.logger.error(f"获取验证码失败: {str(e)}")
            return None
    
    def _load_phone_usage_record(self) -> Dict:
        """加载手机号使用记录"""
        try:
            if self.phone_usage_file.exists():
                with open(self.phone_usage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"加载手机号使用记录失败: {str(e)}")
            return {}
    
    def _save_phone_usage_record(self, record: Dict) -> bool:
        """保存手机号使用记录"""
        try:
            with open(self.phone_usage_file, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"保存手机号使用记录失败: {str(e)}")
            return False
    
    
    def record_phone_usage(self, phone: str = None) -> int:
        """
        记录手机号使用次数，并在达到上限时自动拉黑（持久化，跨批次、跨重启生效）
        
        Args:
            phone: 手机号（可选，默认使用当前手机号）
            
        Returns:
            当前使用次数
        """
        try:
            target_phone = phone or self.current_phone
            if not target_phone:
                self.logger.error("未指定手机号且没有当前手机号")
                return 0
            
            # 转换为字符串
            target_phone = str(target_phone)
            
            # 加载使用记录
            usage_record = self._load_phone_usage_record()
            
            # 兼容新旧格式
            existing = usage_record.get(target_phone, 0)
            if isinstance(existing, dict):
                # 新格式：{"count": x, "blacklisted": bool, ...}
                if existing.get("blacklisted", False):
                    self.logger.warning(f"手机号 {target_phone} 已被拉黑，跳过记录")
                    return existing.get("count", 0)
                current_count = existing.get("count", 0)
            else:
                # 旧格式：直接是数字
                current_count = existing
            
            new_count = current_count + 1
            
            # 更新记录（使用新格式）
            usage_record[target_phone] = {
                "count": new_count,
                "blacklisted": False,
                "last_used": time.time()
            }
            self._save_phone_usage_record(usage_record)
            
            self._log_progress(f"📊 手机号使用记录: {target_phone} 已使用 {new_count}/{self.max_usage_count} 次")
            
            # 如果达到最大使用次数，拉黑
            if new_count >= self.max_usage_count:
                self._log_progress(f"🚫 手机号已达使用上限({self.max_usage_count}次)，开始拉黑: {target_phone}")
                self.blacklist_phone(target_phone, reason="达到使用上限")
            else:
                remaining = self.max_usage_count - new_count
                self._log_progress(f"♻️ 手机号还可使用 {remaining} 次")
            
            return new_count
            
        except Exception as e:
            self.logger.error(f"记录手机号使用失败: {str(e)}")
            return 0
    
    def blacklist_phone(self, phone: str = None, reason: str = "达到使用上限") -> bool:
        """
        拉黑手机号（调用API拉黑，平台将不再返回该号码）
        
        Args:
            phone: 手机号（可选，默认使用当前手机号）
            reason: 拉黑原因（用于日志记录）
            
        Returns:
            成功返回True，失败返回False
        """
        try:
            # 使用指定手机号或当前手机号
            target_phone = phone or self.current_phone
            if not target_phone:
                self.logger.error("未指定手机号且没有当前手机号")
                return False
            
            # 转换为字符串以确保一致性
            target_phone = str(target_phone)
            
            # 确保已登录
            if not self.token:
                if not self.login():
                    return False
            
            self._log_progress(f"🚫 正在拉黑手机号: {target_phone} (原因: {reason})...")
            
            params = {
                'token': self.token,
                'sid': self.project_id,
                'phone': target_phone
            }
            
            result = self._make_request('addBlacklist', params)
            
            if not result:
                self._log_progress("❌ 拉黑手机号失败：无响应")
                return False
            
            code = result.get('code')
            if code in [0, '0', 200, '200']:
                self._log_progress(f"✅ 成功拉黑手机号: {target_phone}")
                self.logger.info(f"API已拉黑该号码，平台将不再返回该号码")
                
                # 清空当前手机号
                if self.current_phone == target_phone:
                    self.current_phone = None
                    
                # 清空可重用号码缓存
                if self.reusable_phone == target_phone:
                    self.reusable_phone = None
                    self.reusable_country_code = None
                
                # 保留使用记录（用于统计和跨批次跟踪），但标记为已拉黑
                usage_record = self._load_phone_usage_record()
                if target_phone in usage_record:
                    existing = usage_record[target_phone]
                    # 兼容新旧格式获取count
                    if isinstance(existing, dict):
                        count = existing.get("count", 0)
                    else:
                        count = existing
                    
                    # 标记为已拉黑，避免重复拉黑
                    usage_record[target_phone] = {
                        "count": count,
                        "blacklisted": True,
                        "time": time.time(),
                        "reason": reason
                    }
                    self._save_phone_usage_record(usage_record)
                
                return True
            else:
                msg = result.get('msg', '未知错误')
                self._log_progress(f"❌ 拉黑手机号失败: {msg}")
                return False
                
        except Exception as e:
            self.logger.error(f"拉黑手机号失败: {str(e)}")
            return False
    
    def release_phone(self, phone: str = None) -> bool:
        """
        释放手机号（不拉黑）
        
        Args:
            phone: 手机号（可选，默认使用当前手机号）
            
        Returns:
            成功返回True，失败返回False
        """
        try:
            target_phone = phone or self.current_phone
            if not target_phone:
                self.logger.error("未指定手机号且没有当前手机号")
                return False
            
            # 确保已登录
            if not self.token:
                if not self.login():
                    return False
            
            self._log_progress(f"🔓 正在释放手机号: {target_phone}...")
            
            params = {
                'token': self.token,
                'sid': self.project_id,
                'phone': target_phone
            }
            
            result = self._make_request('cancelRecv', params)
            
            if not result:
                self.logger.warning("释放手机号API无响应（可能不支持）")
                # 清空当前手机号
                if self.current_phone == target_phone:
                    self.current_phone = None
                return True
            
            code = result.get('code')
            if code in [0, '0', 200, '200']:
                self._log_progress(f"✅ 成功释放手机号: {target_phone}")
                if self.current_phone == target_phone:
                    self.current_phone = None
                return True
            else:
                msg = result.get('msg', '未知错误')
                self.logger.warning(f"释放手机号失败: {msg}")
                # 即使失败也清空当前手机号
                if self.current_phone == target_phone:
                    self.current_phone = None
                return False
                
        except Exception as e:
            self.logger.error(f"释放手机号失败: {str(e)}")
            return False


# 测试函数
def test_phone_verification_service():
    """测试手机验证服务"""
    print("🧪 测试手机验证服务...")
    
    # 配置信息（需要替换为实际值）
    username = "your_username"
    password = "your_password"
    project_id = "1000"  # 项目ID，需要替换
    
    # 创建服务实例
    service = PhoneVerificationService(username, password, project_id)
    
    # 测试登录
    if not service.login():
        print("❌ 登录失败")
        return
    
    # 测试获取手机号
    phone = service.get_phone()
    if not phone:
        print("❌ 获取手机号失败")
        return
    
    print(f"✅ 获取到手机号: {phone}")
    
    # 等待用户手动发送验证码
    input("请手动发送验证码到该手机号，然后按回车继续...")
    
    # 测试获取验证码
    code = service.get_verification_code(max_retries=10, retry_interval=3)
    if code:
        print(f"✅ 获取到验证码: {code}")
    else:
        print("❌ 获取验证码失败")
    
    # 测试拉黑号码
    if service.blacklist_phone():
        print(f"✅ 成功拉黑号码: {phone}")
    else:
        print(f"❌ 拉黑号码失败")


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    test_phone_verification_service()

