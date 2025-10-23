#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自动注册界面组件 - 为XC-Cursor添加自动注册功能
"""

import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QSpinBox, QGroupBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog,
    QFormLayout, QLineEdit, QCheckBox, QTabWidget, QSplitter,
    QRadioButton, QButtonGroup, QComboBox, QStackedWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from ..services.email_service.auto_register_engine import AutoRegisterEngine
from ..services.email_service.register_config_manager import RegisterConfigManager
from ..core.config import Config


class AutoRegisterThread(QThread):
    """自动注册工作线程"""
    
    # 信号定义
    progress_signal = pyqtSignal(str)  # 进度信息
    progress_count_signal = pyqtSignal(int, int)  # 进度计数信号(当前数, 总数)
    finished_signal = pyqtSignal(bool, str, dict)  # 完成信号(成功, 消息, 账号信息)
    log_signal = pyqtSignal(str)  # 日志信号
    email_input_request = pyqtSignal()  # 邮箱输入请求信号
    
    def __init__(self, account_config, account_manager, register_config, count=1, 
                 parallel_enabled=False, parallel_workers=3, headless_mode=False, 
                 register_mode="password"):
        super().__init__()
        self.account_config = account_config  # 账号数据配置
        self.register_config = register_config  # 注册流程配置
        self.account_manager = account_manager
        self.register_count = count
        self.stop_flag = False
        self.headless_mode = headless_mode
        self.register_mode = register_mode
        
        self.logger = logging.getLogger(__name__)
        
        # 创建注册引擎
        self.register_engine = AutoRegisterEngine(account_config, account_manager, register_config)
        self.register_engine.set_progress_callback(self._on_progress)
        
        # 设置无头模式
        if hasattr(self.register_engine, 'set_headless_mode'):
            self.register_engine.set_headless_mode(self.headless_mode)
        
        # 设置注册模式
        if hasattr(self.register_engine, 'set_register_mode'):
            self.register_engine.set_register_mode(self.register_mode)
        
        # 禁用并行注册模式（自动注册始终使用串行）
        self.register_engine.enable_parallel_mode(False, 1)
    
    def _on_progress(self, message: str):
        """进度回调处理"""
        # 处理特殊信号：请求邮箱输入（发射信号到主线程）
        if message == "__REQUEST_EMAIL_INPUT__":
            self.email_input_request.emit()  # 通过信号切换到主线程
            return
        
        self.progress_signal.emit(message)
        self.log_signal.emit(message)  # 移除重复时间戳，让add_log统一处理
    
    def _handle_email_input_request(self):
        """处理邮箱输入请求（在主线程中执行）"""
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton
            from PyQt6.QtCore import Qt
            
            # 创建自定义对话框
            dialog = QDialog()
            dialog.setWindowTitle("输入邮箱")
            dialog.setFixedWidth(400)
            dialog.setFixedHeight(180)
            dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            
            layout = QVBoxLayout()
            layout.setSpacing(15)
            layout.setContentsMargins(20, 20, 20, 20)
            
            # 标题
            label = QLabel("输入注册邮箱:")
            label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    color: #1f2937;
                    font-weight: bold;
                }
            """)
            layout.addWidget(label)
            
            # 邮箱输入框
            email_input = QLineEdit()
            email_input.setPlaceholderText("example@gmail.com")
            email_input.setStyleSheet("""
                QLineEdit {
                    padding: 10px;
                    font-size: 13px;
                    border: 2px solid #e5e7eb;
                    border-radius: 6px;
                    background: #ffffff;
                }
                QLineEdit:focus {
                    border: 2px solid #3b82f6;
                }
            """)
            layout.addWidget(email_input)
            
            # 确认按钮
            btn = QPushButton("确认")
            btn.setFixedHeight(40)
            btn.setStyleSheet("""
                QPushButton {
                    background: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #2563eb;
                }
                QPushButton:pressed {
                    background: #1d4ed8;
                }
            """)
            btn.clicked.connect(dialog.accept)
            layout.addWidget(btn)
            
            dialog.setLayout(layout)
            
            # 回车键也能确认
            email_input.returnPressed.connect(dialog.accept)
            email_input.setFocus()
            
            # 显示对话框并获取输入
            if dialog.exec() == QDialog.DialogCode.Accepted:
                user_email = email_input.text().strip()
                if user_email and '@' in user_email:
                    # 更新注册引擎的account_info
                    if hasattr(self.register_engine, 'account_info'):
                        self.register_engine.account_info['email'] = user_email
                        self.log_signal.emit(f"✅ 已输入邮箱: {user_email}")
                    
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"处理邮箱输入请求失败: {str(e)}")
    
    def stop(self):
        """停止注册"""
        self.stop_flag = True
        # 立即通知注册引擎停止
        if hasattr(self, 'register_engine') and self.register_engine:
            self.register_engine.stop_registration()
        self._on_progress("🛑 正在停止注册...")
    
    def run(self):
        """线程主函数"""
        try:
            # 初始化进度为0
            self.progress_count_signal.emit(0, self.register_count)
            
            # 检查配置
            domains = self.register_config.get_domains()
            if not domains or len(domains) < 1:
                self.finished_signal.emit(False, "请先配置至少一个域名", {})
                return
            
            # 检查是否需要检测银行卡数量（跳过绑卡或无头模式时不检测）
            skip_card_binding = self.register_config.get_skip_card_binding()
            
            if not skip_card_binding and not self.headless_mode:
                # 只有在使用银行卡且非无头模式时才检测数量
                available_cards = self.register_config.get_available_cards_count()
                if available_cards < self.register_count:
                    self.finished_signal.emit(False, f"可用银行卡不足，需要{self.register_count}张，可用{available_cards}张", {})
                    return
            
            # 设置自定义进度回调，用于更新进度
            def progress_callback_with_count(message):
                self._on_progress(message)
                # 从消息中提取进度信息
                if "个账号注册" in message and "进度:" in message:
                    try:
                        # 提取 "进度: X/Y" 部分
                        progress_part = message.split("进度:")[1].strip()
                        current, total = progress_part.split("/")
                        self.progress_count_signal.emit(int(current), int(total))
                    except:
                        pass
                # 优先处理总进度更新
                if "📊 总进度:" in message:
                    try:
                        # 提取 "📊 总进度: X/Y" 部分
                        import re
                        match = re.search(r'总进度:\s*(\d+)/(\d+)', message)
                        if match:
                            current = int(match.group(1))
                            total = int(match.group(2))
                            self.progress_count_signal.emit(current, total)
                    except:
                        pass
                elif "开始注册任务" in message:
                    # 捕获任务开始
                    try:
                        import re
                        match = re.search(r'开始注册任务\s*(\d+)/(\d+)', message)
                        if match:
                            task_num = int(match.group(1))
                            total = int(match.group(2))
                            # 任务开始时立即更新进度（显示正在进行的任务数）
                            self.progress_count_signal.emit(task_num, total)
                    except:
                        pass
                elif "已停止注册" in message:
                    # 停止注册时保持当前进度
                    pass
                elif "已完成" in message and "/" in message:
                    try:
                        # 从停止消息中提取进度
                        parts = message.split("已完成")[1].strip()
                        current, total = parts.split("/")[0:2]
                        current = int(current.strip())
                        total = int(total.split()[0])
                        self.progress_count_signal.emit(current, total)
                    except:
                        pass
            
            # 更新进度回调
            self.register_engine.set_progress_callback(progress_callback_with_count)
            
            # 设置注册模式
            if hasattr(self.register_engine, 'set_register_mode'):
                self.register_engine.set_register_mode(self.register_mode)
            
            # 执行串行批量注册
            results = self.register_engine.batch_register(self.register_count)
            
            # 统计结果
            success_count = len([r for r in results if r['success']])
            completed_count = len(results)
            
            # 发送最终进度
            self.progress_count_signal.emit(completed_count, self.register_count)
            
            if success_count > 0:
                self.finished_signal.emit(
                    True, 
                    f"注册完成！成功 {success_count}/{completed_count} 个账号（总计划：{self.register_count}）", 
                    {"results": results, "completed": completed_count, "success": success_count, "total": self.register_count}
                )
            else:
                self.finished_signal.emit(
                    False, 
                    f"注册失败！完成 {completed_count}/{self.register_count} 个账号，成功 0 个", 
                    {"results": results, "completed": completed_count, "success": 0, "total": self.register_count}
                )
                
        except Exception as e:
            self.logger.error(f"注册线程异常: {str(e)}")
            self.finished_signal.emit(False, f"注册过程异常: {str(e)}", {})


