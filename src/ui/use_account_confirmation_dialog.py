#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
账号切换确认对话框 
"""

import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QCheckBox, QRadioButton, QWidget, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal


class UseAccountConfirmationDialog(QDialog):
    """账号切换确认对话框"""
    
    confirmed = pyqtSignal(dict)  # 发送确认信号和选项
    
    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.account = account or {}
        self.logger = logging.getLogger(__name__)
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle("切换账号")
        self.setFixedSize(480, 280)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)
        
        # 确认文本
        email = self.account.get('email', '未知')
        confirm_label = QLabel(f"确定要使用账号<b>{email}</b>吗？")
        confirm_label.setWordWrap(True)
        layout.addWidget(confirm_label)
        
        # 警告文本
        warning_label = QLabel("此操作可能会重启Cursor ！")
        warning_label.setStyleSheet("color: #E6A23C; font-weight: bold;")
        layout.addWidget(warning_label)
        
        # 重置机器码选项（主复选框）
        self.reset_machine_checkbox = QCheckBox("重置机器码（推荐）")
        self.reset_machine_checkbox.setChecked(True)  # 立即设置为选中
        self.reset_machine_checkbox.setStyleSheet("font-weight: bold; color: #409EFF;")
        self.reset_machine_checkbox.toggled.connect(self.on_reset_machine_toggled)
        layout.addWidget(self.reset_machine_checkbox)
        
        # 机器码选项容器（子选项）
        self.machine_options_widget = QWidget()
        machine_options_layout = QVBoxLayout(self.machine_options_widget)
        machine_options_layout.setContentsMargins(30, 0, 0, 0)  # 左侧缩进
        machine_options_layout.setSpacing(8)
        
        # 子选项1：随机新机器码（默认选中）
        self.use_random_radio = QRadioButton("随机新的机器码并绑定到账号")
        self.use_random_radio.setChecked(True)  # 立即设置为选中
        self.use_random_radio.setEnabled(True)  # 立即设置为启用
        self.use_random_radio.setStyleSheet("color: #67C23A;")
        machine_options_layout.addWidget(self.use_random_radio)
        
        # 子选项2：使用已绑定的机器码
        self.use_existing_radio = QRadioButton("使用该账号已绑定的机器码")
        self.use_existing_radio.setEnabled(True)  # 立即设置为启用
        self.use_existing_radio.setStyleSheet("color: #606266;")
        machine_options_layout.addWidget(self.use_existing_radio)
        
        # 创建单选按钮组确保互斥性
        self.machine_radio_group = QButtonGroup(self)  # 明确指定parent
        self.machine_radio_group.addButton(self.use_random_radio, 1)  # 指定ID
        self.machine_radio_group.addButton(self.use_existing_radio, 2)
        
        # 设置互斥性（备用方案）
        self.machine_radio_group.setExclusive(True)
        
        # 添加点击事件处理，用于调试
        self.use_random_radio.clicked.connect(lambda: None)
        self.use_existing_radio.clicked.connect(lambda: None)
        
        layout.addWidget(self.machine_options_widget)
        
        # 完全重置Cursor选项
        self.full_reset_checkbox = QCheckBox("完全重置Cursor")
        self.full_reset_checkbox.setChecked(False)  # 默认不选中
        layout.addWidget(self.full_reset_checkbox)
        
        layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton("取消")
        cancel_button.setFixedSize(80, 35)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #F5F7FA;
                color: #606266;
                border: 1px solid #DCDFE6;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #ECF5FF;
                color: #409EFF;
                border-color: #C6E2FF;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        confirm_button = QPushButton("确定")
        confirm_button.setFixedSize(80, 35)
        confirm_button.setStyleSheet("""
            QPushButton {
                background-color: #67C23A;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #85CE61;
            }
        """)
        confirm_button.clicked.connect(self.confirm_switch)
        button_layout.addWidget(confirm_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def on_reset_machine_toggled(self, checked):
        """重置机器码选项切换时，控制子选项的启用状态"""
        
        # 只控制单个按钮，不控制容器（避免PyInstaller环境下的问题）
        self.use_random_radio.setEnabled(checked)
        self.use_existing_radio.setEnabled(checked)
        
        # 如果禁用时，重置为默认选择（随机机器码）
        if not checked:
            self.use_random_radio.setChecked(True)
        elif checked and not (self.use_random_radio.isChecked() or self.use_existing_radio.isChecked()):
            # 如果启用时没有任何选项被选中，默认选择第一个
            self.use_random_radio.setChecked(True)
            
    
    def confirm_switch(self):
        """确认切换"""
        # 获取选项
        options = {
            'reset_machine': self.reset_machine_checkbox.isChecked(),
            'use_existing_machine': self.use_existing_radio.isChecked() if self.reset_machine_checkbox.isChecked() else False,
            'use_random_machine': self.use_random_radio.isChecked() if self.reset_machine_checkbox.isChecked() else False,
            'full_reset': self.full_reset_checkbox.isChecked()
        }
        
        self.logger.info(f"用户确认切换账号: {self.account.get('email', '未知')}, 选项: {options}")
        self.confirmed.emit(options)
        self.accept()