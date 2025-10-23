#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cookie解析器 - 解析Cursor的Cookie信息
"""

import base64
import json
import logging
import re
import time
import hashlib
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 移除对已删除api_client的依赖
from ..services.email_service.email_extractor import EmailExtractor


class CookieParser:
    """Cookie解析器，用于解析Cursor的Cookie信息"""
    
    def __init__(self, config=None):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.email_extractor = EmailExtractor(config)
    
    def parse_cookies(self, cookie_text: str) -> Tuple[bool, str, Optional[List[Dict]]]:
        """
        批量解析Cookie信息
        
        Args:
            cookie_text: Cookie文本，支持多种格式
            
        Returns:
            Tuple[bool, str, Optional[List[Dict]]]: (是否成功, 消息, 账号信息列表)
        """
        try:
            cookie_text = cookie_text.strip()
            if not cookie_text:
                return False, "请输入Cookie信息", None
            
            # 首先尝试直接解析JSON格式
            try:
                data = json.loads(cookie_text)
                if isinstance(data, list):
                    self.logger.info(f"📝 JSON批量导入: {len(data)}个账号")
                    return self._parse_json_accounts(data)
                elif isinstance(data, dict):
                    self.logger.info("📝 JSON导入: 1个账号")
                    return self._parse_json_accounts([data])
            except json.JSONDecodeError:
                # 不是JSON格式，继续使用token解析方式
                pass
            
            # 提取所有token
            tokens = self._extract_tokens(cookie_text)
            
            if not tokens:
                return False, "未找到有效的token，请确保包含有效的Cursor认证信息", None
            
            # 解析每个token
            parsed_accounts = []
            failed_accounts = []
            
            for i, token in enumerate(tokens, 1):
                success, message, account_info = self.parse_unified_token(token)
                if success and account_info:
                    account_info['import_index'] = i
                    parsed_accounts.append(account_info)
                else:
                    failed_accounts.append(f"Token{i}: {message}")
            
            # 生成结果消息
            if parsed_accounts:
                success_count = len(parsed_accounts)
                fail_count = len(failed_accounts)
                
                if fail_count == 0:
                    message = f"成功解析{success_count}个账号"
                else:
                    message = f"成功解析{success_count}个账号，{fail_count}个失败"
                
                return True, message, parsed_accounts
            else:
                message = "所有token解析失败"
                if failed_accounts:
                    message += f":\n" + "\n".join(failed_accounts)
                return False, message, None
                
        except Exception as e:
            self.logger.error(f"批量解析Cookie时出错: {str(e)}")
            return False, f"解析Cookie时出错: {str(e)}", None
    
    def _extract_tokens(self, text: str) -> List[str]:
        """从文本中提取所有token"""
        unique_tokens = []
        
        # 首先尝试解析为JSON格式
        try:
            data = json.loads(text)
            if isinstance(data, list):
                # JSON数组格式，直接返回特殊标记让上级知道这是完整JSON
                self.logger.info(f"检测到完整JSON格式，包含{len(data)}个账号，跳过token提取")
                return ['__JSON_COMPLETE__']  # 特殊标记
                    
            elif isinstance(data, dict):
                # 单个账号的JSON格式
                self.logger.info(f"检测到单个账号JSON格式，跳过token提取")
                return ['__JSON_SINGLE__']  # 特殊标记
                        
        except json.JSONDecodeError:
            # 不是JSON格式，继续使用正则表达式
            pass
        
        # 匹配完整格式：同时支持user_xxx::token和user_xxx%3A%3Atoken
        complete_pattern_url = r'(user_[^%\s]+%3A%3A[A-Za-z0-9+/=._-]+)'  # URL编码格式
        complete_pattern_colon = r'(user_[^:\s]+::[A-Za-z0-9+/=._-]+)'     # 冒号格式
        
        complete_matches = []
        complete_matches.extend(re.findall(complete_pattern_url, text))
        complete_matches.extend(re.findall(complete_pattern_colon, text))
        
        # 匹配纯JWT token（以ey开头）
        jwt_pattern = r'\b(ey[A-Za-z0-9+/=._-]{100,})\b'
        jwt_matches = re.findall(jwt_pattern, text)
        
        # 自动识别"user"开头或"账号"开头的行
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('user_') or line.startswith('账号'):
                # 从行中提取token - 支持两种格式
                token_match_url = re.search(r'(user_[^%\s]+%3A%3A[A-Za-z0-9+/=._-]+)', line)
                token_match_colon = re.search(r'(user_[^:\s]+::[A-Za-z0-9+/=._-]+)', line)
                
                if token_match_url:
                    complete_matches.append(token_match_url.group(1))
                elif token_match_colon:
                    complete_matches.append(token_match_colon.group(1))
        
        # 去重
        seen_tokens = set()
        
        # 先添加完整格式
        for match in complete_matches:
            if match not in seen_tokens and len(match) > 50:
                seen_tokens.add(match)
                unique_tokens.append(match)
        
        # 再添加JWT token，确保不重复
        for jwt_token in jwt_matches:
            is_duplicate = False
            for complete_token in complete_matches:
                if jwt_token in complete_token:
                    is_duplicate = True
                    break
            
            if not is_duplicate and jwt_token not in seen_tokens and len(jwt_token) > 100:
                seen_tokens.add(jwt_token)
                unique_tokens.append(jwt_token)
        
        self.logger.info(f"提取到{len(unique_tokens)}个token")
        return unique_tokens
    
    def _extract_user_id_from_json(self, account_data: dict) -> Optional[str]:
        """从JSON账号数据中提取user_id（批量导入优化，不生成临时邮箱）"""
        # 尝试从auth_info中的cachedSignUpType提取
        auth_info = account_data.get('auth_info', {})
        access_token = auth_info.get('cursorAuth/accessToken', '')
        
        # 尝试解析JWT token获取user_id（不提取邮箱信息）
        if access_token and access_token.startswith('ey'):
            try:
                from .common_utils import CommonUtils
                payload = CommonUtils.decode_jwt_payload(access_token)
                if payload and 'sub' in payload:
                    sub = payload['sub']
                    if '|' in sub and 'user_' in sub:
                        parts = sub.split('|')
                        for part in parts:
                            if part.startswith('user_'):
                                return part
            except Exception:
                pass
        
        # 如果WorkosCursorSessionToken存在，尝试从中提取
        workos_token = auth_info.get('WorkosCursorSessionToken', '')
        if workos_token and 'user_' in workos_token:
            match = re.search(r'(user_[^%]+)', workos_token)
            if match:
                return match.group(1)
        
        return None
    
    def _parse_json_accounts(self, data: List[Dict]) -> Tuple[bool, str, Optional[List[Dict]]]:
        """直接解析JSON格式的账号数据"""
        try:
            parsed_accounts = []
            
            for i, item in enumerate(data, 1):
                if not isinstance(item, dict):
                    continue
                
                # 直接从JSON中提取完整信息（不重新解析）
                auth_info = item.get('auth_info', {})
                email = item.get('email', '')  # 直接使用JSON中的邮箱
                
                # 解析创建时间 - 优先使用register_time
                register_time = item.get('register_time', '')
                register_timestamp = item.get('registerTimeStamp', 0)
                
                # 处理时间格式，确保created_at为界面显示格式
                if register_time:
                    # 如果有register_time，转换为界面显示格式
                    try:
                        if len(register_time) > 16:  # YYYY-MM-DD HH:MM:SS 格式
                            created_at = register_time[:16]  # 截取为 YYYY-MM-DD HH:MM
                        else:
                            created_at = register_time
                    except Exception as e:
                        created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
                elif register_timestamp and register_timestamp > 0:
                    # 如果有registerTimeStamp，转换为时间字符串
                    try:
                        created_at = datetime.fromtimestamp(register_timestamp / 1000).strftime('%Y-%m-%d %H:%M')
                        register_time = datetime.fromtimestamp(register_timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    except Exception as e:
                        created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
                        register_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # 如果都没有，使用当前时间
                    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
                    register_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 构建账号信息 - 直接使用JSON中的完整数据，支持灵活字段匹配
                account_info = {
                    'user_id': self._extract_user_id_from_json(item),
                    'access_token': auth_info.get('cursorAuth/accessToken', ''),
                    'refresh_token': auth_info.get('cursorAuth/refreshToken', ''),
                    'WorkosCursorSessionToken': auth_info.get('WorkosCursorSessionToken', ''),
                    'email': email,
                    'created_at': created_at,
                    'register_time': register_time,
                    'registerTimeStamp': register_timestamp,
                    'email_source': 'json_import',
                    'needs_manual_email': False,
                    'format_hint': 'JSON格式导入，信息完整',
                    'import_index': i,
                    'password': item.get('password', ''),
                    'token_expired': False,
                    'machine_info': item.get('machine_info', {}),
                    'membershipType': item.get('membershipType', 'free'),
                    'subscriptionData': {
                        'membershipType': item.get('membershipType', 'free'),
                        'daysRemainingOnTrial': item.get('daysRemainingOnTrial', 0),
                        'trialEligible': item.get('trialEligible', False),
                    },
                    'daysRemainingOnTrial': item.get('daysRemainingOnTrial', 0),
                    'trialDaysRemaining': item.get('trialDaysRemaining', item.get('daysRemainingOnTrial', 0)),
                    'trialEligible': item.get('trialEligible', False),
                    'tokenValidity': item.get('tokenValidity', True),
                    'modelUsage': item.get('modelUsage', {}),
                    'system_type': item.get('system_type', 'windows'),
                    'token_valid': item.get('tokenValidity', True),
                    'subscriptionUpdatedAt': item.get('subscriptionUpdatedAt', 0),
                    'subscriptionStatus': item.get('subscriptionStatus', 'unknown')
                }
                
                # 保存标签和备注信息（用于后续导入）
                if 'tags' in item:
                    account_info['import_tags'] = item['tags']
                if 'remark' in item:
                    account_info['import_remark'] = item['remark']
                
                # 导入其他所有字段（灵活匹配，只导入存在的字段）
                excluded_keys = {'auth_info', 'email', 'password', 'register_time', 'registerTimeStamp', 
                                'machine_info', 'modelUsage', 'tags', 'remark'}
                for key, value in item.items():
                    if key not in excluded_keys and key not in account_info:
                        account_info[key] = value
                
                # 只添加有效的账号（至少要有邮箱和token）
                if email and (account_info['access_token'] or account_info['WorkosCursorSessionToken']):
                    
                    # 🚀 优化：JSON格式导入时只检查JWT长度，不重新解析邮箱
                    current_access_token = account_info.get('access_token', '')
                    
                    if current_access_token and current_access_token.startswith('ey'):
                        jwt_length = len(current_access_token)
                        
                        # 🎯 简化逻辑：只根据JWT长度判断是否需要转换
                        if jwt_length == 413:
                            # 413字符 = session类型，直接使用
                            account_info['token_type'] = 'session'
                        else:
                            # 其他长度需要转换，但JSON导入时不立即转换，标记为待转换
                            account_info['token_type'] = 'pending_conversion'
                    else:
                        # 没有有效JWT
                        account_info['token_type'] = 'unknown'
                    
                    parsed_accounts.append(account_info)
            
            if parsed_accounts:
                message = f"成功从JSON导入{len(parsed_accounts)}个账号"
                self.logger.info(message)
                return True, message, parsed_accounts
            else:
                return False, "JSON中未找到有效的账号信息", None
                
        except Exception as e:
            self.logger.error(f"解析JSON账号数据时出错: {str(e)}")
            return False, f"解析JSON账号数据时出错: {str(e)}", None
    
    def detect_token_format(self, token_string: str) -> str:
        """
        自动检测token格式
        
        Args:
            token_string: 待检测的token字符串
            
        Returns:
            str: 'jwt' | 'workos_token' | 'unknown'
        """
        try:
            token_string = token_string.strip()
            
            # 强制检测：所有user_开头的token都当作WorkosCursorSessionToken格式处理
            if token_string.startswith('user_'):
                self.logger.debug(f"检测到user_开头token，强制使用WorkosCursorSessionToken格式: {token_string[:20]}...")
                return 'workos_token'
            
            # 检测纯JWT格式: eyJxxxxx.eyJxxxxx.xxxxxx (且不以user_开头)
            if token_string.startswith('eyJ') and token_string.count('.') == 2:
                self.logger.debug(f"检测到JWT格式: eyJ...{token_string[-20:]}")
                return 'jwt'
            
            self.logger.warning(f"未知token格式: {token_string[:30]}...")
            return 'unknown'
            
        except Exception as e:
            self.logger.error(f"检测token格式失败: {str(e)}")
            return 'unknown'
    
    def parse_unified_token(self, token_string: str, manual_email: str = '') -> Tuple[bool, str, Optional[Dict]]:
        """
        统一token解析入口 - 自动检测格式并解析
        
        Args:
            token_string: 待解析的token字符串
            manual_email: 手动输入的邮箱（可选）
            
        Returns:
            Tuple[bool, str, Optional[Dict]]: (是否成功, 消息, 账号信息)
        """
        try:
            # 自动检测格式
            format_type = self.detect_token_format(token_string)
            self.logger.info(f"🔍 自动检测到token格式: {format_type}")
            
            if format_type == 'workos_token':
                return self._parse_complete_format(token_string)
            elif format_type == 'jwt':
                return self._parse_jwt_format(token_string)
            else:
                return False, f"不支持的token格式: {token_string[:30]}...", None
                
        except Exception as e:
            return False, f"统一解析失败: {str(e)}", None

    
    def _parse_complete_format(self, token: str) -> Tuple[bool, str, Optional[Dict]]:
        """解析完整格式：user_xxx%3A%3Atoken - 支持自动转换web类型为session类型"""
        try:
            # 解码URL编码
            decoded_token = urllib.parse.unquote(token)
            
            # 尝试两种分隔符
            if '::' in decoded_token:
                parts = decoded_token.split("::", 1)
            elif '%3A%3A' in token:
                parts = token.split("%3A%3A", 1)
            else:
                return False, "完整格式token分割失败，缺少分隔符", None
            
            if len(parts) != 2:
                return False, "完整格式token分割失败", None
            
            user_id = parts[0].strip()
            access_token = parts[1].strip()
            
            if not user_id.startswith("user_"):
                return False, "用户ID格式不正确", None
            
            # 🔥 只检查token类型，不在这里转换（转换由调用方控制）
            if access_token and access_token.startswith('ey'):
                from .common_utils import CommonUtils
                payload = CommonUtils.decode_jwt_payload(access_token)
                if payload:
                    jwt_type = payload.get('type', 'unknown')
                    if jwt_type == 'web':
                        self.logger.debug(f"检测到web类型JWT，需要后续转换")
                    elif jwt_type == 'session':
                        self.logger.debug(f"已是session类型JWT")
                    else:
                        self.logger.debug(f"JWT类型: {jwt_type}")
            
            # 使用处理后的token构建账号信息
            return self._build_account_info(user_id, access_token, format_type="complete")
            
        except Exception as e:
            return False, f"解析完整格式token失败: {str(e)}", None
    
    def _parse_jwt_format(self, jwt_token: str) -> Tuple[bool, str, Optional[Dict]]:
        """解析JWT格式token - 支持导入并自动转换为session类型JWT"""
        try:
            # 清理JWT token（去除空格和换行）
            jwt_token = jwt_token.strip()
            
            # 验证JWT格式（应该有3个部分）
            if jwt_token.count('.') != 2:
                return False, "JWT格式不正确，应该包含3个部分（header.payload.signature）", None
            
            # 解析JWT获取用户信息
            token_info = self._parse_jwt_payload(jwt_token)
            if not token_info:
                return False, "无法解析JWT token，请检查格式是否正确", None
            
            # 提取user_id（从sub字段）
            user_id = None
            if 'sub' in token_info:
                sub = token_info['sub']
                # 处理格式如 auth0|user_xxx
                if '|' in sub:
                    parts = sub.split('|')
                    if len(parts) > 1 and parts[1].startswith('user_'):
                        user_id = parts[1]
                elif sub.startswith('user_'):
                    user_id = sub
            
            if not user_id:
                return False, "无法从JWT中提取user_id，请使用完整的WorkosCursorSessionToken格式", None
            
            self.logger.info(f"✅ 成功从JWT提取user_id: {user_id}")
            
            # 检查JWT类型和长度
            jwt_type = token_info.get('type', 'unknown')
            jwt_length = len(jwt_token)
            self.logger.info(f"JWT类型: {jwt_type}, 长度: {jwt_length}")
            
            # 判断是否需要转换为session类型JWT
            if jwt_length != 413:
                self.logger.info(f"⚠️ JWT长度不是413（当前{jwt_length}），需要转换为session类型")
                # 注意：转换会在three_tab_import_dialog.py中的导入逻辑中处理
                # 这里只需要构造WorkosCursorSessionToken，以便后续转换
            
            # 构建账号信息（使用jwt格式类型，这样会生成WorkosCursorSessionToken）
            return self._build_account_info(user_id, jwt_token, format_type="jwt")
            
        except Exception as e:
            self.logger.error(f"解析JWT格式token失败: {str(e)}")
            return False, f"解析JWT token失败: {str(e)}", None
    
    def _parse_jwt_payload(self, token: str) -> Optional[Dict]:
        """解析JWT token获取用户信息"""
        try:
            # 使用通用工具类解析JWT
            from .common_utils import CommonUtils
            payload_json = CommonUtils.decode_jwt_payload(token)
            if not payload_json:
                self.logger.warning("JWT token格式不正确或解析失败")
                return None
            
            # 提取有用信息
            extracted_info = {}
            
            # 提取用户标识信息
            if 'sub' in payload_json:
                sub = payload_json['sub']
                extracted_info['sub'] = sub
                
                # 检查sub字段是否包含邮箱信息（极少数情况）
                if '@' in sub:
                    extracted_info['email'] = sub
                    self.logger.info(f"从JWT sub字段发现邮箱: {sub}")
                elif '|' in sub:
                    # 处理格式如 auth0|user_xxx
                    # 注意：不再自动生成临时邮箱，由调用方决定
                    pass
            
            # 提取过期时间
            if 'exp' in payload_json:
                extracted_info['token_expires_at'] = payload_json['exp']
                # 检查是否过期
                current_time = int(time.time())
                if payload_json['exp'] < current_time:
                    extracted_info['token_expired'] = True
                    self.logger.warning("Token已过期")
                else:
                    extracted_info['token_expired'] = False
            
            # 提取账号创建时间
            if 'time' in payload_json:
                try:
                    # time字段可能是字符串或数字，统一转换为整数时间戳
                    time_value = payload_json['time']
                    if isinstance(time_value, str):
                        time_timestamp = int(time_value)
                    else:
                        time_timestamp = int(time_value)
                    
                    extracted_info['account_created_at'] = time_timestamp
                    
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"解析Token中的time字段失败: {str(e)}")
            
            # 提取签发时间
            if 'iat' in payload_json:
                extracted_info['iat'] = payload_json['iat']
            
            # 提取其他有用信息
            useful_fields = ['iss', 'aud', 'scope', 'type', 'randomness']
            for field in useful_fields:
                if field in payload_json:
                    extracted_info[f'token_{field}'] = payload_json[field]
            
            return extracted_info
            
        except Exception as e:
            self.logger.warning(f"解析JWT token时出错: {str(e)}")
            return None
    
    def _build_account_info(self, user_id: str, access_token: str, format_type: str = "complete") -> Tuple[bool, str, Optional[Dict]]:
        """构建账号信息"""
        try:
            # 解析JWT获取更多信息
            token_info = self._parse_jwt_payload(access_token) if access_token.count('.') == 2 else {}
            
            # 🔥 修复时间逻辑：导入Token时使用当前导入时间（这是Token导入，不是文件导入）
            # 注意：此方法用于解析单个Token，应该使用当前导入时间
            created_timestamp = int(time.time())
            current_import_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 记录JWT中的原始时间（仅用于调试）
            if token_info:
                if 'account_created_at' in token_info:
                    original_time = datetime.fromtimestamp(token_info['account_created_at']).strftime('%Y-%m-%d %H:%M:%S')
                    self.logger.debug(f"JWT中的原始账号创建时间: {original_time}")
                elif 'iat' in token_info:
                    original_time = datetime.fromtimestamp(token_info['iat']).strftime('%Y-%m-%d %H:%M:%S')
                    self.logger.debug(f"JWT中的token签发时间: {original_time}")
            
            self.logger.info(f"✅ Token导入使用当前时间: {current_import_time}")
            
            account_info = {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": access_token,
                "created_at": current_import_time[:16],  # 界面显示格式：2025-01-09 14:30
                "register_time": current_import_time,    # 完整导入时间：2025-01-09 14:30:25
                "registerTimeStamp": created_timestamp * 1000,  # 毫秒时间戳
                "imported_from": format_type,
                "status": "已导入"
            }
            
            # 🔥 重要改进：根据format_type决定是否生成WorkosCursorSessionToken字段
            if format_type == "complete":
                # WorkosCursorSessionToken格式：已经是完整格式
                account_info["WorkosCursorSessionToken"] = f"{user_id}%3A%3A{access_token}"
            elif format_type == "jwt" and user_id and user_id.startswith("user_"):
                # 🔥 JWT格式：经测试可以逆向构造WorkosCursorSessionToken（100%准确）
                account_info["WorkosCursorSessionToken"] = f"{user_id}%3A%3A{access_token}"
                self.logger.info(f"✅ JWT格式成功逆向构造WorkosCursorSessionToken: {user_id}%3A%3A...")
            else:
                # 其他情况：不生成WorkosCursorSessionToken字段，保持JWT纯净性
                self.logger.debug(f"JWT格式未生成WorkosCursorSessionToken（无有效user_id）: {user_id}")
            
            # 添加JWT解析出的其他信息
            if token_info:
                # 保存token过期信息
                if 'token_expired' in token_info:
                    account_info['token_expired'] = token_info['token_expired']
                if 'token_expires_at' in token_info:
                    account_info['token_expires_at'] = token_info['token_expires_at']
                
                # 保存token类型和其他信息
                for field in ['token_type', 'token_scope', 'token_iss', 'token_aud', 'token_randomness']:
                    if field in token_info:
                        account_info[field] = token_info[field]
            
            # 处理邮箱提取
            email = None
            
            # 🔥 修复WorkosCursorSessionToken导入逻辑：WorkosCursorSessionToken格式只使用API/Dashboard，不混合JWT逻辑
            if format_type == "complete":
                # WorkosCursorSessionToken格式：直接使用API/Dashboard获取真实邮箱（最可靠）
                self.logger.info("WorkosCursorSessionToken格式导入，使用API/Dashboard获取真实邮箱...")
                success, message, real_email = self.email_extractor.extract_real_email(user_id, access_token)
                
                if success and real_email:
                    email = real_email
                    account_info["email_source"] = "api_dashboard"
                    account_info["needs_manual_email"] = False
                    self.logger.info(f"✅ WorkosCursorSessionToken格式成功获取真实邮箱: {email}")
                else:
                    # 🔥 API/Dashboard失败，直接使用@cursor.local备用策略（不检查JWT）
                    clean_user_id = user_id.replace("user_", "") if user_id.startswith("user_") else user_id
                    email = f"{clean_user_id}@cursor.local"
                    account_info["email_source"] = "fallback_local"
                    account_info["needs_manual_email"] = True
                    self.logger.warning(f"⚠️ WorkosCursorSessionToken格式API获取失败，使用备用邮箱: {email} - {message}")
            else:
                # 🔥 JWT格式优化：既然已逆向构造WorkosCursorSessionToken，直接使用API/Dashboard获取真实邮箱
                self.logger.info("JWT格式导入，已逆向构造WorkosCursorSessionToken，使用API/Dashboard获取真实邮箱...")
                success, message, real_email = self.email_extractor.extract_real_email(user_id, access_token)
                
                if success and real_email:
                    email = real_email
                    account_info["email_source"] = "api_dashboard"
                    account_info["needs_manual_email"] = False
                    self.logger.info(f"✅ JWT格式成功获取真实邮箱: {email}")
                else:
                    # API/Dashboard失败，检查是否有手动输入的邮箱
                    manual_email = account_info.get('manual_email', '')
                    if manual_email and '@' in manual_email and not manual_email.endswith('@cursor.local'):
                        email = manual_email
                        account_info["email_source"] = "manual_input"
                        account_info["needs_manual_email"] = False
                        self.logger.info(f"✅ JWT格式使用手动输入邮箱: {email}")
                    else:
                        # 最后备用：使用@cursor.local邮箱
                        clean_user_id = user_id.replace("user_", "") if user_id.startswith("user_") else user_id
                        email = f"{clean_user_id}@cursor.local"
                        account_info["email_source"] = "fallback_local"
                        account_info["needs_manual_email"] = True
                        self.logger.warning(f"⚠️ JWT格式API获取失败，使用备用邮箱: {email} - {message}")
            
            # 添加提示信息 - 根据邮箱来源策略
            email_source = account_info.get("email_source")
            if format_type == "complete":
                if email_source == "api_dashboard":
                    account_info["format_hint"] = "WorkosCursorSessionToken格式，已通过API获取真实邮箱"
                elif email_source == "fallback_local":
                    account_info["format_hint"] = "WorkosCursorSessionToken格式，使用备用邮箱，建议刷新获取真实邮箱"
                else:
                    account_info["format_hint"] = "WorkosCursorSessionToken格式，需要获取真实邮箱"
            else:
                # 🔥 JWT格式的提示信息（已优化支持API获取真实邮箱）
                if email_source == "api_dashboard":
                    account_info["format_hint"] = "JWT格式（已逆向WorkosCursorSessionToken），已通过API获取真实邮箱"
                elif email_source == "manual_input":
                    account_info["format_hint"] = "JWT格式，使用手动输入的真实邮箱"
                elif email_source == "fallback_local":
                    account_info["format_hint"] = "JWT格式，API获取失败，使用备用邮箱（建议刷新）"
                else:
                    account_info["format_hint"] = "JWT格式，需要获取真实邮箱"
            
            account_info["email"] = email
            account_info["password"] = ""  # 🔥 修复：token导入的账号默认无密码，保持空字符串
            
            # 获取订阅状态
            try:
                # 注释：订阅信息将在后续的刷新操作中通过cursor_manager获取
                subscription_info = None
                if subscription_info:
                    membership_type = subscription_info.get('membershipType', 'free')
                    account_info["membershipType"] = membership_type
                    account_info["subscriptionData"] = subscription_info
                    self.logger.info(f"获取到订阅状态: {membership_type}")
                else:
                    account_info["membershipType"] = "free"
            except Exception as e:
                self.logger.warning(f"获取订阅状态失败: {str(e)}")
                account_info["membershipType"] = "free"
            
            # 🔥 修复：确定token类型 - 长度等于413才是session类型
            try:
                current_access_token = account_info.get('access_token', '')
                
                if current_access_token and current_access_token.startswith('ey'):
                    jwt_length = len(current_access_token)
                    if jwt_length == 413:
                        # 长度等于413的JWT是session类型
                        account_info['token_type'] = 'session'
                        self.logger.info(f"ℹ️ JWT长度符合要求({jwt_length}字符)，确认为session类型")
                    else:
                        # 长度不足的JWT，解析原类型
                        from .common_utils import CommonUtils
                        payload = CommonUtils.decode_jwt_payload(current_access_token)
                        if payload:
                            jwt_type = payload.get('type', 'unknown')
                            account_info['token_type'] = jwt_type
                            self.logger.info(f"ℹ️ JWT长度不足({jwt_length}字符)，保持原类型: {jwt_type}")
                        else:
                            account_info['token_type'] = 'unknown'
                else:
                    account_info['token_type'] = 'unknown'
                    
            except Exception as type_error:
                self.logger.warning(f"确定token类型失败: {str(type_error)}")
                account_info['token_type'] = 'unknown'
            
            return True, "解析成功", account_info
            
        except Exception as e:
            return False, f"构建账号信息失败: {str(e)}", None