class ConfigDialog(QDialog):
    """配置对话框"""
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.register_config = config_manager
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("自动注册配置")
        # 调整对话框高度
        self.resize(500, 520)
        self.setMinimumSize(650, 650)
        
        layout = QVBoxLayout(self)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 域名配置标签页
        domain_tab = self._create_domain_tab()
        tab_widget.addTab(domain_tab, "域名配置")
        
        # 银行卡配置标签页
        card_tab = self._create_card_tab()
        tab_widget.addTab(card_tab, "银行卡配置")
        
        # 邮箱配置标签页
        email_tab = self._create_email_tab()
        tab_widget.addTab(email_tab, "邮箱配置")
        
        # 手机号码配置标签页
        phone_tab = self._create_phone_verification_tab()
        tab_widget.addTab(phone_tab, "手机号码配置")
        
        layout.addWidget(tab_widget)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self.save_config)
        # 为保存按钮设置明确的样式，确保在所有主题下都可见
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-width: 80px;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        # 为取消按钮设置明确的样式
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-width: 80px;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #545b62;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _create_domain_tab(self) -> QWidget:
        """创建域名配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        info_label = QLabel("域名配置（支持任意数量，每行一个域名）：")
        layout.addWidget(info_label)
        
        desc_label = QLabel("注册时会从配置的域名中随机选择一个")
        desc_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(desc_label)
        
        example_label = QLabel("示例：\naeth.top\nexample.com\ntest.org")
        example_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(example_label)
        
        # 域名文本输入框
        self.domains_text = QTextEdit()
        self.domains_text.setPlaceholderText("请输入域名，每行一个...")
        self.domains_text.setMaximumHeight(150)
        layout.addWidget(self.domains_text)
        
        layout.addStretch()
        
        return widget
    
    def _create_card_tab(self) -> QWidget:
        """创建银行卡配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 银行卡文本输入
        info_label = QLabel("银行卡信息（每行一张卡）：")
        layout.addWidget(info_label)
        
        format_label = QLabel("格式：卡号,到期日,CVC (持卡人姓名自动随机生成)")
        format_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(format_label)
        
        example_label = QLabel("示例：5598880458332832,0530,351")
        example_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(example_label)
        
        self.cards_text = QTextEdit()
        self.cards_text.setPlaceholderText("请输入银行卡信息，每行一张卡...")
        # 🔥 设置最大高度，确保按钮有足够空间显示
        self.cards_text.setMaximumHeight(300)
        layout.addWidget(self.cards_text)
        
        # 跳过绑卡选项
        self.skip_card_binding_checkbox = QCheckBox("⚡ 跳过绑卡")
        self.skip_card_binding_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF9800;
                padding: 8px;
                background: #FFF3E0;
                border-radius: 6px;
                border-left: 4px solid #FF9800;
            }
            QCheckBox:hover {
                background: #FFE0B2;
            }
        """)
        self.skip_card_binding_checkbox.setToolTip("开启后，注册流程在获取到token并保存账号后立即结束，不再进行绑卡操作")
        layout.addWidget(self.skip_card_binding_checkbox)
        
        # 恢复功能按钮
        reset_layout = QHBoxLayout()
        
        # 恢复初始状态按钮（红框位置）
        self.restore_initial_btn = QPushButton("🔄 恢复初始状态")
        self.restore_initial_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #FF6B6B, stop: 1 #E55353);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #E55353, stop: 1 #CC4B4B);
            }
            QPushButton:pressed {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #CC4B4B, stop: 1 #B84444);
            }
        """)
        self.restore_initial_btn.clicked.connect(self.restore_initial_state)
        reset_layout.addWidget(self.restore_initial_btn)
        
        # 原有的重置按钮
        self.reset_cards_btn = QPushButton("重置所有卡片状态")
        self.reset_cards_btn.clicked.connect(self.reset_cards)
        reset_layout.addWidget(self.reset_cards_btn)
        
        reset_layout.addStretch()
        
        layout.addLayout(reset_layout)
        
        return widget
    
    def _create_email_tab(self) -> QWidget:
        """创建邮箱配置标签页"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)
        
        # 邮箱类型选择
        type_group = QGroupBox("📧 邮箱类型")
        type_layout = QVBoxLayout(type_group)
        type_layout.setSpacing(12)
        
        self.email_type_combo = QComboBox()
        self.email_type_combo.addItems(["域名转发邮箱", "IMAP邮箱 (2925)"])
        self.email_type_combo.currentIndexChanged.connect(self._on_email_type_changed)
        type_layout.addWidget(self.email_type_combo)
        
        main_layout.addWidget(type_group)
        
        # 创建堆叠窗口，用于切换不同的配置界面
        self.email_stack = QStackedWidget()
        
        # 域名转发邮箱配置页面
        domain_forward_widget = self._create_domain_forward_widget()
        self.email_stack.addWidget(domain_forward_widget)
        
        # IMAP邮箱配置页面
        imap_mail_widget = self._create_imap_mail_widget()
        self.email_stack.addWidget(imap_mail_widget)
        
        main_layout.addWidget(self.email_stack)
        main_layout.addStretch()
        
        return widget
    
    def _create_domain_forward_widget(self) -> QWidget:
        """创建域名转发邮箱配置组件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(20)
        
        # 说明文字
        info_label = QLabel("📌 域名邮箱转发逻辑：域名邮箱 → 转发目标邮箱 → 获取验证码")
        info_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 10px; background: #fef2f2; border-radius: 6px; border-left: 4px solid #dc2626;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 转发目标选择
        forward_group = QGroupBox("🎯 转发目标")
        forward_layout = QFormLayout(forward_group)
        forward_layout.setSpacing(15)
        forward_layout.setVerticalSpacing(15)
        
        # 转发目标下拉框
        self.forward_target_combo = QComboBox()
        self.forward_target_combo.addItems(["临时邮箱 (tempmail.plus)", "QQ邮箱", "163邮箱"])
        self.forward_target_combo.currentIndexChanged.connect(self._on_forward_target_changed)
        forward_layout.addRow("转发至:", self.forward_target_combo)
        
        # 授权码获取说明（根据选择的目标动态显示）
        self.forward_help_label = QLabel()
        self.forward_help_label.setStyleSheet("color: #0891b2; font-size: 11px; padding: 8px; background: #cffafe; border-radius: 4px;")
        self.forward_help_label.setWordWrap(True)
        forward_layout.addRow("", self.forward_help_label)
        
        layout.addWidget(forward_group)
        
        # 配置堆叠窗口
        self.forward_config_stack = QStackedWidget()
        
        # 临时邮箱配置
        temp_mail_widget = QWidget()
        temp_mail_layout = QFormLayout(temp_mail_widget)
        temp_mail_layout.setSpacing(15)
        temp_mail_layout.setVerticalSpacing(15)
        
        self.temp_mail_username = QLineEdit()
        self.temp_mail_username.setPlaceholderText("完整邮箱地址，例如: aethxz@mailto.plus")
        temp_mail_layout.addRow("临时邮箱:", self.temp_mail_username)
        
        self.temp_mail_pin = QLineEdit()
        self.temp_mail_pin.setPlaceholderText("PIN码（如无密码保护可留空）")
        temp_mail_layout.addRow("PIN码:", self.temp_mail_pin)
        
        self.forward_config_stack.addWidget(temp_mail_widget)
        
        # QQ邮箱配置
        qq_mail_widget = QWidget()
        qq_mail_layout = QFormLayout(qq_mail_widget)
        qq_mail_layout.setSpacing(15)
        qq_mail_layout.setVerticalSpacing(15)
        
        self.forward_qq_email = QLineEdit()
        self.forward_qq_email.setPlaceholderText("接收验证码的QQ邮箱，例如: 123456789@qq.com")
        qq_mail_layout.addRow("QQ邮箱:", self.forward_qq_email)
        
        qq_password_layout = QHBoxLayout()
        self.forward_qq_password = QLineEdit()
        self.forward_qq_password.setPlaceholderText("QQ邮箱的16位授权码")
        self.forward_qq_password.setEchoMode(QLineEdit.EchoMode.Password)
        qq_password_layout.addWidget(self.forward_qq_password, stretch=1)
        
        self.forward_qq_show_password = QCheckBox("显示密码")
        self.forward_qq_show_password.stateChanged.connect(lambda: self._toggle_forward_password_visibility('qq'))
        qq_password_layout.addWidget(self.forward_qq_show_password)
        
        qq_password_widget = QWidget()
        qq_password_widget.setLayout(qq_password_layout)
        qq_mail_layout.addRow("授权码:", qq_password_widget)
        
        self.forward_config_stack.addWidget(qq_mail_widget)
        
        # 163邮箱配置
        mail_163_widget = QWidget()
        mail_163_layout = QFormLayout(mail_163_widget)
        mail_163_layout.setSpacing(15)
        mail_163_layout.setVerticalSpacing(15)
        
        self.forward_163_email = QLineEdit()
        self.forward_163_email.setPlaceholderText("接收验证码的163邮箱，例如: user@163.com")
        mail_163_layout.addRow("163邮箱:", self.forward_163_email)
        
        mail_163_password_layout = QHBoxLayout()
        self.forward_163_password = QLineEdit()
        self.forward_163_password.setPlaceholderText("163邮箱的授权码")
        self.forward_163_password.setEchoMode(QLineEdit.EchoMode.Password)
        mail_163_password_layout.addWidget(self.forward_163_password, stretch=1)
        
        self.forward_163_show_password = QCheckBox("显示密码")
        self.forward_163_show_password.stateChanged.connect(lambda: self._toggle_forward_password_visibility('163'))
        mail_163_password_layout.addWidget(self.forward_163_show_password)
        
        mail_163_password_widget = QWidget()
        mail_163_password_widget.setLayout(mail_163_password_layout)
        mail_163_layout.addRow("授权码:", mail_163_password_widget)
        
        self.forward_config_stack.addWidget(mail_163_widget)
        
        layout.addWidget(self.forward_config_stack)
        
        # 初始化显示状态
        self._on_forward_target_changed()
        
        return widget
    
    def _create_imap_mail_widget(self) -> QWidget:
        """创建IMAP邮箱配置组件 - 仅2925邮箱（支持无限子邮箱）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(20)
        
        # 说明文字
        info_label = QLabel("📌 2925邮箱支持无限子邮箱，每次注册自动生成随机子邮箱")
        info_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 10px; background: #fef2f2; border-radius: 6px; border-left: 4px solid #dc2626;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 授权码获取说明
        auth_help_label = QLabel("🔑 授权码：2925邮箱的授权码就是登录密码即可")
        auth_help_label.setStyleSheet("color: #0891b2; font-size: 11px; padding: 8px; background: #cffafe; border-radius: 4px;")
        auth_help_label.setWordWrap(True)
        layout.addWidget(auth_help_label)
        
        # 配置表单
        form_group = QGroupBox("📧 2925邮箱配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(15)
        form_layout.setVerticalSpacing(15)
        
        # 2925邮箱地址
        self.imap_email = QLineEdit()
        self.imap_email.setPlaceholderText("2925主邮箱，例如: user@2925.com")
        form_layout.addRow("主邮箱:", self.imap_email)
        
        # 密码行（包含显示密码复选框）
        password_layout = QHBoxLayout()
        self.imap_password = QLineEdit()
        self.imap_password.setPlaceholderText("2925邮箱的登录密码")
        self.imap_password.setEchoMode(QLineEdit.EchoMode.Password)
        password_layout.addWidget(self.imap_password, stretch=1)
        
        self.imap_show_password = QCheckBox("显示密码")
        self.imap_show_password.stateChanged.connect(self._toggle_password_visibility)
        password_layout.addWidget(self.imap_show_password)
        
        password_widget = QWidget()
        password_widget.setLayout(password_layout)
        form_layout.addRow("登录密码:", password_widget)
        
        # 使用随机子邮箱选项
        self.imap_use_random = QCheckBox("启用随机子邮箱（推荐，每次注册使用不同子邮箱）")
        self.imap_use_random.setChecked(True)
        form_layout.addRow("", self.imap_use_random)
        
        # IMAP服务器（可选）
        self.imap_server = QLineEdit()
        self.imap_server.setPlaceholderText("留空自动使用 imap.2925.com")
        form_layout.addRow("IMAP服务器:", self.imap_server)
        
        # IMAP端口
        self.imap_port = QLineEdit()
        self.imap_port.setPlaceholderText("默认 993")
        self.imap_port.setText("993")
        form_layout.addRow("IMAP端口:", self.imap_port)
        
        layout.addWidget(form_group)
        
        return widget
    
    def _on_forward_target_changed(self):
        """转发目标切换时的处理 - 更新帮助文本和配置界面"""
        index = self.forward_target_combo.currentIndex()
        
        # 切换配置堆叠窗口
        self.forward_config_stack.setCurrentIndex(index)
        
        # 更新授权码获取说明
        if index == 0:  # 临时邮箱
            self.forward_help_label.setText("💡 临时邮箱无需授权码，访问 tempmail.plus 创建临时邮箱即可")
        elif index == 1:  # QQ邮箱
            self.forward_help_label.setText(
                "🔑 授权码获取步骤：\n"
                "1. 登录 QQ邮箱 → 设置 → 账户\n"
                "2. 开启 IMAP/SMTP服务 → 生成授权码（需发短信验证）\n"
                "3. 复制16位授权码填入下方"
            )
        elif index == 2:  # 163邮箱
            self.forward_help_label.setText(
                "🔑 授权码获取步骤：\n"
                "1. 登录 163邮箱 → 设置 → POP3/SMTP/IMAP\n"
                "2. 开启 IMAP服务 → 新增授权密码\n"
                "3. 复制授权码填入下方"
            )
    
    def _toggle_forward_password_visibility(self, mail_type):
        """切换转发邮箱密码可见性"""
        if mail_type == 'qq':
            if self.forward_qq_show_password.isChecked():
                self.forward_qq_password.setEchoMode(QLineEdit.EchoMode.Normal)
            else:
                self.forward_qq_password.setEchoMode(QLineEdit.EchoMode.Password)
        elif mail_type == '163':
            if self.forward_163_show_password.isChecked():
                self.forward_163_password.setEchoMode(QLineEdit.EchoMode.Normal)
            else:
                self.forward_163_password.setEchoMode(QLineEdit.EchoMode.Password)
    
    def _toggle_password_visibility(self, state):
        """切换IMAP密码可见性"""
        if state == 2:  # Qt.CheckState.Checked
            self.imap_password.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.imap_password.setEchoMode(QLineEdit.EchoMode.Password)
    
    def _on_email_type_changed(self, index):
        """邮箱类型切换时的处理"""
        self.email_stack.setCurrentIndex(index)
    
    def load_config(self):
        """加载配置到界面"""
        # 加载域名
        domains = self.register_config.get_domains()
        self.domains_text.setPlainText('\n'.join(domains))
        
        # 加载银行卡
        cards = self.register_config.get_card_list()
        cards_text = []
        used_count = 0
        problematic_count = 0
        for card in cards:
            line = f"{card['number']},{card['expiry']},{card.get('cvc', '').strip()}"
            # 优先检查是否是问题卡
            if card.get('problematic', False):
                line += " (问题卡)"
                problematic_count += 1
            elif card.get('used', False):
                line += " (已使用)"
                used_count += 1
            cards_text.append(line)
        
        
        self.cards_text.setPlainText('\n'.join(cards_text))
        
        # 加载跳过绑卡配置
        skip_card_binding = self.register_config.get_skip_card_binding()
        self.skip_card_binding_checkbox.setChecked(skip_card_binding)
        
        # 加载邮箱配置
        email_config = self.register_config.get_email_config()
        email_type = email_config.get('email_type', 'domain_forward')
        
        # 设置邮箱类型：0=域名转发邮箱, 1=IMAP邮箱（默认为域名转发）
        if email_type == 'imap':
            self.email_type_combo.setCurrentIndex(1)
        else:
            # 默认显示域名转发邮箱
            self.email_type_combo.setCurrentIndex(0)
        
        # 加载域名转发邮箱配置
        domain_forward = email_config.get('domain_forward', {})
        
        # 确定当前使用的转发目标
        forward_target = domain_forward.get('forward_target', 'temp_mail')
        target_map = {'temp_mail': 0, 'qq': 1, '163': 2}
        self.forward_target_combo.setCurrentIndex(target_map.get(forward_target, 0))
        
        # 临时邮箱
        temp_mail = domain_forward.get('temp_mail', {})
        self.temp_mail_username.setText(temp_mail.get('username', ''))
        self.temp_mail_pin.setText(temp_mail.get('pin', ''))
        
        # QQ邮箱
        qq_mail = domain_forward.get('qq_mail', {})
        self.forward_qq_email.setText(qq_mail.get('email', ''))
        self.forward_qq_password.setText(qq_mail.get('password', ''))
        
        # 163邮箱
        mail_163 = domain_forward.get('163_mail', {})
        self.forward_163_email.setText(mail_163.get('email', ''))
        self.forward_163_password.setText(mail_163.get('password', ''))
        
        # 加载IMAP邮箱配置（仅2925）
        imap_mail = email_config.get('imap_mail', {})
        self.imap_email.setText(imap_mail.get('email', ''))
        self.imap_password.setText(imap_mail.get('password', ''))
        self.imap_use_random.setChecked(imap_mail.get('use_random_email', True))
        self.imap_server.setText(imap_mail.get('imap_server', ''))
        self.imap_port.setText(str(imap_mail.get('imap_port', 993)))
        
        # 加载手机验证配置
        phone_config = self.register_config.get_phone_verification_config()
        self.phone_verification_enabled.setChecked(phone_config.get('enabled', False))
        self.phone_api_server.setCurrentText(phone_config.get('api_server', 'https://api.haozhuma.com'))
        self.phone_username.setText(phone_config.get('username', ''))
        self.phone_password.setText(phone_config.get('password', ''))
        self.phone_uid.setText(phone_config.get('uid', ''))
        self.phone_max_usage.setValue(phone_config.get('max_usage_count', 3))
        
        # 触发一次转发目标切换，更新UI显示
        self._on_forward_target_changed()
    
    def _create_phone_verification_tab(self) -> QWidget:
        """创建手机号码验证配置标签页"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)
        
        # 说明文字
        info_label = QLabel("📌 手机号验证配置：用于自动处理Cursor注册中的手机号验证环节")
        info_label.setStyleSheet("color: #dc2626; font-size: 12px; padding: 10px; background: #fef2f2; border-radius: 6px; border-left: 4px solid #dc2626;")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)
        
        # 启用手机验证
        self.phone_verification_enabled = QCheckBox("✅ 启用手机号验证")
        self.phone_verification_enabled.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                font-weight: bold;
                color: #495057;
                padding: 10px;
                background: #e7f3ff;
                border-radius: 6px;
                border-left: 4px solid #2196F3;
            }
            QCheckBox:hover {
                background: #cfe2ff;
            }
        """)
        self.phone_verification_enabled.setToolTip("开启后，当注册流程检测到手机号验证页面时，会自动使用接码平台获取手机号并完成验证")
        main_layout.addWidget(self.phone_verification_enabled)
        
        # 接码平台配置组
        platform_group = QGroupBox("🔌 接码平台配置（豪猪）")
        platform_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #495057;
            }
        """)
        platform_layout = QFormLayout(platform_group)
        platform_layout.setSpacing(15)
        platform_layout.setVerticalSpacing(15)
        
        # API服务器（可编辑）
        self.phone_api_server = QComboBox()
        self.phone_api_server.addItems([
            "https://api.haozhuma.com",
            "https://api.haozhuyun.com"
        ])
        self.phone_api_server.setEditable(True)
        platform_layout.addRow("API服务器:", self.phone_api_server)
        
        # 用户名
        self.phone_username = QLineEdit()
        self.phone_username.setPlaceholderText("在豪猪平台注册的API账号")
        platform_layout.addRow("API账号:", self.phone_username)
        
        # 密码
        password_layout = QHBoxLayout()
        self.phone_password = QLineEdit()
        self.phone_password.setPlaceholderText("API密码")
        self.phone_password.setEchoMode(QLineEdit.EchoMode.Password)
        password_layout.addWidget(self.phone_password, stretch=1)
        
        self.phone_show_password = QCheckBox("显示密码")
        self.phone_show_password.stateChanged.connect(self._toggle_phone_password_visibility)
        password_layout.addWidget(self.phone_show_password)
        
        password_widget = QWidget()
        password_widget.setLayout(password_layout)
        platform_layout.addRow("API密码:", password_widget)
        
        # 对接码ID（必填）
        self.phone_uid = QLineEdit()
        self.phone_uid.setPlaceholderText("格式: 项目ID-对接码，例如: 67854-NZYQYJFQ86")
        platform_layout.addRow("对接码ID:", self.phone_uid)
        
        # 使用次数配置
        usage_layout = QHBoxLayout()
        self.phone_max_usage = QSpinBox()
        self.phone_max_usage.setRange(1, 10)
        self.phone_max_usage.setValue(3)
        self.phone_max_usage.setSuffix(" 次")
        self.phone_max_usage.setStyleSheet("QSpinBox { min-width: 80px; }")
        usage_layout.addWidget(self.phone_max_usage)
        
        usage_help = QLabel("（同一号码可重复使用次数后拉黑）")
        usage_help.setStyleSheet("color: #666; font-size: 11px;")
        usage_layout.addWidget(usage_help)
        usage_layout.addStretch()
        
        usage_widget = QWidget()
        usage_widget.setLayout(usage_layout)
        platform_layout.addRow("使用次数:", usage_widget)
        
        main_layout.addWidget(platform_group)
        
        # 帮助信息
        help_group = QGroupBox("💡 使用说明")
        help_layout = QVBoxLayout(help_group)
        help_layout.setSpacing(8)
        
        help_text = QLabel(
            "1. 访问豪猪平台注册账号：<a href='http://h5.haozhuma.com/reg.html'>h5.haozhuma.com/reg.html</a><br>"
            "2. 在平台控制台<b>添加对接码</b><br>"
            "3. 获取API账号、密码、<b>对接码ID</b>"
        )
        help_text.setOpenExternalLinks(True)
        help_text.setWordWrap(True)
        help_text.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 12px;
                padding: 10px;
                background: #f0f0f0;
                border-radius: 6px;
                line-height: 1.6;
            }
        """)
        help_layout.addWidget(help_text)
        
        main_layout.addWidget(help_group)
        
        main_layout.addStretch()
        
        return widget
    
    def _toggle_phone_password_visibility(self, state):
        """切换手机验证密码可见性"""
        if state == 2:  # Qt.CheckState.Checked
            self.phone_password.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.phone_password.setEchoMode(QLineEdit.EchoMode.Password)
    
    def _show_simple_message(self, message):
        """显示简洁的无按钮提示框 - 点击任意位置关闭"""
        from PyQt6.QtCore import QTimer
        
        dialog = QDialog(self)
        dialog.setWindowTitle("提示")
        dialog.setModal(True)
        dialog.setFixedSize(350, 120)
        
        # 去除默认边框，使用自定义样式
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加图标和文字
        icon_label = QLabel("⚠️")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("""
            font-size: 32px; 
            margin-bottom: 10px;
            background-color: transparent;
        """)
        layout.addWidget(icon_label)
        
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("""
            font-size: 14px;
            color: #333333;
            font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
            background-color: transparent;
        """)
        layout.addWidget(msg_label)
        
        # 设置对话框样式
        dialog.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                border: 2px solid #dee2e6;
                border-radius: 8px;
            }
        """)
        
        # 点击任意位置关闭
        def mousePressEvent(event):
            dialog.accept()
        dialog.mousePressEvent = mousePressEvent
        
        # 自动关闭（1秒后）
        QTimer.singleShot(1000, dialog.accept)
        
        dialog.exec()
    
    def _apply_msgbox_style(self, msgbox):
        """为QMessageBox应用统一的样式 - 现代美观设计"""
        msgbox.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
                color: #333333;
                font-size: 14px;
                font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
                border: 2px solid #e0e0e0;
                border-radius: 12px;
            }
            QMessageBox QLabel {
                color: #333333;
                font-size: 14px;
                padding: 15px;
                background-color: transparent;
                line-height: 1.6;
            }
            QMessageBox QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 14px;
                min-width: 100px;
                margin: 8px 6px;
            }
            QMessageBox QPushButton:hover {
                background-color: #1976D2;
            }
            QMessageBox QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
    
    def save_config(self):
        """保存配置"""
        try:
            # 保存域名
            domains_text = self.domains_text.toPlainText().strip()
            domains = [d.strip() for d in domains_text.split('\n') if d.strip()]
            
            if len(domains) < 1:
                self._show_simple_message("请至少配置一个域名")
                return
            
            self.register_config.set_domains(domains)
            
            # 保存银行卡
            cards_text = self.cards_text.toPlainText().strip()
            if cards_text:
                # 🔥 修复：在保存前预处理文本，确保显示标记不污染数据
                cleaned_cards_text = self._clean_cards_text_for_save(cards_text)
                self.register_config.add_cards_from_text(cleaned_cards_text)
            
            # 保存跳过绑卡配置
            skip_card_binding = self.skip_card_binding_checkbox.isChecked()
            self.register_config.set_skip_card_binding(skip_card_binding)
            
            # 保存邮箱配置
            email_type = "imap" if self.email_type_combo.currentIndex() == 1 else "domain_forward"
            
            # 确定转发目标
            forward_index = self.forward_target_combo.currentIndex()
            target_map = {0: 'temp_mail', 1: 'qq', 2: '163'}
            forward_target = target_map.get(forward_index, 'temp_mail')
            
            email_config = {
                "email_type": email_type,
                "domain_forward": {
                    "forward_target": forward_target,  # 当前选择的转发目标
                    "temp_mail": {
                        "username": self.temp_mail_username.text().strip(),
                        "pin": self.temp_mail_pin.text().strip()
                    },
                    "qq_mail": {
                        "email": self.forward_qq_email.text().strip(),
                        "password": self.forward_qq_password.text().strip()
                    },
                    "163_mail": {
                        "email": self.forward_163_email.text().strip(),
                        "password": self.forward_163_password.text().strip()
                    }
                },
                "imap_mail": {
                    "enabled": email_type == "imap",
                    "imap_mode": "2925",  # 固定为2925
                    "email": self.imap_email.text().strip(),
                    "password": self.imap_password.text().strip(),
                    "imap_server": self.imap_server.text().strip(),
                    "imap_port": int(self.imap_port.text().strip()) if self.imap_port.text().strip() else 993,
                    "use_random_email": self.imap_use_random.isChecked(),
                    "register_email": self.imap_email.text().strip()
                }
            }
            
            self.register_config.set_email_config(email_config)
            
            # 保存手机验证配置
            uid = self.phone_uid.text().strip()
            # 从对接码ID自动提取项目ID
            project_id = ""
            if uid and '-' in uid:
                project_id = uid.split('-')[0]
            
            phone_config = {
                "enabled": self.phone_verification_enabled.isChecked(),
                "username": self.phone_username.text().strip(),
                "password": self.phone_password.text().strip(),
                "project_id": project_id,  # 自动提取
                "uid": uid,
                "api_server": self.phone_api_server.currentText().strip(),  # 可编辑保存
                "max_usage_count": self.phone_max_usage.value()
            }
            self.register_config.set_phone_verification_config(phone_config)
            
            self.accept()  # 直接关闭对话框，不显示成功提示
            
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存配置失败: {str(e)}")
    
    def _clean_cards_text_for_save(self, cards_text: str) -> str:
        """
        清理银行卡文本以便保存，移除显示标记但保留状态信息
        
        Args:
            cards_text: 用户编辑的银行卡文本
            
        Returns:
            清理后的银行卡文本，保留状态信息
        """
        try:
            lines = cards_text.strip().split('\n')
            cleaned_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # 检查是否有显示标记
                if line.endswith(' (已使用)'):
                    # 保留标记信息，但保持原有格式
                    cleaned_lines.append(line)
                else:
                    # 没有标记，直接保存
                    cleaned_lines.append(line)
                    
            return '\n'.join(cleaned_lines)
            
        except Exception as e:
            # 如果清理失败，返回原文本
            return cards_text
    
    def restore_initial_state(self):
        """恢复银行卡初始状态 - 清除所有使用标记"""
        # 🔥 修复：使用自定义对话框确保按钮显示
        dialog = QDialog(self)
        dialog.setWindowTitle("确认恢复初始状态")
        dialog.setModal(True)
        dialog.resize(350, 150)  # 缩小对话框大小
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 图标和文本
        content_layout = QHBoxLayout()
        
        # 问号图标
        icon_label = QLabel()
        icon_label.setPixmap(self.style().standardPixmap(self.style().StandardPixmap.SP_MessageBoxQuestion))
        content_layout.addWidget(icon_label)
        content_layout.addSpacing(10)
        
        # 文本内容
        text_layout = QVBoxLayout()
        main_text = QLabel("确定要恢复所有银行卡为初始状态吗？")
        main_text.setWordWrap(True)
        info_text = QLabel("这将清除所有银行卡的使用标记，让它们回到未使用状态。")
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #666666;")
        
        text_layout.addWidget(main_text)
        text_layout.addWidget(info_text)
        content_layout.addLayout(text_layout)
        content_layout.addStretch()
        
        layout.addLayout(content_layout)
        layout.addStretch()
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        yes_btn = QPushButton("是")
        yes_btn.setMinimumSize(80, 30)
        yes_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #003d82;
            }
        """)
        yes_btn.clicked.connect(dialog.accept)
        
        no_btn = QPushButton("否")
        no_btn.setMinimumSize(80, 30)
        no_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #545b62;
            }
            QPushButton:pressed {
                background-color: #3d4246;
            }
        """)
        no_btn.clicked.connect(dialog.reject)
        no_btn.setDefault(True)
        
        button_layout.addWidget(yes_btn)
        button_layout.addWidget(no_btn)
        
        layout.addLayout(button_layout)
        
        # 显示对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.register_config.reset_all_cards():
                # 🔥 移除恢复成功弹窗，直接刷新
                self.load_config()  # 重新加载配置
            else:
                QMessageBox.critical(self, "恢复失败", "恢复银行卡初始状态失败")
    
    def reset_cards(self):
        """重置银行卡状态"""
        # 🔥 修复：使用自定义对话框确保按钮显示
        dialog = QDialog(self)
        dialog.setWindowTitle("确认重置")
        dialog.setModal(True)
        dialog.resize(320, 120)  # 缩小对话框大小
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 图标和文本
        content_layout = QHBoxLayout()
        
        # 问号图标
        icon_label = QLabel()
        icon_label.setPixmap(self.style().standardPixmap(self.style().StandardPixmap.SP_MessageBoxQuestion))
        content_layout.addWidget(icon_label)
        content_layout.addSpacing(10)
        
        # 文本内容
        main_text = QLabel("确定要重置所有银行卡为未使用状态吗？")
        main_text.setWordWrap(True)
        
        content_layout.addWidget(main_text)
        content_layout.addStretch()
        
        layout.addLayout(content_layout)
        layout.addStretch()
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        yes_btn = QPushButton("是")
        yes_btn.setMinimumSize(80, 30)
        yes_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #003d82;
            }
        """)
        yes_btn.clicked.connect(dialog.accept)
        
        no_btn = QPushButton("否")
        no_btn.setMinimumSize(80, 30)
        no_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #545b62;
            }
            QPushButton:pressed {
                background-color: #3d4246;
            }
        """)
        no_btn.clicked.connect(dialog.reject)
        no_btn.setDefault(True)
        
        button_layout.addWidget(yes_btn)
        button_layout.addWidget(no_btn)
        
        layout.addLayout(button_layout)
        
        # 显示对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.register_config.reset_all_cards():
                # 🔥 移除重置成功弹窗，直接刷新
                self.load_config()  # 重新加载配置
            else:
                QMessageBox.critical(self, "重置失败", "重置银行卡状态失败")


