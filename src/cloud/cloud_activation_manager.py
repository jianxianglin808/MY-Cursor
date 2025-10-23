#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XC-Cursor 云端激活码管理器
"""

import logging
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager

try:
    import pymysql
    from pymysql.cursors import DictCursor
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

from .cloud_db_config import CloudDatabaseConfig


class CloudActivationManager:
    """云端激活码管理器"""
    
    def __init__(self):
        """初始化管理器"""
        self.logger = logging.getLogger(__name__)
        self._db_initialized = False
        self._db_config: Optional[Dict[str, Any]] = None
        
        if not MYSQL_AVAILABLE:
            raise ImportError("需要安装 pymysql: pip install pymysql")
    
    def _ensure_initialized(self) -> None:
        """确保数据库已初始化"""
        if self._db_initialized:
            return
        
        try:
            # 获取并验证配置
            config_manager = CloudDatabaseConfig()
            self._db_config = config_manager.get_database_config()
            
            # 初始化数据库表
            self._init_database()
            self._db_initialized = True
            self.logger.info("✅ 云端数据库初始化成功")
            
        except Exception as e:
            self.logger.error(f"❌ 数据库初始化失败: {e}")
            raise
    
    @contextmanager
    def _get_db(self):
        """获取数据库连接的上下文管理器"""
        conn = None
        try:
            conn = pymysql.connect(
                **self._db_config,
                cursorclass=DictCursor
            )
            yield conn
        except pymysql.Error as e:
            self.logger.error(f"数据库错误: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def _init_database(self) -> None:
        """初始化数据库表"""
        with self._get_db() as conn:
            with conn.cursor() as cursor:
                # 创建激活码表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS activation_codes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(32) UNIQUE NOT NULL,
                        created_time DATETIME NOT NULL,
                        expiry_time DATETIME NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        usage_count INT DEFAULT 0,
                        max_usage_count INT DEFAULT NULL,
                        created_by VARCHAR(50) DEFAULT 'admin',
                        remark TEXT,
                        last_used_time DATETIME,
                        first_used_time DATETIME DEFAULT NULL,
                        validity_hours INT DEFAULT NULL,
                        user_type VARCHAR(20) DEFAULT 'normal',
                        INDEX idx_code (code),
                        INDEX idx_expiry (expiry_time)
                    )
                ''')
                
                # 为已存在的表添加 max_usage_count 字段（如果不存在）
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'activation_codes' 
                    AND COLUMN_NAME = 'max_usage_count'
                ''')
                result = cursor.fetchone()
                
                if result and result['count'] == 0:
                    cursor.execute('''
                        ALTER TABLE activation_codes 
                        ADD COLUMN max_usage_count INT DEFAULT NULL AFTER usage_count
                    ''')
                    self.logger.info("✅ 已添加 max_usage_count 字段")
                    conn.commit()
                
                # 为已存在的表添加 first_used_time 字段（如果不存在）
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'activation_codes' 
                    AND COLUMN_NAME = 'first_used_time'
                ''')
                result = cursor.fetchone()
                
                if result and result['count'] == 0:
                    cursor.execute('''
                        ALTER TABLE activation_codes 
                        ADD COLUMN first_used_time DATETIME DEFAULT NULL AFTER last_used_time
                    ''')
                    self.logger.info("✅ 已添加 first_used_time 字段")
                    conn.commit()
                
                # 为已存在的表添加 validity_hours 字段（如果不存在）
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'activation_codes' 
                    AND COLUMN_NAME = 'validity_hours'
                ''')
                result = cursor.fetchone()
                
                if result and result['count'] == 0:
                    cursor.execute('''
                        ALTER TABLE activation_codes 
                        ADD COLUMN validity_hours INT DEFAULT NULL AFTER first_used_time
                    ''')
                    self.logger.info("✅ 已添加 validity_hours 字段")
                    conn.commit()
                
                # 创建使用日志表（简化版）
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS usage_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(32) NOT NULL,
                        used_time DATETIME NOT NULL,
                        success BOOLEAN NOT NULL,
                        INDEX idx_code_time (code, used_time)
                    )
                ''')
                
                conn.commit()
    
    def verify_activation_code(self, code: str, quick: bool = False) -> Dict[str, Any]:
        """
        验证激活码
        
        Args:
            code: 激活码
            quick: 是否快速验证（不更新使用记录）
            
        Returns:
            Dict: 验证结果
        """
        self._ensure_initialized()
        
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    # 查询激活码
                    cursor.execute(
                        "SELECT * FROM activation_codes WHERE code = %s AND is_active = TRUE",
                        (code,)
                    )
                    
                    result = cursor.fetchone()
                    if not result:
                        return self._error_response("激活码不存在或已禁用", 404)
                    
                    now = datetime.now()
                    user_type = result.get('user_type', 'normal')
                    first_used_time = result.get('first_used_time')
                    validity_hours = result.get('validity_hours')
                    
                    # 计算实际到期时间
                    if first_used_time and validity_hours:
                        # 新逻辑：从首次使用时间开始倒计时
                        expiry_time = first_used_time + timedelta(hours=validity_hours)
                    else:
                        # 兼容旧逻辑：使用生成时的到期时间
                        expiry_time = result['expiry_time']
                    
                    # 永久管理员激活码永不过期
                    if user_type == "permanent_admin":
                        self.logger.info(f"永久管理员激活码 {code}，跳过过期检查")
                    elif now > expiry_time:
                        return self._error_response("激活码已过期", 410, {
                            "expiry_time": expiry_time.isoformat()
                        })
                    
                    # 检查使用次数限制
                    max_usage_count = result.get('max_usage_count')
                    current_usage_count = result.get('usage_count', 0)
                    
                    if max_usage_count is not None and current_usage_count >= max_usage_count:
                        return self._error_response(
                            f"激活码使用次数已达上限 ({current_usage_count}/{max_usage_count})", 
                            403,
                            {
                                "usage_count": current_usage_count,
                                "max_usage_count": max_usage_count
                            }
                        )
                    
                    # 更新使用记录（非快速验证时）
                    if not quick:
                        # 如果是首次使用，记录首次使用时间
                        if not first_used_time:
                            cursor.execute(
                                "UPDATE activation_codes SET usage_count = usage_count + 1, "
                                "last_used_time = %s, first_used_time = %s WHERE code = %s",
                                (now, now, code)
                            )
                            conn.commit()  # 提交数据库更改
                            self.logger.info(f"✅ 记录激活码 {code} 的首次使用时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                            # 重新计算到期时间（基于首次使用时间）
                            if validity_hours:
                                expiry_time = now + timedelta(hours=validity_hours)
                        else:
                            cursor.execute(
                                "UPDATE activation_codes SET usage_count = usage_count + 1, "
                                "last_used_time = %s WHERE code = %s",
                                (now, code)
                            )
                            conn.commit()  # 提交数据库更改
                        
                        self._log_usage(code, True)
                        # 更新后的使用次数
                        updated_usage_count = current_usage_count + 1
                    else:
                        # 快速验证不更新，使用当前值
                        updated_usage_count = current_usage_count
                    
                    # 计算剩余时间
                    remaining_hours = (expiry_time - now).total_seconds() / 3600
                    
                    return {
                        "success": True,
                        "code": code,
                        "user_type": result.get('user_type', 'normal'),
                        "is_admin": result.get('user_type') in ['admin', 'permanent_admin'],
                        "remaining_hours": remaining_hours,
                        "expiry_time": expiry_time.isoformat(),
                        "usage_count": updated_usage_count,
                        "max_usage_count": max_usage_count,
                        "message": f"激活码有效，剩余 {remaining_hours:.1f} 小时"
                    }
                    
        except Exception as e:
            self.logger.error(f"验证失败: {e}")
            return self._error_response("服务器内部错误", 500)
    
    def _log_usage(self, code: str, success: bool) -> None:
        """记录使用日志（简化版）"""
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO usage_logs (code, used_time, success) VALUES (%s, %s, %s)",
                        (code, datetime.now(), success)
                    )
        except Exception as e:
            self.logger.warning(f"记录日志失败: {e}")
    
    def quick_verify_activation_code(self, code: str) -> Dict[str, Any]:
        """快速验证激活码（不更新使用记录）"""
        return self.verify_activation_code(code, quick=True)
    
    def create_activation_code(self, 
                             validity_hours: int = 24,
                             remark: str = "",
                             created_by: str = "admin",
                             user_type: str = "normal",
                             max_usage_count: Optional[int] = None) -> Dict[str, Any]:
        """创建激活码"""
        self._ensure_initialized()
        
        try:
            code = self._generate_code()
            now = datetime.now()
            
            # 永久管理员激活码设置100年有效期
            if user_type == "permanent_admin":
                actual_validity_hours = 100 * 365 * 24  # 100年
                expiry_time = now + timedelta(hours=actual_validity_hours)
                self.logger.info(f"✅ 生成永久管理员激活码 {code}，有效期100年")
            else:
                actual_validity_hours = validity_hours
                expiry_time = now + timedelta(hours=validity_hours)
            
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO activation_codes "
                        "(code, created_time, expiry_time, created_by, remark, user_type, max_usage_count, validity_hours) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (code, now, expiry_time, created_by, remark, user_type, max_usage_count, actual_validity_hours)
                    )
                    
            result = {
                "success": True,
                "code": code,
                "created_time": now.isoformat(),
                "expiry_time": expiry_time.isoformat(),
                "validity_hours": actual_validity_hours,
                "user_type": user_type
            }
            
            if max_usage_count is not None:
                result["max_usage_count"] = max_usage_count
            
            return result
            
        except Exception as e:
            self.logger.error(f"创建失败: {e}")
            return self._error_response(f"创建激活码失败: {e}", 500)
    
    def _generate_code(self, length: int = 8) -> str:
        """生成激活码（排除易混淆字符）"""
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return ''.join(random.choices(chars, k=length))
    
    def list_activation_codes(self, include_expired: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        """获取激活码列表"""
        self._ensure_initialized()
        
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    if include_expired:
                        cursor.execute(
                            "SELECT * FROM activation_codes ORDER BY created_time DESC LIMIT %s",
                            (limit,)
                        )
                    else:
                        cursor.execute(
                            "SELECT * FROM activation_codes WHERE is_active = TRUE AND expiry_time > %s "
                            "ORDER BY created_time DESC LIMIT %s",
                            (datetime.now(), limit)
                        )
                    
                    results = cursor.fetchall()
                    now = datetime.now()
                    
                    # 处理结果
                    for result in results:
                        # 格式化日期
                        for key in ['created_time', 'expiry_time', 'last_used_time', 'first_used_time']:
                            if key in result and result[key]:
                                result[key] = result[key].isoformat()
                        
                        # 计算实际到期时间和剩余时间
                        user_type = result.get('user_type', 'normal')
                        first_used_time = result.get('first_used_time')
                        validity_hours = result.get('validity_hours')
                        
                        # 计算实际到期时间
                        if first_used_time and validity_hours:
                            # 新逻辑：从首次使用时间计算到期时间
                            first_used_dt = datetime.fromisoformat(first_used_time)
                            actual_expiry_dt = first_used_dt + timedelta(hours=validity_hours)
                            result['actual_expiry_time'] = actual_expiry_dt.isoformat()
                        else:
                            # 兼容旧逻辑
                            result['actual_expiry_time'] = result.get('expiry_time')
                        
                        # 计算剩余时间
                        if user_type == "permanent_admin":
                            result['remaining_hours'] = float('inf')
                            result['is_expired'] = False
                        else:
                            if result.get('actual_expiry_time'):
                                expiry_dt = datetime.fromisoformat(result['actual_expiry_time'])
                                remaining_hours = max(0, (expiry_dt - now).total_seconds() / 3600)
                                result['remaining_hours'] = remaining_hours
                                result['is_expired'] = remaining_hours <= 0
                            else:
                                result['remaining_hours'] = 0
                                result['is_expired'] = True
                    
                    return results
                    
        except Exception as e:
            self.logger.error(f"获取列表失败: {e}")
            return []
    
    def delete_code(self, code: str) -> Dict[str, Any]:
        """删除激活码"""
        self._ensure_initialized()
        
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    # 检查是否存在
                    cursor.execute("SELECT id FROM activation_codes WHERE code = %s", (code,))
                    if not cursor.fetchone():
                        return self._error_response(f"激活码 {code} 不存在", 404)
                    
                    # 删除激活码和日志
                    cursor.execute("DELETE FROM activation_codes WHERE code = %s", (code,))
                    cursor.execute("DELETE FROM usage_logs WHERE code = %s", (code,))
                    conn.commit()
                    
                    self.logger.info(f"✅ 激活码 {code} 已删除")
                    return {"success": True, "message": f"激活码 {code} 已删除"}
                    
        except Exception as e:
            self.logger.error(f"删除失败: {e}")
            return self._error_response(f"删除失败: {e}", 500)
    
    def delete_codes_batch(self, codes: List[str]) -> Dict[str, Any]:
        """批量删除激活码"""
        if not codes:
            return self._error_response("没有提供要删除的激活码", 400)
        
        self._ensure_initialized()
        
        try:
            successful = []
            failed = []
            
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    for code in codes:
                        try:
                            cursor.execute("SELECT id FROM activation_codes WHERE code = %s", (code,))
                            if not cursor.fetchone():
                                failed.append(f"{code}: 不存在")
                                continue
                            
                            cursor.execute("DELETE FROM activation_codes WHERE code = %s", (code,))
                            cursor.execute("DELETE FROM usage_logs WHERE code = %s", (code,))
                            successful.append(code)
                            
                        except Exception as e:
                            failed.append(f"{code}: {e}")
                    
                    conn.commit()
            
            return {
                "success": True,
                "message": f"批量删除完成: 成功 {len(successful)} 个, 失败 {len(failed)} 个",
                "successful_codes": successful,
                "failed_codes": failed
            }
            
        except Exception as e:
            self.logger.error(f"批量删除失败: {e}")
            return self._error_response(f"批量删除失败: {e}", 500)
    
    def update_code_remark(self, code: str, remark: str) -> Dict[str, Any]:
        """更新激活码备注"""
        self._ensure_initialized()
        
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE activation_codes SET remark = %s WHERE code = %s",
                        (remark, code)
                    )
                    
                    if cursor.rowcount == 0:
                        return self._error_response(f"激活码 {code} 不存在", 404)
                    
                    conn.commit()
                    return {"success": True, "message": f"激活码 {code} 备注已更新"}
                    
        except Exception as e:
            self.logger.error(f"更新备注失败: {e}")
            return self._error_response(f"更新备注失败: {e}", 500)
    
    def update_max_usage_count(self, code: str, max_usage_count: Optional[int]) -> Dict[str, Any]:
        """更新激活码的使用次数限制"""
        self._ensure_initialized()
        
        try:
            with self._get_db() as conn:
                with conn.cursor() as cursor:
                    # 检查激活码是否存在
                    cursor.execute("SELECT id FROM activation_codes WHERE code = %s", (code,))
                    if not cursor.fetchone():
                        return self._error_response(f"激活码 {code} 不存在", 404)
                    
                    # 更新限制次数
                    cursor.execute(
                        "UPDATE activation_codes SET max_usage_count = %s WHERE code = %s",
                        (max_usage_count, code)
                    )
                    conn.commit()
                    
                    if max_usage_count is None:
                        return {"success": True, "message": f"激活码 {code} 限制次数已设为无限制"}
                    else:
                        return {"success": True, "message": f"激活码 {code} 限制次数已更新为 {max_usage_count}"}
                    
        except Exception as e:
            self.logger.error(f"更新限制次数失败: {e}")
            return self._error_response(f"更新限制次数失败: {e}", 500)
    
    def _error_response(self, error: str, code: int, extra: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成错误响应"""
        response = {
            "success": False,
            "error": error,
            "code": code
        }
        if extra:
            response.update(extra)
        return response


# 全局单例实例
_global_cloud_manager = None

def get_global_cloud_manager_instance() -> CloudActivationManager:
    """获取全局云端激活管理器实例"""
    global _global_cloud_manager
    if _global_cloud_manager is None:
        _global_cloud_manager = CloudActivationManager()
    return _global_cloud_manager
