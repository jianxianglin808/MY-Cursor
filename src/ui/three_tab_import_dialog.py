#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三标签页导入对话框 - 现代化的导入界面
"""

import logging
import json
from typing import Optional
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QTextEdit, QPushButton, QMessageBox, QLineEdit,
    QProgressDialog, QApplication, QFileDialog
)

from ..utils.cookie_parser import CookieParser
from ..core.config import Config
from .email_input_dialog import EmailInputDialog


class ImportWorkerThread(QThread):
    """导入工作线程"""
    
    finished = pyqtSignal(bool, str, list)  # success, message, accounts
    progress = pyqtSignal(str)  # 进度信号
    accounts_ready = pyqtSignal(list)  # 账号准备就绪信号（用于快速刷新）
    
    def __init__(self, parser: CookieParser, cookie_text: str, import_type: str, config, email: str = None):
        super().__init__()
        self.parser = parser
        self.cookie_text = cookie_text
        self.import_type = import_type
        self.config = config  # 添加config属性
        self.email = email
        self.logger = logging.getLogger(__name__)
    
    def run(self):
        try:
            if self.import_type == "workos_token":
                # WorkosCursorSessionToken直接按完整格式解析
                self.progress.emit("🔍 开始解析WorkosCursorSessionToken...")
                self.progress.emit("📝 按完整格式Token处理")
                success, message, account = self.parser._parse_complete_format(self.cookie_text)
                accounts = [account] if success and account else []
            elif self.import_type == "access_token":
                # AccessToken直接按JWT格式解析
                self.progress.emit("🔍 开始解析AccessToken...")
                self.progress.emit("📝 按JWT格式Token处理")
                success, message, account = self.parser._parse_jwt_format(self.cookie_text)
                accounts = [account] if success and account else []
                # 如果用户输入了邮箱，替换默认邮箱
                if success and account and self.email:
                    account['email'] = self.email
                    account['email_source'] = 'manual'
                    account['needs_manual_email'] = False
                    self.progress.emit(f"✅ 使用用户输入邮箱: {self.email}")
            elif self.import_type == "unified_token":
                # 🔥 统一Token导入（单个）- 需要转换
                self.progress.emit("🔍 开始解析Token...")
                success, message, accounts = self.parser.parse_cookies(self.cookie_text)
                # 如果用户输入了邮箱，替换邮箱
                if success and accounts and len(accounts) > 0 and self.email:
                    accounts[0]['email'] = self.email
                    accounts[0]['email_source'] = 'manual'
                    accounts[0]['needs_manual_email'] = False
                    self.progress.emit(f"✅ 使用用户输入邮箱: {self.email}")
            else:
                # 批量导入（卡密批量新增）- 不转换token
                self.progress.emit("🔍 开始批量解析...")
                success, message, accounts = self.parser.parse_cookies(self.cookie_text)
                        
            # 导入逻辑区分：batch批量不转换，单个导入需要转换
            if success and accounts:
                try:
                    from ..utils.tag_manager import get_tag_manager
                    
                    tag_manager = get_tag_manager()
                    
                    # 判断是否需要转换（只有token导入需要转换，卡密批量新增不转换）
                    need_convert = (self.import_type == "unified_token")
                    
                    if need_convert:
                        # 单个导入：检测并转换JWT
                        from ..utils.session_token_converter import SessionTokenConverter
                        converter = SessionTokenConverter(self.config)
                        
                        self.progress.emit(f"🔍 检查Token状态...")
                        
                        for account in accounts:
                            email = account.get('email', '')
                            workos_token = account.get('WorkosCursorSessionToken', '')
                            access_token = account.get('access_token', '')
                            user_id = account.get('user_id', '')
                            
                            # 检查是否需要转换
                            needs_conversion = False
                            if access_token:
                                if len(access_token) != 413:
                                    needs_conversion = True
                            elif workos_token:
                                needs_conversion = True
                            
                            if needs_conversion and workos_token and user_id:
                                self.progress.emit(f"🔄 开始转换 {email} 的token...")
                                convert_success, jwt_access, jwt_refresh = converter.convert_workos_to_session_jwt(
                                    workos_token, user_id
                                )
                                
                                if convert_success and jwt_access:
                                    account['access_token'] = jwt_access
                                    account['refresh_token'] = jwt_refresh or jwt_access
                                    account['token_type'] = 'session'
                                    self.progress.emit(f"✅ {email} 转换成功")
                                else:
                                    self.progress.emit(f"⚠️ {email} 转换失败，将导入原始token")
                    else:
                        # 批量导入：直接导入不转换
                        self.progress.emit(f"💡 批量导入模式，跳过JWT转换（可后续使用刷新token功能）")
                    
                    # 批量保存所有账号
                    self.progress.emit(f"💾 批量保存 {len(accounts)} 个账号...")
                    existing_accounts = self.config.load_accounts()
                    
                    for account in accounts:
                        email = account.get('email', '')
                        
                        # 处理refresh_token
                        access_token = account.get('access_token', '')
                        refresh_token = account.get('refresh_token', '')
                        if not refresh_token or refresh_token.strip() == '':
                            if access_token and access_token.strip():
                                account['refresh_token'] = access_token
                        
                        # 处理创建时间
                        if 'created_at' not in account or not account['created_at']:
                            if 'register_time' in account and account['register_time']:
                                register_time = account['register_time']
                                if len(register_time) > 16:
                                    account['created_at'] = register_time[:16]
                                else:
                                    account['created_at'] = register_time
                            else:
                                from datetime import datetime
                                account['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                        
                        # 提取标签和备注信息（暂存）
                        account['_import_tags'] = account.pop('import_tags', None)
                        account['_import_remark'] = account.pop('import_remark', None)
                        
                        # 更新或添加到列表
                        found = False
                        for i, acc in enumerate(existing_accounts):
                            if acc.get('email') == email:
                                # 智能时间处理
                                if account.get('email_source') != 'json_import':
                                    if 'created_at' in acc and acc['created_at']:
                                        account['created_at'] = acc['created_at']
                                existing_accounts[i] = account
                                found = True
                                break
                        if not found:
                            existing_accounts.append(account)
                    
                    # 一次性保存所有账号
                    if self.config.save_accounts(existing_accounts):
                        self.progress.emit(f"✅ 成功批量保存 {len(accounts)} 个账号")
                        # 🚀 发送账号就绪信号，用于快速刷新UI
                        self.accounts_ready.emit(existing_accounts)
                    else:
                        self.progress.emit(f"❌ 批量保存失败")
                    
                    # 处理标签和备注（批量操作）
                    all_accounts = accounts
                    
                    # 批量处理标签
                    tags_to_add = {}  # {email: [tag_ids]}
                    for account in all_accounts:
                        import_tags = account.pop('_import_tags', None)
                        if import_tags:
                            email = account.get('email', '')
                            tags_to_add[email] = import_tags
                    
                    if tags_to_add:
                        self.progress.emit(f"📌 批量处理 {len(tags_to_add)} 个账号的标签...")
                        for email, tag_ids in tags_to_add.items():
                            for tag_id in tag_ids:
                                if tag_manager.get_tag(tag_id):
                                    tag_manager.add_tag_to_account(email, tag_id)
                    
                    # 批量处理备注
                    remarks_to_add = {}  # {email: remark}
                    for account in all_accounts:
                        import_remark = account.pop('_import_remark', None)
                        if import_remark:
                            email = account.get('email', '')
                            remarks_to_add[email] = import_remark
                    
                    if remarks_to_add:
                        self.progress.emit(f"📝 批量处理 {len(remarks_to_add)} 个账号的备注...")
                        try:
                            remarks = self.config.load_remarks()
                            remarks.update(remarks_to_add)
                            self.config.save_remarks(remarks)
                        except Exception as remark_error:
                            self.logger.error(f"批量导入备注失败: {str(remark_error)}")
                    
                    self.progress.emit(f"🎉 成功导入并保存 {len(accounts)} 个账号")
                    
                except Exception as save_error:
                    self.logger.error(f"保存导入账号失败: {str(save_error)}")
                    self.progress.emit(f"⚠️ 导入成功但保存失败: {str(save_error)}")
            
            self.finished.emit(success, message, accounts or [])
        except Exception as e:
            self.logger.error(f"导入过程出错: {str(e)}")
            self.finished.emit(False, f"导入过程出错: {str(e)}", [])


class ThreeTabImportDialog(QDialog):
    """三标签页导入对话框"""
    
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.config = config if config else Config()
        self.parser = CookieParser(self.config)
        self.imported_accounts = []
        
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("新增账号")
        self.setFixedSize(600, 500)  # 原900x600缩小0.7倍
        self.setModal(True)
        
        # 设置样式
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: white;
            }
            QTabWidget::pane {
                border: 1px solid #3a3a4a;
                border-radius: 8px;
                background-color: #2a2a3a;
            }
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                background-color: #3a3a4a;
                color: #ccc;
                padding: 12px 20px;
                margin: 2px;
                border-radius: 6px;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #4a4a5a;
                color: white;
            }
            QTextEdit {
                background-color: #2a2a3a;
                color: white;
                border: 2px solid #4a4a5a;
                border-radius: 8px;
                padding: 10px;
                font-family: "Consolas", "Monaco", monospace;
                font-size: 12px;
            }
            QTextEdit:focus {
                border-color: #4CAF50;
            }
            QLineEdit {
                background-color: #2a2a3a;
                color: white;
                border: 2px solid #4a4a5a;
                border-radius: 6px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
            QLabel {
                color: #ddd;
            }
        """)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 创建标签页控件
        self.tab_widget = QTabWidget()
        
        # 创建三个标签页
        self.create_batch_tab()
        self.create_unified_token_tab()  # 🔥 合并SessionToken和AccessToken为统一导入
        
        main_layout.addWidget(self.tab_widget)
    
    def create_batch_tab(self):
        """创建卡密文本批量新增标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("批量导入Cookie/Token")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50;")
        layout.addWidget(title_label)
        
        # 说明
        info_label = QLabel("支持多种格式混合导入，每行一个账号：")
        info_label.setStyleSheet("color: #bbb;")
        layout.addWidget(info_label)
        
        # 输入框
        self.batch_input = QTextEdit()
        self.batch_input.setPlaceholderText(
            "1、支持user格式token批量导入\n\n"
            "2、支持文件批量导入\n\n"
        )
        layout.addWidget(self.batch_input)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 从文件导入按钮
        file_import_button = QPushButton("📁 从文件导入")
        file_import_button.clicked.connect(self.import_from_file)
        button_layout.addWidget(file_import_button)
        
        # 批量导入按钮
        import_button = QPushButton("💾 批量导入")
        import_button.clicked.connect(lambda: self.start_import("batch"))
        button_layout.addWidget(import_button)
        
        layout.addLayout(button_layout)
        
        self.tab_widget.addTab(tab, "卡密文本批量新增")
    
    def create_unified_token_tab(self):
        """创建统一Token导入标签页 - 自动检测SessionToken/JWT格式"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("Token导入")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50;")
        layout.addWidget(title_label)
        
        # Token输入
        self.unified_token_input = QTextEdit()
        self.unified_token_input.setPlaceholderText(
            "请输入user格式的Token，系统将自动检测并解析\n\n"
        )
        layout.addWidget(self.unified_token_input)
        
        # 解析日志显示区域
        log_label = QLabel("解析过程:")
        log_label.setStyleSheet("color: #bbb; margin-top: 10px;")
        layout.addWidget(log_label)
        
        self.unified_log_display = QTextEdit()
        self.unified_log_display.setReadOnly(True)
        self.unified_log_display.setMaximumHeight(100)
        self.unified_log_display.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a2a;
                border: 1px solid #3a3a4a;
                font-family: "Consolas", "Monaco", monospace;
                font-size: 11px;
                color: #aaa;
            }
        """)
        self.unified_log_display.setPlaceholderText("解析日志将在这里显示...")
        layout.addWidget(self.unified_log_display)
        
        # 导入按钮
        import_button = QPushButton("新增账号")
        import_button.clicked.connect(lambda: self.start_import("unified_token"))
        layout.addWidget(import_button)
        
        self.tab_widget.addTab(tab, "Token导入")
    
    
    def import_from_file(self):
        """从文件导入账号"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择导入文件",
            "",
            "JSON文件 (*.json);;文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # 尝试解析为JSON格式
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    # 完整的JSON数组格式
                    self.batch_input.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
                elif isinstance(data, dict):
                    # 单个账号JSON格式
                    self.batch_input.setPlainText(json.dumps([data], indent=2, ensure_ascii=False))
                else:
                    # 其他JSON格式，直接显示
                    self.batch_input.setPlainText(content)
            except json.JSONDecodeError:
                # 不是JSON格式，作为普通文本处理
                self.batch_input.setPlainText(content)
            
            
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"读取文件时出错：{str(e)}")
    
    def start_import(self, import_type: str):
        """开始导入"""
        try:
            cookie_text = ""
            email = None
            
            if import_type == "batch":
                cookie_text = self.batch_input.toPlainText().strip()
                if not cookie_text:
                    QMessageBox.warning(self, "错误", "请输入要批量导入的内容")
                    return
            elif import_type == "unified_token":
                # 🔥 统一Token导入 - 自动检测格式，无需手动邮箱
                cookie_text = self.unified_token_input.toPlainText().strip()
                if not cookie_text:
                    QMessageBox.warning(self, "错误", "请输入Token")
                    return
            
            # 禁用所有按钮
            self.setEnabled(False)
            
            # 创建工作线程
            self.worker = ImportWorkerThread(self.parser, cookie_text, import_type, self.config, email)
            self.worker.finished.connect(self.on_import_finished)
            self.worker.progress.connect(self.show_progress_log)
            self.worker.accounts_ready.connect(self.on_accounts_ready)  # 🚀 连接快速刷新信号
            self.worker.start()
            
        except Exception as e:
            self.logger.error(f"开始导入时出错: {str(e)}")
            QMessageBox.critical(self, "错误", f"开始导入时出错: {str(e)}")
            self.setEnabled(True)
    
    def on_accounts_ready(self, all_accounts: list):
        """账号准备就绪 - 立即通知主窗口快速刷新"""
        try:
            # 🚀 通知主窗口账号已准备好，可以快速刷新UI
            main_window = self.parent()
            if main_window and hasattr(main_window, 'quick_refresh_accounts'):
                main_window.quick_refresh_accounts(all_accounts)
                self.logger.info(f"🚀 已通知主窗口快速刷新 {len(all_accounts)} 个账号")
        except Exception as e:
            self.logger.error(f"通知主窗口快速刷新失败: {str(e)}")
    
    def on_import_finished(self, success: bool, message: str, accounts: list):
        """导入完成处理"""
        try:
            # 重新启用界面
            self.setEnabled(True)
            
            if not success:
                QMessageBox.warning(self, "导入失败", message)
                return
            
            if not accounts:
                QMessageBox.information(self, "导入结果", "没有成功解析到任何账号")
                return
            
            # 处理导入的账号
            final_accounts = []
            
            # 分离需要手动输入邮箱的账号
            auto_accounts = []
            manual_accounts = []
            
            for account in accounts:
                if account.get('needs_manual_email', False):
                    manual_accounts.append(account)
                else:
                    auto_accounts.append(account)
            
            # 直接添加自动解析的账号
            final_accounts.extend(auto_accounts)
            
            # 为需要手动输入的账号处理
            manual_input_accounts = []  # 用户手动输入的账号
            if manual_accounts:
                for i, account in enumerate(manual_accounts, 1):
                    user_id = account.get('user_id', '未知')
                    
                    # 创建邮箱输入对话框
                    dialog = EmailInputDialog(account, self)
                    dialog.setWindowTitle(f"输入真实邮箱 ({i}/{len(manual_accounts)})")
                    
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        real_email = dialog.get_real_email()
                        if real_email:
                            account['email'] = real_email
                            account['email_source'] = 'manual'
                            account['needs_manual_email'] = False
                            manual_input_accounts.append(account)
                            final_accounts.append(account)
                            self.logger.info(f"用户为账号 {user_id} 输入邮箱: {real_email}")
                        else:
                            self.logger.warning(f"用户取消为账号 {user_id} 输入邮箱")
                            continue
                    else:
                        # 用户取消了
                        if len(manual_accounts) > 1:
                            reply = QMessageBox.question(
                                self,
                                "确认取消",
                                f"您取消了第{i}个账号的邮箱输入。\n\n是否继续处理剩余账号？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.Yes
                            )
                            if reply != QMessageBox.StandardButton.Yes:
                                break
                        else:
                            break
                
                # 批量保存用户手动输入邮箱的账号
                if manual_input_accounts:
                    from datetime import datetime
                    try:
                        existing_accounts = self.config.load_accounts()
                        for account in manual_input_accounts:
                            email = account.get('email', '')
                            
                            # 处理refresh_token
                            access_token = account.get('access_token', '')
                            refresh_token = account.get('refresh_token', '')
                            if not refresh_token or refresh_token.strip() == '':
                                if access_token and access_token.strip():
                                    account['refresh_token'] = access_token
                            
                            # 处理创建时间
                            if 'created_at' not in account or not account['created_at']:
                                account['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                            
                            # 更新或添加到列表
                            found = False
                            for i, acc in enumerate(existing_accounts):
                                if acc.get('email') == email:
                                    existing_accounts[i] = account
                                    found = True
                                    break
                            if not found:
                                existing_accounts.append(account)
                        
                        # 一次性保存
                        self.config.save_accounts(existing_accounts)
                        self.logger.info(f"✅ 批量保存 {len(manual_input_accounts)} 个手动输入的账号")
                    except Exception as e:
                        self.logger.error(f"批量保存手动输入账号失败: {str(e)}")
            
            # 账号已在工作线程中批量保存，这里只需要显示结果
            if final_accounts:
                self.imported_accounts = final_accounts
                
                auto_count = len(auto_accounts)
                manual_count = len([acc for acc in final_accounts if acc.get('email_source') == 'manual'])
                
                result_msg = f"成功导入 {len(final_accounts)} 个账号"
                if auto_count > 0:
                    result_msg += f"\n🌐 自动解析: {auto_count} 个"
                if manual_count > 0:
                    result_msg += f"\n✏️ 手动输入: {manual_count} 个"
                
                QMessageBox.information(self, "导入成功", result_msg)
                self.accept()
            else:
                QMessageBox.information(self, "导入取消", "没有账号被导入")
                
        except Exception as e:
            self.logger.error(f"处理导入结果时出错: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理导入结果时出错: {str(e)}")
            self.setEnabled(True)
    
    def show_progress_log(self, message: str):
        """显示进度日志"""
        try:
            # 🔥 更新：在统一Token标签页显示日志
            current_tab = self.tab_widget.currentIndex()
            if current_tab == 1 and hasattr(self, 'unified_log_display'):  # 统一Token标签页
                self.unified_log_display.append(message)
        except Exception as e:
            self.logger.error(f"显示进度日志失败: {str(e)}")
    
    def get_imported_accounts(self):
        """获取导入的账号列表"""
        return self.imported_accounts