class AutoRegisterWidget(QWidget):
    """自动注册主界面组件"""
    
    def __init__(self, account_manager, config=None, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self.register_config = RegisterConfigManager()  # 注册配置管理
        self.account_config = config if config else Config()  # 使用传入的配置或创建新的
        
        self.logger = logging.getLogger(__name__)
        
        # 工作线程
        self.register_thread = None
        
        self.init_ui()
        self.setup_connections()
    
    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 5, 15, 15)  # 减少上边距
        layout.setSpacing(10)
        
        # 创建顶部横幅区域
        header_widget = self._create_header_widget()
        layout.addWidget(header_widget)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # 左侧控制面板
        control_panel = self._create_control_panel()
        splitter.addWidget(control_panel)
        
        # 右侧日志面板
        log_panel = self._create_log_panel()
        splitter.addWidget(log_panel)
        
        # 设置分割比例 - 增加左侧宽度，避免拥挤
        splitter.setSizes([280, 420])  # 左侧更宽敞，右侧保持合理大小
    
    def _create_header_widget(self) -> QWidget:
        """创建美化的头部组件"""
        header = QWidget()
        header.setFixedHeight(100)  # 增加头部高度
        header.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, 
                    stop: 0 #667eea, stop: 1 #764ba2);
                border-radius: 12px;
                margin-bottom: 5px;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # 左侧图标和标题
        left_layout = QVBoxLayout()
        
        title = QLabel("🤖 自动注册系统")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 18px;
                font-weight: bold;
                background: transparent;
            }
        """)
        
        subtitle = QLabel("智能状态检测 • 全自动化注册流程")
        subtitle.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.8);
                font-size: 12px;
                background: transparent;
            }
        """)
        
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)
        layout.addLayout(left_layout)
        
        layout.addStretch()
        
        # 右侧状态指示器
        status_layout = QVBoxLayout()
        
        self.header_status = QLabel("🟢 系统就绪")
        self.header_status.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }
        """)
        
        status_layout.addWidget(self.header_status)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(status_layout)
        
        self._header_widget = header
        return header
    
    def _create_control_panel(self) -> QWidget:
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)  # 增加边距
        layout.setSpacing(20)  # 增加组件间距
        
        # 配置状态组
        config_group = QGroupBox("📋 配置状态")
        config_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #495057;
            }
        """)
        config_layout = QVBoxLayout(config_group)
        config_layout.setContentsMargins(15, 15, 15, 15)  # 增加组内边距
        config_layout.setSpacing(15)  # 增加配置项间距
        
        self.domain_status_label = QLabel("🌐 域名配置: 未检查")
        self.card_status_label = QLabel("💳 银行卡: 未检查")
        self.email_status_label = QLabel("📧 邮箱配置: 未检查")
        self.phone_status_label = QLabel("📱 手机验证: 未检查")
        
        # 美化状态标签
        for label in [self.domain_status_label, self.card_status_label, self.email_status_label, self.phone_status_label]:
            label.setStyleSheet("""
                QLabel {
                    padding: 12px 16px;
                    border-radius: 6px;
                    background-color: white;
                    border: 1px solid #dee2e6;
                    font-size: 12px;
                    min-height: 18px;
                }
            """)
        
        config_layout.addWidget(self.domain_status_label)
        config_layout.addWidget(self.card_status_label)
        config_layout.addWidget(self.email_status_label)
        config_layout.addWidget(self.phone_status_label)
        
        layout.addWidget(config_group)
        
        # 注册控制组
        register_group = QGroupBox("🚀 注册控制")
        register_group.setMinimumHeight(200)  # 恢复原始高度
        register_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #495057;
            }
        """)
        register_layout = QVBoxLayout(register_group)
        register_layout.setContentsMargins(15, 15, 15, 15)  # 增加组内边距
        register_layout.setSpacing(12)  # 适中的控件间距
        register_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)  # 设置左上对齐
        
        # 注册配置 - 分成两行布局
        
        # 第一行：注册数量
        first_row = QHBoxLayout()
        first_row.setSpacing(30)
        first_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # 注册数量配置
        count_label = QLabel("注册数量:")
        count_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #495057;")
        first_row.addWidget(count_label)
        
        self.count_spinbox = QSpinBox()
        self.count_spinbox.setRange(1, 99999)
        self.count_spinbox.setValue(1)
        self.count_spinbox.setStyleSheet("""
            QSpinBox {
                font-size: 13px;
                font-weight: bold;
                min-width: 50px;
                max-width: 60px;
                padding: 4px;
            }
        """)
        first_row.addWidget(self.count_spinbox)
        
        first_row.addStretch()  # 右侧拉伸
        
        # 第二行：无头模式和注册模式
        second_row = QHBoxLayout()
        second_row.setSpacing(30)
        second_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # 无头模式配置
        self.headless_checkbox = QCheckBox("无头模式")
        self.headless_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #495057;
            }
        """)
        self.headless_checkbox.setToolTip("启用后浏览器在后台运行，不显示界面，跳过绑卡流程")
        self.headless_checkbox.setChecked(False)
        second_row.addWidget(self.headless_checkbox)
        
        # 注册模式选择
        mode_label = QLabel("注册模式:")
        mode_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #495057;")
        second_row.addWidget(mode_label)
        
        # 创建单选按钮组
        self.register_mode_group = QButtonGroup()
        
        self.password_radio = QRadioButton("账号密码")
        self.password_radio.setToolTip("账号密码模式：邮箱 → 设置密码 → 邮箱验证 → 完成注册")
        self.password_radio.setStyleSheet("""
            QRadioButton {
                font-size: 13px;
                color: #495057;
                margin-right: 8px;
                font-weight: bold;
            }
        """)
        
        self.email_code_radio = QRadioButton("验证码")
        self.email_code_radio.setChecked(True)
        self.email_code_radio.setToolTip("邮箱验证码模式：输入邮箱 → 验证码登录 → 完成注册")
        self.email_code_radio.setStyleSheet("""
            QRadioButton {
                font-size: 13px;
                color: #495057;
                margin-right: 8px;
                font-weight: bold;
            }
        """)
        
        # 添加到按钮组
        self.register_mode_group.addButton(self.password_radio, 0)
        self.register_mode_group.addButton(self.email_code_radio, 1)
        
        second_row.addWidget(self.password_radio)
        second_row.addWidget(self.email_code_radio)
        
        second_row.addStretch()
        
        # 添加两行到主布局
        register_layout.addLayout(first_row)
        register_layout.addLayout(second_row)
        
        # 进度条和进度标签
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(5)
        
        # 进度文本标签 - 删除，不需要额外的文本标签
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")  # 显示 当前/总数 格式
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                background-color: #f8f9fa;
                text-align: center;
                font-weight: bold;
                font-size: 12px;
                color: #495057;
                height: 22px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #4CAF50, stop: 1 #45a049);
                border-radius: 4px;
                margin: 1px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        register_layout.addWidget(progress_widget)
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)  # 增加按钮间距
        
        self.config_btn = QPushButton("⚙️ 配置设置")
        self.start_btn = QPushButton("▶️ 开始注册")
        self.stop_btn = QPushButton("⏹️ 停止注册")
        self.stop_btn.setEnabled(False)
        
        # 美化按钮样式
        button_style = """
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #004085;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #dee2e6;
            }
        """
        
        config_button_style = """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """
        
        stop_button_style = """
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:pressed {
                background-color: #bd2130;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #dee2e6;
            }
        """
        
        self.config_btn.setStyleSheet(config_button_style)
        self.start_btn.setStyleSheet(button_style)
        self.stop_btn.setStyleSheet(stop_button_style)
        
        button_layout.addWidget(self.config_btn)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        
        register_layout.addLayout(button_layout)
        
        layout.addWidget(register_group)
        
        # 状态信息组
        status_group = QGroupBox("📊 注册状态")
        status_group.setMaximumHeight(120)  # 限制最大高度
        status_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #495057;
            }
        """)
        status_layout = QVBoxLayout(status_group)
        status_layout.setContentsMargins(15, 15, 15, 15)  # 增加组内边距
        status_layout.setSpacing(15)  # 增加间距
        
        self.status_label = QLabel("🟢 准备就绪")
        self.status_label.setStyleSheet("""
            QLabel {
                padding: 15px;
                border-radius: 6px;
                background-color: white;
                border: 1px solid #dee2e6;
                font-size: 13px;
                font-weight: bold;
                color: #28a745;
                min-height: 25px;
            }
        """)
        status_layout.addWidget(self.status_label)
        
        layout.addWidget(status_group)
        
        layout.addStretch()
        
        return panel
    
    def _create_log_panel(self) -> QWidget:
        """创建日志面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # 日志标题栏
        title_widget = QWidget()
        title_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8f9fa);
                border: 1px solid #e9ecef;
                border-bottom: none;
                border-radius: 8px 8px 0 0;
                padding: 8px;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(12, 8, 12, 8)
        
        log_title = QLabel("📝 注册日志")
        log_title.setStyleSheet("""
            QLabel {
                color: #495057;
                font-weight: bold;
                font-size: 14px;
                background: transparent;
                padding: 2px 0;
            }
        """)
        title_layout.addWidget(log_title)
        title_layout.addStretch()
        
        # 添加实时状态指示
        self.log_status_indicator = QLabel("●")
        self.log_status_indicator.setStyleSheet("""
            QLabel {
                color: #28a745;
                font-size: 16px;
                background: transparent;
            }
        """)
        title_layout.addWidget(self.log_status_indicator)
        
        layout.addWidget(title_widget)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                color: #495057;
                border: 1px solid #e9ecef;
                border-radius: 0 0 8px 8px;
                padding: 12px;
                font-family: 'Consolas', 'Monaco', monospace;
                line-height: 1.4;
                selection-background-color: #b3d7ff;
            }
            QTextEdit:focus {
                border-color: #2196F3;
            }
        """)
        layout.addWidget(self.log_text)
        
        # 底部工具栏
        toolbar_widget = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_widget)
        toolbar_layout.setContentsMargins(0, 5, 0, 0)
        
        # 清空日志按钮
        clear_btn = QPushButton("🗑️ 清空日志")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #545b62;
            }
        """)
        clear_btn.clicked.connect(self.clear_log)
        
        # 自动滚动开关
        self.auto_scroll_checkbox = QCheckBox("自动滚动")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.setStyleSheet("""
            QCheckBox {
                color: #495057;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #6c757d;
                border-radius: 3px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #007bff;
                border-radius: 3px;
                background-color: #007bff;
            }
        """)
        
        toolbar_layout.addWidget(self.auto_scroll_checkbox)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(clear_btn)
        
        layout.addWidget(toolbar_widget)
        
        return panel
    
    def setup_connections(self):
        """设置信号连接"""
        self.config_btn.clicked.connect(self.show_config_dialog)
        self.start_btn.clicked.connect(self.start_register)
        self.stop_btn.clicked.connect(self.stop_register)
        
        # 定期更新配置状态
        self.update_config_status()
    
    def update_config_status(self):
        """更新配置状态显示"""
        try:
            # 🚀 启动时不检查激活码，显示默认状态  
            self.header_status.setText("🟢 系统就绪")
            
            # 检查域名配置
            domains = self.register_config.get_domains()
            if len(domains) >= 1 and all(domains):
                self.domain_status_label.setText(f"域名配置: ✅ 已配置 {len(domains)} 个域名")
                self.domain_status_label.setStyleSheet("color: #4CAF50;")
            else:
                self.domain_status_label.setText("域名配置: ❌ 需要配置")
                self.domain_status_label.setStyleSheet("color: #F44336;")
            
            # 检查银行卡
            card_list = self.register_config.get_card_list()
            total_cards = len(card_list)
            # 🔥 修复：使用与RegisterConfigManager相同的判断逻辑
            available_cards = self.register_config.get_available_cards_count()
            used_cards = total_cards - available_cards
            
            if available_cards > 0:
                self.card_status_label.setText(f"银行卡: ✅ 可用 {available_cards}/{total_cards} 张 (已用 {used_cards} 张)")
                self.card_status_label.setStyleSheet("color: #4CAF50;")
            elif total_cards > 0:
                self.card_status_label.setText(f"银行卡: ⚠️ 已用完 {used_cards}/{total_cards} 张")
                self.card_status_label.setStyleSheet("color: #FF9800;")
            else:
                self.card_status_label.setText("银行卡: ❌ 无可用卡片")
                self.card_status_label.setStyleSheet("color: #F44336;")
            
            # 检查邮箱配置
            email_config = self.register_config.get_email_config()
            email_type = email_config.get('email_type', 'domain_forward')
            
            is_configured = False
            config_desc = ""
            
            if email_type == 'imap':
                # 检查IMAP邮箱配置（2925）
                imap_mail = email_config.get('imap_mail', {})
                if imap_mail.get('email') and imap_mail.get('password'):
                    is_configured = True
                    config_desc = "IMAP邮箱(2925)已配置"
            else:
                # 检查域名转发邮箱配置
                domain_forward = email_config.get('domain_forward', {})
                forward_target = domain_forward.get('forward_target', 'temp_mail')
                
                if forward_target == 'temp_mail':
                    temp_mail = domain_forward.get('temp_mail', {})
                    if temp_mail.get('username'):
                        is_configured = True
                        config_desc = "域名转发→临时邮箱已配置"
                elif forward_target == 'qq':
                    qq_mail = domain_forward.get('qq_mail', {})
                    if qq_mail.get('email') and qq_mail.get('password'):
                        is_configured = True
                        config_desc = "域名转发→QQ邮箱已配置"
                elif forward_target == '163':
                    mail_163 = domain_forward.get('163_mail', {})
                    if mail_163.get('email') and mail_163.get('password'):
                        is_configured = True
                        config_desc = "域名转发→163邮箱已配置"
            
            if is_configured:
                self.email_status_label.setText(f"邮箱配置: ✅ {config_desc}")
                self.email_status_label.setStyleSheet("color: #4CAF50;")
            else:
                self.email_status_label.setText("邮箱配置: ❌ 邮箱未配置")
                self.email_status_label.setStyleSheet("color: #F44336;")
            
            # 检查手机验证配置
            phone_config = self.register_config.get_phone_verification_config()
            phone_enabled = phone_config.get('enabled', False)
            phone_username = phone_config.get('username', '')
            phone_password = phone_config.get('password', '')
            phone_project_id = phone_config.get('project_id', '')
            
            if phone_enabled and phone_username and phone_password and phone_project_id:
                self.phone_status_label.setText(f"手机验证: ✅ 已启用（项目{phone_project_id}）")
                self.phone_status_label.setStyleSheet("color: #4CAF50;")
            elif phone_enabled:
                self.phone_status_label.setText("手机验证: ⚠️ 已启用但配置不完整")
                self.phone_status_label.setStyleSheet("color: #FF9800;")
            else:
                self.phone_status_label.setText("手机验证: ⚪ 未启用")
                self.phone_status_label.setStyleSheet("color: #9E9E9E;")
                
        except Exception as e:
            self.logger.error(f"更新配置状态失败: {str(e)}")
    
    def update_admin_status(self, check_server=False):
        """更新管理员状态显示 - 只在需要时才验证服务器"""
        try:
            from ..services.activation_service.client_config import ClientConfigManager
            client_config = ClientConfigManager()
            
            # 🚀 启动时只检查本地缓存，不验证服务器
            saved_code = client_config.get_saved_activation_code(force_server_check=False)
            if not saved_code:
                self.header_status.setText("🔐 需要激活")
                return
            
            # 获取用户类型和管理员状态
            user_type = client_config.get_user_type()
            is_admin = client_config.is_admin_user()
            
            # 获取剩余时长并格式化显示
            remaining_hours = client_config.get_remaining_hours()
            if remaining_hours is not None:
                if remaining_hours >= 24:
                    time_display = f"剩余 {remaining_hours/24:.1f} 天"
                elif remaining_hours >= 1:
                    time_display = f"剩余 {remaining_hours:.1f} 小时"
                else:
                    time_display = f"剩余 {remaining_hours*60:.0f} 分钟"
            else:
                time_display = "时长未知"
            
            # 根据用户类型设置不同的状态显示
            if user_type == "permanent_admin":
                self.header_status.setText(f"🔥 永久管理员 - {time_display}")
            elif user_type == "admin":
                self.header_status.setText(f"🔧 管理员 - {time_display}")
            elif is_admin:
                self.header_status.setText(f"🔧 管理员权限 - {time_display}")
            else:
                self.header_status.setText(f"🟢 系统就绪 - {time_display}")
        except Exception as e:
            self.logger.error(f"更新管理员状态失败: {str(e)}")
            self.header_status.setText("🟢 系统就绪")
    
    def show_config_dialog(self):
        """显示配置对话框"""
        dialog = ConfigDialog(self.register_config, self)
        # 🔥 无论对话框如何关闭，都更新状态（包括重置操作）
        dialog.exec()
        self.update_config_status()
        self.add_log("✅ 配置已更新")
    

    def start_register(self):
        """开始注册"""
        try:
            # 🔐 激活码验证流程
            from .activation_dialog import ActivationDialog
            from ..services.activation_service.client_config import ClientConfigManager
            
            self.add_log("🚀 开始激活码验证...")
            client_config = ClientConfigManager()
            
            # 检查本地缓存
            saved_code = client_config.get_saved_activation_code(force_server_check=False)
            
            if saved_code:
                # 使用本地缓存
                user_type = client_config.get_user_type()
                type_icons = {
                    "permanent_admin": "🔥 永久管理员",
                    "admin": "🔧 管理员", 
                    "normal": "👤 普通用户"
                }
                
                # 获取剩余时长并格式化显示
                remaining_hours = client_config.get_remaining_hours()
                if remaining_hours is not None:
                    if remaining_hours >= 24:
                        time_display = f"剩余 {remaining_hours/24:.1f} 天"
                    elif remaining_hours >= 1:
                        time_display = f"剩余 {remaining_hours:.1f} 小时"
                    else:
                        time_display = f"剩余 {remaining_hours*60:.0f} 分钟"
                else:
                    time_display = "时长未知"
                
                self.add_log(f"✅ {type_icons.get(user_type, '👤 普通用户')} - {time_display}")
                
            else:
                # 激活码失效或不存在，需要重新验证
                self.add_log("🔐 激活码失效或不存在，需要验证...")
                
                # 弹出激活对话框进行云端验证
                activation_dialog = ActivationDialog(self)
                if activation_dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                
                # 验证成功后获取用户类型
                self.add_log("🔍 激活对话框验证完成，检查保存状态...")
                try:
                    saved_code = client_config.get_saved_activation_code()
                    self.add_log(f"🔍 获取激活码结果: {bool(saved_code)}")
                    if saved_code:
                        user_type = client_config.get_user_type()
                        type_icons = {
                            "permanent_admin": "🔥 永久管理员",
                            "admin": "🔧 管理员", 
                            "normal": "👤 普通用户"
                        }
                        self.add_log(f"✅ {type_icons.get(user_type, '👤 普通用户')} - 验证通过")
                    else:
                        # 激活对话框成功但获取失败，可能是格式问题，但仍继续
                        self.add_log("⚠️ 激活对话框成功但获取状态失败，继续注册流程")
                except Exception as e:
                    self.add_log(f"❌ 获取激活码状态失败: {str(e)}")
                    # 但不要返回，继续注册流程，因为激活对话框已经成功了
                    self.add_log("✅ 激活对话框验证成功，继续注册流程")
            
            # 检查配置
            domains = self.register_config.get_domains()
            if len(domains) < 1 or not all(domains):
                QMessageBox.warning(self, "配置错误", "请先配置至少一个域名")
                return
            
            count = self.count_spinbox.value()
            
            # 检查是否需要检测银行卡数量（跳过绑卡或无头模式时不检测）
            skip_card_binding = self.register_config.get_skip_card_binding()
            is_headless = self.headless_checkbox.isChecked()
            
            if not skip_card_binding and not is_headless:
                # 只有在使用银行卡且非无头模式时才检测数量
                available_cards = self.register_config.get_available_cards_count()
                
                if available_cards < count:
                    # 使用自定义对话框确保按钮文字显示
                    msgbox = QMessageBox(self)
                    msgbox.setIcon(QMessageBox.Icon.Question)
                    msgbox.setWindowTitle("银行卡不足")
                    msgbox.setText(f"可用银行卡只有 {available_cards} 张，需要 {count} 张。\n是否重置所有卡片状态？")
                    msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    
                    # 设置按钮文字和样式
                    yes_button = msgbox.button(QMessageBox.StandardButton.Yes)
                    no_button = msgbox.button(QMessageBox.StandardButton.No)
                    yes_button.setText("是")
                    no_button.setText("否")
                    
                    # 应用样式
                    msgbox.setStyleSheet("""
                        QMessageBox {
                            background-color: #ffffff;
                        }
                        QPushButton {
                            background-color: #007bff;
                            color: white;
                            border: none;
                            padding: 8px 20px;
                            border-radius: 4px;
                            font-weight: bold;
                            min-width: 80px;
                        }
                        QPushButton:hover {
                            background-color: #0056b3;
                        }
                    """)
                    
                    reply = msgbox.exec()
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        self.register_config.reset_all_cards()
                        self.update_config_status()
                    else:
                        return
            
            # 获取无头模式配置和注册模式配置
            headless_mode = self.headless_checkbox.isChecked()
            
            # 获取注册模式
            register_mode = "password" if self.password_radio.isChecked() else "email_code"
            
            # 启动注册线程（串行模式）
            self.register_thread = AutoRegisterThread(
                self.account_config,  # 账号数据配置
                self.account_manager,
                self.register_config,  # 注册流程配置
                count,
                parallel_enabled=False,  # 禁用并行
                parallel_workers=1,
                headless_mode=headless_mode,
                register_mode=register_mode
            )
            
            # 连接信号
            self.register_thread.progress_signal.connect(self.update_status)
            self.register_thread.progress_count_signal.connect(self.update_progress)
            self.register_thread.log_signal.connect(self.add_log)
            self.register_thread.finished_signal.connect(self.on_register_finished)
            self.register_thread.email_input_request.connect(self.register_thread._handle_email_input_request)
            
            # 更新界面状态
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, count)  # 设置进度范围
            self.progress_bar.setValue(0)  # 先设为0
            
            # 更新头部状态显示
            if hasattr(self, 'header_status'):
                self.header_status.setText(f"🚀 注册中 (1/{count})")
            
            # 启动线程
            self.register_thread.start()
            
            # 线程启动后立即更新进度为1/count（表示正在注册第1个）
            self.update_progress(1, count)
            
        except Exception as e:
            # 🔄 确保在异常时恢复按钮状态
            self.start_btn.setText("🚀 开始注册")
            self.start_btn.setEnabled(True)
            self.add_log(f"❌ 启动注册失败: {str(e)}")
            QMessageBox.critical(self, "启动失败", f"启动注册失败: {str(e)}")
    
    def stop_register(self):
        """停止注册 - 等待线程真正停止"""
        if self.register_thread and self.register_thread.isRunning():
            self.register_thread.stop()
            self.add_log("🛑 正在停止注册...")
            
            # 立即更新UI状态
            self.status_label.setText("🛑 正在停止...")
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 15px;
                    border-radius: 6px;
                    background-color: white;
                    border: 1px solid #dee2e6;
                    font-size: 13px;
                    font-weight: bold;
                    color: #ffc107;
                    min-height: 25px;
                }
            """)
            
            # 更新头部状态
            if hasattr(self, 'header_status'):
                self.header_status.setText("🛑 停止中...")
            
            # 禁用停止按钮防止重复点击
            self.stop_btn.setEnabled(False)
            
            # 等待线程真正停止后，由on_register_finished恢复按钮状态
        else:
            self.add_log("⚠️ 没有正在运行的注册任务")
    
    def on_register_finished(self, success: bool, message: str, data: dict):
        """注册完成处理"""
        # 更新界面状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        
        # 重置头部状态
        if hasattr(self, 'header_status'):
            if success:
                # 从数据中获取统计信息
                completed = data.get('completed', 0)
                success_count = data.get('success', 0)
                total = data.get('total', 0)
                self.header_status.setText(f"✅ 完成 {completed}/{total} (成功 {success_count})")
            else:
                self.header_status.setText("❌ 注册失败")
        
        # 更新状态
        if success:
            self.status_label.setText("✅ 注册完成")
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 15px;
                    border-radius: 6px;
                    background-color: white;
                    border: 1px solid #dee2e6;
                    font-size: 13px;
                    font-weight: bold;
                    color: #28a745;
                    min-height: 25px;
                }
            """)
        else:
            self.status_label.setText("❌ 注册失败")
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 15px;
                    border-radius: 6px;
                    background-color: white;
                    border: 1px solid #dee2e6;
                    font-size: 13px;
                    font-weight: bold;
                    color: #dc3545;
                    min-height: 25px;
                }
            """)
        
        # 显示结果
        self.add_log(f"📊 注册结果: {message}")
        
        # 更新配置状态（刷新银行卡显示）
        self.update_config_status()
        
        # 只在注册成功时刷新账号列表和订阅状态
        if success:
            # 刷新主窗口的账号列表
            if self.parent() and hasattr(self.parent(), 'refresh_account_list'):
                self.parent().refresh_account_list()
                self.add_log("✅ 账号列表已刷新")
            
            # 自动刷新刚注册账号的订阅状态（只刷新一次）
            self._auto_refresh_new_accounts(data)
    
    def _auto_refresh_new_accounts(self, data: dict):
        """自动刷新新注册账号的订阅状态"""
        try:
            results = data.get('results', [])
            if not results:
                return
            
            # 找出成功注册的账号
            success_accounts = []
            for result in results:
                if result.get('success') and result.get('email'):
                    # 从账号池中找到对应的账号
                    accounts = self.account_config.load_accounts()
                    for acc in accounts:
                        if acc.get('email') == result['email']:
                            success_accounts.append(acc)
                            break
            
            if success_accounts:
                self.add_log(f"🔄 开始刷新 {len(success_accounts)} 个新注册账号的订阅状态...")
                # 调用账号管理器的并发刷新功能
                if hasattr(self.account_manager, 'start_concurrent_refresh'):
                    # 使用QTimer延迟执行，确保UI已更新
                    from PyQt6.QtCore import QTimer
                    def delayed_refresh():
                        self.account_manager.start_concurrent_refresh(success_accounts)
                        self.add_log(f"✅ 已启动新账号的订阅状态刷新")
                    
                    QTimer.singleShot(1000, delayed_refresh)  # 延迟1秒执行
                    
        except Exception as e:
            self.logger.error(f"自动刷新新账号失败: {str(e)}")
            self.add_log(f"⚠️ 自动刷新新账号失败: {str(e)}")
    
    def update_status(self, message: str):
        """更新状态显示"""
        self.status_label.setText(message)
    
    def update_progress(self, current: int, total: int):
        """更新进度显示"""
        # 更新进度条
        self.progress_bar.setValue(current)
        self.progress_bar.setMaximum(total)
        
        
        # 更新头部状态 - 统一显示数字进度
        if hasattr(self, 'header_status'):
            if current < total:
                self.header_status.setText(f"🚀 注册中 ({current}/{total})")
            else:
                self.header_status.setText(f"✅ 完成 ({current}/{total})")
    
    def add_log(self, message: str):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 流程轮数标记：绿色+粗体
        if "🚀" in message:
            colored_message = f'<span style="color: #28a745; font-weight: bold;">[{timestamp}] {message}</span>'
        # 进度统计：蓝色+粗体
        elif "📊" in message:
            colored_message = f'<span style="color: #17a2b8; font-weight: bold;">[{timestamp}] {message}</span>'
        # 错误信息：红色+粗体
        elif "❌" in message or "失败" in message or "错误" in message:
            colored_message = f'<span style="color: #dc3545; font-weight: bold;">[{timestamp}] {message}</span>'
        # 警告信息：黄色+粗体
        elif "⚠️" in message or "警告" in message:
            colored_message = f'<span style="color: #ffc107; font-weight: bold;">[{timestamp}] {message}</span>'
        else:
            # 其他所有日志使用默认颜色
            colored_message = f'<span style="color: #d4d4d4;">[{timestamp}] {message}</span>'
        
        self.log_text.append(colored_message)
        
        # 更新状态指示器
        self.log_status_indicator.setStyleSheet("""
            QLabel {
                color: #ffc107;
                font-size: 16px;
                background: transparent;
            }
        """)
        
        # 自动滚动到底部（如果启用）
        if hasattr(self, 'auto_scroll_checkbox') and self.auto_scroll_checkbox.isChecked():
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.log_text.setTextCursor(cursor)
        
        # 0.5秒后恢复状态指示器颜色
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, self._reset_log_indicator)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
    
    # update_scale_factor已删除 - 使用Qt6自动DPI缩放
    
    def _reset_log_indicator(self):
        """重置日志状态指示器"""
        if hasattr(self, 'log_status_indicator'):
            self.log_status_indicator.setStyleSheet("""
                QLabel {
                    color: #28a745;
                    font-size: 16px;
                    background: transparent;
                }
            """)


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试界面
    widget = AutoRegisterWidget(None, None)
    widget.show()
    
    sys.exit(app.exec())
