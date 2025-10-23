#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cursor设置对话框 - 用于配置Cursor安装路径等设置
"""

import os
import sys
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFileDialog, QGroupBox, QMessageBox, QFrame,
    QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

class CursorSettingsDialog(QDialog):
    """Cursor设置对话框"""
    
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
        self.setWindowTitle("Cursor设置")
        self.setFixedSize(600, 720)
        self.setModal(True)
        
        # 设置现代化样式
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8fafc, stop: 1 #e2e8f0);
                color: #1e293b;
                font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
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
        
        # 主布局
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 标题和版本号
        title_layout = QHBoxLayout()
        title_label = QLabel("🔧 Cursor设置")
        title_font = QFont("Microsoft YaHei", 16, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #0f172a; margin-bottom: 10px;")
        title_layout.addWidget(title_label)
        
        # 版本号
        from ..core.version_config import VersionConfig
        version_label = QLabel(f"v{VersionConfig.APP_VERSION}")
        version_label.setStyleSheet("color: #64748b; font-size: 14px; margin-bottom: 10px;")
        title_layout.addWidget(version_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Cursor安装路径设置组
        install_group = QGroupBox("📁 Cursor安装路径")
        install_layout = QVBoxLayout(install_group)
        install_layout.setSpacing(15)
        
        # 说明文字
        desc_label = QLabel("示例：D:/cursor 或 D:/cursor/Cursor.exe")
        desc_label.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 10px;")
        desc_label.setWordWrap(True)
        install_layout.addWidget(desc_label)
        
        # 路径输入区域
        path_layout = QHBoxLayout()
        
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
        self.status_label.setStyleSheet("font-size: 12px; margin-top: 5px;")
        install_layout.addWidget(self.status_label)
        
        layout.addWidget(install_group)
        
        # 浏览器路径设置组
        browser_group = QGroupBox("🌐 浏览器设置")
        browser_layout = QVBoxLayout(browser_group)
        browser_layout.setSpacing(15)
        
        # 浏览器说明文字
        # 根据操作系统设置不同的描述
        if sys.platform.startswith('linux'):
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到可执行文件"
        elif sys.platform == 'darwin':
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到可执行文件"
        else:  # Windows
            browser_desc = "支持Chrome、Edge、Firefox，路径需要精确到.exe"
        browser_desc_label = QLabel(browser_desc)
        browser_desc_label.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 10px;")
        browser_desc_label.setWordWrap(True)
        browser_layout.addWidget(browser_desc_label)
        
        # 浏览器路径输入区域
        browser_path_layout = QHBoxLayout()
        
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
        self.browser_status_label.setStyleSheet("font-size: 12px; margin-top: 5px;")
        browser_layout.addWidget(self.browser_status_label)
        
        layout.addWidget(browser_group)
        
        # 网络设置组
        network_group = QGroupBox("🌐 网络设置")
        network_layout = QVBoxLayout(network_group)
        network_layout.setSpacing(15)
        
        # 代理开关
        self.use_proxy_checkbox = QCheckBox("使用系统代理")
        self.use_proxy_checkbox.setStyleSheet("""
            QCheckBox {
                color: #334155;
                font-size: 13px;
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
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPg==);
            }
            QCheckBox::indicator:hover {
                border-color: #3b82f6;
            }
        """)
        network_layout.addWidget(self.use_proxy_checkbox)
        
        # 代理状态提示
        self.proxy_status_label = QLabel()
        self.proxy_status_label.setStyleSheet("font-size: 12px; margin-top: 5px;")
        network_layout.addWidget(self.proxy_status_label)
        
        # 更新代理状态提示
        self.use_proxy_checkbox.stateChanged.connect(self.update_proxy_status)
        
        layout.addWidget(network_group)
        
        # 备份与恢复组
        backup_group = QGroupBox("💾 备份与恢复")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setSpacing(15)
        
        # 备份说明
        backup_desc = QLabel("备份Cursor的对话记录和设置")
        backup_desc.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 10px;")
        backup_layout.addWidget(backup_desc)
        
        # 备份按钮布局
        backup_btn_layout = QHBoxLayout()
        
        self.create_backup_btn = QPushButton("💾 创建备份")
        self.create_backup_btn.clicked.connect(self.create_backup)
        backup_btn_layout.addWidget(self.create_backup_btn)
        
        self.restore_backup_btn = QPushButton("📂 恢复备份")
        self.restore_backup_btn.clicked.connect(self.restore_backup)
        backup_btn_layout.addWidget(self.restore_backup_btn)
        
        backup_layout.addLayout(backup_btn_layout)
        layout.addWidget(backup_group)
        
        # 重置管理组
        reset_group = QGroupBox("🔄 重置管理")
        reset_layout = QVBoxLayout(reset_group)
        reset_layout.setSpacing(15)
        
        # 重置说明
        reset_desc = QLabel("重置Cursor的机器码和设备标识")
        reset_desc.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 10px;")
        reset_layout.addWidget(reset_desc)
        
        # 重置按钮布局
        reset_btn_layout = QHBoxLayout()
        
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
        layout.addWidget(reset_group)
        
        # 创建隐藏的标签，用于内部逻辑
        self.data_dir_label = QLabel()
        self.data_dir_label.hide()  # 隐藏
        
        self.db_path_label = QLabel()
        self.db_path_label.hide()  # 隐藏
        
        # layout.addWidget(info_group)  # 不添加到布局中
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #e2e8f0; margin: 10px 0;")
        layout.addWidget(separator)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.reset_btn = QPushButton("🔄 重置为默认")
        self.reset_btn.setProperty("class", "secondary")
        self.reset_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(self.reset_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        self.save_btn = QPushButton("💾 保存设置")
        self.save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 连接信号
        self.path_input.textChanged.connect(self.update_path_info)
        
    def load_current_settings(self):
        """加载当前设置"""
        try:
            # 获取当前配置的安装路径 - 优先显示目录路径
            install_path = self.config.config_data.get('cursor', {}).get('install_path', '')
            install_dir = self.config.config_data.get('cursor', {}).get('install_directory', '')
            
            # 显示目录路径而不是exe路径
            display_path = install_dir if install_dir else install_path
            self.path_input.setText(display_path)
            
            # 获取浏览器路径
            browser_path = self.config.config_data.get('browser', {}).get('path', '')
            self.browser_path_input.setText(browser_path)
            
            # 获取代理设置
            use_proxy = self.config.get_use_proxy()
            self.use_proxy_checkbox.setChecked(use_proxy)
            
            # 更新路径信息
            self.update_path_info()
            self.update_browser_info()
            self.update_proxy_status()
            
        except Exception as e:
            self.logger.error(f"加载设置失败: {str(e)}")
    
    def browse_cursor_path(self):
        """浏览选择Cursor安装路径"""
        try:
            # 获取当前路径作为起始目录
            current_path = self.path_input.text()
            start_dir = current_path if current_path and os.path.exists(current_path) else os.path.expanduser("~")
            
            # 打开文件夹选择对话框
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
            # 获取当前路径作为起始目录
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
            
            # 打开文件选择对话框
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
                # 检查路径是否存在
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
            self.browser_status_label.setText(f"❌ 更新信息失败: {str(e)}")
            self.browser_status_label.setStyleSheet("color: #dc2626; font-size: 12px;")
    
    def update_proxy_status(self):
        """更新代理状态显示"""
        try:
            # 无论启用还是禁用都不显示状态文字
            self.proxy_status_label.setText("")
            self.proxy_status_label.setStyleSheet("")
        except Exception as e:
            self.logger.error(f"更新代理状态失败: {str(e)}")
    
    def update_path_info(self):
        """更新路径信息显示"""
        try:
            install_path = self.path_input.text().strip()
            
            if install_path:
                # 检查路径是否存在
                if os.path.exists(install_path):
                    self.status_label.setText("✅ 路径有效")
                    self.status_label.setStyleSheet("color: #059669; font-size: 12px;")
                else:
                    self.status_label.setText("❌ 路径不存在")
                    self.status_label.setStyleSheet("color: #dc2626; font-size: 12px;")
                
                # 显示相关路径信息
                if os.name == 'nt':  # Windows
                    data_dir = os.path.join(os.getenv("APPDATA", ""), "Cursor")
                    db_path = os.path.join(data_dir, "User", "globalStorage", "state.vscdb")
                else:
                    data_dir = self.config._get_cursor_data_dir()
                    db_path = self.config._get_cursor_db_path()
                
                self.data_dir_label.setText(f"📂 数据目录: {data_dir}")
                self.db_path_label.setText(f"🗄️ 数据库路径: {db_path}")
                
            else:
                self.status_label.setText("🔍 未设置（将使用自动检测）")
                self.status_label.setStyleSheet("color: #64748b; font-size: 12px;")
                
                # 显示默认路径信息
                data_dir = self.config._get_cursor_data_dir()
                db_path = self.config._get_cursor_db_path()
                self.data_dir_label.setText(f"📂 数据目录: {data_dir}")
                self.db_path_label.setText(f"🗄️ 数据库路径: {db_path}")
                
        except Exception as e:
            self.logger.error(f"更新路径信息失败: {str(e)}")
            self.status_label.setText(f"❌ 更新信息失败: {str(e)}")
            self.status_label.setStyleSheet("color: #dc2626; font-size: 12px;")
    
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
            
            # 验证Cursor路径
            if install_path and not os.path.exists(install_path):
                QMessageBox.warning(self, "路径错误", "指定的Cursor安装路径不存在，请检查后重试。")
                return
            
            # 验证浏览器路径
            if browser_path and not os.path.exists(browser_path):
                QMessageBox.warning(self, "路径错误", "指定的浏览器路径不存在，请检查后重试。")
                return
            
            # 保存Cursor路径到配置
            cursor_success = self.config.set_cursor_install_path(install_path)
            
            # 保存浏览器路径到配置
            browser_success = True
            try:
                if 'browser' not in self.config.config_data:
                    self.config.config_data['browser'] = {}
                self.config.config_data['browser']['path'] = browser_path
                self.config._save_config()
                self.logger.info(f"浏览器路径已设置为: {browser_path if browser_path else '系统默认'}")
            except Exception as e:
                self.logger.error(f"保存浏览器路径失败: {str(e)}")
                browser_success = False
            
            # 保存代理设置
            proxy_success = True
            try:
                self.config.set_use_proxy(use_proxy)
            except Exception as e:
                self.logger.error(f"保存代理设置失败: {str(e)}")
                proxy_success = False
            
            if cursor_success and browser_success and proxy_success:
                # 立即应用设置变更
                self._apply_settings_immediately()
                
                # 发出设置变更信号
                self.settings_changed.emit()
                
                self.accept()
            else:
                QMessageBox.warning(self, "保存失败", "保存设置时出现错误，请重试。")
                
        except Exception as e:
            self.logger.error(f"保存设置失败: {str(e)}")
            QMessageBox.critical(self, "保存失败", f"保存设置时出错: {str(e)}")
    
    def _apply_settings_immediately(self):
        """立即应用设置变更，无需重启"""
        try:
            # 重新初始化CursorPatcher，使其使用新的路径配置
            if hasattr(self.parent(), 'cursor_manager') and self.parent().cursor_manager:
                cursor_manager = self.parent().cursor_manager
                # 重新创建CursorPatcher实例
                from ..services.cursor_service.cursor_patcher import CursorPatcher
                cursor_manager.cursor_patcher = CursorPatcher(self.config)
                self.logger.info("CursorPatcher已更新为使用新路径配置")
            
            # 更新DrissionPage的浏览器配置
            self._update_drissionpage_config()
            
            self.logger.info("设置已立即生效")
            
        except Exception as e:
            self.logger.error(f"立即应用设置失败: {str(e)}")
    
    def _update_drissionpage_config(self):
        """更新DrissionPage的浏览器配置"""
        try:
            browser_path = self.config.config_data.get('browser', {}).get('path', '')
            if browser_path:
                # 设置DrissionPage使用指定的浏览器
                try:
                    from DrissionPage.common import Settings
                    Settings.singleton_tab_obj = None  # 重置单例，确保使用新配置
                    self.logger.info(f"DrissionPage浏览器路径已更新: {browser_path}")
                except ImportError:
                    self.logger.warning("DrissionPage未安装，跳过浏览器配置更新")
            else:
                self.logger.info("使用系统默认浏览器")
                
        except Exception as e:
            self.logger.error(f"更新DrissionPage配置失败: {str(e)}")
    
    def create_backup(self):
        """创建备份 - 委托给主窗口"""
        if self.parent():
            self.parent().create_backup()
    
    def restore_backup(self):
        """恢复备份 - 委托给主窗口"""
        if self.parent():
            self.parent().restore_backup()
    
    def reset_machine_id(self):
        """重置机器码 - 委托给主窗口"""
        if self.parent():
            self.parent().reset_machine_id()
    
    def complete_reset_cursor(self):
        """完全重置 - 委托给主窗口"""
        if self.parent():
            self.parent().complete_reset_cursor()
