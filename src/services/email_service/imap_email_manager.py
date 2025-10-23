#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IMAP邮箱管理器 - 支持邮件接收和验证码提取
支持2925邮箱、QQ邮箱等IMAP协议的邮箱
"""

import datetime
import email
import imaplib
import logging
import random
import re
import string
import time
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Optional, Tuple, List, Dict


class ImapEmailManager:
    """IMAP邮箱管理类，用于处理邮箱登录、验证码获取等功能"""

    def __init__(self, config_manager=None):
        """
        初始化IMAP邮箱管理器
        
        Args:
            config_manager: 配置管理器，需要有 get_email_config() 方法
        """
        self.config_manager = config_manager
        self.imap = None
        self.is_logged_in = False
        self.logger = logging.getLogger(__name__)
        self.registration_start_time = None  # 注册开始时间戳

    @property
    def mail_config(self):
        """获取最新的IMAP邮箱配置"""
        if self.config_manager:
            email_config = self.config_manager.get_email_config()
            email_type = email_config.get('email_type', 'domain_forward')
            
            # 2925邮箱模式
            if email_type == 'imap':
                return email_config.get('imap_mail', {})
            
            # 域名转发模式，根据转发目标返回对应配置
            elif email_type == 'domain_forward':
                domain_forward = email_config.get('domain_forward', {})
                forward_target = domain_forward.get('forward_target', 'temp_mail')
                
                if forward_target == 'qq':
                    return domain_forward.get('qq_mail', {})
                elif forward_target == '163':
                    return domain_forward.get('163_mail', {})
        
        return {}

    @property
    def email(self):
        """获取IMAP邮箱地址"""
        return self.mail_config.get("email", "")

    @property
    def password(self):
        """获取邮箱密码/授权码"""
        return self.mail_config.get("password", "")

    @property
    def imap_server(self):
        """获取IMAP服务器地址"""
        # 如果用户配置了IMAP服务器，直接使用
        configured_server = self.mail_config.get("imap_server", "")
        if configured_server:
            return configured_server
        
        # 如果没有配置，根据邮箱域名自动匹配
        if self.email:
            server, _ = self.get_imap_settings_by_domain(self.email)
            return server
        return ""

    @property
    def imap_port(self):
        """获取IMAP服务器端口"""
        return self.mail_config.get("imap_port", 993)

    @property
    def use_random_email(self):
        """是否使用随机子邮箱"""
        return self.mail_config.get("use_random_email", False)

    @property
    def register_email(self):
        """获取注册邮箱基础地址"""
        return self.mail_config.get("register_email", "")

    def get_imap_settings_by_domain(self, email_address: str) -> Tuple[str, int]:
        """
        根据邮箱域名自动匹配IMAP服务器配置
        
        Args:
            email_address: 邮箱地址
            
        Returns:
            tuple: (imap_server, imap_port)
        """
        if not email_address or '@' not in email_address:
            return "", 993

        domain = email_address.split('@')[-1].lower()

        # 支持的邮箱配置
        imap_configs = {
            "2925.com": ("imap.2925.com", 993),
            "qq.com": ("imap.qq.com", 993),
            "163.com": ("imap.163.com", 993),
            "126.com": ("imap.126.com", 993),
            "gmail.com": ("imap.gmail.com", 993),
            "outlook.com": ("outlook.office365.com", 993),
            "hotmail.com": ("outlook.office365.com", 993),
        }

        return imap_configs.get(domain, ("", 993))

    def _connect_imap(self) -> Tuple[bool, str, Optional[Exception]]:
        """
        连接IMAP服务器并验证账号
        
        Returns:
            tuple: (是否成功, 消息, 错误详情)
        """
        try:
            # 关闭之前的连接
            if self.imap:
                try:
                    self.imap.logout()
                except:
                    pass

            # 获取IMAP服务器配置
            imap_server = self.imap_server
            imap_port = self.imap_port

            if not imap_server:
                return False, "无法自动匹配IMAP服务器，请手动指定", None

            self.logger.info(f"尝试连接邮箱服务器: {imap_server}:{imap_port}")
            
            # 连接到IMAP服务器
            self.imap = imaplib.IMAP4_SSL(imap_server, imap_port)

            # 登录验证
            self.logger.info(f"尝试验证邮箱: {self.email}")
            self.imap.login(self.email, self.password)
            self.logger.info(f"邮箱验证成功: {self.email}")

            # 设置状态
            self.is_logged_in = True

            return True, "邮箱验证成功", None

        except imaplib.IMAP4.error as e:
            self.logger.error(f"邮箱验证失败: {str(e)}")
            error_msg = str(e)
            
            if "LOGIN failed" in error_msg or "AUTHENTICATIONFAILED" in error_msg.upper():
                return False, "邮箱登录失败：用户名或授权码错误。请确保：1. 在邮箱网页版设置中开启了IMAP服务。 2. 使用的是生成的'授权码'，而不是邮箱登录密码。", e
            elif "AUTHENTICATE failed" in error_msg:
                return False, "邮箱身份验证失败：请检查您的授权码是否正确，并确认邮箱已开启IMAP服务。", e
            elif "Connection refused" in error_msg:
                return False, "无法连接到邮箱服务器：连接被拒绝。请检查网络防火墙设置。", e
            elif "timed out" in error_msg:
                return False, "连接邮箱服务器超时：请检查您的网络连接是否正常。", e
            else:
                return False, f"邮箱验证失败，底层错误: {str(e)}", e

        except Exception as e:
            self.logger.error(f"邮箱连接过程中发生未知错误: {str(e)}", exc_info=True)
            return False, f"发生未知错误: {str(e)}", e

    def check_login_status(self) -> bool:
        """
        检查登录状态是否有效
        
        Returns:
            bool: 是否已登录
        """
        if not self.imap or not self.is_logged_in:
            # 尝试重新连接并验证
            success, _, _ = self._connect_imap()
            return success

        try:
            # 尝试执行一个简单的IMAP命令来检查连接
            status, _ = self.imap.noop()
            return status == 'OK'
        except:
            return False

    def generate_sub_account(self, suffix: str = None, firstname: str = None, lastname: str = None) -> Tuple[Optional[str], str]:
        """
        生成子账号（支持2925无限子邮箱）
        
        Args:
            suffix: 子账号后缀，如果为None则随机生成
            firstname: 名字，用于生成子邮箱前缀
            lastname: 姓氏，暂未使用
            
        Returns:
            tuple: (子账号, 消息)
        """
        try:
            # 如果不使用随机子邮箱，则直接返回配置的注册邮箱
            if not self.use_random_email:
                if not self.register_email:
                    return None, "未配置注册邮箱，请在设置中配置"
                return self.register_email, "使用配置的注册邮箱"

            # 使用随机子邮箱
            if not self.register_email:
                return None, "未配置注册邮箱，无法生成随机子邮箱，请在设置中配置"

            # 检查注册邮箱格式
            if '@' not in self.register_email:
                return None, "注册邮箱格式不正确，无法生成随机子邮箱"

            # 提取域名部分
            domain = self.register_email.split('@')[-1]
            base_prefix = self.register_email.split('@')[0]

            # 如果没有提供后缀，则生成随机后缀
            if not suffix:
                # 生成3-4位随机字符（2925邮箱专用，简短易读）
                random_length = random.randint(2, 4)
                suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=random_length))

            # 生成随机子邮箱
            if base_prefix:
                # 2925邮箱支持 username+suffix@domain 格式
                sub_account = f"{base_prefix}+{suffix}@{domain}"
            elif firstname:
                # 如果提供了firstname且@前没有字符
                sub_account = f"{firstname.lower()}_{suffix}@{domain}"
            else:
                # 只使用随机后缀
                sub_account = f"{suffix}@{domain}"

            return sub_account, "随机子邮箱生成成功"

        except Exception as e:
            return None, f"生成子账号失败: {str(e)}"

    def get_verification_code(
        self, 
        max_retries: int = 40, 
        retry_interval: int = 2,
        time_limit_minutes: int = None,
        registration_time: float = None,
        sub_account: str = None,
        use_stored_registration_time: bool = True,
        is_email_code_mode: bool = True
    ) -> Optional[str]:
        """
        从邮箱中获取验证码
        
        Args:
            max_retries: 最大重试次数（默认40次）
            retry_interval: 重试间隔(秒，默认2秒)
            time_limit_minutes: 验证码邮件的时间限制(分钟)
            registration_time: 第二次点击验证码登录的时间戳
            sub_account: 子邮箱账号
            use_stored_registration_time: 是否使用存储的注册时间
            is_email_code_mode: 是否为验证码注册模式（用于区分注册/登录场景）
            
        Returns:
            str: 验证码，如果未找到则返回None
        """
        # 连接收件邮箱
        success, message, _ = self._connect_imap()
        if not success:
            self.logger.error(f"连接收件邮箱失败: {message}")
            return None

        self.logger.info("已连接收件邮箱")

        # 记录当前时间，作为验证码查找的起始时间点
        search_start_time = datetime.now().replace(tzinfo=None)

        # 处理注册时间逻辑
        if registration_time is None and use_stored_registration_time and self.registration_start_time:
            registration_time = self.registration_start_time
            self.logger.info(f"使用存储的注册时间: {registration_time}")

        # 解析注册时间为datetime对象（供动态容错使用）
        base_time_limit = None
        if registration_time:
            if isinstance(registration_time, (int, float)):
                base_time_limit = datetime.fromtimestamp(registration_time)
            elif isinstance(registration_time, str):
                try:
                    base_time_limit = datetime.strptime(registration_time, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        base_time_limit = datetime.fromtimestamp(float(registration_time))
                    except:
                        self.logger.warning(f"无法解析注册时间: {registration_time}")
            elif isinstance(registration_time, datetime):
                base_time_limit = registration_time
        
        # 初始时间限制（10秒容错）
        if base_time_limit:
            time_limit = base_time_limit - timedelta(seconds=10)
            self.logger.info(f"初始时间限制: {time_limit} (10秒容错)")
        elif time_limit_minutes:
            time_limit = search_start_time - timedelta(minutes=time_limit_minutes)
            self.logger.info(f"只获取{time_limit_minutes}分钟内的验证码邮件")
        else:
            time_limit = None
            self.logger.info("不限制验证码邮件的时间")

        if sub_account:
            self.logger.info(f"过滤条件：子邮箱 {sub_account}（仅2925模式生效）")

        self.logger.info(f"开始获取邮箱验证码，最多尝试{max_retries}次，每次间隔{retry_interval}秒...")

        # 记录已检查过的邮件特征
        checked_email_signatures = set()

        for attempt in range(max_retries):
            self.logger.info(f"第{attempt + 1}次尝试获取验证码...")

            try:
                # 选择收件箱
                status, data = self.imap.select("INBOX")
                if status != "OK":
                    self.logger.error("选择收件箱失败")
                    if attempt < max_retries - 1:
                        time.sleep(retry_interval)
                    continue

                num_messages = int(data[0].decode())
                self.logger.info(f"收件箱共有 {num_messages} 封邮件")

                if num_messages == 0:
                    self.logger.info("收件箱为空，等待新邮件...")
                    if attempt < max_retries - 1:
                        time.sleep(retry_interval)
                    continue

                # 计算检查范围：最近5封邮件
                start_check = max(1, num_messages - 4)

                # 从最新到最旧检查最近5封邮件
                for i in range(num_messages, start_check - 1, -1):
                    self.logger.debug(f"检查邮件 {i}")

                    # 获取邮件内容
                    status, msg_data = self.imap.fetch(str(i), "(RFC822)")
                    if status != "OK":
                        self.logger.error(f"获取邮件 {i} 失败")
                        continue

                    # 解析邮件
                    raw_email = msg_data[0][1]
                    email_message = email.message_from_bytes(raw_email)

                    # 生成邮件唯一签名
                    message_id = email_message.get("Message-ID", "")
                    date_header = email_message.get("Date", "")
                    email_signature = f"{message_id}|{date_header}"

                    # 如果已经检查过这封邮件，跳过
                    if email_signature in checked_email_signatures:
                        self.logger.debug(f"邮件 {i} 已检查过，跳过")
                        continue

                    # 标记为已检查
                    checked_email_signatures.add(email_signature)

                    # 解析发件人
                    from_header = email_message.get("From", "")
                    from_name, from_addr = self._parse_email_address(from_header)
                    from_field = (from_name + " " + from_addr).lower()

                    # 解析主题
                    subject = self._decode_header(email_message.get("Subject", "")).lower()

                    # 解析日期（需要转换为本地时间以便正确比较）
                    date_str = email_message.get("Date", "")
                    date_obj = None
                    try:
                        date_obj = email.utils.parsedate_to_datetime(date_str)
                        if date_obj.tzinfo:
                            # 转换为本地时间（naive datetime）
                            import datetime as dt
                            date_obj = date_obj.astimezone(dt.timezone(dt.timedelta(hours=8)))
                            date_obj = date_obj.replace(tzinfo=None)
                    except:
                        self.logger.warning(f"无法解析邮件 {i} 的日期")
                        continue

                    self.logger.info(f"📧 邮件{i}: 发件人={from_addr}, 主题={subject[:30]}, 日期={date_str}")

                    # 1. 检查时间是否在限制范围内
                    is_recent = True
                    if time_limit and date_obj:
                        if date_obj < time_limit:
                            is_recent = False
                            self.logger.info(f"  ⏭️ 跳过（时间早）: 邮件={date_obj.strftime('%Y-%m-%d %H:%M:%S')}, 限制={time_limit.strftime('%Y-%m-%d %H:%M:%S')}")
                            continue
                        else:
                            self.logger.info(f"  ✅ 时间符合: 邮件={date_obj.strftime('%Y-%m-%d %H:%M:%S')}")

                    # 2. 检查发件人是否是Cursor
                    is_cursor_email = (
                        "no-reply@cursor.sh" in from_addr.lower() or
                        "cursor" in from_field or
                        "cursor" in subject
                    )
                    
                    if not is_cursor_email:
                        self.logger.info(f"  ⏭️ 跳过（发件人不是Cursor）")
                        continue
                    else:
                        self.logger.info(f"  ✅ 发件人是Cursor")

                    # 3. 检查主题，匹配验证码相关邮件
                    is_verification_email = (
                        "登录" in subject or     # 中文"登录"
                        "注册" in subject or     # 中文"注册"
                        "sign" in subject or     # 英文"sign in"
                        "register" in subject or # 英文"register"
                        "signup" in subject or   # 英文"sign up"
                        "验证" in subject or     # 中文"验证"
                        "挑战" in subject or     # 中文"挑战"
                        "verification" in subject or
                        "code" in subject or
                        "verify" in subject or
                        "confirm" in subject or
                        "challenge" in subject   # 英文"挑战"
                    )
                    
                    if not is_verification_email:
                        self.logger.info(f"  ⏭️ 跳过（主题不包含登录/验证关键词）")
                        continue
                    else:
                        self.logger.info(f"  ✅ 主题包含登录/验证关键词")

                    if is_cursor_email and is_verification_email and is_recent:
                        self.logger.info(f"找到符合条件的验证码邮件: {i}")

                        # 提取邮件正文
                        body = self._extract_email_body(email_message)

                        # 从邮件内容中提取验证码
                        verification_code = self._extract_verification_code(body)

                        if verification_code:
                            self.logger.info(f"成功获取验证码: {verification_code}")
                            return verification_code
                        else:
                            self.logger.info("邮件内容中未找到验证码")

                # 如果循环结束还没找到
                self.logger.info(f"检查完所有新邮件，未找到验证码，等待 {retry_interval} 秒后重试...")
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)

            except Exception as e:
                self.logger.error(f"获取验证码时出错: {str(e)}", exc_info=True)
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)

        self.logger.error(f"在 {max_retries} 次尝试内未能获取到验证码")
        return None

    def _extract_verification_code(self, email_content: str) -> Optional[str]:
        """
        从邮件内容中提取验证码（支持中英文格式）
        
        Args:
            email_content: 邮件内容
            
        Returns:
            str: 验证码，如果未找到则返回None
        """
        if not email_content:
            return None

        self.logger.info("开始从邮件内容中提取验证码")

        # 避免将邮箱地址中的数字误识别为验证码
        if self.email:
            email_content = email_content.replace(self.email, '')

        # 模式1: 英文格式带空格的验证码
        pattern_spaced = r'one-time code is:\s*\n*\s*(\d\s+\d\s+\d\s+\d\s+\d\s+\d)'
        match = re.search(pattern_spaced, email_content, re.IGNORECASE)
        if match:
            code = match.group(1).replace(" ", "")
            self.logger.info(f"✅ 找到带空格的验证码: {code}")
            return code

        # 模式2: 英文格式连续的6位验证码
        pattern_continuous = r'one-time code is:\s*\n*\s*(\d{6})'
        match = re.search(pattern_continuous, email_content, re.IGNORECASE)
        if match:
            code = match.group(1)
            self.logger.info(f"✅ 找到连续的验证码: {code}")
            return code

        # 模式3: 中文格式 - 验证码单独一行（6位数字）
        # 匹配独立成行的6位数字
        pattern_chinese = r'(?:验证码|code)[：:是]?\s*[\r\n]+\s*(\d{6})\s*[\r\n]'
        match = re.search(pattern_chinese, email_content, re.IGNORECASE)
        if match:
            code = match.group(1)
            self.logger.info(f"✅ 找到中文格式验证码: {code}")
            return code

        # 模式4: 更宽松的匹配 - 查找独立的6位数字（避免误匹配）
        # 排除明显是日期、时间、邮箱的数字
        lines = email_content.split('\n')
        for line in lines:
            line = line.strip()
            # 如果这一行只有一个6位数字
            if re.match(r'^\d{6}$', line):
                self.logger.info(f"✅ 找到独立行6位验证码: {line}")
                return line

        self.logger.warning("❌ 未能从邮件内容中提取验证码")
        self.logger.debug(f"邮件内容前500字符: {email_content[:500]}")
        return None

    def logout(self) -> Tuple[bool, str]:
        """登出邮箱"""
        try:
            if self.imap:
                self.imap.logout()

            self.is_logged_in = False
            return True, "登出成功"
        except Exception as e:
            return False, f"登出失败: {str(e)}"

    def _extract_email_body(self, email_message) -> str:
        """提取邮件正文"""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # 跳过附件
                if "attachment" in content_disposition:
                    continue

                # 提取文本内容
                if content_type == "text/plain" or content_type == "text/html":
                    try:
                        body_part = part.get_payload(decode=True).decode()
                        body += body_part
                    except:
                        pass
        else:
            # 非多部分邮件
            try:
                body = email_message.get_payload(decode=True).decode()
            except:
                pass

        return body

    def _decode_header(self, header: str) -> str:
        """解码邮件头"""
        if not header:
            return ""

        try:
            decoded_header = decode_header(header)
            header_parts = []

            for content, encoding in decoded_header:
                if isinstance(content, bytes):
                    if encoding:
                        try:
                            header_parts.append(content.decode(encoding))
                        except:
                            header_parts.append(content.decode('utf-8', errors='replace'))
                    else:
                        header_parts.append(content.decode('utf-8', errors='replace'))
                else:
                    header_parts.append(content)

            return " ".join(header_parts)
        except:
            return header

    def _parse_email_address(self, address: str) -> Tuple[str, str]:
        """解析邮件地址"""
        if not address:
            return "", ""

        try:
            parsed = email.utils.parseaddr(address)
            name = self._decode_header(parsed[0])
            addr = parsed[1]
            return name, addr
        except:
            match = re.search(r'<([^>]+)>', address)
            if match:
                addr = match.group(1)
                name = address.split('<')[0].strip()
                return name, addr
            else:
                return "", address.strip()

