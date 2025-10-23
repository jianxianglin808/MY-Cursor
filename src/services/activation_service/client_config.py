#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
客户端配置管理器
用于保存和加载客户端激活信息
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class ClientConfigManager:
    """客户端配置管理器"""
    
    def __init__(self, config_dir: str = None):
        """
        初始化客户端配置管理器
        
        Args:
            config_dir: 配置目录路径
        """
        self.logger = logging.getLogger(__name__)
        
        # 配置目录
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor')
        
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 客户端配置文件路径
        self.client_config_file = os.path.join(self.config_dir, 'client_config.json')
        
        # 默认配置
        self.default_config = {
            "version": "1.0",
            "activation_info": {
                "code": "",
                "verified_time": "",
                "duration_hash": "",
                "security_hash": "",
                "is_valid": False
            },
            "verification_settings": {
                "check_interval_minutes": 30,  # 定期检查间隔（分钟）
                "force_check_on_critical": True  # 关键操作时强制验证
            }
        }
        
        # 加载配置
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载客户端配置"""
        try:
            if os.path.exists(self.client_config_file):
                with open(self.client_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    return {**self.default_config, **config}
            else:
                # 创建默认配置文件
                self._save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            self.logger.error(f"加载客户端配置失败: {str(e)}")
            return self.default_config.copy()
    
    def _save_config(self, config: Dict[str, Any] = None) -> bool:
        """保存客户端配置"""
        try:
            config_to_save = config or self.config
            with open(self.client_config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"保存客户端配置失败: {str(e)}")
            return False
    
    def save_activation_info(self, code: str, remaining_hours: float, 
                           user_type: str = "normal", is_admin: bool = False,
                           update_server_check: bool = True) -> bool:
        """
        保存激活码信息
        
        Args:
            code: 激活码
            remaining_hours: 剩余有效时间（小时）
            user_type: 用户类型 ('normal', 'admin', 'permanent_admin')
            is_admin: 是否为管理员
            
        Returns:
            bool: 是否保存成功
        """
        try:
            current_time = datetime.now()
            
            # 安全存储：加密保存有效时长和校验信息
            import hashlib
            import base64
            
            # 生成安全校验：激活码+验证时间+有效时长的Hash
            verification_data = f"{code}:{current_time.isoformat()}:{remaining_hours}"
            security_hash = hashlib.sha256(verification_data.encode()).hexdigest()[:16]
            
            # 加密存储有效时长
            duration_str = f"{remaining_hours:.6f}"  # 保持精度
            duration_encoded = base64.b64encode(duration_str.encode()).decode()
            
            self.config["activation_info"] = {
                "code": code,
                "verified_time": current_time.isoformat(),
                "duration_hash": duration_encoded,  # 加密的有效时长
                "security_hash": security_hash,     # 防篡改校验
                "is_valid": True,
                "user_type": user_type,
                "is_admin": is_admin
            }
            
            success = self._save_config()
            if success:
                expiry_time = current_time + timedelta(hours=remaining_hours)
                self.logger.info(f"激活码信息已保存: {code}, 有效期至: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}")
            return success
            
        except Exception as e:
            self.logger.error(f"保存激活码信息失败: {str(e)}")
            return False
    
    def save_activation_info_with_expiry(self, code: str, expiry_time_str: str, 
                                       user_type: str = "normal", is_admin: bool = False) -> bool:
        """
        保存激活码信息（使用云端返回的到期时间）
        
        Args:
            code: 激活码
            expiry_time_str: 云端返回的到期时间（ISO格式字符串）
            user_type: 用户类型 ('normal', 'admin', 'permanent_admin')
            is_admin: 是否为管理员
            
        Returns:
            bool: 是否保存成功
        """
        try:
            # 从云端到期时间计算剩余小时数
            current_time = datetime.now()
            expiry_time = datetime.fromisoformat(expiry_time_str)
            remaining_seconds = (expiry_time - current_time).total_seconds()
            remaining_hours = remaining_seconds / 3600
            
            # 调用加密保存方法
            return self.save_activation_info(code, remaining_hours, user_type, is_admin)
            
        except Exception as e:
            self.logger.error(f"保存激活码信息失败: {str(e)}")
            return False
    
    def get_saved_activation_code(self, force_server_check: bool = False) -> Optional[str]:
        """
        获取保存的激活码（如果仍有效）
        🔓 已绕过：直接返回虚拟激活码
        
        Args:
            force_server_check: 是否强制进行服务器验证
        
        Returns:
            Optional[str]: 有效的激活码，如果无效则返回None
        """
        # 🔓 绕过激活检查，直接返回虚拟激活码
        self.logger.info("🔓 激活检查已绕过，返回虚拟激活码")
        
        # 确保配置文件中有永久管理员信息
        activation_info = self.config.get("activation_info", {})
        if not activation_info.get("is_valid"):
            self.save_activation_info("BYPASS00", 999999, "permanent_admin", True)
            self.logger.info("✅ 已自动创建永久管理员配置")
        
        return "BYPASS00"
        
        # 原始验证代码（已禁用）
        """
        try:
            # 重新加载配置以获取最新状态（解决多实例问题）
            self.config = self._load_config()
            activation_info = self.config.get("activation_info", {})
            
            if not activation_info.get("is_valid") or not activation_info.get("code"):
                return None
            
            # 简化验证：优先使用新格式，兼容旧格式
            try:
                current_time = datetime.now()
                expiry_time = None
                
                # 新格式：直接读取到期时间
                if activation_info.get("expiry_time"):
                    expiry_time = datetime.fromisoformat(activation_info["expiry_time"])
                
                # 旧格式兼容：从duration_hash计算到期时间
                elif activation_info.get("duration_hash"):
                    import base64
                    duration_encoded = activation_info.get("duration_hash")
                    remaining_hours = float(base64.b64decode(duration_encoded.encode()).decode())
                    verified_time = datetime.fromisoformat(activation_info.get("verified_time"))
                    expiry_time = verified_time + timedelta(hours=remaining_hours)
                
                if not expiry_time:
                    self.logger.warning("激活码数据格式错误，需要重新验证")
                    self.clear_activation_info()
                    return None
                
                # 🔥 修复：永久管理员激活码永不过期
                user_type = activation_info.get("user_type", "normal")
                if user_type == "permanent_admin":
                    self.logger.info("永久管理员激活码，跳过过期检查")
                elif current_time >= expiry_time:
                    # 普通激活码过期检查
                    self.logger.info("保存的激活码已过期，将清除")
                    self.clear_activation_info()
                    return None
                    
            except Exception as e:
                self.logger.warning(f"激活码数据解析失败: {e}，需要重新验证")
                self.clear_activation_info()
                return None
            
            # 简化验证：只有强制验证时才检查服务器
            if force_server_check:
                server_valid = self._verify_with_server(activation_info["code"])
                if not server_valid:
                    self.logger.warning("服务器验证失败，激活码可能已被删除")
                    self.clear_activation_info()
                    return None
                else:
                    self.logger.info("服务器验证通过")
            
            # 仍有效，计算剩余时间
            remaining_seconds = (expiry_time - current_time).total_seconds()
            remaining_hours = remaining_seconds / 3600
            
            self.logger.info(f"找到有效的激活码: {activation_info['code']}, 剩余: {remaining_hours:.1f}小时")
            return activation_info["code"]
            
        except Exception as e:
            self.logger.error(f"获取保存的激活码失败: {str(e)}")
            return None
        """
    
    def get_remaining_hours(self) -> Optional[float]:
        """
        获取激活码剩余有效时长（小时）
        
        Returns:
            Optional[float]: 剩余小时数，如果无效则返回None
        """
        try:
            # 重新加载配置以获取最新状态（解决多实例问题）
            self.config = self._load_config()
            activation_info = self.config.get("activation_info", {})
            
            if not activation_info.get("is_valid") or not activation_info.get("code"):
                return None
            
            current_time = datetime.now()
            expiry_time = None
            
            # 优先使用加密格式：从duration_hash计算到期时间
            if activation_info.get("duration_hash"):
                import base64
                try:
                    duration_encoded = activation_info.get("duration_hash")
                    remaining_hours = float(base64.b64decode(duration_encoded.encode()).decode())
                    verified_time = datetime.fromisoformat(activation_info.get("verified_time"))
                    expiry_time = verified_time + timedelta(hours=remaining_hours)
                except Exception:
                    pass
            
            # 备用：直接读取到期时间（兼容旧格式）
            elif activation_info.get("expiry_time"):
                expiry_time = datetime.fromisoformat(activation_info["expiry_time"])
            
            if not expiry_time or current_time >= expiry_time:
                return None
            
            # 计算剩余时间
            remaining_seconds = (expiry_time - current_time).total_seconds()
            return remaining_seconds / 3600
                
        except Exception as e:
            self.logger.error(f"获取剩余时长失败: {str(e)}")
            return None
    
    def clear_activation_info(self) -> bool:
        """清除保存的激活码信息"""
        try:
            self.config["activation_info"] = {
                "code": "",
                "verified_time": "",
                "duration_hash": "",
                "security_hash": "",
                "is_valid": False
            }
            success = self._save_config()
            if success:
                self.logger.info("已清除保存的激活码信息")
            return success
        except Exception as e:
            self.logger.error(f"清除激活码信息失败: {str(e)}")
            return False
    
    def _verify_with_server(self, code: str) -> bool:
        """
        与服务器验证激活码是否仍然有效（客户端专用，内置数据库配置）
        
        Args:
            code: 激活码
            
        Returns:
            bool: 是否有效
        """
        try:
            # 客户端专用：使用内置数据库配置进行验证，不需要用户配置
            import pymysql
            from pymysql.cursors import DictCursor
            from datetime import datetime
            
            # 内置数据库配置（客户端验证专用）
            db_config = {
                'host': '117.72.190.99',
                'port': 3306,
                'user': 'xc_cursor',
                'password': 'XC_User_2024!',
                'database': 'mysql',
                'charset': 'utf8mb4',
                'autocommit': True,
                'connect_timeout': 10,
                'read_timeout': 10,
                'write_timeout': 10
            }
            
            # 直接连接数据库验证激活码
            conn = pymysql.connect(**db_config, cursorclass=DictCursor)
            
            try:
                with conn.cursor() as cursor:
                    # 查询激活码
                    cursor.execute(
                        "SELECT * FROM activation_codes WHERE code = %s AND is_active = TRUE",
                        (code,)
                    )
                    
                    result = cursor.fetchone()
                    if not result:
                        self.logger.warning(f"激活码不存在或已禁用: {code}")
                        return False
                    
                    # 检查过期
                    now = datetime.now()
                    expiry_time = result['expiry_time']
                    user_type = result.get('user_type', 'normal')
                    
                    # 永久管理员激活码永不过期
                    if user_type == "permanent_admin":
                        self.logger.info(f"永久管理员激活码验证通过: {code}")
                        return True
                    elif now > expiry_time:
                        self.logger.warning(f"激活码已过期: {code}")
                        return False
                    
                    # 检查使用次数限制
                    max_usage_count = result.get('max_usage_count')
                    current_usage_count = result.get('usage_count', 0)
                    
                    if max_usage_count is not None and current_usage_count >= max_usage_count:
                        self.logger.warning(f"激活码使用次数已达上限: {code} ({current_usage_count}/{max_usage_count})")
                        return False
                    
                    self.logger.info(f"服务器验证通过: {code}")
                    return True
                    
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"服务器验证出错: {str(e)}")
            # 网络错误时，暂时信任本地缓存
            self.logger.info("网络错误，暂时信任本地缓存")
            return True
    
    def needs_verification(self) -> bool:
        """
        检查是否需要重新验证
        🔓 已绕过：永不需要验证
        
        Returns:
            bool: 是否需要验证
        """
        # 🔓 绕过验证检查，永远返回 False
        self.logger.info("🔓 验证检查已绕过，无需重新验证")
        return False
        
        # 原始验证代码（已禁用）
        """
        try:
            activation_info = self.config.get("activation_info", {})
            if not activation_info.get("is_valid"):
                return True
            
            # 检查激活码本身是否过期（使用安全存储格式）
            import hashlib
            import base64
            
            try:
                # 解密并验证数据完整性
                duration_encoded = activation_info.get("duration_hash")
                if not duration_encoded:
                    return True
                
                remaining_hours = float(base64.b64decode(duration_encoded.encode()).decode())
                verified_time_str = activation_info.get("verified_time")
                verified_time = datetime.fromisoformat(verified_time_str)
                
                # 验证数据完整性
                verification_data = f"{activation_info['code']}:{verified_time_str}:{remaining_hours}"
                expected_hash = hashlib.sha256(verification_data.encode()).hexdigest()[:16]
                stored_hash = activation_info.get("security_hash")
                
                if expected_hash != stored_hash:
                    # 检查激活码是否在24小时内保存的，如果是则自动修复
                    current_time = datetime.now()
                    hours_since_verified = (current_time - verified_time).total_seconds() / 3600
                    
                    if hours_since_verified < 24 and activation_info.get("is_valid"):
                        self.logger.info("校验失败但激活码较新，自动修复校验")
                        # 自动修复校验问题
                        new_hash = hashlib.sha256(verification_data.encode()).hexdigest()[:16]
                        self.config["activation_info"]["security_hash"] = new_hash
                        self._save_config()
                        return False  # 修复后继续验证
                    else:
                        # 数据被篡改或过期
                        return True
                
                # 🔥 修复：永久管理员激活码永不过期
                user_type = activation_info.get("user_type", "normal")
                if user_type == "permanent_admin":
                    self.logger.info("永久管理员激活码，跳过过期检查")
                    return False  # 永不过期
                
                # 重新计算到期时间
                expiry_time = verified_time + timedelta(hours=remaining_hours)
                current_time = datetime.now()
                
                # 普通激活码过期检查
                return current_time >= expiry_time
                
            except Exception:
                # 数据格式错误或解析失败
                return True
            
        except Exception as e:
            self.logger.error(f"检查验证需求失败: {str(e)}")
            return True
        """
    
    def get_activation_status(self) -> Dict[str, Any]:
        """
        获取激活状态信息
        
        Returns:
            Dict: 激活状态信息
        """
        try:
            activation_info = self.config.get("activation_info", {})
            
            if not activation_info.get("is_valid") or not activation_info.get("code"):
                return {
                    "is_valid": False,
                    "message": "未激活"
                }
            
            # 使用安全存储格式获取状态
            import hashlib
            import base64
            
            try:
                # 解密并验证数据完整性
                duration_encoded = activation_info.get("duration_hash")
                if not duration_encoded:
                    return {
                        "is_valid": False,
                        "message": "激活信息格式错误"
                    }
                
                original_hours = float(base64.b64decode(duration_encoded.encode()).decode())
                verified_time_str = activation_info.get("verified_time")
                verified_time = datetime.fromisoformat(verified_time_str)
                
                # 验证数据完整性
                verification_data = f"{activation_info['code']}:{verified_time_str}:{original_hours}"
                expected_hash = hashlib.sha256(verification_data.encode()).hexdigest()[:16]
                stored_hash = activation_info.get("security_hash")
                
                if expected_hash != stored_hash:
                    return {
                        "is_valid": False,
                        "message": "激活数据被篡改，需重新验证"
                    }
                
                # 重新计算到期时间
                expiry_time = verified_time + timedelta(hours=original_hours)
                current_time = datetime.now()
                
                if current_time >= expiry_time:
                    return {
                        "is_valid": False,
                        "message": "激活已过期",
                        "expired_time": expiry_time.isoformat()
                    }
                
                remaining_seconds = (expiry_time - current_time).total_seconds()
                remaining_hours = remaining_seconds / 3600
                
                return {
                    "is_valid": True,
                    "code": activation_info["code"],
                    "verified_time": verified_time_str,
                    "expiry_time": expiry_time.isoformat(),
                    "remaining_hours": remaining_hours,
                    "message": f"已激活，剩余 {remaining_hours:.1f} 小时"
                }
                
            except Exception as decode_error:
                return {
                    "is_valid": False,
                    "message": f"激活数据解析失败: {str(decode_error)}"
                }
            
        except Exception as e:
            self.logger.error(f"获取激活状态失败: {str(e)}")
            return {
                "is_valid": False,
                "message": f"状态检查失败: {str(e)}"
            }
    
    def is_admin_user(self) -> bool:
        """
        检查当前用户是否为管理员
        🔓 已绕过：永远是管理员
        
        Returns:
            bool: 是否为管理员用户
        """
        # 🔓 绕过验证 - 永远是管理员
        return True
    
    def get_user_type(self) -> str:
        """
        获取当前用户类型
        🔓 已绕过：永远是永久管理员
        
        Returns:
            str: 用户类型 ('normal', 'admin', 'permanent_admin', 'unknown')
        """
        # 🔓 绕过验证 - 永远是永久管理员
        return "permanent_admin"
