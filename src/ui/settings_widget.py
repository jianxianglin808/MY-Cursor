#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
设置标签页 - 用于配置Cursor安装路径等设置
"""

import os
import sys
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFileDialog, QGroupBox, QMessageBox, QFrame,
    QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QDesktopServices, QCursor

class SettingsWidget(QWidget):
    """设置标签页"""
    
    # 设置变更信号
    settings_changed = pyqtSignal()
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.init_ui()
        self.load_current_settings()
        
    def init_ui(self):
        """初始化UI"""
        # 设置现代化样式
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
            }
            QGroupBox {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8fafc);
                border: 2px solid #e2e8f0;
                border-radius: 12px;
                margin-top: 1ex;
                font-weight: bold;
                padding-top: 15px;
                color: #334155;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                color: #0f172a;
                font-size: 14px;
                font-weight: bold;
            }
            QLabel {
                color: #334155;
                font-size: 13px;
            }
            QLineEdit {
                background: #ffffff;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                color: #1e293b;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
                background: #ffffff;
            }
            QTextEdit {
                background: #ffffff;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 12px;
                color: #1e293b;
            }
            QTextEdit:focus {
                border-color: #3b82f6;
                background: #ffffff;
            }
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #3b82f6, stop: 1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: bold;
                font-size: 12px;
                min-height: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2563eb, stop: 1 #1d4ed8);
            }
            QPushButton:pressed {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #1d4ed8, stop: 1 #1e40af);
            }
            QPushButton[class="secondary"] {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #6b7280, stop: 1 #4b5563);
            }
            QPushButton[class="secondary"]:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #4b5563, stop: 1 #374151);
            }
        """)
        
        # 主布局 - 不使用滚动区域
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 左右分栏布局
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(15)
        
        # 左栏
        left_column = QVBoxLayout()
        left_column.setSpacing(0)
        
        # Cursor安装路径设置组
        install_group = QGroupBox("📁 Cursor安装路径")
        install_layout = QVBoxLayout(install_group)
        install_layout.setSpacing(10)
        
        # 说明文字
        desc_label = QLabel("示例：D:/cursor 或 D:/cursor/Cursor.exe")
        desc_label.setStyleSheet("color: #64748b; font-size: 12px;")
        desc_label.setWordWrap(True)
        install_layout.addWidget(desc_label)
        
        # 路径输入区域
        path_layout = QHBoxLayout()
        path_layout.setSpacing(10)
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("例如：D:/cursor")
        path_layout.addWidget(self.path_input)
        
        self.browse_btn = QPushButton("📁 浏览")
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.clicked.connect(self.browse_cursor_path)
        path_layout.addWidget(self.browse_btn)
        
        install_layout.addLayout(path_layout)
        
        # 当前检测状态
        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 12px;")
        install_layout.addWidget(self.status_label)
        
        left_column.addWidget(install_group)
        
        # 右栏
        right_column = QVBoxLayout()
        right_column.setSpacing(0)
        
        # 浏览器路径设置组
        browser_group = QGroupBox("🌐 浏览器设置")
        browser_layout = QVBoxLayout(browser_group)
        browser_layout.setSpacing(10)
        
        # 浏览器说明文字
        # 根据操作系统设置不同的描述
        if sys.platform.startswith('linux'):
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到可执行文件"
        elif sys.platform == 'darwin':
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到可执行文件"
        else:  # Windows
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到.exe"
        browser_desc_label = QLabel(browser_desc)
        browser_desc_label.setStyleSheet("color: #64748b; font-size: 12px;")
        browser_desc_label.setWordWrap(True)
        browser_layout.addWidget(browser_desc_label)
        
        # 浏览器路径输入区域
        browser_path_layout = QHBoxLayout()
        browser_path_layout.setSpacing(10)
        
        self.browser_path_input = QLineEdit()
        # 根据操作系统设置不同的占位符
        if sys.platform == 'darwin':  # macOS
            browser_placeholder = "例如：/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        elif sys.platform.startswith('linux'):  # Linux
            browser_placeholder = "例如：/usr/bin/google-chrome 或 /usr/bin/chromium-browser"
        else:  # Windows
            browser_placeholder = "例如：D:/Chrome/Application/chrome.exe"
        self.browser_path_input.setPlaceholderText(browser_placeholder)
        browser_path_layout.addWidget(self.browser_path_input)
        
        self.browse_browser_btn = QPushButton("📁 浏览")
        self.browse_browser_btn.setFixedWidth(80)
        self.browse_browser_btn.clicked.connect(self.browse_browser_path)
        browser_path_layout.addWidget(self.browse_browser_btn)
        
        browser_layout.addLayout(browser_path_layout)
        
        # 浏览器状态
        self.browser_status_label = QLabel()
        self.browser_status_label.setStyleSheet("font-size: 12px;")
        browser_layout.addWidget(self.browser_status_label)
        
        right_column.addWidget(browser_group)
        
        # 添加左右两栏到主布局
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        layout.addLayout(columns_layout)
        
        # 备份与恢复 + 重置管理 - 横跨整个页面，左右排列
        bottom_groups_layout = QHBoxLayout()
        bottom_groups_layout.setSpacing(15)
        
        # 备份与恢复组
        backup_group = QGroupBox("💾 备份与恢复")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setSpacing(10)
        
        # 备份说明
        backup_desc = QLabel("备份Cursor的对话记录和设置")
        backup_desc.setStyleSheet("color: #64748b; font-size: 12px;")
        backup_layout.addWidget(backup_desc)
        
        # 备份按钮布局
        backup_btn_layout = QHBoxLayout()
        backup_btn_layout.setSpacing(10)
        
        self.create_backup_btn = QPushButton("💾 创建备份")
        self.create_backup_btn.clicked.connect(self.create_backup)
        backup_btn_layout.addWidget(self.create_backup_btn)
        
        self.restore_backup_btn = QPushButton("📂 恢复备份")
        self.restore_backup_btn.clicked.connect(self.restore_backup)
        backup_btn_layout.addWidget(self.restore_backup_btn)
        
        backup_layout.addLayout(backup_btn_layout)
        bottom_groups_layout.addWidget(backup_group, 1)
        
        # 重置管理组
        reset_group = QGroupBox("🔄 重置管理")
        reset_layout = QVBoxLayout(reset_group)
        reset_layout.setSpacing(10)
        
        # 重置说明
        reset_desc = QLabel("重置Cursor的机器码和设备标识")
        reset_desc.setStyleSheet("color: #64748b; font-size: 12px;")
        reset_layout.addWidget(reset_desc)
        
        # 重置按钮布局
        reset_btn_layout = QHBoxLayout()
        reset_btn_layout.setSpacing(10)
        
        self.reset_machine_btn = QPushButton("🔄 重置机器码")
        self.reset_machine_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f59e0b, stop: 1 #d97706);
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #d97706, stop: 1 #b45309);
            }
        """)
        self.reset_machine_btn.clicked.connect(self.reset_machine_id)
        reset_btn_layout.addWidget(self.reset_machine_btn)
        
        self.complete_reset_btn = QPushButton("💥 完全重置")
        self.complete_reset_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ef4444, stop: 1 #dc2626);
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #dc2626, stop: 1 #b91c1c);
            }
        """)
        self.complete_reset_btn.clicked.connect(self.complete_reset_cursor)
        reset_btn_layout.addWidget(self.complete_reset_btn)
        
        reset_layout.addLayout(reset_btn_layout)
        bottom_groups_layout.addWidget(reset_group, 1)
        
        layout.addLayout(bottom_groups_layout)
        
        # 网络代理设置 - 只占半栏
        proxy_row_layout = QHBoxLayout()
        proxy_row_layout.setSpacing(15)
        
        proxy_group = QGroupBox("🌐 网络代理")
        proxy_layout = QHBoxLayout(proxy_group)
        proxy_layout.setSpacing(10)
        
        self.use_proxy_checkbox = QCheckBox("使用系统代理")
        self.use_proxy_checkbox.setStyleSheet("""
            QCheckBox {
                color: #334155;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #e2e8f0;
                border-radius: 4px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #3b82f6;
                border-color: #3b82f6;
            }
            QCheckBox::indicator:hover {
                border-color: #3b82f6;
            }
        """)
        proxy_layout.addWidget(self.use_proxy_checkbox)
        
        proxy_row_layout.addWidget(proxy_group, 1)
        
        # 手动验证码模式 - 右侧半栏
        manual_verify_group = QGroupBox("✍️ 邮箱验证码-手动模式")
        manual_verify_layout = QHBoxLayout(manual_verify_group)
        manual_verify_layout.setSpacing(10)
        
        self.manual_verify_checkbox = QCheckBox("手动输入邮箱及验证码")
        self.manual_verify_checkbox.setStyleSheet("""
            QCheckBox {
                color: #334155;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #e2e8f0;
                border-radius: 4px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #10b981;
                border-color: #10b981;
            }
            QCheckBox::indicator:hover {
                border-color: #10b981;
            }
        """)
        self.manual_verify_checkbox.setToolTip("开启后：\n1. 邮箱：弹窗输入，程序自动填写\n2. 密码：程序自动生成填写\n3. 验证码：浏览器中手动输入\n4. 人机验证：程序自动处理")
        manual_verify_layout.addWidget(self.manual_verify_checkbox)
        
        proxy_row_layout.addWidget(manual_verify_group, 1)
        
        layout.addLayout(proxy_row_layout)
        
        # Token转换组 - 横跨整个页面
        from PyQt6.QtWidgets import QTextEdit
        token_group = QGroupBox("🔄 Token转换")
        token_layout = QVBoxLayout(token_group)
        token_layout.setSpacing(8)
        
        # 说明文字和状态
        desc_status_layout = QHBoxLayout()
        desc_status_layout.setSpacing(20)
        
        token_desc = QLabel("输入user开头的Token，转换为长效Token")
        token_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        token_desc.setWordWrap(False)
        desc_status_layout.addWidget(token_desc)
        
        # 状态标签（显示转换过程）- 右侧显示区域
        self.convert_status_label = QLabel("")
        self.convert_status_label.setStyleSheet("""
            font-size: 12px;
            padding: 2px 8px;
            background: transparent;
        """)
        self.convert_status_label.setMinimumWidth(200)
        desc_status_layout.addWidget(self.convert_status_label, 1)
        
        token_layout.addLayout(desc_status_layout)
        
        # 左右布局：输入框 + 中间按钮 + 输出框
        token_convert_layout = QHBoxLayout()
        token_convert_layout.setSpacing(10)
        
        # 左边：输入框
        self.token_input = QTextEdit()
        self.token_input.setPlaceholderText("输入user_xxx开头的Token...")
        self.token_input.setFixedHeight(110)
        token_convert_layout.addWidget(self.token_input, 1)
        
        # 中间：转换和复制按钮（垂直排列）
        button_container = QVBoxLayout()
        button_container.setSpacing(10)
        button_container.addStretch()
        
        self.convert_btn = QPushButton("🔄 转换")
        self.convert_btn.setFixedSize(100, 40)
        self.convert_btn.clicked.connect(self.convert_token)
        button_container.addWidget(self.convert_btn)
        
        copy_btn = QPushButton("📋 复制")
        copy_btn.setFixedSize(100, 40)
        copy_btn.clicked.connect(self.copy_converted_token)
        button_container.addWidget(copy_btn)
        
        button_container.addStretch()
        token_convert_layout.addLayout(button_container)
        
        # 右边：输出框
        self.token_output = QTextEdit()
        self.token_output.setPlaceholderText("长效Token将显示在这里...")
        self.token_output.setFixedHeight(110)
        self.token_output.setReadOnly(True)
        token_convert_layout.addWidget(self.token_output, 1)
        
        token_layout.addLayout(token_convert_layout)
        
        layout.addWidget(token_group)
        
        # 底部按钮和版本号区域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # 版本号和项目地址（左侧）
        from ..core.version_config import VersionConfig
        version_label = QLabel(f"版本号：v{VersionConfig.APP_VERSION}")
        version_label.setStyleSheet("color: #64748b; font-size: 12px;")
        button_layout.addWidget(version_label)
        
        # 分隔符
        separator_label = QLabel("  |  ")
        separator_label.setStyleSheet("color: #cbd5e0; font-size: 12px;")
        button_layout.addWidget(separator_label)
        
        # 项目地址链接
        project_link = QLabel('<a href="https://github.com/Aeth247/XC-Cursor" style="color: #3b82f6; text-decoration: none;">项目地址：https://github.com/Aeth247/XC-Cursor</a>')
        project_link.setOpenExternalLinks(True)
        project_link.setStyleSheet("""
            QLabel {
                color: #3b82f6;
                font-size: 12px;
            }
            QLabel:hover {
                color: #2563eb;
            }
        """)
        project_link.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        project_link.setToolTip("点击访问 GitHub 项目主页")
        button_layout.addWidget(project_link)
        
        button_layout.addStretch()
        
        # 导出诊断日志按钮
        export_log_btn = QPushButton("📋 导出诊断日志")
        export_log_btn.setFixedWidth(140)
        export_log_btn.setStyleSheet("""
            QPushButton {
                background: #6366f1;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #4f46e5;
            }
            QPushButton:pressed {
                background: #4338ca;
            }
        """)
        export_log_btn.clicked.connect(self.export_diagnostic_logs)
        button_layout.addWidget(export_log_btn)
        
        self.reset_btn = QPushButton("🔄 重置为默认")
        self.reset_btn.setProperty("class", "secondary")
        self.reset_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(self.reset_btn)
        
        self.save_btn = QPushButton("💾 保存设置")
        self.save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
        
        # 连接信号
        self.path_input.textChanged.connect(self.update_path_info)
        self.browser_path_input.textChanged.connect(self.update_browser_info)
        
    def load_current_settings(self):
        """加载当前设置"""
        try:
            # 确保config_data不为None
            if self.config.config_data is None:
                self.config.config_data = {}
            
            # 获取当前配置的安装路径
            install_path = self.config.config_data.get('cursor', {}).get('install_path', '')
            install_dir = self.config.config_data.get('cursor', {}).get('install_directory', '')
            
            display_path = install_dir if install_dir else install_path
            self.path_input.setText(display_path)
            
            # 获取浏览器路径
            browser_config = self.config.config_data.get('browser', {})
            if isinstance(browser_config, dict):
                browser_path = browser_config.get('path', '')
            else:
                browser_path = ''
            self.browser_path_input.setText(browser_path)
            
            # 获取代理设置
            use_proxy = self.config.get_use_proxy()
            self.use_proxy_checkbox.setChecked(use_proxy)
            
            # 获取手动验证码模式设置
            manual_verify = self.config.get_manual_verify_mode()
            self.manual_verify_checkbox.setChecked(manual_verify)
            
            # 更新路径信息
            self.update_path_info()
            self.update_browser_info()
            
        except Exception as e:
            self.logger.error(f"加载设置失败: {str(e)}")
    
    def browse_cursor_path(self):
        """浏览选择Cursor安装路径"""
        try:
            current_path = self.path_input.text()
            start_dir = current_path if current_path and os.path.exists(current_path) else os.path.expanduser("~")
            
            folder = QFileDialog.getExistingDirectory(
                self,
                "选择Cursor安装目录",
                start_dir,
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
            )
            
            if folder:
                self.path_input.setText(folder)
                
        except Exception as e:
            self.logger.error(f"浏览文件夹失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"选择文件夹时出错: {str(e)}")
    
    def browse_browser_path(self):
        """浏览选择浏览器路径"""
        try:
            current_path = self.browser_path_input.text()
            
            # 根据操作系统设置默认起始目录
            if sys.platform == 'darwin':  # macOS
                default_dir = "/Applications"
            elif sys.platform.startswith('linux'):  # Linux
                default_dir = "/usr/bin"
            else:  # Windows
                default_dir = "C:/Program Files"
            
            start_dir = os.path.dirname(current_path) if current_path and os.path.exists(current_path) else default_dir
            
            # 根据操作系统设置文件过滤器
            if sys.platform == 'darwin' or sys.platform.startswith('linux'):  # macOS/Linux
                file_filter = "所有文件 (*)"
            else:  # Windows
                file_filter = "可执行文件 (*.exe);;所有文件 (*.*)"
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择浏览器可执行文件",
                start_dir,
                file_filter
            )
            
            if file_path:
                self.browser_path_input.setText(file_path)
                
        except Exception as e:
            self.logger.error(f"浏览浏览器文件失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"选择浏览器文件时出错: {str(e)}")
    
    def update_browser_info(self):
        """更新浏览器信息显示"""
        try:
            browser_path = self.browser_path_input.text().strip()
            
            if browser_path:
                if os.path.exists(browser_path):
                    self.browser_status_label.setText("✅ 浏览器路径有效")
                    self.browser_status_label.setStyleSheet("color: #059669; font-size: 12px;")
                else:
                    self.browser_status_label.setText("❌ 浏览器路径不存在")
                    self.browser_status_label.setStyleSheet("color: #dc2626; font-size: 12px;")
            else:
                self.browser_status_label.setText("🔍 未设置（将使用系统默认浏览器）")
                self.browser_status_label.setStyleSheet("color: #64748b; font-size: 12px;")
                
        except Exception as e:
            self.logger.error(f"更新浏览器信息失败: {str(e)}")
    
    def update_path_info(self):
        """更新路径信息显示"""
        try:
            install_path = self.path_input.text().strip()
            
            if install_path:
                if os.path.exists(install_path):
                    self.status_label.setText("✅ 路径有效")
                    self.status_label.setStyleSheet("color: #059669; font-size: 12px;")
                else:
                    self.status_label.setText("❌ 路径不存在")
                    self.status_label.setStyleSheet("color: #dc2626; font-size: 12px;")
            else:
                self.status_label.setText("🔍 未设置（将使用自动检测）")
                self.status_label.setStyleSheet("color: #64748b; font-size: 12px;")
                
        except Exception as e:
            self.logger.error(f"更新路径信息失败: {str(e)}")
    
    def reset_to_default(self):
        """重置为默认设置"""
        try:
            reply = QMessageBox.question(
                self, "确认重置", 
                "确定要重置为默认设置吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.path_input.setText("")
                self.browser_path_input.setText("")
                self.update_path_info()
                self.update_browser_info()
                
        except Exception as e:
            self.logger.error(f"重置设置失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"重置设置时出错: {str(e)}")
    
    def save_settings(self):
        """保存设置"""
        try:
            install_path = self.path_input.text().strip()
            browser_path = self.browser_path_input.text().strip()
            use_proxy = self.use_proxy_checkbox.isChecked()
            manual_verify = self.manual_verify_checkbox.isChecked()
            
            # 验证路径
            if install_path and not os.path.exists(install_path):
                QMessageBox.warning(self, "路径错误", "指定的Cursor安装路径不存在，请检查后重试。")
                return
            
            if browser_path and not os.path.exists(browser_path):
                QMessageBox.warning(self, "路径错误", "指定的浏览器路径不存在，请检查后重试。")
                return
            
            # 保存配置
            cursor_success = self.config.set_cursor_install_path(install_path)
            
            browser_success = True
            try:
                # 确保config_data不为None
                if self.config.config_data is None:
                    self.config.config_data = {}
                
                # 确保browser是字典类型
                if 'browser' not in self.config.config_data or not isinstance(self.config.config_data['browser'], dict):
                    self.config.config_data['browser'] = {}
                
                self.config.config_data['browser']['path'] = browser_path
                self.config._save_config()
                self.logger.info(f"浏览器路径已设置为: {browser_path if browser_path else '系统默认'}")
            except Exception as e:
                self.logger.error(f"保存浏览器路径失败: {str(e)}")
                browser_success = False
            
            proxy_success = True
            try:
                self.config.set_use_proxy(use_proxy)
            except Exception as e:
                self.logger.error(f"保存代理设置失败: {str(e)}")
                proxy_success = False
            
            manual_verify_success = True
            try:
                self.config.set_manual_verify_mode(manual_verify)
            except Exception as e:
                self.logger.error(f"保存手动验证码模式设置失败: {str(e)}")
                manual_verify_success = False
            
            if cursor_success and browser_success and proxy_success and manual_verify_success:
                self._apply_settings_immediately()
                self.settings_changed.emit()
                # 静默保存，不显示成功提示
            else:
                QMessageBox.warning(self, "保存失败", "保存设置时出现错误，请重试。")
                
        except Exception as e:
            self.logger.error(f"保存设置失败: {str(e)}")
            QMessageBox.critical(self, "保存失败", f"保存设置时出错: {str(e)}")
    
    def _apply_settings_immediately(self):
        """立即应用设置变更"""
        try:
            if hasattr(self.parent(), 'cursor_manager') and self.parent().cursor_manager:
                cursor_manager = self.parent().cursor_manager
                from ..services.cursor_service.cursor_patcher import CursorPatcher
                cursor_manager.cursor_patcher = CursorPatcher(self.config)
                self.logger.info("CursorPatcher已更新")
            
            self._update_drissionpage_config()
            self.logger.info("设置已立即生效")
            
        except Exception as e:
            self.logger.error(f"立即应用设置失败: {str(e)}")
    
    def _update_drissionpage_config(self):
        """更新DrissionPage的浏览器配置"""
        try:
            browser_config = self.config.config_data.get('browser', {})
            if isinstance(browser_config, dict):
                browser_path = browser_config.get('path', '')
            else:
                browser_path = ''
            
            if browser_path:
                try:
                    from DrissionPage.common import Settings
                    Settings.singleton_tab_obj = None
                    self.logger.info(f"DrissionPage浏览器路径已更新: {browser_path}")
                except ImportError:
                    self.logger.warning("DrissionPage未安装")
            else:
                self.logger.info("使用系统默认浏览器")
                
        except Exception as e:
            self.logger.error(f"更新DrissionPage配置失败: {str(e)}")
    
    def create_backup(self):
        """创建备份 - 委托给主窗口"""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'create_backup'):
                main_window.create_backup()
            else:
                self.logger.error("无法获取主窗口或主窗口没有create_backup方法")
                QMessageBox.warning(self, "错误", "无法执行创建备份操作")
        except Exception as e:
            self.logger.error(f"调用创建备份失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"调用创建备份失败: {str(e)}")
    
    def restore_backup(self):
        """恢复备份 - 委托给主窗口"""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'restore_backup'):
                main_window.restore_backup()
            else:
                self.logger.error("无法获取主窗口或主窗口没有restore_backup方法")
                QMessageBox.warning(self, "错误", "无法执行恢复备份操作")
        except Exception as e:
            self.logger.error(f"调用恢复备份失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"调用恢复备份失败: {str(e)}")
    
    def export_diagnostic_logs(self):
        """导出诊断日志到桌面"""
        try:
            import zipfile
            import datetime
            import shutil
            from pathlib import Path
            
            # 收集所有日志和配置信息
            log_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'logs')
            config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor')
            
            # 创建临时目录
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            desktop = os.path.join(os.path.expanduser("~"), 'Desktop')
            zip_name = f"XC-Cursor-Diagnostic-{timestamp}.zip"
            zip_path = os.path.join(desktop, zip_name)
            
            # 创建诊断报告
            report_content = []
            report_content.append("="*80)
            report_content.append("MY Cursor 诊断报告")
            report_content.append("="*80)
            report_content.append(f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report_content.append(f"系统: {sys.platform}")
            report_content.append(f"Python: {sys.version}")
            
            try:
                import platform
                report_content.append(f"平台详情: {platform.platform()}")
            except:
                pass
            
            # 添加版本信息
            try:
                from ..core.version_config import VersionConfig
                report_content.append(f"应用版本: v{VersionConfig.APP_VERSION}")
                report_content.append(f"版本类型: {VersionConfig.get_version_type()}")
            except:
                pass
            
            report_content.append("\n配置路径:")
            report_content.append(f"  - 配置目录: {config_dir}")
            report_content.append(f"  - 日志目录: {log_dir}")
            
            # 检查关键文件
            report_content.append("\n关键文件检查:")
            key_files = [
                os.path.join(config_dir, 'config.json'),
                os.path.join(config_dir, 'accounts.json'),
                os.path.join(log_dir, 'debug.log'),
                os.path.join(log_dir, 'startup_error.log'),
            ]
            for file_path in key_files:
                exists = "✓" if os.path.exists(file_path) else "✗"
                size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                report_content.append(f"  {exists} {file_path} ({size} bytes)")
            
            report_content.append("\n"+ "="*80)
            
            # 创建zip文件
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加诊断报告
                zipf.writestr('DIAGNOSTIC_REPORT.txt', '\n'.join(report_content))
                
                # 添加所有日志文件
                if os.path.exists(log_dir):
                    for log_file in Path(log_dir).glob('*.log'):
                        arcname = f'logs/{log_file.name}'
                        zipf.write(log_file, arcname=arcname)
                
                # 添加配置文件（不包含敏感信息）
                config_file = os.path.join(config_dir, 'config.json')
                if os.path.exists(config_file):
                    zipf.write(config_file, arcname='config.json')
            
            self.logger.info(f"诊断日志已导出到: {zip_path}")
            
            # 显示成功消息
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("导出成功")
            msg.setText(f"诊断日志已导出到桌面：\n\n{zip_name}")
            msg.setInformativeText("请将此文件发送给开发者以帮助解决问题。")
            
            # 添加打开文件夹按钮
            open_folder_btn = msg.addButton("打开文件夹", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            
            msg.exec()
            
            # 如果用户点击了打开文件夹
            if msg.clickedButton() == open_folder_btn:
                if sys.platform == 'darwin':
                    os.system(f'open "{desktop}"')
                elif sys.platform == 'win32':
                    os.startfile(desktop)
                else:
                    os.system(f'xdg-open "{desktop}"')
                    
        except Exception as e:
            self.logger.error(f"导出诊断日志失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"导出诊断日志失败:\n{str(e)}")
    
    def reset_machine_id(self):
        """重置机器码 - 委托给主窗口"""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'reset_machine_id'):
                main_window.reset_machine_id()
            else:
                self.logger.error("无法获取主窗口或主窗口没有reset_machine_id方法")
                QMessageBox.warning(self, "错误", "无法执行重置机器码操作")
        except Exception as e:
            self.logger.error(f"调用重置机器码失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"调用重置机器码失败: {str(e)}")
    
    def complete_reset_cursor(self):
        """完全重置 - 委托给主窗口"""
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'complete_reset_cursor'):
                main_window.complete_reset_cursor()
            else:
                self.logger.error("无法获取主窗口或主窗口没有complete_reset_cursor方法")
                QMessageBox.warning(self, "错误", "无法执行完全重置操作")
        except Exception as e:
            self.logger.error(f"调用完全重置失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"调用完全重置失败: {str(e)}")
    
    def convert_token(self):
        """转换Token"""
        try:
            input_token = self.token_input.toPlainText().strip()
            
            if not input_token:
                self.convert_status_label.setText("请输入Token")
                self.convert_status_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 2px 8px; background: transparent;")
                return
            
            # 检查是否是user开头的token
            if not input_token.startswith('user_'):
                self.convert_status_label.setText("Token必须以user_开头")
                self.convert_status_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 2px 8px; background: transparent;")
                return
            
            self.convert_status_label.setText("正在转换，请稍候...")
            self.convert_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 2px 8px; background: transparent;")
            self.convert_btn.setEnabled(False)
            
            # 强制刷新UI显示状态
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # 执行转换
            from ..utils.session_token_converter import SessionTokenConverter
            converter = SessionTokenConverter(self.config)
            
            # 解析token，提取user_id
            if '::' in input_token or '%3A%3A' in input_token:
                separator = '::' if '::' in input_token else '%3A%3A'
                parts = input_token.split(separator, 1)
                user_id = parts[0] if len(parts) >= 1 else None
            else:
                # 如果没有::，整个就是workos_token
                user_id = None
            
            success, access_token, refresh_token = converter.convert_workos_to_session_jwt(input_token, user_id)
            
            if success and access_token:
                self.token_output.setText(access_token)
                self.convert_status_label.setText("转换成功")
                self.convert_status_label.setStyleSheet("color: #059669; font-size: 12px; padding: 2px 8px; background: transparent;")
                self.logger.info(f"✅ Token转换成功: {len(access_token)}字符")
            else:
                self.convert_status_label.setText("转换失败")
                self.convert_status_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 2px 8px; background: transparent;")
                self.token_output.setText("转换失败，请检查Token是否正确")
                self.logger.error("Token转换失败")
            
        except Exception as e:
            self.logger.error(f"Token转换异常: {str(e)}")
            self.convert_status_label.setText("转换失败")
            self.convert_status_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 2px 8px; background: transparent;")
            self.token_output.setText(f"转换异常: {str(e)}")
        finally:
            self.convert_btn.setEnabled(True)
    
    def copy_converted_token(self):
        """复制转换后的长效Token"""
        try:
            jwt_token = self.token_output.toPlainText().strip()
            
            if not jwt_token or jwt_token == "长效Token将显示在这里...":
                QMessageBox.warning(self, "提示", "没有可复制的长效Token")
                return
            
            from ..utils.common_utils import CommonUtils
            success = CommonUtils.copy_to_clipboard(jwt_token, show_message=True)
            
            if success:
                self.logger.info("长效Token已复制到剪贴板")
                self.convert_status_label.setText("✅ 长效Token已复制到剪贴板")
                self.convert_status_label.setStyleSheet("color: #059669; font-size: 12px;")
            else:
                QMessageBox.warning(self, "复制失败", "无法复制到剪贴板")
                
        except Exception as e:
            self.logger.error(f"复制Token失败: {str(e)}")
            QMessageBox.warning(self, "复制失败", f"复制失败: {str(e)}")

