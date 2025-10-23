#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用工具类 - 整合项目中重复的逻辑
功能：JWT解码、剪贴板操作、通用工具函数
作者：小纯归来
创建时间：2025年9月
"""

import re
import json
import base64
import logging
from typing import Optional, Dict, Any, Union
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class CommonUtils:
    """通用工具类 - 提供项目中常用的工具函数"""
    
    @staticmethod
    def extract_jwt_token(token_string: str) -> Optional[str]:
        """
        从token字符串中提取JWT token
        支持多种格式：user_xxx::token、直接JWT等
        """
        if not isinstance(token_string, str) or not token_string.strip():
            return None
        
        token_string = token_string.strip()
        
        # 方法1：直接匹配以ey开头的JWT token
        match = re.search(r'ey[A-Za-z0-9+/=_-]+\.[A-Za-z0-9+/=_-]+\.[A-Za-z0-9+/=_-]*', token_string)
        if match:
            return match.group(0)
        
        # 方法2：如果是user_开头的token，说明是WorkosCursorSessionToken格式，不应该拆分
        if token_string.startswith('user_'):
            # 🔥 修复：WorkosCursorSessionToken不应该拆分成JWT，应该通过PKCE API转换
            logger.debug(f"检测到WorkosCursorSessionToken格式，需要通过PKCE API转换: {token_string[:20]}...")
            return None
        
        # 方法3：如果整个字符串就是JWT格式
        if token_string.startswith('ey') and token_string.count('.') >= 2:
            return token_string
            
        logger.debug(f"无法从字符串中提取JWT token: {token_string[:20]}...")
        return None
    
    @staticmethod
    def decode_jwt_payload(jwt_token: str) -> Optional[Dict]:
        """
        解码JWT token的payload部分
        
        Args:
            jwt_token: JWT token字符串
            
        Returns:
            dict: 解码后的payload数据，失败时返回None
        """
        try:
            if not jwt_token:
                return None
            
            # 使用统一的JWT格式验证
            if not JWTUtils.is_valid_jwt_format(jwt_token):
                logger.warning("JWT token格式不正确，不是标准的三部分格式")
                return None
            
            parts = jwt_token.split('.')
            
            # 获取payload部分（第二部分）
            payload = parts[1]
            
            # 添加padding如果需要（Base64解码要求长度是4的倍数）
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            # Base64解码
            decoded_bytes = base64.urlsafe_b64decode(payload)
            payload_data = json.loads(decoded_bytes.decode('utf-8'))
            
            return payload_data
            
        except Exception as e:
            logger.warning(f"解码JWT token失败: {str(e)}")
            return None
    
    @staticmethod
    def extract_user_id_from_token(access_token: str) -> Optional[str]:
        """
        从JWT token中提取用户ID
        
        Args:
            access_token: 访问令牌
            
        Returns:
            str: 用户ID，失败时返回None
        """
        try:
            payload = CommonUtils.decode_jwt_payload(access_token)
            if not payload:
                return None
                
            # 获取sub字段
            sub = payload.get('sub')
            if not sub:
                return None
                
            # 从sub中提取user_id（格式：auth0|user_xxxxx）
            if '|' in sub:
                user_id = sub.split('|', 1)[1]  # 获取|后面的部分
                logger.debug(f"从token中提取到user_id: {user_id}")
                return user_id
            else:
                # 如果没有|分隔符，直接使用sub作为user_id
                return sub
                
        except Exception as e:
            logger.warning(f"从token提取user_id失败: {str(e)}")
            return None
    
    @staticmethod
    def copy_to_clipboard(text: str, show_message: bool = False) -> bool:
        """
        复制文本到剪贴板
        
        Args:
            text: 要复制的文本
            show_message: 是否显示复制成功的消息
            
        Returns:
            bool: 是否复制成功
        """
        try:
            # 方法1：使用Qt剪贴板（优先）
            try:
                clipboard = QApplication.clipboard()
                clipboard.setText(text)
                if show_message:
                    logger.info(f"已复制到剪贴板: {text[:20]}...")
                return True
            except Exception as qt_error:
                logger.debug(f"Qt剪贴板复制失败: {qt_error}")
                
            # 方法2：使用pyperclip作为备选
            try:
                import pyperclip
                pyperclip.copy(text)
                if show_message:
                    logger.info(f"已复制到剪贴板(pyperclip): {text[:20]}...")
                return True
            except ImportError:
                logger.debug("pyperclip未安装，跳过备选方法")
            except Exception as py_error:
                logger.debug(f"pyperclip复制失败: {py_error}")
                
            logger.warning("无法复制到剪贴板，所有方法都失败")
            return False
            
        except Exception as e:
            logger.error(f"复制到剪贴板时出错: {str(e)}")
            return False
    
    
    @staticmethod
    def safe_get_nested_value(data: Dict, keys: str, default: Any = None) -> Any:
        """
        安全地获取嵌套字典的值
        
        Args:
            data: 数据字典
            keys: 用点分隔的键路径，如 'user.profile.name'
            default: 默认值
            
        Returns:
            Any: 获取的值或默认值
        """
        try:
            current = data
            for key in keys.split('.'):
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return default
            return current
        except Exception:
            return default
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """
        验证邮箱格式
        
        Args:
            email: 邮箱地址
            
        Returns:
            bool: 是否为有效邮箱
        """
        if not email or not isinstance(email, str):
            return False
            
        # 简单的邮箱格式验证
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, email.strip()))
    
    @staticmethod
    def truncate_string(text: str, max_length: int = 50, suffix: str = "...") -> str:
        """
        截断字符串到指定长度
        
        Args:
            text: 原始字符串
            max_length: 最大长度
            suffix: 后缀
            
        Returns:
            str: 截断后的字符串
        """
        if not text or len(text) <= max_length:
            return text
            
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def get_api_headers(user_id: str = None, access_token: str = None, account: Dict = None) -> Dict[str, str]:
        """
        生成Cursor API请求的通用headers
        
        Args:
            user_id: 用户ID
            access_token: 访问令牌  
            account: 账号信息（用于判断导入格式）
            
        Returns:
            Dict[str, str]: API请求headers
        """
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://cursor.com/dashboard",
            "Origin": "https://cursor.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors", 
            "Sec-Fetch-Site": "same-origin"
        }
        
        if not access_token:
            return base_headers
            
        # 🔥 修复：统一使用URL编码格式
        if account and account.get('imported_from') == 'jwt':
            # JWT格式：优先提取user_id使用Cookie方式
            if not user_id and access_token:
                user_id = CommonUtils.extract_user_id_from_token(access_token)
            
            if user_id:
                # 使用URL编码格式（%3A%3A代表::）
                base_headers["Cookie"] = f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"
            else:
                # 无法提取user_id，使用Bearer Token方式
                base_headers["Authorization"] = f"Bearer {access_token}"
        elif access_token.startswith('ey') and access_token.count('.') == 2:
            # 检测到JWT格式（自动检测）：先尝试提取user_id
            auto_user_id = CommonUtils.extract_user_id_from_token(access_token)
            if auto_user_id:
                base_headers["Cookie"] = f"WorkosCursorSessionToken={auto_user_id}%3A%3A{access_token}"
            else:
                base_headers["Authorization"] = f"Bearer {access_token}"
        elif user_id and access_token:
            # WorkosCursorSessionToken格式：使用URL编码格式保持一致性
            base_headers["Cookie"] = f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"
        else:
            # 备用：尝试Bearer Token方式
            base_headers["Authorization"] = f"Bearer {access_token}"
            
        return base_headers


class JWTUtils:
    """JWT工具类 - 专门处理JWT相关操作"""
    
    @staticmethod
    def is_valid_jwt_format(token: str) -> bool:
        """
        检查是否为有效的JWT格式
        
        Args:
            token: 待检查的token
            
        Returns:
            bool: 是否为有效JWT格式
        """
        if not token:
            return False
            
        # 检查基本格式
        parts = token.split('.')
        return len(parts) == 3 and all(len(part) > 0 for part in parts)
    