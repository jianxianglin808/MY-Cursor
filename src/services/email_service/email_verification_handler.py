#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
邮箱验证码处理器 - 统一tempmail和IMAP两种方式
支持：
1. tempmail.plus API获取验证码
2. IMAP协议邮箱（2925、QQ等）获取验证码
"""

import re
import time
import logging
import requests
from datetime import datetime
from typing import Optional, Dict

from .imap_email_manager import ImapEmailManager


class EmailVerificationHandler:
    """邮箱验证码处理器，统一tempmail和IMAP两种方式"""
    
    def __init__(self, email_address: str, config_manager=None, account_info=None):
        """
        初始化邮箱验证码处理器
        
        Args:
            email_address: 注册使用的邮箱地址
            config_manager: 配置管理器
            account_info: 账号信息字典（可能包含临时邮箱标记）
        """
        self.email_address = email_address
        self.username = email_address.split('@')[0] if '@' in email_address else email_address
        self.domain = email_address.split('@')[1] if '@' in email_address else ''
        self.config_manager = config_manager
        self.account_info = account_info or {}
        
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        
        # 设置请求头
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # BC1P临时邮箱管理器（按需初始化）
        self.bc1p_manager = None
        
        # 确定邮箱类型并初始化
        self._init_email_handler()
        
        self.logger.info(f"初始化邮箱验证码处理器: {email_address}")
        self.logger.info(f"使用邮箱类型: {self.email_type}")
    
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
        except:
            pass
    
    def _init_email_handler(self):
        """初始化邮箱处理器，根据配置决定使用tempmail、IMAP或BC1P临时邮箱"""
        try:
            # 优先检查是否使用BC1P临时邮箱（从account_info中判断）
            if self.account_info.get('use_bc1p_temp_mail', False):
                self.email_type = 'bc1p_temp_mail'
                self.imap_manager = None
                self._init_bc1p_temp_mail()
                self.logger.info("使用BC1P临时邮箱模式")
                return
            
            if self.config_manager:
                email_config = self.config_manager.get_email_config()
                self.email_type = email_config.get('email_type', 'domain_forward')
                
                # 判断是否需要使用IMAP
                use_imap = False
                
                if self.email_type == 'imap':
                    # 2925邮箱模式，使用IMAP
                    use_imap = True
                    self.logger.info("使用2925 IMAP邮箱模式")
                elif self.email_type == 'domain_forward':
                    # 域名转发模式，检查转发目标
                    domain_forward = email_config.get('domain_forward', {})
                    forward_target = domain_forward.get('forward_target', 'temp_mail')
                    
                    if forward_target in ['qq', '163']:
                        # 转发到QQ或163邮箱，使用IMAP接收验证码
                        use_imap = True
                        self.logger.info(f"使用域名转发→{forward_target.upper()}邮箱模式（IMAP）")
                    else:
                        # 转发到临时邮箱
                        self.logger.info("使用域名转发→临时邮箱模式")
                
                if use_imap:
                    self.imap_manager = ImapEmailManager(config_manager=self.config_manager)
                    self._load_imap_config()
                else:
                    self.imap_manager = None
                    self._load_temp_mail_config()
            else:
                # 默认使用临时邮箱
                self.email_type = 'domain_forward'
                self.imap_manager = None
                self._load_temp_mail_config()
                
        except Exception as e:
            self.logger.error(f"初始化邮箱处理器失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            # 默认使用临时邮箱
            self.email_type = 'domain_forward'
            self.imap_manager = None
            self._load_temp_mail_config()
    
    def _init_bc1p_temp_mail(self):
        """初始化BC1P临时邮箱"""
        try:
            from .bc1p_temp_mail_manager import BC1PTempMailManager
            self.bc1p_manager = BC1PTempMailManager()
            # 使用已生成的邮箱地址
            self.bc1p_manager.current_email = self.email_address
            self.logger.info(f"BC1P临时邮箱初始化成功: {self.email_address}")
        except Exception as e:
            self.logger.error(f"初始化BC1P临时邮箱失败: {str(e)}")
            self.bc1p_manager = None
    
    def _load_imap_config(self):
        """加载IMAP邮箱配置"""
        try:
            email_config = self.config_manager.get_email_config()
            email_type = email_config.get('email_type', 'domain_forward')
            
            if email_type == 'imap':
                # 2925邮箱配置
                imap_config = email_config.get('imap_mail', {})
                self.imap_email = imap_config.get('email', '')
                self.imap_use_random = imap_config.get('use_random_email', False)
                self.logger.info(f"2925 IMAP邮箱: {self.imap_email}")
                self.logger.info(f"使用随机子邮箱: {self.imap_use_random}")
            else:
                # 域名转发到QQ/163邮箱配置
                domain_forward = email_config.get('domain_forward', {})
                forward_target = domain_forward.get('forward_target', 'temp_mail')
                
                if forward_target == 'qq':
                    qq_mail = domain_forward.get('qq_mail', {})
                    self.imap_email = qq_mail.get('email', '')
                    self.logger.info(f"QQ邮箱: {self.imap_email}")
                elif forward_target == '163':
                    mail_163 = domain_forward.get('163_mail', {})
                    self.imap_email = mail_163.get('email', '')
                    self.logger.info(f"163邮箱: {self.imap_email}")
                
                self.imap_use_random = False  # 域名转发模式不使用随机子邮箱
            
        except Exception as e:
            self.logger.error(f"加载IMAP配置失败: {str(e)}")
    
    def _load_temp_mail_config(self):
        """加载临时邮箱配置"""
        try:
            if self.config_manager:
                email_config = self.config_manager.get_email_config()
                
                # 从新的配置格式读取
                domain_forward = email_config.get('domain_forward', {})
                temp_mail_config = domain_forward.get('temp_mail', {})
                
                # 兼容旧格式
                if not temp_mail_config:
                    temp_mail_config = email_config.get('temp_mail', {})
                
                full_temp_mail = temp_mail_config.get('username', '')
                self.temp_mail_pin = temp_mail_config.get('pin', temp_mail_config.get('epin', ''))
                
                if full_temp_mail and '@' in full_temp_mail:
                    self.temp_mail_username, extension = full_temp_mail.split("@", 1)
                    self.temp_mail_extension = f"@{extension}"
                    self.logger.debug(f"临时邮箱: {self.temp_mail_username}{self.temp_mail_extension}")
                elif full_temp_mail:
                    self.temp_mail_username = full_temp_mail
                    self.temp_mail_extension = "@mailto.plus"
                else:
                    self.temp_mail_username = self.username
                    self.temp_mail_extension = f'@{self.domain}'
            else:
                self.temp_mail_username = self.username
                self.temp_mail_extension = f'@{self.domain}'
                self.temp_mail_pin = ''
                
        except Exception as e:
            self.logger.error(f"加载临时邮箱配置失败: {str(e)}")
            self.temp_mail_username = self.username
            self.temp_mail_extension = f'@{self.domain}'
            self.temp_mail_pin = ''
    
    def get_verification_code(self, max_retries: int = 20, retry_interval: int = 5, registration_time: float = None, is_email_code_mode: bool = True) -> Optional[str]:
        """
        获取邮箱验证码 - 统一tempmail、IMAP和BC1P临时邮箱三种方式
        
        Args:
            max_retries: 最大重试次数（默认20次）
            retry_interval: 重试间隔(秒)
            registration_time: 注册开始时间戳（只获取此时间之后的邮件）
            is_email_code_mode: 是否为验证码注册模式（用于区分注册/登录场景）
            
        Returns:
            str: 验证码，如果获取失败返回None
        """
        # 判断是否使用BC1P临时邮箱
        if self.bc1p_manager:
            # 使用BC1P临时邮箱方式获取验证码
            return self._get_verification_code_via_bc1p(max_retries, retry_interval)
        # 判断是否使用IMAP：有imap_manager实例就使用IMAP
        elif self.imap_manager:
            # 使用IMAP方式获取验证码（包括2925和域名转发到QQ/163）
            return self._get_verification_code_via_imap(max_retries, retry_interval, registration_time, is_email_code_mode)
        else:
            # 使用tempmail方式获取验证码（域名转发到临时邮箱）
            return self._get_verification_code_via_tempmail(max_retries, retry_interval, registration_time, is_email_code_mode)
    
    def _get_verification_code_via_bc1p(self, max_retries: int, retry_interval: int) -> Optional[str]:
        """通过BC1P临时邮箱方式获取验证码"""
        try:
            self.logger.info("使用BC1P临时邮箱方式获取验证码")
            
            # 调用BC1P临时邮箱管理器获取验证码
            code = self.bc1p_manager.get_verification_code(
                email=self.email_address,
                max_retries=max_retries,
                retry_interval=retry_interval
            )
            
            if code:
                self.logger.info(f"🎉 通过BC1P临时邮箱成功获取验证码: {code}")
            else:
                self.logger.error("❌ 通过BC1P临时邮箱获取验证码失败")
            
            return code
            
        except Exception as e:
            self.logger.error(f"BC1P临时邮箱获取验证码失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def _get_verification_code_via_imap(self, max_retries: int, retry_interval: int, registration_time: float = None, is_email_code_mode: bool = True) -> Optional[str]:
        """通过IMAP方式获取验证码"""
        try:
            self.logger.info("使用IMAP方式获取验证码")
            
            # 设置注册时间（用于过滤邮件）
            if registration_time is None:
                registration_time = time.time()
            self.imap_manager.registration_start_time = registration_time
            
            # 确定要匹配的邮箱地址
            # 如果是2925子邮箱模式，需要匹配子邮箱地址
            # 如果是域名+QQ模式，需要匹配QQ邮箱地址（因为收件人是QQ邮箱）
            if '+' in self.email_address:
                # 2925子邮箱模式
                match_email = self.email_address
            else:
                # 域名+QQ模式：传入None，不检查收件人
                match_email = None
            
            # 调用IMAP管理器获取验证码
            code = self.imap_manager.get_verification_code(
                max_retries=max_retries,
                retry_interval=retry_interval,
                registration_time=registration_time,
                sub_account=match_email,  # 传入要匹配的邮箱地址
                is_email_code_mode=is_email_code_mode  # 传入注册模式
            )
            
            if code:
                self.logger.info(f"🎉 通过IMAP成功获取验证码: {code}")
            else:
                self.logger.error("❌ 通过IMAP获取验证码失败")
            
            return code
            
        except Exception as e:
            self.logger.error(f"IMAP获取验证码失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def _get_verification_code_via_tempmail(self, max_retries: int, retry_interval: int, registration_time: float = None, is_email_code_mode: bool = True) -> Optional[str]:
        """通过tempmail方式获取验证码"""
        try:
            from datetime import datetime, timedelta
            
            self.logger.debug(f"开始获取验证码: {self.email_address}")
            self.logger.debug(f"最大重试次数: {max_retries}, 重试间隔: {retry_interval}秒")
            
            # 记录注册时间（用于过滤邮件）
            if registration_time is None:
                registration_time = time.time()
            self.logger.info(f"只获取时间戳 {registration_time} ({datetime.fromtimestamp(registration_time).strftime('%Y-%m-%d %H:%M:%S')}) 之后的邮件")
            
            # 记录开始获取时的邮件ID，用于过滤旧邮件
            starting_mail_id = None
            
            # 构建完整的临时邮箱地址
            full_temp_email = f"{self.temp_mail_username}{self.temp_mail_extension}"
            self.logger.debug(f"使用临时邮箱地址: {full_temp_email}")
            
            # 开始重试循环
            for attempt in range(max_retries):
                self.logger.debug(f"等待验证码... ({(attempt + 1) * retry_interval}/{max_retries * retry_interval}秒)")
                
                try:
                    # 获取邮件列表 - 构建API URL
                    # 根据PIN码是否为空来决定是否包含epin参数
                    if self.temp_mail_pin:
                        mail_list_url = f"https://tempmail.plus/api/mails?email={full_temp_email}&limit=20&epin={self.temp_mail_pin}"
                        self.logger.debug(f"使用PIN码访问")
                    else:
                        mail_list_url = f"https://tempmail.plus/api/mails?email={full_temp_email}&limit=20"
                        self.logger.debug("无密码保护模式访问")
                    self.logger.debug(f"请求邮件列表")
                    
                    response = self.session.get(mail_list_url, timeout=10)
                    self.logger.debug(f"响应状态: {response.status_code}")
                    
                    if response.status_code != 200:
                        error_msg = f"❌ 获取邮件列表失败: HTTP {response.status_code}"
                        self.logger.error(error_msg)
                        self.logger.error(f"完整响应内容: {response.text}")
                        
                        # 分析具体错误原因
                        if response.status_code == 404:
                            self.logger.error("🔍 可能原因: 临时邮箱地址不存在或已过期")
                        elif response.status_code == 403:
                            self.logger.error("🔍 可能原因: PIN码错误或权限不足")
                        elif response.status_code == 500:
                            self.logger.error("🔍 可能原因: tempmail.plus服务器内部错误")
                        
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                        
                    try:
                        mail_list_data = response.json()
                        # 🔍 调试：打印邮件列表数据结构，查看时间字段
                        self.logger.debug(f"📦 邮件列表数据: {mail_list_data}")
                    except Exception as json_error:
                        self.logger.error(f"解析邮件列表JSON失败: {str(json_error)}")
                        self.logger.error(f"响应内容: {response.text}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                        
                    if not mail_list_data.get("result"):
                        self.logger.debug("⚠️ 临时邮箱中暂无新邮件")
                        
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                        
                    # 获取最新邮件的ID
                    first_id = mail_list_data.get("first_id")
                    if not first_id:
                        self.logger.debug("未找到邮件ID")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                    
                    # 从邮件列表中提取时间信息（用于显示）
                    mail_list = mail_list_data.get("mail_list", [])
                    mail_time_str = ""
                    if mail_list and len(mail_list) > 0:
                        mail_time_str = mail_list[0].get("time", "")
                    
                    # 第一次获取时记录起始邮件ID（但不跳过第一次的邮件，要检查时间）
                    if attempt == 0 and starting_mail_id is None:
                        starting_mail_id = first_id
                        self.logger.debug(f"📌 记录起始邮件ID: {starting_mail_id}（首次获取，检查时间后决定是否使用）")
                        if mail_time_str:
                            self.logger.debug(f"📌 起始邮件时间: {mail_time_str} (临时邮箱显示)")
                    
                    # 从第二次尝试开始（attempt>0），检查邮件ID：只处理比起始ID大的邮件（不删除，只跳过）
                    if attempt > 0 and starting_mail_id and first_id <= starting_mail_id:
                        self.logger.debug(f"⏭️ 跳过旧邮件ID: {first_id} (起始ID: {starting_mail_id}，已处理过，继续等待）")
                        if mail_time_str:
                            self.logger.debug(f"   邮件时间: {mail_time_str}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                    
                    # 显示新邮件的信息
                    self.logger.info(f"📬 找到邮件ID: {first_id} (尝试次数: {attempt+1}, 起始ID: {starting_mail_id or '无'})")
                    
                    # 检查邮件时间是否在点击时间之后
                    if mail_time_str:
                        try:
                            # 解析邮件时间: "2025-10-08 13:25:56" (邮件列表显示的时间)
                            mail_dt = datetime.strptime(mail_time_str, "%Y-%m-%d %H:%M:%S")
                            # 点击时间（北京时间UTC+8）需要减5小时转换为邮件时区（UTC+3），再减2秒容错
                            click_dt = datetime.fromtimestamp(registration_time)
                            click_dt_mail_tz = click_dt - timedelta(hours=5) - timedelta(seconds=2)  # 5小时时区差，减2秒容错
                            time_diff = (mail_dt - click_dt_mail_tz).total_seconds()
                            
                            self.logger.debug(f"⏰ 邮件时间: {mail_time_str} (邮件列表显示)")
                            self.logger.debug(f"⏰ 点击时间: {click_dt.strftime('%Y-%m-%d %H:%M:%S')} (北京UTC+8) → {click_dt_mail_tz.strftime('%Y-%m-%d %H:%M:%S')} (邮件时区UTC+3，-2秒容错)")
                            self.logger.debug(f"⏰ 时间差: {time_diff:.1f}秒")
                            
                            # 如果邮件时间早于点击时间（含2秒容错），跳过这封邮件（不删除，只跳过）
                            if time_diff < 0:
                                self.logger.debug(f"⏭️ 跳过旧邮件: 邮件时间早于点击时间（含2秒容错） {abs(time_diff):.1f}秒（不删除，继续等待）")
                                if attempt < max_retries - 1:
                                    time.sleep(retry_interval)
                                continue
                            else:
                                self.logger.debug(f"✅ 邮件时间符合: 晚于点击时间（含2秒容错） {time_diff:.1f}秒")
                                
                        except Exception as e:
                            self.logger.debug(f"⏰ 邮件时间: {mail_time_str} (原始)")
                            self.logger.debug(f"时间解析失败: {e}")
                            # 时间解析失败时，继续处理（不过滤）
                    
                    # 获取具体邮件内容
                    if self.temp_mail_pin:
                        mail_detail_url = f"https://tempmail.plus/api/mails/{first_id}?email={full_temp_email}&epin={self.temp_mail_pin}"
                    else:
                        mail_detail_url = f"https://tempmail.plus/api/mails/{first_id}?email={full_temp_email}"
                    self.logger.debug(f"请求邮件详情")
                    
                    mail_detail_response = self.session.get(mail_detail_url, timeout=10)
                    self.logger.debug(f"详情响应状态: {mail_detail_response.status_code}")
                    
                    if mail_detail_response.status_code != 200:
                        self.logger.error(f"获取邮件详情失败: HTTP {mail_detail_response.status_code}")
                        self.logger.error(f"响应内容: {mail_detail_response.text[:500]}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                        
                    try:
                        mail_detail_data = mail_detail_response.json()
                    except Exception as json_error:
                        self.logger.error(f"解析邮件详情JSON失败: {str(json_error)}")
                        self.logger.error(f"响应内容: {mail_detail_response.text}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                        
                    if not mail_detail_data.get("result"):
                        self.logger.error("邮件详情解析失败")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                    
                    # 从邮件内容中提取验证码
                    mail_text = mail_detail_data.get("text", "")
                    mail_subject = mail_detail_data.get("subject", "")
                    mail_html = mail_detail_data.get("html", "")
                    
                    self.logger.info(f"📧 找到邮件主题: {mail_subject}")
                    self.logger.debug(f"邮件文本内容(前200字符): {mail_text[:200]}")
                    self.logger.debug(f"邮件HTML内容(前200字符): {mail_html[:200]}")
                    
                    # 检查是否是Cursor验证码邮件
                    if not self._is_cursor_verification_email(mail_subject, mail_text, is_email_code_mode):
                        self.logger.debug("不是Cursor验证码邮件，继续等待...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_interval)
                        continue
                    
                    # 提取验证码
                    code = self._extract_verification_code_from_content(mail_text, mail_html)
                    if code:
                        self.logger.info(f"🎉 成功获取验证码: {code}")
                        # 不在这里清空，等验证码输入完成后再清空
                        return code
                    else:
                        self.logger.warning("未能从邮件中提取验证码")
                        self.logger.debug(f"完整邮件文本: {mail_text}")
                        self.logger.debug(f"完整邮件HTML: {mail_html}")
                        
                except requests.RequestException as e:
                    self.logger.error(f"网络请求失败: {str(e)}")
                except Exception as e:
                    self.logger.error(f"处理邮件时发生错误: {str(e)}")
                    import traceback
                    self.logger.error(f"错误详情: {traceback.format_exc()}")
                
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
                    
            self.logger.error("获取验证码超时")
            return None
            
        except Exception as e:
            self.logger.error(f"获取验证码失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def _is_cursor_verification_email(self, subject: str, text: str, is_email_code_mode: bool = True) -> bool:
        """检查是否是Cursor验证码邮件（根据注册模式动态过滤）"""
        subject_lower = subject.lower()
        text_lower = text.lower()
        
        self.logger.debug(f"检查邮件主题: {subject_lower}")
        
        # 检查主题关键词（只保留核心关键词）
        subject_keywords = ['登录', '注册', 'sign', 'register', 'signup']
        has_subject_keyword = any(keyword in subject_lower or keyword in subject for keyword in subject_keywords)
        
        # 检查内容关键词
        content_keywords = ['cursor', 'one-time code', 'verification code', 'sign in']
        has_content_keyword = any(keyword in text_lower for keyword in content_keywords)
        
        self.logger.debug(f"主题关键词匹配: {has_subject_keyword}")
        self.logger.debug(f"内容关键词匹配: {has_content_keyword}")
        
        is_cursor_email = has_subject_keyword or has_content_keyword
        self.logger.debug(f"是否为Cursor验证码邮件: {is_cursor_email}")
        
        return is_cursor_email
    
    def _extract_verification_code_from_content(self, mail_text: str, mail_html: str = "") -> Optional[str]:
        """
        从邮件内容中提取验证码
        使用正则表达式匹配6位数字验证码
        """
        self.logger.debug("开始提取验证码...")
        
        # 模式1: 提取6位数字验证码，确保不紧跟在字母或域名相关符号后面
        self.logger.debug("尝试模式1: 常规6位数字")
        code_match = re.search(r"(?<![a-zA-Z@.])\b(\d{6})\b", mail_text)
        if code_match:
            code = code_match.group(1)
            self.logger.debug(f"✅ 通过常规模式匹配到验证码: {code}")
            return code
        
        # 模式2: 从HTML内容中查找
        if mail_html:
            self.logger.debug("尝试模式2: HTML标签内6位数字")
            code_match_html = re.search(r"<[^>]*>(\d{6})<", mail_html)
            if code_match_html:
                code = code_match_html.group(1)
                self.logger.debug(f"✅ 通过HTML标签模式匹配到验证码: {code}")
                return code
        
        # 模式3: Cursor邮件特定格式 - 带空格的验证码
        self.logger.debug("尝试模式3: 带空格的验证码格式")
        pattern_spaced = r'one-time code is:\s*\n*\s*(\d\s+\d\s+\d\s+\d\s+\d\s+\d)'
        match = re.search(pattern_spaced, mail_text, re.IGNORECASE)
        if match:
            code = match.group(1).replace(" ", "")
            self.logger.debug(f"✅ 通过带空格模式匹配到验证码: {code}")
            return code
        
        # 模式4: Cursor邮件特定格式 - 连续6位验证码
        self.logger.debug("尝试模式4: one-time code is格式")
        pattern_continuous = r'one-time code is:\s*\n*\s*(\d{6})'
        match = re.search(pattern_continuous, mail_text, re.IGNORECASE)
        if match:
            code = match.group(1)
            self.logger.debug(f"✅ 通过连续数字模式匹配到验证码: {code}")
            return code
        
        # 模式5: 更宽松的6位数字匹配
        self.logger.debug("尝试模式5: 宽松6位数字匹配")
        all_codes = re.findall(r'\b\d{6}\b', mail_text)
        if all_codes:
            # 过滤掉可能是日期或其他数字的内容
            for code in all_codes:
                if not self._is_likely_date_or_other(code, mail_text):
                    self.logger.debug(f"✅ 通过宽松模式匹配到验证码: {code}")
                    return code
        
        self.logger.debug("❌ 所有模式均未匹配到验证码")
        return None
    
    def _is_likely_date_or_other(self, code: str, text: str) -> bool:
        """检查6位数字是否可能是日期或其他非验证码内容"""
        # 简单检查：如果在邮箱地址附近，可能不是验证码
        code_index = text.find(code)
        if code_index == -1:
            return False
            
        # 检查前后文本
        start = max(0, code_index - 20)
        end = min(len(text), code_index + len(code) + 20)
        context = text[start:end]
        
        # 如果包含@符号，可能是邮箱地址的一部分
        if '@' in context:
            self.logger.debug(f"代码 {code} 可能是邮箱地址的一部分: {context}")
            return True
            
        return False
    
    def _cleanup_tempmail_plus(self, email_address: str, first_id: str, pin: str) -> bool:
        """清理临时邮箱中的邮件"""
        try:
            self.logger.debug(f"开始清理临时邮件: {first_id}")
            
            delete_url = "https://tempmail.plus/api/mails/"
            payload = {
                "email": email_address,
                "first_id": first_id,
            }
            
            # 只有PIN不为空时才添加epin参数
            if pin:
                payload["epin"] = pin
            
            self.logger.debug(f"清理邮件URL: {delete_url}")
            self.logger.debug(f"清理邮件参数: {payload}")
            
            # 最多尝试5次
            for attempt in range(5):
                self.logger.debug(f"清理邮件尝试 {attempt + 1}/5")
                
                response = self.session.delete(delete_url, data=payload, timeout=10)
                self.logger.debug(f"清理响应状态码: {response.status_code}")
                
                try:
                    result = response.json().get("result")
                    self.logger.debug(f"清理结果: {result}")
                    
                    if result is True:
                        self.logger.debug("✅ 成功清理临时邮件")
                        return True
                except Exception as e:
                    self.logger.debug(f"解析清理响应失败: {str(e)}")
                    self.logger.debug(f"响应内容: {response.text}")
                
                if attempt < 4:  # 不是最后一次尝试
                    time.sleep(0.5)
            
            self.logger.debug("❌ 清理临时邮件失败")
            return False
            
        except Exception as e:
            self.logger.error(f"清理临时邮件时发生错误: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")
            return False


class ConfigAdapter:
    """
    配置适配器
    用于测试和调试
    """
    
    def __init__(self, temp_mail_username="", temp_mail_extension="@tempmail.plus", temp_mail_pin=""):
        self.temp_mail_username = temp_mail_username
        self.temp_mail_extension = temp_mail_extension 
        self.temp_mail_pin = temp_mail_pin
        
    def get_temp_mail(self):
        return self.temp_mail_username
    
    def get_temp_mail_ext(self):
        return self.temp_mail_extension
    
    def get_temp_mail_epin(self):
        return self.temp_mail_pin


# 测试函数
def test_email_verification():
    """测试验证码获取功能"""
    print("🧪 测试邮箱验证码处理器...")
    
    # 创建测试配置
    test_config = ConfigAdapter(
        temp_mail_username="testuser",
        temp_mail_extension="@tempmail.plus", 
        temp_mail_pin="your_pin_here"
    )
    
    # 创建处理器
    handler = EmailVerificationHandler("testuser@tempmail.plus")
    
    # 测试获取验证码
    code = handler.get_verification_code(max_retries=3, retry_interval=2)
    
    if code:
        print(f"✅ 成功获取验证码: {code}")
    else:
        print("❌ 获取验证码失败")
    
    return code


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    test_email_verification()