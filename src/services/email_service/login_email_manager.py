#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
登录邮箱管理器 - 管理用于一键登录的邮箱列表
"""

import json
import os
import logging
from typing import Optional, Dict, List
from pathlib import Path


class LoginEmailManager:
    """登录邮箱管理器 - 类似CardManager的邮箱管理"""
    
    def __init__(self, config_file: str = None):
        """
        初始化邮箱管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.logger = logging.getLogger(__name__)
        
        # 默认配置文件路径
        if config_file:
            self.config_file = Path(config_file)
        else:
            # 默认保存在项目目录下
            from ...core.config import Config
            config_dir = Path(Config.get_config_dir())
            self.config_file = config_dir / "login_emails.json"
        
        # 当前使用的邮箱
        self.current_email = None
        
        # 加载邮箱列表
        self.emails = self._load_emails()
    
    def _load_emails(self) -> List[str]:
        """加载邮箱列表"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    emails = data.get('emails', [])
                    self.logger.info(f"✅ 加载了 {len(emails)} 个登录邮箱")
                    return emails
            else:
                self.logger.info("📝 登录邮箱列表为空，创建新文件")
                return []
        except Exception as e:
            self.logger.error(f"加载邮箱列表失败: {str(e)}")
            return []
    
    def _save_emails(self):
        """保存邮箱列表"""
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {'emails': self.emails}
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"✅ 已保存 {len(self.emails)} 个邮箱到配置文件")
        except Exception as e:
            self.logger.error(f"保存邮箱列表失败: {str(e)}")
    
    def add_emails(self, email_list: List[str]) -> int:
        """
        添加邮箱到列表
        
        Args:
            email_list: 邮箱列表
            
        Returns:
            int: 成功添加的数量
        """
        added_count = 0
        for email in email_list:
            email = email.strip()
            if email and '@' in email and email not in self.emails:
                self.emails.append(email)
                added_count += 1
        
        if added_count > 0:
            self._save_emails()
            self.logger.info(f"✅ 添加了 {added_count} 个邮箱")
        
        return added_count
    
    def get_next_email(self) -> Optional[str]:
        """
        获取下一个可用邮箱
        
        Returns:
            str: 邮箱地址，如果没有可用邮箱则返回None
        """
        if not self.emails:
            self.logger.warning("⚠️ 登录邮箱列表为空")
            return None
        
        # 取第一个邮箱
        self.current_email = self.emails[0]
        self.logger.info(f"📧 获取登录邮箱: {self.current_email}")
        return self.current_email
    
    def mark_email_used(self):
        """标记当前邮箱已使用（删除）"""
        if self.current_email and self.current_email in self.emails:
            self.emails.remove(self.current_email)
            self._save_emails()
            self.logger.info(f"✅ 邮箱 {self.current_email} 已登录成功，从列表移除")
            self.current_email = None
    
    def get_available_count(self) -> int:
        """获取可用邮箱数量"""
        return len(self.emails)
    
    def clear_all_emails(self):
        """清空所有邮箱"""
        self.emails = []
        self._save_emails()
        self.logger.info("✅ 已清空所有登录邮箱")


