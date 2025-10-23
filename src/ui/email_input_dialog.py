#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
邮箱输入对话框 - 用于手动输入真实邮箱
"""

import re
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QMessageBox
)
from PyQt6.QtCore import Qt


class EmailInputDialog(QDialog):
    """邮箱输入对话框"""
    
    def __init__(self, account_info: dict, parent=None):
        super().__init__(parent)
        self.account_info = account_info
        self.real_email = None
        
        self.init_ui()
        
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("输入真实邮箱")
        self.setFixedSize(450, 280)
        self.setModal(True)
        
        # 设置样式
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
                color: #333333;
            }
            QLabel {
                color: #333333;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                color: #333333;
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #bdbdbd;
                color: #757575;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("✏️ 请输入真实邮箱")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3;")
        layout.addWidget(title_label)
        
        # 说明信息
        format_hint = self.account_info.get('format_hint', '需要手动输入真实邮箱')
        info_text = (
            f"📋 账号信息\n\n"
            f"用户ID：{self.account_info.get('user_id', '未知')}\n"
            f"格式：{format_hint}\n\n"
            f"🔒 为了安全，Cursor不提供邮箱API接口\n"
            f"请手动输入此账号的真实邮箱地址："
        )
        
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                background-color: #fff3e0;
                border: 1px solid #ff9800;
                border-radius: 6px;
                padding: 12px;
                color: #e65100;
            }
        """)
        layout.addWidget(info_label)
        
        # 邮箱输入框
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("例如：your-email@example.com")
        
        # 如果解析出的邮箱看起来是真实的，就预填充
        current_email = self.account_info.get('email', '')
        if current_email and not current_email.endswith('@cursor.local'):
            self.email_input.setText(current_email)
        
        layout.addWidget(self.email_input)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 跳过按钮
        skip_button = QPushButton("跳过（使用解析邮箱）")
        skip_button.setStyleSheet("""
            QPushButton {
                background-color: #9e9e9e;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        skip_button.clicked.connect(self.skip_input)
        button_layout.addWidget(skip_button)
        
        button_layout.addStretch()
        
        # 确认按钮
        confirm_button = QPushButton("确认")
        confirm_button.clicked.connect(self.confirm_input)
        button_layout.addWidget(confirm_button)
        
        # 取消按钮
        cancel_button = QPushButton("取消")
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # 设置焦点到输入框
        self.email_input.setFocus()
    
    def validate_email(self, email: str) -> bool:
        """验证邮箱格式 - 使用通用工具类"""
        from ..utils.common_utils import CommonUtils
        return CommonUtils.validate_email(email)
    
    def confirm_input(self):
        """确认输入"""
        email = self.email_input.text().strip()
        
        if not email:
            QMessageBox.warning(self, "警告", "请输入邮箱地址！")
            return
        
        if not self.validate_email(email):
            QMessageBox.warning(self, "警告", "请输入有效的邮箱格式！")
            return
        
        self.real_email = email
        self.accept()
    
    def skip_input(self):
        """跳过输入，使用解析的邮箱"""
        self.real_email = self.account_info.get('email')
        self.accept()
    
    def get_real_email(self) -> Optional[str]:
        """获取真实邮箱"""
        return self.real_email

