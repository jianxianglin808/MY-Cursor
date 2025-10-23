#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
激活码验证对话框 - 简化版
只需要验证激活码，不需要机器码和QQ
"""

import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..services.activation_service.client_config import ClientConfigManager


class ActivationDialog(QDialog):
    """激活码验证对话框 - 简化版"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # 客户端激活验证：不需要数据库配置，直接使用内置验证
        self.client_config = ClientConfigManager()
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("激活码验证")
        self.setFixedSize(400, 250)
        self.setModal(True)

        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8fafc, stop: 1 #e2e8f0);
                font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #1e293b;
            }
            QLineEdit {
                background: white;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                padding: 12px;
                font-size: 16px;
                font-weight: bold;
                color: #1e293b;
                letter-spacing: 2px;
            }
            QLineEdit:focus {
                border: 2px solid #3b82f6;
                background: #fefefe;
            }
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #3b82f6, stop: 1 #1d4ed8);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2563eb, stop: 1 #1e40af);
            }
            QPushButton:pressed {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #1d4ed8, stop: 1 #1e3a8a);
            }
            QPushButton#cancel_btn {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #6b7280, stop: 1 #4b5563);
            }
            QPushButton#cancel_btn:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #4b5563, stop: 1 #374151);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 简化的标题
        title_label = QLabel("🔐 激活码验证")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #1e293b; margin: 5px 0;")
        layout.addWidget(title_label)
        
        # 激活码输入区域
        self.create_activation_input(layout)
        
        # 按钮区域
        self.create_buttons(layout)

        # 设置焦点到激活码输入框
        self.activation_input.setFocus()

    def create_activation_input(self, parent_layout):
        """创建激活码输入区域"""
        # 激活码输入框
        self.activation_input = QLineEdit()
        self.activation_input.setPlaceholderText("请输入激活码")
        self.activation_input.setMaxLength(8)
        self.activation_input.textChanged.connect(self.on_activation_code_changed)
        self.activation_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                padding: 15px;
                font-size: 18px;
                font-weight: bold;
                color: #1e293b;
                letter-spacing: 3px;
                text-align: center;
            }
            QLineEdit:focus {
                border: 2px solid #3b82f6;
                background: #fefefe;
            }
        """)
        parent_layout.addWidget(self.activation_input)

        # 状态提示
        self.status_label = QLabel("请输入激活码")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("margin: 5px 0; font-size: 12px; color: #64748b;")
        parent_layout.addWidget(self.status_label)

    def create_buttons(self, parent_layout):
        """创建按钮区域"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        # 取消按钮
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        # 验证按钮
        self.verify_btn = QPushButton("验证激活码")
        self.verify_btn.clicked.connect(self.verify_activation_code)
        self.verify_btn.setDefault(True)  # 设为默认按钮，可以按Enter触发
        button_layout.addWidget(self.verify_btn)

        parent_layout.addLayout(button_layout)

    def on_activation_code_changed(self, text):
        """激活码输入变化时的处理"""
        text = text.strip().upper()
        
        if not text:
            self.status_label.setText("")
            self.status_label.setStyleSheet("color: #6b7280;")
        elif len(text) < 8:
            self.status_label.setText(f"请输入激活码 ({len(text)}/8)")
            self.status_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        elif len(text) == 8:
            self.status_label.setText("✓ 激活码格式正确")
            self.status_label.setStyleSheet("color: #10b981; font-weight: bold;")

        # 自动转换为大写
        if text != self.activation_input.text():
            cursor_pos = self.activation_input.cursorPosition()
            self.activation_input.setText(text)
            self.activation_input.setCursorPosition(cursor_pos)

    def verify_activation_code(self):
        """验证激活码"""
        try:
            activation_code = self.activation_input.text().strip().upper()

            if not activation_code:
                QMessageBox.warning(self, "输入错误", "请输入激活码！")
                return

            if len(activation_code) != 8:
                QMessageBox.warning(self, "输入错误", "激活码格式不正确！")
                return

            # 🔄 显示验证进度提示
            self.verify_btn.setText("🔄 验证中...")
            self.verify_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            
            # 强制刷新界面，确保提示立即显示
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()

            # 使用客户端内置验证（不需要用户配置数据库）
            result = self._verify_activation_code_builtin(activation_code)
            
            # 🔄 恢复按钮状态
            self.verify_btn.setText("🔐 验证激活码")
            self.verify_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)

            if result.get("success"):
                # 验证成功，保存激活码信息
                remaining_hours = result.get("remaining_hours", 24)
                user_type = result.get("user_type", "normal")
                is_admin = result.get("is_admin", False)
                # 处理激活码保存 - 统一使用remaining_hours方式
                if user_type == "permanent_admin":
                    # 永久管理员：使用999999小时表示永久
                    save_success = self.client_config.save_activation_info(
                        activation_code, 999999, user_type, is_admin)
                else:
                    # 普通用户：使用云端返回的remaining_hours
                    remaining_hours = result.get("remaining_hours", 24)  # 默认24小时
                    save_success = self.client_config.save_activation_info(
                        activation_code, remaining_hours, user_type, is_admin)
                
                # 精简成功提示：只保留关键信息
                type_display = (
                    "🔥 永久管理员" if user_type == "permanent_admin" else (
                        "🔧 管理员" if user_type == "admin" else "👤 普通用户"
                    )
                )

                if user_type == "permanent_admin":
                    core_info = f"{type_display} | 永久有效"
                else:
                    core_info = f"{type_display} | 剩余 {remaining_hours:.1f} 小时"

                save_info = "已保存" if save_success else "保存失败"
                success_msg = f"✅ 验证成功 | {core_info} | {save_info}"
                
                # 直接接受对话框，不显示任何弹窗
                self.accept()
            else:
                # 验证失败
                error_msg = result.get("error", "未知错误")
                QMessageBox.warning(
                    self, "验证失败", 
                    f"❌ 激活码验证失败！\n\n"
                    f"错误原因: {error_msg}\n\n"
                    f"💡 请联系管理员获取新的激活码。"
                )

        except Exception as e:
            # 🔄 确保在异常时恢复按钮状态
            self.verify_btn.setText("🔐 验证激活码")
            self.verify_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            
            self.logger.error(f"验证激活码失败: {str(e)}")
            QMessageBox.critical(self, "验证错误", f"验证过程出现错误:\n{str(e)}")

    def _verify_activation_code_builtin(self, code: str) -> dict:
        """
        内置激活码验证（客户端专用，不需要用户配置数据库）
        🔓 已绕过：直接返回永久管理员权限
        """
        # 🔓 绕过激活验证 - 直接返回成功
        self.logger.info(f"🔓 激活验证已绕过，授予永久管理员权限")
        return {
            "success": True,
            "code": code or "BYPASS00",
            "user_type": "permanent_admin",
            "is_admin": True,
            "remaining_hours": float('inf'),
            "expiry_time": None,
            "message": "激活验证已绕过 - 永久管理员权限"
        }
        
        # 原始验证代码（已禁用）
        """
        try:
            import pymysql
            from pymysql.cursors import DictCursor
            from datetime import datetime, timedelta
            
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
                        return {"success": False, "error": "激活码不存在或已禁用"}
                    
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
                        return {
                            "success": True,
                            "code": code,
                            "user_type": user_type,
                            "is_admin": True,
                            "remaining_hours": float('inf'),
                            "expiry_time": None,  # 永久管理员不需要到期时间
                            "message": "永久管理员激活码验证成功"
                        }
                    elif now > expiry_time:
                        return {"success": False, "error": "激活码已过期"}
                    
                    # 检查使用次数限制
                    max_usage_count = result.get('max_usage_count')
                    current_usage_count = result.get('usage_count', 0)
                    
                    if max_usage_count is not None and current_usage_count >= max_usage_count:
                        return {
                            "success": False, 
                            "error": f"激活码使用次数已达上限 ({current_usage_count}/{max_usage_count})"
                        }
                    
                    # 计算剩余时间
                    remaining_hours = (expiry_time - now).total_seconds() / 3600
                    
                    # 更新使用记录
                    if not first_used_time:
                        # 首次使用，记录首次使用时间
                        cursor.execute(
                            "UPDATE activation_codes SET usage_count = usage_count + 1, "
                            "last_used_time = %s, first_used_time = %s WHERE code = %s",
                            (now, now, code)
                        )
                        self.logger.info(f"✅ 记录激活码 {code} 的首次使用时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                        # 重新计算到期时间（基于首次使用时间）
                        if validity_hours:
                            expiry_time = now + timedelta(hours=validity_hours)
                            remaining_hours = (expiry_time - now).total_seconds() / 3600
                    else:
                        # 非首次使用，只更新最后使用时间
                        cursor.execute(
                            "UPDATE activation_codes SET usage_count = usage_count + 1, "
                            "last_used_time = %s WHERE code = %s",
                            (now, code)
                        )
                    
                    conn.commit()
                    
                    return {
                        "success": True,
                        "code": code,
                        "user_type": user_type,
                        "is_admin": user_type in ['admin', 'permanent_admin'],
                        "remaining_hours": remaining_hours,
                        "expiry_time": expiry_time.isoformat(),
                        "message": f"激活码有效，剩余 {remaining_hours:.1f} 小时"
                    }
                    
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"内置验证失败: {str(e)}")
            return {"success": False, "error": f"验证失败: {str(e)}"}
        """

    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.verify_activation_code()
        else:
            super().keyPressEvent(event)