#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
账号列表组件 - 现代简洁版
支持并发刷新和高效的账号管理功能
"""

import logging
import time
import json
import os
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTableWidget, QTableWidgetItem, QMessageBox,
    QHeaderView, QAbstractItemView, QMenu, QCheckBox, QDialog, QProgressBar, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QTimer
from PyQt6.QtGui import QAction, QColor, QCursor

# 导入其他组件
from .tag_management_dialog import TagManagementDialog
from .use_account_confirmation_dialog import UseAccountConfirmationDialog  # 新的确认对话框
from ..utils.tag_manager import get_tag_manager
from ..core.version_config import VersionConfig


class FlyStyleSwitchThread(QThread):
    """账号切换线程 - 使用 reset_cursor_account 方法实现账号切换"""
    switch_finished = pyqtSignal(bool, str)
    progress_updated = pyqtSignal(str)
    
    def __init__(self, cursor_manager, account, options):
        super().__init__()
        self.cursor_manager = cursor_manager
        self.account = account
        self.options = options  # 对应 fly-cursor-free 的选项
        
    def run(self):
        """执行切换 - 直接调用新的 reset_cursor_account 方法"""
        try:
            email = self.account.get('email', '未知')
            self.progress_updated.emit(f"🔄 开始重置Cursor账号: {email}")
            
            # 🔥 重要修复：使用新的XCCursorManager应用账号
            from ..services.cursor_service.xc_cursor_manage import XCCursorManager
            xc_manager = XCCursorManager(self.cursor_manager.config)
            
            email = self.account.get('email', '')
            access_token = self.account.get('access_token', '')
            refresh_token = self.account.get('refresh_token', access_token)  # 按照cursor-ideal逻辑，默认等于access_token
            user_id = self.account.get('user_id', '')
            
            success, message = xc_manager.apply_account(email, access_token, refresh_token, user_id,
                                                      progress_callback=self.progress_updated.emit,
                                                      cursor_manager=self.cursor_manager,
                                                      options=self.options)
            
            # 发出完成信号
            if success:
                self.progress_updated.emit("✅ 账号切换完成")
                self.switch_finished.emit(True, message)
            else:
                self.progress_updated.emit("❌ 账号切换失败")
                self.switch_finished.emit(False, message)
                
        except Exception as e:
            error_msg = f"切换过程中出现错误: {str(e)}"
            self.progress_updated.emit("❌ 切换异常")
            self.switch_finished.emit(False, error_msg)


class TokenConversionThread(QThread):
    """Token转换的后台线程"""
    progress_updated = pyqtSignal(int, int, str)  # 已完成数量，总数量，当前账号
    conversion_completed = pyqtSignal(int, int, int)  # 成功数量，失败数量，跳过数量
    account_converted = pyqtSignal(dict)  # 单个账号转换完成
    
    def __init__(self, accounts_to_convert, config=None):
        super().__init__()
        self.accounts_to_convert = accounts_to_convert
        self.config = config
        self.total_count = len(accounts_to_convert)
        self.completed_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self._should_stop = False
        
    def stop(self):
        """停止转换"""
        self._should_stop = True
        
    def run(self):
        """执行Token转换"""
        try:
            from ..utils.session_token_converter import SessionTokenConverter
            converter = SessionTokenConverter(self.config)
            
            # 定义停止检查函数
            def should_stop():
                return self._should_stop
            
            # 🔥 定义进度回调函数
            def progress_callback(completed, total, email, status):
                self.completed_count = completed
                # 发射进度更新信号
                self.progress_updated.emit(completed, total, email)
            
            # 使用统一的浏览器复用转换方法
            convert_results = converter.batch_convert_accounts(
                accounts=self.accounts_to_convert,
                config=self.config,
                progress_callback=progress_callback,  # 🔥 添加进度回调
                stop_flag=should_stop
            )
            
            # 发出完成信号
            self.conversion_completed.emit(
                convert_results.get('converted', 0),
                convert_results.get('failed', 0), 
                convert_results.get('skipped', 0)
            )
            
        except Exception as e:
            logging.error(f"Token转换过程中出错: {str(e)}")
            self.conversion_completed.emit(0, self.total_count, 0)


class ConcurrentRefreshThread(QThread):
    """并发刷新账号订阅信息的线程"""
    progress_updated = pyqtSignal(int, int, int, str)  # 成功数量，已完成数量，总数量，当前账号
    refresh_completed = pyqtSignal(int, int, list)  # 成功数量，总数量，失败账号列表
    account_refreshed = pyqtSignal(dict)  # 单个账号刷新完成
    
    def __init__(self, cursor_manager, accounts_to_refresh, parent=None):
        super().__init__(parent)
        self.cursor_manager = cursor_manager
        self.accounts_to_refresh = accounts_to_refresh
        self.success_count = 0
        self.completed_count = 0
        self.total_count = len(accounts_to_refresh)
        self._should_stop = False
        self.failed_accounts = []  # 记录失败的账号邮箱
        self.logger = logging.getLogger(__name__)
        # 保存配置对象引用
        self.config = parent.config if parent and hasattr(parent, 'config') else None
        
    def stop(self):
        """停止刷新"""
        self._should_stop = True
        
    def run(self):
        """执行并发刷新"""
        try:
            self.logger.info(f"🚀 并发刷新线程启动，准备刷新 {len(self.accounts_to_refresh)} 个账号")
            for acc in self.accounts_to_refresh[:3]:  # 显示前3个账号
                self.logger.info(f"   - {acc.get('email', '未知')}")
            
            # 🚀 优化：使用100个线程池并发执行，大幅提升处理速度
            max_workers = min(100, len(self.accounts_to_refresh))
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_account = {}
                for account in self.accounts_to_refresh:
                    if self._should_stop:
                        break
                    future = executor.submit(self._refresh_single_account, account)
                    future_to_account[future] = account
                
                # 收集结果并更新进度条
                for future in as_completed(future_to_account):
                    if self._should_stop:
                        break
                        
                    account = future_to_account[future]
                    try:
                        success = future.result()
                        if success:
                            self.success_count += 1
                        else:
                            # 记录失败的账号
                            email = account.get('email', '')
                            if email:
                                self.failed_accounts.append(email)
                        
                        self.completed_count += 1
                        
                        # 🔥 发送进度更新信号（用于进度条）- 包含成功数量
                        self.progress_updated.emit(self.success_count, self.completed_count, self.total_count, account.get('email', ''))
                        
                    except Exception as e:
                        logging.error(f"刷新账号 {account.get('email', '未知')} 时出错: {str(e)}")
                        # 记录异常的账号
                        email = account.get('email', '')
                        if email:
                            self.failed_accounts.append(email)
                        self.completed_count += 1
                        # 即使失败也发送进度
                        self.progress_updated.emit(self.success_count, self.completed_count, self.total_count, account.get('email', ''))
            
            # 全部完成后，在后台线程统一保存到配置文件
            if self.config and self.success_count > 0:
                try:
                    self.logger.info(f"💾 刷新完成，在后台线程统一保存 {self.success_count} 个账号...")
                    all_accounts = self.config.load_accounts()
                    
                    # 🔥 第一步：去重账号列表（保留最新的）
                    seen_emails = {}
                    duplicate_count = 0
                    
                    for acc in all_accounts:
                        email = acc.get('email', '')
                        if email:
                            if email in seen_emails:
                                # 发现重复，比较更新时间
                                existing_time = seen_emails[email].get('subscriptionUpdatedAt', 0)
                                current_time = acc.get('subscriptionUpdatedAt', 0)
                                if current_time > existing_time:
                                    # 当前账号更新，替换旧的
                                    seen_emails[email] = acc
                                    self.logger.warning(f"⚠️ 发现重复账号 {email}，保留较新的记录")
                                duplicate_count += 1
                            else:
                                seen_emails[email] = acc
                    
                    if duplicate_count > 0:
                        self.logger.warning(f"🔧 去重完成：移除了 {duplicate_count} 个重复账号")
                    
                    # 🔥 第二步：更新所有刷新成功的账号数据
                    updated_count = 0
                    for refreshed_account in self.accounts_to_refresh:
                        email = refreshed_account.get('email', '')
                        
                        if email in seen_emails:
                            seen_emails[email].update(refreshed_account)
                            updated_count += 1
                            self.logger.debug(f"✅ 更新账号: {email}")
                    
                    # 重新生成账号列表
                    final_accounts = list(seen_emails.values())
                    
                    # 统一保存
                    self.config.save_accounts(final_accounts)
                    self.logger.info(f"✅ 已保存 {updated_count} 个账号的刷新数据到配置文件")
                except Exception as save_error:
                    self.logger.error(f"❌ 后台保存失败: {str(save_error)}")
            
            # 记录失败账号信息
            if self.failed_accounts:
                self.logger.info(f"⚠️ 有 {len(self.failed_accounts)} 个账号刷新失败，将标记显示")
            
            # 发出完成信号（包含失败账号列表）
            self.refresh_completed.emit(self.success_count, self.total_count, self.failed_accounts)
            
        except Exception as e:
            logging.error(f"并发刷新过程中出错: {str(e)}")
            self.refresh_completed.emit(self.success_count, self.total_count, [])
    
    def _refresh_single_account(self, account):
        """刷新单个账号（在线程池中执行）- 修复：确保account对象被正确更新"""
        try:
            # 🔥 关键修复：refresh_account_subscription会直接修改account对象
            # 所以这里返回的True/False表示是否成功，account对象本身已被更新
            success = self.cursor_manager.refresh_account_subscription(account)
            if success:
                # 🔍 添加调试日志确认数据更新
                email = account.get('email', '未知')
                membership = account.get('membershipType', 'unknown')
                individual_membership = account.get('individualMembershipType', '')
                trial_days = account.get('trialDaysRemaining', account.get('daysRemainingOnTrial', 0))
                updated_at = account.get('subscriptionUpdatedAt', 0)
                self.logger.info(f"✅ 账号 {email} 刷新成功:")
                self.logger.info(f"   membershipType: '{membership}'")
                self.logger.info(f"   individualMembershipType: '{individual_membership}'")
                self.logger.info(f"   trialDaysRemaining: {trial_days}")
                self.logger.info(f"   subscriptionUpdatedAt: {updated_at}")
                
                # 🔥 发射信号，通知UI更新缓存
                self.account_refreshed.emit(account)
            return success
        except Exception as e:
            logging.error(f"刷新账号 {account.get('email', '未知')} 失败: {str(e)}")
            return False


class TimeTableWidgetItem(QTableWidgetItem):
    """自定义时间列的TableWidgetItem，支持正确的时间排序"""
    
    def __init__(self, time_str: str, timestamp: float = None):
        super().__init__(time_str)
        # 存储时间戳用于排序
        self.timestamp = timestamp if timestamp is not None else 0
    
    def __lt__(self, other):
        """自定义排序比较方法"""
        if isinstance(other, TimeTableWidgetItem):
            return self.timestamp < other.timestamp
        return super().__lt__(other)


class SubscriptionTableWidgetItem(QTableWidgetItem):
    """自定义订阅状态列的TableWidgetItem，支持按优先级排序"""
    
    # 🔥 排序优先级（数值越高优先级越高）：Pro > 试用 > 免费版 > Hobby
    PRIORITY_MAP = {
        'pro': 5,       # Pro最高优先级
        'professional': 5,  # Professional等同Pro
        'trial': 4,     # 试用第二优先级
        'free_trial': 4,    # 免费试用等同试用
        'free': 3,      # 免费版第三优先级
        'basic': 3,     # 基础版等同免费版
        'hobby': 2,     # Hobby最低优先级
        'unknown': 1,   # 未知类型
        '': 0          # 空值
    }
    
    def __init__(self, display_text: str, subscription_type: str = '', trial_days: int = 0):
        super().__init__(display_text)
        # 存储订阅类型用于排序
        self.subscription_type = subscription_type.lower()
        self.priority = self.PRIORITY_MAP.get(self.subscription_type, 0)
        # 🔧 确保trial_days不为None，转换为0
        self.trial_days = trial_days if trial_days is not None else 0
    
    def __lt__(self, other):
        """自定义排序比较方法"""
        if isinstance(other, SubscriptionTableWidgetItem):
            # 🔥 第一步：先按优先级排序（Pro > Trial > Free > Hobby）
            # priority值越大越优先，所以要用 > 来让大的排前面
            if self.priority != other.priority:
                return self.priority > other.priority  # 注意：这里用>让高优先级排前面
            
            # 🔥 第二步：优先级相同，按具体类型的内部排序
            # 如果都是试用状态，按试用天数排序（天数少的优先，即将到期的排在前面）
            if "试用" in self.text() and "试用" in other.text():
                self_days = self.trial_days if self.trial_days is not None else 0
                other_days = other.trial_days if other.trial_days is not None else 0
                return self_days < other_days  # 试用1天 < 试用2天
            
            # 如果都是Pro状态，按剩余天数排序
            if "Pro" in self.text() and "Pro" in other.text():
                self_days = self.trial_days if self.trial_days is not None else 9999  # Pro（未知天数）设为9999
                other_days = other.trial_days if other.trial_days is not None else 9999
                # 排序目标：Pro → Pro1天 → Pro2天 → ... → Pro7天
                if self_days == 9999 and other_days != 9999:
                    return True  # Pro排在ProX天前面
                elif self_days != 9999 and other_days == 9999:
                    return False  # ProX天排在Pro后面
                else:
                    return self_days < other_days  # Pro1天 < Pro2天
            
            # 其他情况按文本排序
            return self.text() < other.text()
        return super().__lt__(other)


class AccountListWidget(QWidget):
    """现代简洁的账号列表组件"""
    status_message = pyqtSignal(str)
    batch_progress_signal = pyqtSignal(int, int, int, bool)  # 参数：当前进度, 成功数, 总数, 是否显示
    reset_refresh_btn_signal = pyqtSignal()  # 恢复刷新Token按钮的信号
    reset_bind_card_btn_signal = pyqtSignal()  # 恢复批量绑卡按钮的信号
    refresh_ui_signal = pyqtSignal()  # 刷新UI但保持选中状态的信号
    log_message_signal = pyqtSignal(str)  # 日志消息信号，用于显示在日志栏
    
    def __init__(self, config, cursor_manager, parent=None):
        super().__init__(parent)
        self.config = config
        self.cursor_manager = cursor_manager
        self.logger = logging.getLogger(__name__)
        self.dashboard_browser = None  # 用于跟踪打开的浏览器实例
        self.switch_thread = None
        
        # 并发刷新相关
        self.refresh_thread = None
        self.refresh_progress_bar = None
        self.refresh_timer = None
        
        # Token转换相关
        self.conversion_thread = None
        
        # 排序状态记录
        self.current_sort_column = -1
        self.current_sort_order = Qt.SortOrder.AscendingOrder
        
        # 当前显示的账号列表（排序后的）
        self.current_displayed_accounts = []
        
        # 排序防抖标志（防止快速点击导致卡死）
        self._is_sorting = False
        
        # Shift批量选择优化：记录最后一个勾选的复选框行号
        self._last_checked_row = None
        
        # 初始化标记管理器
        self.tag_manager = get_tag_manager()
        
        # 初始化备注存储 (从配置文件加载持久化数据)
        self.account_remarks = self.config.load_remarks()  # 格式: {email: remark_type} - 从文件加载
        self.remark_types = ["自用", "商用", "用尽"]
        self.remark_colors = {
            "自用": "#28a745",  # 绿色
            "商用": "#409eff",  # 蓝色  
            "用尽": "#f56c6c"   # 红色
        }
        
        # 🔥 刷新防抖机制
        self._refresh_timer = None
        self._pending_refresh = False
        
        # 🔥 增量更新机制 - 避免全量刷新
        self._accounts_cache = {}  # 账号缓存: {email: account_data}
        
        # 用量显示状态跟踪（记录哪些账号已经加载过用量）
        self.loaded_usage_accounts = set()  # 存储已加载用量的邮箱
        
        # 删除简单的切换记录，改为使用数据库检测
        
        self.init_ui()
        
        # 初始化完成
        self.setup_connections()
        
        # ⚡ 启动优化：延迟加载账号列表，避免阻塞主窗口显示
        # 🔥 进一步延迟加载时间，让主窗口先完全显示
        QTimer.singleShot(300, self._delayed_load_accounts)
        
        # 初始化完成后确保列宽设置正确
        self.apply_column_widths()
        
        # 设置定时器定期刷新当前账号状态
        self.account_refresh_timer = QTimer()
        self.account_refresh_timer.timeout.connect(self.update_current_account_display)
        self.account_refresh_timer.start(3000)  # 每3秒检查一次
        
        # 🔥 标记：数据是否已加载
        self._data_loaded = False
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 处理表格大小变化"""
        if obj == self.accounts_table and hasattr(self, 'loading_overlay'):
            if event.type() == event.Type.Resize:
                # 调整加载占位符大小以匹配表格
                self.loading_overlay.setGeometry(self.accounts_table.rect())
        return super().eventFilter(obj, event)
    
    def refresh_config(self):
        """刷新配置并清理浏览器实例"""
        try:
            # 重新加载配置数据
            self.config.config_data = self.config._load_config()
            
            # 确保config_data是字典
            if not isinstance(self.config.config_data, dict):
                self.logger.error(f"配置数据不是字典类型: {type(self.config.config_data)}")
                self.config.config_data = {}
            
            # 确保browser配置是字典类型
            if 'browser' in self.config.config_data:
                if not isinstance(self.config.config_data['browser'], dict):
                    self.logger.warning(f"检测到浏览器配置格式错误: {type(self.config.config_data['browser'])}")
                    self.config.config_data['browser'] = {'path': ''}
            
            # 清理现有的浏览器实例，以便下次使用新配置
            if self.dashboard_browser:
                try:
                    self.dashboard_browser.quit()
                    self.logger.info("已关闭旧的浏览器实例")
                except Exception as e:
                    self.logger.warning(f"关闭浏览器时出错: {str(e)}")
                finally:
                    # 无论如何都要清空引用
                    self.dashboard_browser = None
                    self.logger.info("浏览器实例引用已清空")
            
            self.logger.info("账号列表组件配置已刷新")
            
        except Exception as e:
            self.logger.error(f"刷新配置失败: {str(e)}")
    
    def __del__(self):
        """析构函数，清理资源"""
        try:
            # 清理浏览器实例
            if hasattr(self, 'dashboard_browser') and self.dashboard_browser:
                self._cleanup_browser(self.dashboard_browser)
            
            # 清理可能残留的Chrome进程
            self._cleanup_chrome_processes()
        except:
            pass  # 忽略析构时的错误
    
    def _cleanup_chrome_processes(self):
        """清理残留的Chrome进程"""
        try:
            import psutil
            
            self.logger.info("🧹 开始清理残留的Chrome进程...")
            killed_count = 0
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    proc_name = proc.info['name'].lower()
                    
                    # 检查是否是Chrome进程
                    if 'chrome' in proc_name or 'chromium' in proc_name:
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline:
                            cmdline_str = ' '.join(cmdline).lower()
                            # 只杀死DrissionPage启动的Chrome进程
                            if 'drissionpage' in cmdline_str or 'remote-debugging-port' in cmdline_str:
                                proc.kill()
                                killed_count += 1
                                self.logger.debug(f"🔪 清理Chrome进程: PID={proc.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            if killed_count > 0:
                self.logger.info(f"✅ 清理了 {killed_count} 个残留的Chrome进程")
            else:
                self.logger.debug("✅ 没有残留的Chrome进程")
                
        except ImportError:
            self.logger.debug("psutil未安装，跳过Chrome进程清理")
        except Exception as e:
            self.logger.warning(f"清理Chrome进程失败: {str(e)}")
    
    def _show_simple_message(self, message):
        """显示简洁的无按钮提示框 - 点击任意位置关闭"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        
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
    
    def _show_delete_confirmation(self, count: int) -> bool:
        """显示删除确认对话框
        
        Args:
            count: 要删除的账号数量
            
        Returns:
            bool: True表示确认删除，False表示取消
        """
        msgbox = QMessageBox(self)
        msgbox.setIcon(QMessageBox.Icon.Warning)
        msgbox.setWindowTitle("确认删除")
        msgbox.setText(f"确定要删除选中的 {count} 个账号吗？")
        
        # 应用统一样式
        self._apply_msgbox_style(msgbox)
        
        # 添加自定义按钮
        yes_btn = msgbox.addButton("🗑️ 确定删除", QMessageBox.ButtonRole.YesRole)
        no_btn = msgbox.addButton("❌ 取消", QMessageBox.ButtonRole.NoRole)
        
        # 设置默认按钮为取消
        msgbox.setDefaultButton(no_btn)
        
        # 执行对话框
        msgbox.exec()
        
        return msgbox.clickedButton() == yes_btn
    
    def _remove_account_from_table(self, email: str):
        """从表格中删除指定账号，避免重新加载所有账号
        
        Args:
            email: 要删除的账号邮箱
        """
        try:
            # 查找对应的行
            for row in range(self.accounts_table.rowCount()):
                email_item = self.accounts_table.item(row, 2)
                if email_item and email_item.text() == email:
                    # 删除该行
                    self.accounts_table.removeRow(row)
                    # 更新缓存
                    if hasattr(self, '_accounts_cache') and email in self._accounts_cache:
                        del self._accounts_cache[email]
                    # 更新序号
                    self._update_row_numbers()
                    # 更新统计信息
                    self.update_selected_count()
                    self.logger.info(f"✅ 从表格删除账号: {email}")
                    break
        except Exception as e:
            self.logger.error(f"从表格删除账号失败: {str(e)}")
    
    def _reset_progress_bar(self):
        """重置进度条为待命状态"""
        try:
            if hasattr(self, 'operation_progress_bar'):
                self.operation_progress_bar.setValue(0)
                self.operation_progress_bar.setFormat("待命")
            self.logger.debug("进度条已重置为待命状态")
        except Exception as e:
            self.logger.error(f"重置进度条失败: {str(e)}")
    
    def _update_row_numbers(self):
        """更新所有行的序号"""
        try:
            for row in range(self.accounts_table.rowCount()):
                number_item = self.accounts_table.item(row, 1)
                if number_item:
                    number_item.setText(str(row + 1))
        except Exception as e:
            self.logger.error(f"更新序号失败: {str(e)}")
    
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
            /* 删除按钮特殊样式 */
            QPushButton[text*="删除"] {
                background-color: #f44336;
            }
            QPushButton[text*="删除"]:hover {
                background-color: #e53935;
            }
            QPushButton[text*="删除"]:pressed {
                background-color: #d32f2f;
            }
            /* 取消按钮特殊样式 */
            QPushButton[text*="取消"] {
                background-color: #757575;
            }
            QPushButton[text*="取消"]:hover {
                background-color: #616161;
            }
            QPushButton[text*="取消"]:pressed {
                background-color: #424242;
            }
            /* 确定按钮（绿色） */
            QPushButton[text*="导出选中"] {
                background-color: #4CAF50;
            }
            QPushButton[text*="导出选中"]:hover {
                background-color: #45a049;
            }
            /* 导出全部按钮（蓝色） */
            QPushButton[text*="导出全部"] {
                background-color: #2196F3;
            }
        """)
    
    def init_ui(self):
        """初始化用户界面"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # 顶部工具栏
        self.create_toolbar(layout)
        
        # 账号表格
        self.create_table(layout)
        
        # 底部状态栏
        self.create_status_bar(layout)
        
        # 应用基础样式
        self.apply_base_styles()
        
    def create_toolbar(self, parent_layout):
        """创建顶部工具栏"""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        
        # 当前账号显示（带主页按钮）
        current_account_container = QWidget()
        current_account_layout = QHBoxLayout(current_account_container)
        current_account_layout.setContentsMargins(0, 0, 0, 0)
        current_account_layout.setSpacing(6)
        
        self.current_account_label = QLabel("当前账号：未登录")
        self.current_account_label.setStyleSheet("""
            QLabel {
                background: #e9ecef;
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 10px 16px;
                color: #495057;
                font-weight: 500;
                font-size: 14px;
            }
        """)
        
        # 当前账号主页按钮
        self.current_account_home_btn = QPushButton("🏠")
        self.current_account_home_btn.setToolTip("打开当前账号主页")
        self.current_account_home_btn.setFixedSize(24, 24)
        self.current_account_home_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 12px;
                padding: 0px;
                font-size: 14px;
                width: 24px;
                height: 24px;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: #007bff;
                color: white;
                text-align: center;
            }
            QPushButton:hover {
                background: #0056b3;
            }
            QPushButton:pressed {
                background: #004085;
            }
            QPushButton:disabled {
                background: #e0e0e0;
                color: #9e9e9e;
            }
        """)
        self.current_account_home_btn.clicked.connect(self.open_current_account_homepage)
        self.current_account_home_btn.setEnabled(False)  # 默认禁用，有当前账号时启用
        
        current_account_layout.addWidget(self.current_account_label)
        current_account_layout.addWidget(self.current_account_home_btn)
        
        toolbar.addWidget(current_account_container)
        
        toolbar.addStretch()
        
        # 创建操作按钮组
        from ..core.version_config import VersionConfig
        
        buttons = []
        
        # 刷新按钮（完整版和精简版都显示）
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.toggle_refresh_subscriptions)
        buttons.append((self.refresh_btn, "#DC143C"))  # 深红色 - 刷新
        
        # 刷新Token按钮（完整版和精简版都显示）
        self.refresh_token_btn = QPushButton("🔑 刷新Token")
        self.refresh_token_btn.clicked.connect(self.toggle_refresh_tokens)
        buttons.append((self.refresh_token_btn, "#8b5cf6"))  # 紫色 - Token
        
        # 批量绑卡按钮（仅完整版显示）
        if VersionConfig.is_full_version():
            self.batch_bind_card_btn = QPushButton("💳 批量绑卡")
            self.batch_bind_card_btn.clicked.connect(self.toggle_batch_bind_cards)
            buttons.append((self.batch_bind_card_btn, "#f59e0b"))  # 橙色 - 绑卡
            
            # 一键登录按钮（支持开始/停止切换）
            self.quick_login_btn = QPushButton("🔐 一键登录")
            self.quick_login_btn.clicked.connect(self.toggle_quick_login)
            buttons.append((self.quick_login_btn, "#06b6d4"))  # 青色 - 登录
        
        # 设置限额按钮（完整版和精简版都显示）
        set_limit_btn = QPushButton("💰 设置限额")
        set_limit_btn.clicked.connect(self.batch_set_limit)
        buttons.append((set_limit_btn, "#10b981"))  # 绿色 - 限额
        
        # 批量操作按钮 - 单独显示
        self.select_all_btn = QPushButton("✅ 全选")
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        
        delete_selected_btn = QPushButton("❌ 删除")
        delete_selected_btn.clicked.connect(self.delete_selected_accounts)
        
        # 添加批量操作按钮
        buttons.extend([
            (self.select_all_btn, "#17a2b8"),      # 青色 - 全选
            (delete_selected_btn, "#dc3545")  # 红色 - 删除
        ])
        
        for btn, color in buttons:
            btn.setFixedHeight(36)
            
            # 计算hover和pressed颜色
            if color == "#4A90E2":  # 蓝色
                hover_color = "#3A7BD5"
                pressed_color = "#2A66C0"
            elif color == "#50C878":  # 绿色
                hover_color = "#45B368"
                pressed_color = "#3A9E58"
            elif color == "#9B59B6":  # 紫色
                hover_color = "#8E44AD"
                pressed_color = "#7D3C98"
            elif color == "#FF6B6B":  # 珊瑚红
                hover_color = "#FF5252"
                pressed_color = "#E53935"
            elif color == "#DC143C":  # 深红色（Crimson）
                hover_color = "#B91C1C"
                pressed_color = "#991B1B"
            elif color == "#FF9800":  # 橙色
                hover_color = "#F57C00"
                pressed_color = "#E65100"
            elif color == "#f59e0b":  # 绑卡橙色
                hover_color = "#d97706"
                pressed_color = "#b45309"
            elif color == "#17a2b8":  # 青色
                hover_color = "#138496"
                pressed_color = "#117a8b"
            elif color == "#dc3545":  # 红色
                hover_color = "#c82333"
                pressed_color = "#bd2130"
            elif color == "#10b981":  # 绿色（限额）
                hover_color = "#059669"
                pressed_color = "#047857"
            elif color == "#8b5cf6":  # 紫色（Token刷新）
                hover_color = "#7c3aed"
                pressed_color = "#6d28d9"
            elif color == "#06b6d4":  # 青色（一键登录）
                hover_color = "#0891b2"
                pressed_color = "#0e7490"
            else:  # 默认灰色
                hover_color = "#5a6268"
                pressed_color = "#545b62"
            
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-weight: 500;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {pressed_color};
                }}
                QPushButton:focus {{
                    outline: none;
                }}
                QPushButton:disabled {{
                    background-color: #6c757d;
                    opacity: 0.5;
                }}
                QPushButton::menu-indicator {{
                    image: none;
                    width: 0px;
                }}
            """)
            toolbar.addWidget(btn)
            
        parent_layout.addLayout(toolbar)
        
    def create_table(self, parent_layout):
        """创建表格"""
        # 表格容器
        table_container = QWidget()
        table_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
            }
        """)
        
        container_layout = QVBoxLayout(table_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建表格
        self.accounts_table = QTableWidget()
        
        # 根据版本配置设置列
        if VersionConfig.is_full_version():
            # 完整版：包含订阅状态、用途和用量
            self.accounts_table.setColumnCount(11)
            self.accounts_table.setHorizontalHeaderLabels([
                "选择", "序号", "邮箱", "创建时间", "订阅状态", "用途", "用量", "备注", "🔄 切换", "🏠 主页", "📋 详情"
            ])
        else:
            # 精简版：包含用量
            self.accounts_table.setColumnCount(9)
            self.accounts_table.setHorizontalHeaderLabels([
                "选择", "序号", "邮箱", "创建时间", "用量", "备注", "🔄 切换", "🏠 主页", "📋 详情"
            ])
        
        # 表格样式 - 现代美化设计
        self.accounts_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #e9ecef;
                border-radius: 12px;
                gridline-color: #f1f3f4;
                font-size: 13px;
                selection-background-color: transparent;
                color: #495057;
                outline: none;
            }
            QTableWidget::item {
                padding: 12px 8px;
                border: none;
                border-bottom: 1px solid #f8f9fa;
                text-align: center;
            }
            QTableWidget::item:selected {
                background: transparent;
                color: #495057;
                border: none;
            }
            QTableWidget::item:hover {
                background: #e8f4fd;
                color: #1976d2;
            }
            QHeaderView::section {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8f9fa);
                border: none;
                border-bottom: 2px solid #dee2e6;
                border-right: 1px solid #f1f3f4;
                padding: 14px 8px;
                color: #495057;
                font-weight: 600;
                font-size: 12px;
                text-align: center;
            }
            QHeaderView::section:last {
                border-right: none;
            }
            QHeaderView::section:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f1f3f4, stop: 1 #e9ecef);
            }
        """)
        
        # 表格属性
        self.accounts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.accounts_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.accounts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setShowGrid(False)
        self.accounts_table.verticalHeader().setDefaultSectionSize(48)
        
        # 启用悬停效果 - 整行高亮
        self.accounts_table.setMouseTracking(True)
        self.accounts_table.setAlternatingRowColors(False)
        
        # 使用响应式列宽设置 - 允许用户调整宽度
        header = self.accounts_table.horizontalHeader()
        
        # 默认禁用排序，通过双击启用
        self.accounts_table.setSortingEnabled(False)
        
        # 连接表头双击事件
        header = self.accounts_table.horizontalHeader()
        header.sectionDoubleClicked.connect(self.on_header_double_clicked)
        
        # 🔥 监听Qt原生排序信号，确保排序后重置Shift选择缓存
        header.sortIndicatorChanged.connect(self._on_native_sort)
        
        if VersionConfig.is_full_version():
            # 完整版列设置
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)     # 选择
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)     # 序号
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)         # 邮箱 - 拉伸
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)     # 创建时间
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)     # 订阅状态
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)     # 用途
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)     # 用量
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)     # 备注
            header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)     # 切换
            header.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)     # 主页
            header.setSectionResizeMode(10, QHeaderView.ResizeMode.Interactive)    # 详情
        else:
            # 精简版列设置
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)     # 选择
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)     # 序号
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)         # 邮箱 - 拉伸
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)     # 创建时间
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)     # 用量
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)     # 备注
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)     # 切换
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)     # 主页
            header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)     # 详情
        
        # 设置各列最小宽度 - 不固定宽度，允许用户调整
        header.setMinimumSectionSize(40)  # 全局最小宽度
        
        if VersionConfig.is_full_version():
            # 完整版列宽
            self.accounts_table.setColumnWidth(0, 50)   # 选择
            self.accounts_table.setColumnWidth(1, 50)   # 序号
            self.accounts_table.setColumnWidth(2, 180)  # 邮箱
            self.accounts_table.setColumnWidth(3, 100)  # 创建时间
            self.accounts_table.setColumnWidth(4, 90)   # 订阅状态
            self.accounts_table.setColumnWidth(5, 70)   # 用途
            self.accounts_table.setColumnWidth(6, 90)   # 用量
            self.accounts_table.setColumnWidth(7, 100)  # 备注
            self.accounts_table.setColumnWidth(8, 70)   # 切换
            self.accounts_table.setColumnWidth(9, 70)   # 主页
            self.accounts_table.setColumnWidth(10, 70)  # 详情
        else:
            # 精简版列宽
            self.accounts_table.setColumnWidth(0, 60)   # 选择
            self.accounts_table.setColumnWidth(1, 60)   # 序号
            self.accounts_table.setColumnWidth(2, 200)  # 邮箱
            self.accounts_table.setColumnWidth(3, 120)  # 创建时间
            self.accounts_table.setColumnWidth(4, 90)   # 用量
            self.accounts_table.setColumnWidth(5, 150)  # 备注
            self.accounts_table.setColumnWidth(6, 80)   # 切换
            self.accounts_table.setColumnWidth(7, 80)   # 主页
            self.accounts_table.setColumnWidth(8, 80)   # 详情
        
        container_layout.addWidget(self.accounts_table)
        
        # 创建加载中占位符（覆盖在表格上方）
        self.loading_overlay = QWidget(self.accounts_table)
        self.loading_overlay.setStyleSheet("""
            QWidget {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 8px;
            }
        """)
        
        loading_layout = QVBoxLayout(self.loading_overlay)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        loading_label = QLabel("⏳ 正在加载账号列表...")
        loading_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                color: #6c757d;
                font-weight: 500;
                padding: 20px;
            }
        """)
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(loading_label)
        
        # 默认显示加载中，覆盖整个表格
        self.loading_overlay.setGeometry(self.accounts_table.geometry())
        self.loading_overlay.show()
        self.loading_overlay.raise_()  # 确保在最上层
        
        # 监听表格大小变化，自动调整占位符大小
        self.accounts_table.installEventFilter(self)
        
        parent_layout.addWidget(table_container)
        
    def create_status_bar(self, parent_layout):
        """创建底部状态栏"""
        status_widget = QWidget()
        status_widget.setFixedHeight(32)
        status_widget.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border-top: 1px solid #e9ecef;
            }
        """)
        
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(16, 6, 16, 6)
        
        # 📊 账号总数显示（放在左边）
        self.account_count_label = QLabel()
        self.account_count_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 12px;
                font-weight: 500;
                padding: 0;
                margin: 0;
            }
        """)
        status_layout.addWidget(self.account_count_label)
        
        # ✅ 选中账号数量显示
        self.selected_count_label = QLabel()
        self.selected_count_label.setStyleSheet("""
            QLabel {
                color: #0d6efd;
                font-size: 12px;
                font-weight: 600;
                padding: 2px 8px;
                margin-left: 12px;
                background: rgba(13, 110, 253, 0.1);
                border: 1px solid rgba(13, 110, 253, 0.2);
                border-radius: 10px;
            }
        """)
        status_layout.addWidget(self.selected_count_label)
        
        # 添加弹性空间
        status_layout.addStretch()
        
        # 📊 通用操作进度条（中间位置）- 支持刷新、转换token、绑卡等所有操作
        self.operation_progress_label = QLabel("操作进度：")
        self.operation_progress_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 12px;
                font-weight: 500;
                padding: 0;
                margin-right: 8px;
            }
        """)
        self.operation_progress_label.setVisible(True)  # 常驻显示
        status_layout.addWidget(self.operation_progress_label)
        
        from PyQt6.QtWidgets import QProgressBar
        self.operation_progress_bar = QProgressBar()
        self.operation_progress_bar.setFixedWidth(280)  # 加宽以显示更多信息
        self.operation_progress_bar.setFixedHeight(20)
        self.operation_progress_bar.setTextVisible(True)
        self.operation_progress_bar.setFormat("待命")  # 默认显示待命状态
        self.operation_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                text-align: center;
                background-color: #f8f9fa;
                font-size: 11px;
                font-weight: 600;
                color: #495057;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4CAF50, stop:1 #45a049);
                border-radius: 3px;
            }
        """)
        self.operation_progress_bar.setMinimum(0)
        self.operation_progress_bar.setMaximum(100)
        self.operation_progress_bar.setValue(0)
        self.operation_progress_bar.setVisible(True)  # 常驻显示
        status_layout.addWidget(self.operation_progress_bar)
        
        # 保持兼容性：batch_progress_bar 指向 operation_progress_bar
        self.batch_progress_bar = self.operation_progress_bar
        self.batch_progress_label = self.operation_progress_label
        
        # 添加一点间距
        status_layout.addSpacing(16)
        
        # 🕐 当前时间显示（放在右边）
        self.current_time_label = QLabel()
        self.current_time_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 12px;
                font-weight: 500;
                padding: 0;
                margin: 0;
            }
        """)
        status_layout.addWidget(self.current_time_label)
        
        # 更新时间显示并启动定时器
        self.update_current_time()
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_current_time)
        self.time_timer.start(1000)  # 每秒更新一次
        
        # 初始化账号总数显示
        self.update_account_count()
        # 初始化选中数量显示
        self.update_selected_count()
        
        parent_layout.addWidget(status_widget)
        
    def setup_connections(self):
        """设置事件连接"""
        # 右键菜单
        self.accounts_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.accounts_table.customContextMenuRequested.connect(self.show_context_menu)
        
        # 单击事件 - 用于切换、主页、详情列的整个单元格点击
        self.accounts_table.cellClicked.connect(self.handle_cell_click)
        
        # 双击事件
        self.accounts_table.cellDoubleClicked.connect(self.handle_cell_double_click)
        
        # 批量绑卡进度条更新信号
        self.batch_progress_signal.connect(self.update_batch_progress)
        
        # 刷新Token按钮恢复信号
        self.reset_refresh_btn_signal.connect(self._reset_refresh_token_button)
        
        # 批量绑卡按钮恢复信号
        self.reset_bind_card_btn_signal.connect(self._reset_bind_card_button)
        
        # 刷新UI信号（保持选中状态）
        self.refresh_ui_signal.connect(self._refresh_without_losing_selection)
        
    @pyqtSlot(int, int, int, bool)
    def update_batch_progress(self, current_index: int, success_count: int, total: int, visible: bool):
        """更新批量绑卡进度条
        
        Args:
            current_index: 当前处理到第几个
            success_count: 成功数量
            total: 总数量
            visible: 是否显示进度条
        """
        if visible:
            # 更新进度条
            progress = int((current_index / total) * 100) if total > 0 else 0
            self.operation_progress_bar.setMaximum(100)
            self.operation_progress_bar.setValue(progress)
            self.operation_progress_bar.setFormat(f"绑卡中 {current_index}/{total} (成功{success_count}) - {progress}%")
        else:
            # 🔥 显示完成状态，保留1分钟后再重置
            self.operation_progress_bar.setValue(100)
            failed_count = total - success_count
            if failed_count > 0:
                self.operation_progress_bar.setFormat(f"⚠️ 绑卡完成 成功{success_count}/{total} 失败{failed_count}")
            else:
                self.operation_progress_bar.setFormat(f"✅ 绑卡完成 {success_count}/{total}")
            
            # 取消之前的定时器（如果存在）
            if hasattr(self, '_progress_reset_timer') and self._progress_reset_timer:
                self._progress_reset_timer.stop()
                self._progress_reset_timer = None
            
            # 1分钟后重置进度条
            from PyQt6.QtCore import QTimer
            self._progress_reset_timer = QTimer()
            self._progress_reset_timer.setSingleShot(True)
            self._progress_reset_timer.timeout.connect(self._reset_progress_bar)
            self._progress_reset_timer.start(60000)  # 60秒
    
    def update_single_account_in_table(self, email: str):
        """增量更新：只更新指定邮箱的账号行，不刷新整个表格"""
        try:
            # 从配置加载最新的账号数据
            accounts = self.config.load_accounts()
            target_account = None
            for acc in accounts:
                if acc.get('email') == email:
                    target_account = acc
                    break
            
            if not target_account:
                self.logger.warning(f"未找到账号: {email}")
                return
            
            # 查找表格中对应的行
            for row in range(self.accounts_table.rowCount()):
                email_item = self.accounts_table.item(row, 2)
                if email_item and email_item.text() == email:
                    # 找到了，只更新这一行
                    self.logger.info(f"🔄 增量更新账号: {email} (第{row+1}行)")
                    
                    # 保存勾选状态
                    checkbox = self.accounts_table.cellWidget(row, 0)
                    was_checked = checkbox.isChecked() if checkbox else False
                    
                    # 重新填充这一行
                    self.fill_account_row(row, target_account)
                    
                    # 恢复勾选状态
                    if was_checked:
                        new_checkbox = self.accounts_table.cellWidget(row, 0)
                        if new_checkbox:
                            new_checkbox.setChecked(True)
                    
                    # 更新缓存
                    self._accounts_cache[email] = target_account
                    return
            
            # 如果表格中没有找到，说明是新账号，添加到末尾
            self.logger.info(f"➕ 新增账号到表格: {email}")
            row = self.accounts_table.rowCount()
            self.accounts_table.setRowCount(row + 1)
            self.fill_account_row(row, target_account)
            self._accounts_cache[email] = target_account
            
            # 更新账号总数显示
            self.update_account_count()
            
        except Exception as e:
            self.logger.error(f"增量更新账号失败: {str(e)}")
    
    def _debounced_refresh_ui(self):
        """防抖刷新UI - 避免短时间内多次刷新"""
        # 如果已经有待处理的刷新，重置计时器
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer.deleteLater()
        
        # 创建新的计时器，500ms后执行刷新
        self._refresh_timer = QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh_ui)
        self._refresh_timer.start(500)  # 500ms防抖延迟
        
        # 标记有待处理的刷新
        if not self._pending_refresh:
            self._pending_refresh = True
            self.logger.debug("⏱️ 刷新已排队（防抖500ms）")
    
    def _do_refresh_ui(self):
        """执行实际的UI刷新"""
        try:
            if self._pending_refresh:
                self.logger.info("🔄 执行防抖后的UI刷新")
                self._refresh_without_losing_selection()
                self._pending_refresh = False
        except Exception as e:
            self.logger.error(f"刷新UI失败: {str(e)}")
            self._pending_refresh = False
    
    @pyqtSlot()
    def _delayed_load_accounts(self):
        """延迟加载账号列表 - 启动优化"""
        try:
            start_time = time.time()
            self.logger.info("⚡ 开始延迟加载账号列表...")
            
            # 显示加载提示
            self.status_message.emit("⚡ 正在加载账号列表...")
            
            # 加载账号
            self.load_accounts()
            
            # 🔥 标记数据已加载
            self._data_loaded = True
            
            # 隐藏加载占位符
            if hasattr(self, 'loading_overlay'):
                self.loading_overlay.hide()
            
            elapsed = time.time() - start_time
            self.logger.info(f"✅ 账号列表加载完成，耗时 {elapsed:.2f}秒")
            self.status_message.emit(f"✅ 已加载 {len(self.current_displayed_accounts)} 个账号")
        except Exception as e:
            self.logger.error(f"延迟加载账号列表失败: {str(e)}")
            self.status_message.emit(f"❌ 加载失败: {str(e)}")
            # 加载失败也要隐藏占位符
            if hasattr(self, 'loading_overlay'):
                self.loading_overlay.hide()
    
    def quick_refresh_accounts(self, accounts: list):
        """快速刷新账号列表 - 直接使用已加载的账号数据，无需读取文件"""
        try:
            self.logger.info(f"🚀 快速刷新：直接显示 {len(accounts)} 个账号")
            self.display_accounts(accounts)
            
            # 更新缓存
            self._accounts_cache = {acc.get('email', ''): acc for acc in accounts if acc.get('email')}
            
            self.logger.info("✅ 快速刷新完成")
        except Exception as e:
            self.logger.error(f"快速刷新账号列表失败: {str(e)}")
            self.status_message.emit(f"快速刷新失败: {str(e)}")
    
    def load_accounts(self):
        """加载账号列表 - 优化版：减少不必要的IO操作"""
        try:
            # 🔥 使用账号缓存，避免频繁读取文件
            accounts = self.config.load_accounts()
            self.display_accounts(accounts)
            
            # 更新缓存
            self._accounts_cache = {acc.get('email', ''): acc for acc in accounts if acc.get('email')}
            
            # 更新底部账号总数显示
            self.update_account_count()
            
        except Exception as e:
            self.logger.error(f"加载账号列表失败: {str(e)}")
            self.status_message.emit(f"加载账号列表失败: {str(e)}")
    
    @pyqtSlot()
    def refresh_table(self):
        """刷新表格显示 - 重新加载账号列表"""
        try:
            self.logger.info("🔄 开始刷新账号表格...")
            self.load_accounts()
            # 刷新后重新应用列宽设置，确保显示正常
            self.apply_column_widths()
            self.logger.info("✅ 账号表格刷新完成")
        except Exception as e:
            self.logger.error(f"刷新表格失败: {str(e)}")
            self.status_message.emit(f"刷新表格失败: {str(e)}")
    
    def apply_column_widths(self):
        """应用列宽设置 - 仅在需要时重置为默认宽度，保持用户调整"""
        try:
            # 只在必要时重新设置列宽（例如表格重建后）
            # 保持用户的调整，不强制重置列宽
            header = self.accounts_table.horizontalHeader()
            
            if VersionConfig.is_full_version():
                # 完整版列宽检查
                if header.sectionSize(4) < 80:  # 订阅状态
                    self.accounts_table.setColumnWidth(4, 90)
                if header.sectionSize(5) < 70:  # 用途
                    self.accounts_table.setColumnWidth(5, 80)
                if header.sectionSize(6) < 80:  # 用量
                    self.accounts_table.setColumnWidth(6, 90)
                if header.sectionSize(7) < 100:  # 备注
                    self.accounts_table.setColumnWidth(7, 120)
                if header.sectionSize(8) < 60:  # 切换
                    self.accounts_table.setColumnWidth(8, 70)
                if header.sectionSize(9) < 60:  # 主页
                    self.accounts_table.setColumnWidth(9, 70)
                if header.sectionSize(10) < 60:  # 详情
                    self.accounts_table.setColumnWidth(10, 70)
            else:
                # 精简版列宽检查
                if header.sectionSize(4) < 80:  # 用量
                    self.accounts_table.setColumnWidth(4, 90)
                if header.sectionSize(5) < 100:  # 备注
                    self.accounts_table.setColumnWidth(5, 120)
                if header.sectionSize(6) < 60:  # 切换
                    self.accounts_table.setColumnWidth(6, 80)
                if header.sectionSize(7) < 60:  # 主页
                    self.accounts_table.setColumnWidth(7, 80)
                if header.sectionSize(8) < 60:  # 详情
                    self.accounts_table.setColumnWidth(8, 80)
        except Exception as e:
            self.logger.warning(f"应用列宽设置时出错: {str(e)}")
    
    # record_switched_account已删除 - 改为使用数据库检测真实登录状态
    
    def update_current_account_display(self):
        """更新当前账号显示 - 从Cursor数据库检测真实登录状态"""
        try:
            # 使用cursor_manager获取真实的当前账号信息
            current_account = self.cursor_manager.get_current_account()
            
            if current_account and current_account.get('is_logged_in'):
                # 显示真实登录的账号
                email = current_account.get('email', '未知')
                self.current_account_label.setText(f"当前账号：{email}")
                self.current_account_label.setStyleSheet("""
                    QLabel {
                        background: #d4edda;
                        border: 1px solid #c3e6cb;
                        border-radius: 6px;
                        padding: 10px 16px;
                        color: #155724;
                        font-weight: 500;
                        font-size: 14px;
                    }
                """)
                # 启用当前账号主页按钮
                self.current_account_home_btn.setEnabled(True)
                # 🔥 修复：避免重复日志，只在账号变化时打印
                if not hasattr(self, '_last_logged_account') or self._last_logged_account != email:
                    self.logger.info(f"检测到当前登录账号: {email}")
                    self._last_logged_account = email
            else:
                # 显示未登录状态
                self.current_account_label.setText("当前账号：未登录")
                self.current_account_label.setStyleSheet("""
                    QLabel {
                        background: #e9ecef;
                        border: 1px solid #ced4da;
                        border-radius: 6px;
                        padding: 10px 16px;
                        color: #495057;
                        font-weight: 500;
                        font-size: 14px;
                    }
                """)
                # 禁用当前账号主页按钮
                self.current_account_home_btn.setEnabled(False)
                
        except Exception as e:
            self.logger.error(f"更新当前账号显示失败: {str(e)}")
            # 发生错误时显示错误状态
            self.current_account_label.setText("当前账号：检测失败")
            self.current_account_label.setStyleSheet("""
                QLabel {
                    background: #f8d7da;
                    border: 1px solid #f5c6cb;
                    border-radius: 6px;
                    padding: 10px 16px;
                    color: #721c24;
                    font-weight: 500;
                    font-size: 14px;
                }
            """)
            # 禁用当前账号主页按钮
            self.current_account_home_btn.setEnabled(False)
    
    def display_accounts(self, accounts):
        """显示账号列表 - 优化版：批量渲染提升性能"""
        # ⚡ 性能优化：在批量更新期间禁用界面刷新
        self.accounts_table.setUpdatesEnabled(False)
        
        try:
            # 🔥 修复：先禁用排序，避免清理时触发排序
            self.accounts_table.setSortingEnabled(False)
            
            # 连接表头双击事件
            header = self.accounts_table.horizontalHeader()
            header.sectionDoubleClicked.connect(self.on_header_double_clicked)
            
            # 清理表格，重置所有行和单元格
            self.accounts_table.clearContents()
            self.accounts_table.setRowCount(0)
            
            # 🔥 修复：重置排序指示器，确保没有残留的排序状态
            header.setSortIndicatorShown(False)
            
            # 🔥 新增：对账号进行默认排序
            if accounts:
                accounts = self._sort_accounts_by_priority(accounts)
            
            # 🔥 保存当前显示的账号列表（排序后的）
            self.current_displayed_accounts = accounts.copy() if accounts else []
            self.logger.debug(f"📋 保存排序后的账号列表，共 {len(self.current_displayed_accounts)} 个账号")
            
            if not accounts:
                self.show_welcome_message()
                # 更新账号总数显示（0个账号）
                self.update_account_count()
                # 更新选中数量显示（无账号时隐藏）
                self.update_selected_count()
                return
            
            # 设置新的行数
            self.accounts_table.setRowCount(len(accounts))
            
            # 直接填充所有数据（包括按钮）
            for row, account in enumerate(accounts):
                self.fill_account_row(row, account, lazy_load_buttons=False)
            
            # 更新账号总数显示
            self.update_account_count()
            
            # 更新选中数量显示
            self.update_selected_count()
            
            # 🚀 启动优化：延迟检测当前账号，避免阻塞启动（改为2秒，让表格先显示）
            QTimer.singleShot(2000, self.update_current_account_display)
            
            # 强制应用列宽设置，确保显示正常
            self.apply_column_widths()
            
            # 🔥 修复：数据填充完成后重新启用排序
            self.accounts_table.setSortingEnabled(True)
            
        finally:
            # ⚡ 性能优化：恢复界面刷新（一次性刷新所有变更）
            self.accounts_table.setUpdatesEnabled(True)
            # 强制立即刷新表格
            self.accounts_table.viewport().update()
        
        # 重置Shift选择的起始行（账号列表已重新加载，行号已变化）
        self._last_checked_row = None
        
        # 数据填充完成
        self.logger.debug(f"✅ 表格渲染完成，共 {len(accounts)} 个账号")
    
    def _sort_accounts_by_priority(self, accounts):
        """按优先级对账号进行排序：订阅状态 > 创建时间"""
        try:
            def get_sort_key(account):
                # 获取订阅状态优先级
                membership_type = account.get('membershipType', 'free').lower()
                individual_type = account.get('individualMembershipType', '').lower()
                subscription_type = individual_type if individual_type else membership_type
                trial_days = account.get('trialDaysRemaining', account.get('daysRemainingOnTrial', 0))
                
                # 🔥 按用户要求的排序优先级：Pro > 试用(天数少优先) > 免费版 > Hobby
                subscription_priority = 0
                if subscription_type in ['pro', 'professional']:
                    # Pro账号：计算剩余天数，区分Pro和Pro1-7天
                    pro_days = self._calculate_pro_remaining_days(account)
                    if pro_days is not None and pro_days > 0 and pro_days <= 7:
                        # Pro1天-Pro7天：优先级 1000-1 到 1000-7
                        subscription_priority = 1000 - pro_days  # Pro1天=999, Pro2天=998, ..., Pro7天=993
                    else:
                        # Pro（未知或>7天）：最高优先级
                        subscription_priority = 1000
                elif trial_days and trial_days > 0:
                    # 试用账号：天数少的在前（即将到期的优先）
                    # 使用900减去天数，确保天数少的优先级更高
                    subscription_priority = 900 - trial_days
                elif subscription_type in ['free', 'basic']:
                    subscription_priority = 800   # 免费版第三优先级
                elif subscription_type in ['hobby']:
                    subscription_priority = 700   # Hobby最低优先级
                elif subscription_type in ['free_trial', 'trial']:
                    subscription_priority = 600   # 过期试用
                else:
                    subscription_priority = 500   # 其他未知类型
                
                # 创建时间（时间戳，早的在前）
                created_at = account.get('created_at', 0)
                if isinstance(created_at, str) and created_at:
                    try:
                        # 尝试解析字符串时间
                        import re
                        from datetime import datetime
                        match = re.search(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})', created_at)
                        if match:
                            year, month, day, hour, minute = match.groups()
                            dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
                            time_priority = dt.timestamp()
                        else:
                            time_priority = 0
                    except:
                        time_priority = 0
                elif isinstance(created_at, (int, float)) and created_at > 0:
                    time_priority = created_at
                else:
                    time_priority = 0
                
                # 🔥 修复：订阅优先级（降序），创建时间（升序，早的在前）
                return (-subscription_priority, time_priority)
            
            # 执行排序
            sorted_accounts = sorted(accounts, key=get_sort_key)
            
            # 🔥 修复：移除默认排序的状态显示
            # self.logger.info(f"📊 账号列表已按优先级排序：订阅状态 > 创建时间（早的在前）")
            return sorted_accounts
            
        except Exception as e:
            self.logger.error(f"账号排序失败: {str(e)}")
            return accounts  # 排序失败时返回原列表
    
    def fill_account_row(self, row: int, account: dict, lazy_load_buttons: bool = False):
        """填充单行数据
        
        Args:
            row: 行号
            account: 账号数据
            lazy_load_buttons: 是否延迟加载按钮（用于加速初始渲染）
        """
        try:
            # 防御性检查：确保account是字典
            if not isinstance(account, dict):
                self.logger.error(f"第 {row} 行账号数据不是字典类型: {type(account)}")
                return
            
            # 选择框 - 完全无外框样式
            checkbox = QCheckBox()
            checkbox.setStyleSheet("""
                QCheckBox {
                    background: transparent;
                    border: none;
                    outline: none;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border-radius: 2px;
                    border: 1px solid #dee2e6;
                    background: white;
                }
                QCheckBox::indicator:hover {
                    border-color: #007bff;
                }
                QCheckBox::indicator:checked {
                    background: #007bff;
                    border-color: #007bff;
                }
            """)
            # 连接状态改变信号，实时更新选中数量
            checkbox.stateChanged.connect(self.update_selected_count)
            self.accounts_table.setCellWidget(row, 0, checkbox)
            
            # 序号 - 简单显示
            index_item = QTableWidgetItem(str(row + 1))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            index_item.setForeground(QColor("#6c757d"))
            self.accounts_table.setItem(row, 1, index_item)
            
            # 邮箱
            email = account.get('email', '未知')
            email_item = QTableWidgetItem(email)
            
            # 检查是否有密码（账号密码注册）
            password = account.get('password', '') or ''  # 处理None的情况
            has_password = bool(password.strip())
            
            if email.endswith('@cursor.local'):
                email_item.setForeground(QColor("#dc3545"))
                email_item.setToolTip("临时邮箱")
            elif has_password:
                # 账号密码注册：添加浅蓝色背景标记
                email_item.setBackground(QColor("#e3f2fd"))  # 浅蓝色背景
                email_item.setForeground(QColor("#1976d2"))  # 深蓝色字体
                email_item.setToolTip("🔐 账号密码注册")
            
            self.accounts_table.setItem(row, 2, email_item)
            
            # 创建时间 - 兼容多种时间格式
            created_at = account.get('created_at', '')
            timestamp = 0  # 用于排序的时间戳
            
            if isinstance(created_at, (int, float)) and created_at > 0:
                # 时间戳格式
                timestamp = created_at
                time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(created_at))
            elif isinstance(created_at, str) and created_at:
                # 字符串格式，尝试解析并重新格式化
                try:
                    from datetime import datetime
                    import re
                    
                    # 尝试解析ISO 8601格式 (如 "2025-10-11T00:20:20.253Z")
                    if 'T' in created_at:
                        try:
                            # 去除毫秒部分
                            clean_time = re.sub(r'\.\d+Z?$', '', created_at)
                            # 解析UTC时间
                            dt = datetime.fromisoformat(clean_time.replace('Z', '+00:00'))
                            # 转换为时间戳后再用本地时区格式化（自动转为北京时间）
                            timestamp = dt.timestamp()
                            time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))
                        except Exception:
                            # ISO格式解析失败，尝试其他格式
                            pass
                    
                    # 尝试解析普通格式 (如 "2025-09-07 10:22")
                    if not timestamp and len(created_at) > 10:
                        match = re.search(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})', created_at)
                        if match:
                            year, month, day, hour, minute = match.groups()
                            time_str = f"{year}-{month}-{day} {hour}:{minute}"
                            try:
                                dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
                                timestamp = dt.timestamp()
                            except:
                                timestamp = 0
                        else:
                            time_str = created_at
                    elif not timestamp:
                        time_str = created_at
                except Exception:
                    time_str = created_at
            else:
                time_str = '未知'
                
            # 创建时间项 - 使用自定义的TimeTableWidgetItem
            time_item = TimeTableWidgetItem(time_str, timestamp)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.accounts_table.setItem(row, 3, time_item)
            
            # 完整版特有功能
            if VersionConfig.is_full_version():
                # 订阅状态（在第4列）
                self.create_subscription_status(row, account)
                # 用途（在第5列）
                self.create_remark_display(row, account)
                # 用量（在第6列）
                self.create_usage_cost_cell(row, account)
                # 备注（在第7列）
                self.create_remark_input(row, account)
                
                # 🔥 操作按钮：延迟加载以加速初始渲染
                if lazy_load_buttons:
                    # 启动时只显示占位符，按钮稍后按需创建
                    self._create_button_placeholder(row, 8)
                    self._create_button_placeholder(row, 9)
                    self._create_button_placeholder(row, 10)
                else:
                    # 正常渲染按钮
                    self.create_switch_button(row, account)
                    self.create_homepage_button(row, account)
                    self.create_details_button(row, account)
            else:
                # 精简版布局
                # 用量（在第4列）
                self.create_usage_cost_cell(row, account)
                # 备注（在第5列）
                self.create_remark_input(row, account)
                
                # 🔥 操作按钮：延迟加载
                if lazy_load_buttons:
                    self._create_button_placeholder(row, 6)
                    self._create_button_placeholder(row, 7)
                    self._create_button_placeholder(row, 8)
                else:
                    self.create_switch_button(row, account)
                    self.create_homepage_button(row, account)
                    self.create_details_button(row, account)
            
        except Exception as e:
            self.logger.error(f"填充行 {row} 数据失败: {str(e)}")
            self.logger.error(f"问题账号数据: {account.get('email', '未知邮箱')}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
                    
    
    def _create_button_placeholder(self, row: int, col: int):
        """创建按钮占位符 - 快速渲染"""
        placeholder = QLabel("...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #ccc; font-size: 12px;")
        self.accounts_table.setCellWidget(row, col, placeholder)
    
    def _lazy_load_all_buttons(self):
        """延迟加载所有行的按钮"""
        try:
            self.logger.info("🔄 开始延迟加载操作按钮...")
            total_rows = len(self.current_displayed_accounts)
            
            # 🔥 分批加载，每批20行，避免一次性阻塞UI
            batch_size = 20
            current_batch = 0
            
            def load_batch():
                nonlocal current_batch
                start_row = current_batch * batch_size
                end_row = min(start_row + batch_size, total_rows)
                
                for row in range(start_row, end_row):
                    if row < self.accounts_table.rowCount():
                        # 🔥 修复：直接从表格读取邮箱，然后查找对应账号
                        email_item = self.accounts_table.item(row, 2)
                        if email_item:
                            email = email_item.text()
                            # 从缓存中查找账号（使用邮箱作为key）
                            account = self._accounts_cache.get(email)
                            if not account:
                                # 如果缓存中没有，从配置文件查找
                                accounts = self.config.load_accounts()
                                for acc in accounts:
                                    if acc.get('email') == email:
                                        account = acc
                                        self._accounts_cache[email] = acc
                                        break
                            
                            if account:
                                # 根据版本创建按钮
                                if VersionConfig.is_full_version():
                                    self.create_switch_button(row, account)
                                    self.create_homepage_button(row, account)
                                    self.create_details_button(row, account)
                                else:
                                    self.create_switch_button(row, account)
                                    self.create_homepage_button(row, account)
                                    self.create_details_button(row, account)
                
                current_batch += 1
                
                # 如果还有未加载的批次，继续
                if end_row < total_rows:
                    QTimer.singleShot(10, load_batch)  # 10ms后加载下一批
                else:
                    self.logger.info(f"✅ 所有按钮加载完成，共 {total_rows} 行")
            
            # 开始加载第一批
            load_batch()
            
        except Exception as e:
            self.logger.error(f"延迟加载按钮失败: {str(e)}")
    
    def create_usage_cost_cell(self, row: int, account: dict):
        """创建用量费用单元格 - 按需加载（启动优化）"""
        email = account.get('email', '')
        
        # 检查account中是否已有用量数据（来自刷新按钮或之前加载）
        usage_data = account.get('modelUsageData')
        
        # 🚀 启动优化：只在已有缓存数据时才显示，否则一律显示"点击加载"
        if usage_data:
            # 有缓存数据，创建可点击的标签
            cost_label = QLabel()
            cost_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cost_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cost_label.setToolTip("点击刷新用量")
            
            # 确定列号
            col = 6 if VersionConfig.is_full_version() else 4
            self.accounts_table.setCellWidget(row, col, cost_label)
            
            # 直接显示缓存数据
            self._display_usage_data(cost_label, account, usage_data)
            self.loaded_usage_accounts.add(email)
            
            # 绑定点击事件用于刷新
            cost_label.mousePressEvent = lambda event: self._on_usage_label_clicked(row, account, cost_label)
        else:
            # 🚀 启动优化：没有缓存数据，显示点击加载按钮（不自动加载）
            load_btn = QPushButton("点击加载")
            load_btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid #d1d5db;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    color: #6b7280;
                    background: #f9fafb;
                }
                QPushButton:hover {
                    background: #e5e7eb;
                    color: #374151;
                }
            """)
            load_btn.clicked.connect(lambda: self._on_load_usage_clicked(row, account, load_btn))
            
            # 确定列号
            col = 6 if VersionConfig.is_full_version() else 4
            self.accounts_table.setCellWidget(row, col, load_btn)
    
    def _display_usage_data(self, cost_label, account, usage_data):
        """显示用量数据"""
        try:
            total_cost = usage_data.get('totalCostUSD', 0)
            
            # 根据订阅状态决定除数：Ultra除以400，Pro除以50，其他除以10
            # 检查多个字段以确保正确识别订阅类型
            subscription_type = account.get('subscription_type', '').lower()
            membership_type = account.get('membershipType', '').lower()
            individual_type = account.get('individualMembershipType', '').lower()
            
            # 判断订阅类型
            is_ultra = (
                'ultra' in subscription_type or 
                'ultra' in membership_type or 
                'ultra' in individual_type
            )
            
            is_pro = (
                'pro' in subscription_type or 
                'pro' in membership_type or 
                'pro' in individual_type or
                'professional' in subscription_type or
                'professional' in membership_type
            )
            
            # 根据订阅类型设置除数
            if is_ultra:
                divisor = 400
            elif is_pro:
                divisor = 50
            else:
                divisor = 10
            percentage = (total_cost / divisor) * 100
            
            # 封顶100%
            if percentage > 100:
                percentage = 100.0
            
            # 显示用量百分比
            if percentage >= 100:
                cost_label.setText("100%")
                cost_label.setStyleSheet("color: #dc2626; font-size: 12px; font-weight: bold;")
            elif percentage > 80:
                cost_label.setText(f"{percentage:.1f}%")
                cost_label.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: bold;")
            elif percentage > 0:
                cost_label.setText(f"{percentage:.1f}%")
                cost_label.setStyleSheet("color: #16a34a; font-size: 12px; font-weight: bold;")
            else:
                cost_label.setText("0%")
                cost_label.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: bold;")
                
            # 只记录异常情况的日志
            if percentage >= 80:
                subscription_label = "Ultra" if is_ultra else ("Pro" if is_pro else "Free")
                self.logger.debug(f"⚠️ 高用量: {account.get('email', '')} - ${total_cost:.2f} / ${divisor} = {percentage:.1f}% ({subscription_label})")
            
        except Exception as e:
            self.logger.error(f"显示用量数据失败: {str(e)}")
            cost_label.setText("错误")
            cost_label.setStyleSheet("color: #ef4444; font-size: 11px;")
    
    def _on_usage_label_clicked(self, row, account, cost_label):
        """点击已加载的用量标签时刷新"""
        cost_label.setText("...")
        cost_label.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: bold;")
        self._load_usage_cost_async(account, cost_label, force_refresh=True)
    
    def _on_load_usage_clicked(self, row, account, button):
        """点击加载用量时的处理"""
        email = account.get('email', '')
        
        # 替换按钮为可点击的标签
        cost_label = QLabel("...")
        cost_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cost_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cost_label.setToolTip("点击刷新用量")
        cost_label.setStyleSheet("""
            color: #6b7280;
            font-size: 12px;
            font-weight: bold;
        """)
        
        col = 6 if VersionConfig.is_full_version() else 4
        self.accounts_table.setCellWidget(row, col, cost_label)
        
        # 标记为已加载
        self.loaded_usage_accounts.add(email)
        
        # 绑定点击事件用于刷新
        cost_label.mousePressEvent = lambda event: self._on_usage_label_clicked(row, account, cost_label)
        
        # 异步加载费用
        self._load_usage_cost_async(account, cost_label, force_refresh=False)
    
    def _load_usage_cost_async(self, account, cost_label, force_refresh=False):
        """异步加载账号费用 - 优先使用缓存"""
        import threading
        
        def load_cost():
            try:
                from ..utils.api_cache_manager import get_api_cache_manager
                cache_manager = get_api_cache_manager()
                
                user_id = account.get('user_id', '')
                access_token = account.get('access_token', '')
                email = account.get('email', '')
                
                if not user_id or not access_token:
                    try:
                        cost_label.setText("N/A")
                        cost_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
                    except RuntimeError:
                        pass
                    return
                
                usage_data = None
                
                # 如果不是强制刷新，按优先级获取数据
                if not force_refresh:
                    # 1. 优先从account中读取（刷新按钮已填充）
                    usage_data = account.get('modelUsageData')
                    if usage_data:
                        self.logger.info(f"📦 使用account中的缓存数据: {email}")
                    
                    # 2. 如果account中没有，尝试从缓存读取
                    if not usage_data:
                        usage_data = cache_manager.get_cached_data(user_id, access_token, 'usage', ttl=600)
                        if usage_data:
                            self.logger.info(f"📦 使用API缓存数据: {email}")
                
                # 3. 如果没有缓存或强制刷新，调用API
                if not usage_data or force_refresh:
                    self.logger.info(f"🔄 调用API获取用量数据: {email}")
                    usage_data = self.cursor_manager._get_model_usage_from_api(user_id, access_token, account)
                    if usage_data:
                        # 更新account和缓存
                        account['modelUsageData'] = usage_data
                        cache_manager.set_cached_data(user_id, access_token, 'usage', usage_data)
                        
                        # 🔥 更新current_displayed_accounts缓存
                        if self.current_displayed_accounts:
                            for acc in self.current_displayed_accounts:
                                if acc.get('user_id') == user_id or acc.get('email') == email:
                                    acc['modelUsageData'] = usage_data
                                    self.logger.debug(f"✅ 用量刷新-更新缓存: {email}")
                                    break
                        
                        # 保存到配置文件
                        accounts = self.config.load_accounts()
                        for acc in accounts:
                            if acc.get('user_id') == user_id:
                                acc['modelUsageData'] = usage_data
                                break
                        self.config.save_accounts(accounts)
                
                # 显示数据
                if usage_data:
                    try:
                        self._display_usage_data(cost_label, account, usage_data)
                    except RuntimeError:
                        pass
                else:
                    try:
                        cost_label.setText("N/A")
                        cost_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
                    except RuntimeError:
                        pass
                    
            except Exception as e:
                self.logger.error(f"加载费用失败: {str(e)}")
                try:
                    cost_label.setText("错误")
                    cost_label.setStyleSheet("color: #ef4444; font-size: 11px;")
                except RuntimeError:
                    pass
        
        # 后台线程执行
        thread = threading.Thread(target=load_cost, daemon=True)
        thread.start()
    
    def create_remark_input(self, row: int, account: dict):
        """创建备注输入框"""
        email = account.get('email', '')
        remark = account.get('remark', '')  # 从账号数据获取备注
        
        # 创建输入框（与订阅状态一致的样式）
        remark_input = QLineEdit()
        remark_input.setText(remark)
        remark_input.setPlaceholderText("备注...")
        remark_input.setMaxLength(50)  # 限制最大长度
        remark_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 11px;
                color: #495057;
            }
            QLineEdit:focus {
                background: #f0f8ff;
                border: 1px solid #80bdff;
            }
            QLineEdit:hover {
                border-color: #cbd5e0;
            }
        """)
        
        # 失去焦点时自动保存
        def save_remark():
            new_remark = remark_input.text().strip()
            if new_remark != remark:
                account['remark'] = new_remark
                # 获取所有账号并保存
                accounts = self.config.load_accounts()
                for acc in accounts:
                    if acc.get('email') == email:
                        acc['remark'] = new_remark
                        break
                self.config.save_accounts(accounts)
                self.logger.info(f"✅ 已保存备注: {email} -> {new_remark}")
        
        remark_input.editingFinished.connect(save_remark)
        
        # 根据版本类型设置到正确的列（直接设置，不用容器）
        if VersionConfig.is_full_version():
            # 完整版：备注在第7列
            self.accounts_table.setCellWidget(row, 7, remark_input)
        else:
            # 精简版：备注在第5列
            self.accounts_table.setCellWidget(row, 5, remark_input)
        
    def create_tag_display(self, row: int, account: dict):
        """创建标记显示"""
        email = account.get('email', '')
        account_tags = self.tag_manager.get_account_tags(email)
        
        # 🔥 修复：优化标记显示逻辑
        if account_tags:
            main_tag = account_tags[0]
            tag_name = main_tag.display_name
            tag_color = main_tag.color
            tag_id = main_tag.tag_id
            
            # 调试日志（仅在需要时启用）
            # self.logger.debug(f"📌 账号 {email} 的标记: {tag_name} (ID: {tag_id}, Color: {tag_color})")
            
            tag_label = QLabel(tag_name)
            tag_label.setStyleSheet(f"""
                QLabel {{
                    background: {tag_color};
                    color: white;
                    border-radius: 10px;
                    padding: 3px 10px;
                    font-size: 12px;
                    font-weight: 500;
                }}
            """)
            tag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tag_label.setToolTip("双击切换标记")
            
            # 创建容器确保与备注列样式一致
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(tag_label)
            
        # 🔥 修复：移除容器级别的双击事件，避免与表格事件冲突
        # container.mouseDoubleClickEvent = lambda event: self.cycle_account_tag(email, row)
            
            # 根据版本类型设置到正确的列
            if VersionConfig.is_full_version():
                # 完整版：试用标记在第5列
                self.accounts_table.setCellWidget(row, 5, container)
            else:
                # 精简版：试用标记在第4列
                self.accounts_table.setCellWidget(row, 4, container)
        else:
            # 默认显示"自用"
            personal_label = QLabel("自用")
            personal_label.setStyleSheet("""
                QLabel {
                    background: #28a745;
                    color: white;
                    border-radius: 10px;
                    padding: 3px 10px;
                    font-size: 12px;
                    font-weight: 500;
                }
            """)
            personal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            personal_label.setToolTip("双击切换标记")
            
            # 创建容器确保与备注列样式一致
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(personal_label)
            
        # 🔥 修复：移除容器级别的双击事件，避免与表格事件冲突
        # container.mouseDoubleClickEvent = lambda event: self.cycle_account_tag(email, row)
            
            # 根据版本类型设置到正确的列
            if VersionConfig.is_full_version():
                # 完整版：试用标记在第5列
                self.accounts_table.setCellWidget(row, 5, container)
            else:
                # 精简版：试用标记在第4列
                self.accounts_table.setCellWidget(row, 4, container)
    
    def _calculate_pro_remaining_days(self, account: dict) -> Optional[int]:
        """
        计算Pro账号剩余天数 - 基于账单开始日期倒数
        
        逻辑：
        - 账单开始日期当天 = Pro7天
        - 账单开始日期 + 1天 = Pro6天
        - 账单开始日期 + 6天 = Pro1天
        - 账单开始日期 + 7天及以后 = 已过期
        """
        try:
            from datetime import datetime, timezone
            
            # 优先从 usage_summary 获取账单开始日期（更准确）
            billing_cycle_start = None
            usage_summary = account.get('usage_summary', {})
            if usage_summary and 'billingCycleStart' in usage_summary:
                billing_cycle_start = usage_summary['billingCycleStart']
            
            # 降级：从订阅信息获取
            if not billing_cycle_start:
                subscription_info = account.get('subscription_info', {})
                if subscription_info and 'billingCycleStart' in subscription_info:
                    billing_cycle_start = subscription_info['billingCycleStart']
            
            # 如果有账单开始日期，使用新逻辑
            if billing_cycle_start:
                try:
                    # 解析 ISO 8601 格式的时间（如 "2025-10-01T00:00:00.000Z"）
                    if isinstance(billing_cycle_start, str):
                        # 移除毫秒和时区标识进行解析
                        billing_start_str = billing_cycle_start.replace('Z', '+00:00')
                        if '.' in billing_start_str:
                            billing_start_time = datetime.fromisoformat(billing_start_str.split('.')[0])
                        else:
                            billing_start_time = datetime.fromisoformat(billing_start_str.replace('+00:00', ''))
                        
                        # 计算从账单开始日期到现在过了多少天
                        now = datetime.now()
                        days_since_start = (now - billing_start_time).days
                        
                        # Pro7天周期：账单开始日期 = 7天，过1天 = 6天...
                        days_remaining = 7 - days_since_start
                        
                        return days_remaining  # 可能为负数（已过期）
                        
                except Exception as parse_error:
                    self.logger.warning(f"解析账单开始日期失败 {billing_cycle_start}: {parse_error}")
            
            # 降级到旧逻辑：基于创建时间（兼容旧数据）
            created_at = account.get('created_at') or account.get('register_time')
            if not created_at:
                return None
            
            # 解析创建时间
            try:
                if isinstance(created_at, (int, float)) and created_at > 0:
                    from datetime import timedelta
                    created_time = datetime.fromtimestamp(created_at)
                elif isinstance(created_at, str):
                    if len(created_at) <= 14 and '-' in created_at[:5]:
                        current_year = datetime.now().year
                        created_at = f"{current_year}-{created_at}"
                    
                    if len(created_at) >= 16:
                        created_time = datetime.strptime(created_at[:16], '%Y-%m-%d %H:%M')
                    else:
                        return None
                else:
                    return None
            except Exception as parse_error:
                self.logger.warning(f"时间解析失败 {created_at}: {parse_error}")
                return None
            
            # 使用创建时间 + 14天计算（旧逻辑）
            from datetime import timedelta
            expiry_time = created_time + timedelta(days=14)
            now = datetime.now()
            days_remaining = (expiry_time - now).days + 1
            
            return days_remaining
            
        except Exception as e:
            self.logger.warning(f"计算Pro剩余天数失败: {e}")
            return None
    
    def create_subscription_status(self, row: int, account: dict):
        """创建订阅状态 - 恢复彩色标签显示"""
        # 🔥 修复：优先使用individualMembershipType，其次才是membershipType
        membership_type = account.get('membershipType', 'free')
        individual_type = account.get('individualMembershipType', '')
        subscription_type = individual_type if individual_type else membership_type
        
        trial_days = account.get('trialDaysRemaining', account.get('daysRemainingOnTrial', 0))
        has_subscription_data = account.get('subscriptionUpdatedAt', 0) > 0
        
        # 🔥 修复：先判断具体订阅类型，再判断试用天数（避免拦截Ultra/Pro）
        if subscription_type.lower() in ['pro', 'professional']:
            # 计算Pro剩余天数
            pro_days_remaining = self._calculate_pro_remaining_days(account)
            
            if has_subscription_data:
                # Pro始终显示剩余天数（包括负数和0）
                if pro_days_remaining is not None:
                    text = f"Pro{pro_days_remaining}天"
                    # 根据剩余天数设置颜色
                    if pro_days_remaining > 7:
                        color = "#28a745"  # 绿色：>7天
                    elif pro_days_remaining > 3:
                        color = "#ffc107"  # 黄色：4-7天
                    elif pro_days_remaining > 0:
                        color = "#dc3545"  # 红色：1-3天
                    else:
                        color = "#6c757d"  # 灰色：≤0天（已过期）
                    trial_days = pro_days_remaining if pro_days_remaining > 0 else 0
                else:
                    # 无法计算剩余天数
                    text = "Pro"
                    color = "#28a745"
                    trial_days = 9999
            else:
                text = "Pro(需刷新)"
                color = "#ffc107"
                # 需刷新的Pro也设为9999，排在已知天数的Pro前面
                trial_days = 9999
        elif subscription_type.lower() == 'ultra':
            # Ultra订阅：显示剩余天数
            if has_subscription_data:
                if trial_days and trial_days > 0:
                    text = f"Ultra{trial_days}天"
                    # 根据剩余天数设置颜色
                    if trial_days > 7:
                        color = "#9c27b0"  # 紫色：>7天
                    elif trial_days > 3:
                        color = "#ffc107"  # 黄色：4-7天
                    else:
                        color = "#dc3545"  # 红色：≤3天
                else:
                    text = "Ultra"
                    color = "#9c27b0"  # 紫色
            else:
                text = "Ultra(需刷新)"
                color = "#ffc107"
        elif subscription_type.lower() in ['hobby']:
            if has_subscription_data:
                text = "Hobby"
                color = "#17a2b8"  # 蓝色
            else:
                text = "Hobby(需刷新)"
                color = "#ffc107"
        elif subscription_type.lower() in ['free_trial', 'trial']:
            # 试用版：显示剩余天数
            if has_subscription_data:
                if trial_days and trial_days > 0:
                    text = f"试用{trial_days}天"
                    color = "#28a745" if trial_days > 7 else "#ffc107" if trial_days > 3 else "#dc3545"
                else:
                    text = "试用版"
                    color = "#17a2b8"
            else:
                text = "试用版(需刷新)"
                color = "#ffc107"
        elif subscription_type.lower() in ['free', 'basic']:
            if has_subscription_data:
                text = "免费版" 
                color = "#6c757d"
            else:
                text = "免费版(需刷新)"
                color = "#ffc107"
        elif subscription_type in ['灭活', 'inactive', 'deactivated']:
            # 处理灭活状态
            if has_subscription_data:
                text = "已灭活"
                color = "#dc3545"  # 红色
            else:
                text = "灭活(需刷新)"
                color = "#dc3545"
        elif trial_days and trial_days > 0:
            # 未知订阅类型但有试用天数（兜底判断）
            text = f"试用{trial_days}天"
            color = "#28a745" if trial_days > 7 else "#ffc107" if trial_days > 3 else "#dc3545"
        else:
            # 显示实际的订阅类型，而不是硬编码
            if has_subscription_data:
                # 显示实际的订阅类型，首字母大写
                actual_type = subscription_type.title() if subscription_type else "未知"
                text = actual_type
                color = "#9c27b0"  # 紫色表示未知类型
            else:
                text = f"{subscription_type}(需刷新)" if subscription_type else "未知(需刷新)"
                color = "#dc3545"

        # 创建彩色标签
        status_label = QLabel(text)
        status_label.setStyleSheet(f"""
            QLabel {{
                background: {color};
                color: white;
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 12px;
                font-weight: 500;
            }}
        """)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 创建容器确保居中
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)
        
        if VersionConfig.is_full_version():
            # 先设置一个隐藏的QTableWidgetItem用于排序
            subscription_item = SubscriptionTableWidgetItem(text, subscription_type, trial_days)
            subscription_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.accounts_table.setItem(row, 4, subscription_item)
            # 然后设置显示的widget
            self.accounts_table.setCellWidget(row, 4, container)
    
    def create_remark_display(self, row: int, account: dict):
        """创建备注显示（已隐藏，保留逻辑）"""
        email = account.get('email', '')
        current_remark = self.account_remarks.get(email, "自用")  # 默认为"自用"
        
        remark_label = QLabel(current_remark)
        remark_label.setStyleSheet(f"""
            QLabel {{
                background: {self.remark_colors[current_remark]};
                color: white;
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 12px;
                font-weight: 500;
            }}
        """)
        remark_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        remark_label.setToolTip("双击切换备注")
        
        # 创建可点击的容器
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(remark_label)
        
        # 🔥 修复：移除容器级别的双击事件，避免与表格事件冲突  
        # container.mouseDoubleClickEvent = lambda event: self.toggle_remark(email, row)
        
        # 完整版显示用途
        if VersionConfig.is_full_version():
            self.accounts_table.setCellWidget(row, 5, container)
    
    def toggle_remark(self, email: str, row: int):
        """切换备注类型（已隐藏，保留逻辑）"""
        try:
            current_remark = self.account_remarks.get(email, "自用")
            
            # 找到当前备注在列表中的索引
            current_index = self.remark_types.index(current_remark)
            
            # 切换到下一个备注类型（循环）
            next_index = (current_index + 1) % len(self.remark_types)
            new_remark = self.remark_types[next_index]
            
            # 更新存储
            self.account_remarks[email] = new_remark
            
            # 立即保存到文件实现持久化
            self.config.save_remarks(self.account_remarks)
            
            # 完整版更新UI显示
            if VersionConfig.is_full_version():
                # 🔥 修复：更新表格中的备注显示，确保列索引正确
                remark_column = 5  # 用途固定在第5列
                container = self.accounts_table.cellWidget(row, remark_column)
                if container:
                    label = container.findChild(QLabel)
                    if label:
                        label.setText(new_remark)
                        label.setStyleSheet(f"""
                            QLabel {{
                                background: {self.remark_colors[new_remark]};
                                color: white;
                                border-radius: 10px;
                                padding: 3px 12px;
                                font-size: 11px;
                                font-weight: 500;
                            }}
                        """)
                        
                        self.logger.info(f"✅ 更新备注显示: {email} -> {new_remark} (列{remark_column})")
            
            self.logger.info(f"账号 {email} 备注已切换为: {new_remark}，已保存到文件")
            
        except Exception as e:
            self.logger.error(f"切换备注失败: {str(e)}")
            
    
            
    def create_switch_button(self, row: int, account: dict):
        """创建切换账号按钮"""
        # 创建容器来确保居中对齐
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        account_email = account.get('email', '')
        
        # 使用cursor_manager检测真实的当前账号
        is_current = False
        try:
            current_account = self.cursor_manager.get_current_account()
            if current_account and current_account.get('is_logged_in'):
                current_email = current_account.get('email', '')
                is_current = (current_email == account_email)
        except Exception as e:
            is_current = False
        
        if is_current:
            # 当前账号使用不同的图标和样式
            btn = QPushButton("★")  # 使用红色五角星表示当前账号
            btn.setToolTip("⭐ 当前正在使用的账号")
            btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    border-radius: 12px;
                    padding: 0px;
                    font-size: 16px;
                    width: 24px;
                    height: 24px;
                    min-width: 24px;
                    max-width: 24px;
                    min-height: 24px;
                    max-height: 24px;
                    background: transparent;
                    color: #dc3545;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(220, 53, 69, 0.1);
                }
                QPushButton:pressed {
                    background: rgba(220, 53, 69, 0.2);
                }
            """)
        else:
            # 其他账号使用切换图标
            btn = QPushButton("🔄")  # 使用切换图标
            btn.setToolTip("🔄 切换到此账号")
            btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    border-radius: 12px;
                    padding: 0px;
                    font-size: 14px;
                    width: 24px;
                    height: 24px;
                    min-width: 24px;
                    max-width: 24px;
                    min-height: 24px;
                    max-height: 24px;
                    background: #6c757d;
                    color: white;
                    text-align: center;
                }
                QPushButton:hover {
                    background: #5a6268;
                }
                QPushButton:pressed {
                    background: #545b62;
                }
            """)
        
        # 使用邮箱作为唯一标识，避免闭包问题
        email = account.get('email', '')
        if not email:
            self.logger.warning(f"⚠️ 第{row}行账号邮箱为空！")
        btn.clicked.connect(lambda checked=False, e=email: self._handle_switch_click(e))
        layout.addWidget(btn)
        # 根据版本设置列位置
        col = 8 if VersionConfig.is_full_version() else 6
        self.accounts_table.setCellWidget(row, col, container)
    
    def _handle_switch_click(self, email: str):
        """处理切换按钮点击 - 通过邮箱查找账号"""
        try:
            self.logger.info(f"🔄 切换按钮点击，邮箱: {email}")
            
            # 从配置中获取最新的账号信息
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email') == email:
                    account = acc
                    break
            
            if not account:
                self.logger.error(f"❌ 未找到账号: {email}")
                self.status_message.emit(f"❌ 未找到账号: {email}")
                return
            
            # 切换账号
            self.switch_account(account)
        except Exception as e:
            self.logger.error(f"处理切换按钮点击失败: {str(e)}")
            self.status_message.emit(f"❌ 切换账号失败: {str(e)}")
    
    def create_homepage_button(self, row: int, account: dict):
        """创建打开主页按钮"""
        # 创建容器来确保居中对齐
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn = QPushButton("🏠")
        btn.setToolTip("打开Cursor主页")
        btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 12px;
                padding: 0px;
                font-size: 14px;
                width: 24px;
                height: 24px;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: #007bff;
                color: white;
                text-align: center;
            }
            QPushButton:hover {
                background: #0056b3;
            }
            QPushButton:pressed {
                background: #004085;
            }
        """)
        # 使用邮箱作为唯一标识，避免闭包问题
        email = account.get('email', '')
        btn.clicked.connect(lambda checked=False, e=email: self._handle_homepage_click(e))
        layout.addWidget(btn)
        # 根据版本设置列位置
        col = 9 if VersionConfig.is_full_version() else 7
        self.accounts_table.setCellWidget(row, col, container)
    
    def _handle_homepage_click(self, email: str):
        """处理主页按钮点击 - 通过邮箱查找账号"""
        try:
            self.logger.info(f"🏠 主页按钮点击，邮箱: {email}")
            
            # 从配置中获取最新的账号信息
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email') == email:
                    account = acc
                    break
            
            if not account:
                self.logger.error(f"❌ 未找到账号: {email}")
                self.status_message.emit(f"❌ 未找到账号: {email}")
                return
            
            # 打开主页
            self.open_homepage(account)
        except Exception as e:
            self.logger.error(f"处理主页按钮点击失败: {str(e)}")
            self.status_message.emit(f"❌ 打开主页失败: {str(e)}")
    
    def create_details_button(self, row: int, account: dict):
        """创建账号详情按钮"""
        # 创建容器来确保居中对齐
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn = QPushButton("📋")
        btn.setToolTip("查看账号详情")
        btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 12px;
                padding: 0px;
                font-size: 14px;
                width: 24px;
                height: 24px;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: #6c757d;
                color: white;
                text-align: center;
            }
            QPushButton:hover {
                background: #545b62;
            }
            QPushButton:pressed {
                background: #495057;
            }
        """)
        # 使用邮箱作为唯一标识，避免闭包问题
        email = account.get('email', '')
        btn.clicked.connect(lambda checked=False, e=email: self._handle_details_click(e))
        layout.addWidget(btn)
        # 根据版本设置列位置
        col = 10 if VersionConfig.is_full_version() else 8
        self.accounts_table.setCellWidget(row, col, container)
    
    def _handle_details_click(self, email: str):
        """处理详情按钮点击 - 通过邮箱查找账号"""
        try:
            self.logger.info(f"📋 详情按钮点击，邮箱: {email}")
            
            # 从配置中获取最新的账号信息
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email') == email:
                    account = acc
                    break
            
            if not account:
                self.logger.error(f"❌ 未找到账号: {email}")
                self.status_message.emit(f"❌ 未找到账号: {email}")
                return
            
            # 显示详情
            self.show_account_details(account)
        except Exception as e:
            self.logger.error(f"处理详情按钮点击失败: {str(e)}")
            self.status_message.emit(f"❌ 显示详情失败: {str(e)}")
        
    
    def show_welcome_message(self):
        """显示欢迎信息"""
        # 确保表格完全清理后再设置欢迎信息
        self.accounts_table.clearContents()
        self.accounts_table.clearSpans()  # 清理之前的跨列设置
        self.accounts_table.setRowCount(1)
        
        # 创建欢迎信息容器 - 可点击样式
        welcome_widget = QWidget()
        welcome_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8f9fa, stop: 1 #e9ecef);
                border: 2px dashed #007bff;
                border-radius: 12px;
                margin: 10px;
            }
            QWidget:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #e3f2fd, stop: 1 #bbdefb);
                border-color: #0056b3;
            }
        """)
        welcome_widget.setCursor(Qt.CursorShape.PointingHandCursor)  # 设置手形光标
        
        # 添加点击事件 - 点击时导入Token
        welcome_widget.mousePressEvent = lambda event: self.trigger_import_accounts()
        
        welcome_layout = QVBoxLayout(welcome_widget)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.setContentsMargins(40, 30, 40, 30)
        
        # 主标题
        welcome_label = QLabel("🎉 欢迎使用 MY Cursor")
        welcome_label.setStyleSheet("""
            QLabel {
                color: #007bff;
                font-size: 20px;
                font-weight: bold;
                margin: 0;
                background: transparent;
                border: none;
            }
        """)
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(welcome_label)
        
        # 副标题 - 简化为一行文字
        subtitle_label = QLabel("点击可快速导入账号")
        subtitle_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 16px;
                font-weight: 500;
                margin-top: 8px;
                background: transparent;
                border: none;
            }
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(subtitle_label)
        
        # 设置欢迎组件到表格
        self.accounts_table.setCellWidget(0, 0, welcome_widget)
        
        # 动态跨越所有列 - 完整版10列，精简版8列
        total_columns = 10 if VersionConfig.is_full_version() else 8
        self.accounts_table.setSpan(0, 0, 1, total_columns)
        
        # 设置行高适应内容
        self.accounts_table.setRowHeight(0, 150)
    
    def trigger_import_accounts(self):
        """触发导入账号功能"""
        try:
            # 向上查找主窗口
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'show_unified_import_dialog'):
                main_window = main_window.parent()
            
            if main_window and hasattr(main_window, 'show_unified_import_dialog'):
                # 调用三标签页导入对话框
                main_window.show_unified_import_dialog()
                self.logger.info("🎯 通过欢迎界面触发三标签页导入对话框")
            elif hasattr(self.parent(), 'show_import_dialog'):
                self.parent().show_import_dialog() 
                self.logger.info("🎯 通过欢迎界面显示导入对话框")
            else:
                # 发出状态消息提示用户
                self.status_message.emit("💡 请使用主窗口上方的'导入/导出'按钮导入账号")
                self.logger.info("🎯 欢迎界面点击 - 提示用户使用导入功能")
        except Exception as e:
            self.logger.error(f"触发导入账号功能失败: {str(e)}")
            self.status_message.emit("⚠️ 导入功能暂不可用，请使用主窗口导入按钮")
        
    # ==================== 事件处理 ====================
    
    def handle_cell_click(self, row: int, column: int):
        """处理单击事件 - 支持切换、主页、详情列的整个单元格点击"""
        try:
            # 检测修饰键状态 - 如果按住Shift/Ctrl，优先让默认选择行为生效
            from PyQt6.QtWidgets import QApplication
            modifiers = QApplication.keyboardModifiers()
            from PyQt6.QtCore import Qt
            
            if modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                return  # 让默认的区间选择行为生效
            
            # 🔍 调试日志
            self.logger.info(f"🖱️ 单击事件: row={row}, column={column}")
            
            # 🔥 修复：从表格的邮箱列获取邮箱，确保数据映射正确
            email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
            if not email_item:
                self.logger.warning(f"⚠️ 无法获取第{row}行的邮箱数据")
                return
            
            email = email_item.text()
            self.logger.info(f"📧 从表格获取邮箱: {email}")
            
            # 🔥 优化：直接通过邮箱查找账号（表格支持排序，行索引不可靠）
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email', '') == email:
                    account = acc
                    break
            
            if not account:
                self.logger.error(f"❌ 找不到邮箱对应的账号: {email}")
                return
            
            # 🔍 调试日志：显示当前操作的账号
            self.logger.info(f"🎯 单击操作账号: {email}")
            
            # 根据版本类型确定正确的列位置
            if VersionConfig.is_full_version():
                # 完整版：切换=8，主页=9，详情=10
                if column == 8:  # 切换列
                    self.logger.info(f"🔄 触发切换账号: {email}")
                    self.switch_account(account)
                elif column == 9:  # 主页列
                    self.logger.info(f"🏠 触发打开主页: {email}")
                    self.open_homepage(account)
                elif column == 10:  # 详情列
                    self.logger.info(f"📋 触发查看详情: {email}")
                    self.show_account_details(account)
            else:
                # 精简版：切换=6，主页=7，详情=8
                if column == 6:  # 切换列
                    self.logger.info(f"🔄 触发切换账号: {email}")
                    self.switch_account(account)
                elif column == 7:  # 主页列
                    self.logger.info(f"🏠 触发打开主页: {email}")
                    self.open_homepage(account)
                elif column == 8:  # 详情列
                    self.logger.info(f"📋 触发查看详情: {email}")
                    self.show_account_details(account)
                
        except Exception as e:
            self.logger.error(f"处理单击事件失败: {str(e)}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
    
    def handle_cell_double_click(self, row: int, column: int):
        """处理双击事件 - 修复排序后的列索引错位问题"""
        try:
            # 🔍 添加调试日志查看双击事件
            self.logger.info(f"🖱️ 双击事件: row={row}, column={column}")
            
            
            # 🔥 修复：从表格的邮箱列获取邮箱，而不是使用行索引
            email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
            if not email_item:
                self.logger.warning(f"⚠️ 无法获取第{row}行的邮箱数据")
                return
            
            email = email_item.text()
            self.logger.info(f"📧 从表格获取邮箱: {email}")
            
            # 通过邮箱查找对应的账号数据
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email', '') == email:
                    account = acc
                    break
            
            if not account:
                self.logger.warning(f"⚠️ 找不到邮箱对应的账号: {email}")
                return
            
            # 🔍 调试日志：显示当前操作的账号
            self.logger.info(f"🎯 双击操作账号: {email}")
            
            if column == 2:  # 邮箱列
                # 双击邮箱时选中行并勾选复选框，支持Shift区间选择
                from PyQt6.QtWidgets import QApplication
                modifiers = QApplication.keyboardModifiers()
                from PyQt6.QtCore import Qt
                
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    # Shift + 双击：区间选择复选框（优化版 - 使用缓存的最后选中行）
                    if self._last_checked_row is not None:
                        # 区间勾选复选框
                        start_row = min(self._last_checked_row, row)
                        end_row = max(self._last_checked_row, row)
                        
                        selected_count = 0
                        for r in range(start_row, end_row + 1):
                            checkbox = self.accounts_table.cellWidget(r, 0)
                            if checkbox and isinstance(checkbox, QCheckBox):
                                checkbox.setChecked(True)
                                selected_count += 1
                                # 同时选中表格行
                                self.accounts_table.selectRow(r)
                        
                        # 更新最后选中的行
                        self._last_checked_row = row
                        self.logger.info(f"✅ 区间选择复选框: 第{start_row+1}行到第{end_row+1}行 (共{selected_count}个)")
                    else:
                        # 没有之前勾选的，直接勾选当前行
                        checkbox = self.accounts_table.cellWidget(row, 0)
                        if checkbox and isinstance(checkbox, QCheckBox):
                            checkbox.setChecked(True)
                            self._last_checked_row = row  # 记录这次勾选的行
                            self.accounts_table.selectRow(row)
                            self.logger.info(f"✅ 勾选复选框: 第{row+1}行 ({email})")
                else:
                    # 普通双击：勾选复选框并选中行
                    checkbox = self.accounts_table.cellWidget(row, 0)
                    if checkbox and isinstance(checkbox, QCheckBox):
                        # 切换复选框状态
                        current_state = checkbox.isChecked()
                        checkbox.setChecked(not current_state)
                        # 如果勾选了，记录这个行号供下次Shift选择使用
                        if not current_state:  # 变为勾选状态
                            self._last_checked_row = row
                        self.accounts_table.selectRow(row)
                        self.logger.info(f"✅ 切换复选框: 第{row+1}行 ({email}) -> {'勾选' if not current_state else '取消勾选'}")
            elif VersionConfig.is_full_version():
                # 完整版的双击事件：订阅状态(4), 用途(5), 用量(6), 备注(7)
                if column == 4:  # 订阅状态列 - 不处理双击
                    self.logger.info(f"🔍 双击订阅状态列，无操作")
                elif column == 5:  # 用途列  
                    self.logger.info(f"📝 双击用途列: {email}")
                    self.toggle_remark(email, row)
                elif column == 7:  # 备注列 - 聚焦输入框
                    self.logger.info(f"📝 双击备注列: {email}")
                    widget = self.accounts_table.cellWidget(row, column)
                    if widget and isinstance(widget, QLineEdit):
                        widget.setFocus()
                        widget.selectAll()
                else:
                    self.logger.info(f"🔍 双击列{column}，无特殊处理")
            else:
                # 精简版的双击事件：用量(4), 备注(5)
                if column == 5:  # 备注列 - 聚焦输入框
                    self.logger.info(f"📝 双击备注列: {email}")
                    widget = self.accounts_table.cellWidget(row, column)
                    if widget and isinstance(widget, QLineEdit):
                        widget.setFocus()
                        widget.selectAll()
                else:
                    self.logger.info(f"🔍 双击列{column}，无特殊处理")
        except Exception as e:
            self.logger.error(f"处理双击事件失败: {str(e)}")
    
    def _on_native_sort(self, logical_index: int, order: Qt.SortOrder):
        """处理Qt原生排序信号 - 重置Shift选择缓存"""
        try:
            # Qt原生排序不会调用我们的display_accounts，需要手动重置缓存
            self._last_checked_row = None
            self.logger.debug(f"📊 Qt原生排序触发 - 列{logical_index}，已重置Shift选择缓存")
        except Exception as e:
            self.logger.error(f"处理原生排序信号失败: {str(e)}")
    
    def on_header_double_clicked(self, logical_index: int):
        """处理表头双击事件 - 实现二级排序功能"""
        try:
            # 防抖：如果正在排序，忽略新的点击
            if self._is_sorting:
                self.logger.debug("⏸️ 排序进行中，忽略重复点击")
                return
            
            # 只对创建时间列(3)和订阅状态列(4)启用排序
            if logical_index == 3 or (VersionConfig.is_full_version() and logical_index == 4):
                # 设置排序标志
                self._is_sorting = True
                
                try:
                    # 确定排序顺序
                    if self.current_sort_column == logical_index:
                        # 如果是同一列，切换排序顺序
                        if self.current_sort_order == Qt.SortOrder.AscendingOrder:
                            self.current_sort_order = Qt.SortOrder.DescendingOrder
                        else:
                            self.current_sort_order = Qt.SortOrder.AscendingOrder
                    else:
                        # 新列，默认升序
                        self.current_sort_column = logical_index
                        self.current_sort_order = Qt.SortOrder.AscendingOrder
                    
                    # 调试日志：显示排序参数
                    column_name = "创建时间" if logical_index == 3 else "订阅状态"
                    secondary_sort = "订阅状态" if logical_index == 3 else "创建时间"
                    order_text = "升序" if self.current_sort_order == Qt.SortOrder.AscendingOrder else "降序"
                    self.logger.info(f"📊 执行二级排序: 主排序={column_name}({order_text}), 次排序={secondary_sort}")
                    
                    # 优化：优先使用已加载的账号数据，避免重复I/O操作
                    if self.current_displayed_accounts:
                        accounts = self.current_displayed_accounts
                        self.logger.debug("⚡ 使用已加载的账号数据进行排序")
                    else:
                        accounts = self.config.load_accounts()
                        self.logger.debug("💾 从磁盘加载账号数据")
                    
                    # 执行二级排序
                    sorted_accounts = self._sort_accounts_with_secondary(accounts, logical_index, self.current_sort_order)
                    
                    # 保存排序后的账号列表
                    self.current_displayed_accounts = sorted_accounts.copy()
                    self.logger.info(f"📋 手动排序后更新显示列表，共 {len(self.current_displayed_accounts)} 个账号")
                    
                    # 重新显示排序后的账号
                    self.display_accounts(sorted_accounts)
                    
                    self.logger.info(f"✅ 排序完成: {column_name}{order_text} + {secondary_sort}次排序")
                    
                finally:
                    # 确保标志位被重置
                    self._is_sorting = False
                
        except Exception as e:
            self._is_sorting = False  # 出错时也要重置标志位
            logging.error(f"处理表头双击事件时出错: {str(e)}")
            QMessageBox.warning(self, "错误", f"排序时出错: {str(e)}")
    
    def _sort_accounts_with_secondary(self, accounts, primary_column, primary_order):
        """执行二级排序
        - 订阅状态列排序时，次排序按创建时间
        - 创建时间列排序时，次排序按订阅状态
        """
        from datetime import datetime
        
        def get_sort_key(account):
            # 准备创建时间键
            created_at_str = account.get('created_at', account.get('createdAt', ''))
            try:
                if created_at_str:
                    # 尝试多种日期格式解析
                    try:
                        # ISO格式：2024-09-17T10:39:00
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    except:
                        try:
                            # 完整格式：2024-09-17 10:39
                            created_at = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M')
                        except:
                            try:
                                # 短格式：09-17 10:39 (假定为当前年份)
                                current_year = datetime.now().year
                                created_at = datetime.strptime(f"{current_year}-{created_at_str}", '%Y-%m-%d %H:%M')
                            except:
                                # 其他格式失败，使用最小值
                                created_at = datetime.min
                else:
                    created_at = datetime.min
            except:
                created_at = datetime.min
            
            # 准备订阅状态键
            membership_type = account.get('membershipType', 'free').lower()
            trial_days = account.get('trialDaysRemaining', account.get('daysRemainingOnTrial', 0))
            
            # 定义优先级（数字越小优先级越高）：Pro > 试用 > 免费版 > Hobby
            if 'pro' in membership_type or 'professional' in membership_type:
                subscription_priority = 1  # Pro最高优先级
            elif trial_days > 0:
                subscription_priority = 2  # 试用第二优先级
            elif 'hobby' in membership_type:
                subscription_priority = 4  # Hobby最低优先级
            else:  # free
                subscription_priority = 3  # 免费版第三优先级
            
            # 根据主排序列决定排序键
            if primary_column == 3:  # 创建时间列排序
                # 主排序：创建时间，次排序：订阅状态
                if primary_order == Qt.SortOrder.DescendingOrder:
                    # 降序：时间大的在前
                    return (-created_at.timestamp() if created_at != datetime.min else float('inf'), subscription_priority)
                else:
                    # 升序：时间小的在前
                    return (created_at.timestamp() if created_at != datetime.min else float('inf'), subscription_priority)
                    
            elif primary_column == 4:  # 订阅状态列排序
                # 主排序：订阅状态，次排序：创建时间
                if primary_order == Qt.SortOrder.DescendingOrder:
                    # 降序：优先级大的在前（即数字小的在前，所以取反）
                    return (-subscription_priority, created_at.timestamp() if created_at != datetime.min else float('inf'))
                else:
                    # 升序：优先级小的在前
                    return (subscription_priority, created_at.timestamp() if created_at != datetime.min else float('inf'))
            else:
                # 其他列，按创建时间排序
                return (created_at.timestamp() if created_at != datetime.min else float('inf'), subscription_priority)
        
        # 执行排序
        sorted_accounts = sorted(accounts, key=get_sort_key)
        
        return sorted_accounts
                
    def cycle_account_tag(self, email: str, row: int):
        """循环切换状态标记：自用 -> 商用 -> 用尽 -> 自用"""
        try:
            current_tags = self.tag_manager.get_account_tags(email)
            
            # 🔥 修复：添加商用到标记循环中
            tag_cycle = [None, 'commercial', 'exhausted']
            tag_names = ['自用', '商用', '用尽']
            
            current_index = 0  # 默认是自用(无标记)
            if current_tags:
                tag_id = current_tags[0].tag_id  # 使用tag_id而不是id
                if tag_id == 'commercial':
                    current_index = 1
                elif tag_id == 'exhausted':
                    current_index = 2
            
            # 下一个标记（只在两个状态间切换）
            next_index = (current_index + 1) % len(tag_cycle)
            next_tag_id = tag_cycle[next_index]
            next_tag_name = tag_names[next_index]
            
            # 应用新标记
            if next_tag_id:
                self.tag_manager.set_account_tags(email, [next_tag_id])
            else:
                # 设置为自用（清空标记）
                self.tag_manager.set_account_tags(email, [])
            
            # 更新UI显示
            self.update_tag_display(row, email, next_tag_name, next_tag_id)
            
            self.status_message.emit(f"状态标记已切换为: {next_tag_name}")
            self.logger.info(f"账号 {email} 状态标记已切换为: {next_tag_name}")
            
        except Exception as e:
            self.logger.error(f"切换状态标记失败: {str(e)}")
    
    def update_tag_display(self, row: int, email: str, tag_name: str, tag_id: str):
        """更新状态标记的UI显示 - 修复列索引错位问题"""
        try:
            # 🔥 修复：根据版本确定正确的列索引
            if VersionConfig.is_full_version():
                tag_column = 5  # 完整版：试用标记在第5列
            else:
                tag_column = 4  # 精简版：试用标记在第4列
            
            container = self.accounts_table.cellWidget(row, tag_column)
            if container:
                label = container.findChild(QLabel)
                if label:
                    # 根据标记类型设置颜色
                    if tag_id == "exhausted":
                        color = "#f56c6c"  # 红色 - 用尽
                    elif tag_id == "commercial":
                        color = "#409eff"  # 🔥 新增：蓝色 - 商用
                    else:
                        color = "#28a745"  # 绿色 - 自用
                    
                    label.setText(tag_name)
                    label.setStyleSheet(f"""
                        QLabel {{
                            background: {color};
                            color: white;
                            border-radius: 10px;
                            padding: 3px 8px;
                            font-size: 11px;
                            font-weight: 500;
                        }}
                    """)
                    
                    self.logger.info(f"✅ 更新标记显示: {email} -> {tag_name} (列{tag_column})")
        except Exception as e:
            self.logger.error(f"更新标记显示失败: {str(e)}")
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        row = self.accounts_table.rowAt(position.y())
        if row < 0:
            return
            
        try:
            # 🔧 修复：直接从表格中获取邮箱信息，确保与显示的数据一致
            email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
            if not email_item:
                return
            email = email_item.text()
            
            # 从配置中找到对应的完整账号信息（用于获取token等其他信息）
            accounts = self.config.load_accounts()
            account = None
            for acc in accounts:
                if acc.get('email', '') == email:
                    account = acc
                    break
            
            if not account:
                return
            
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu {
                    background-color: white;
                    border: 2px solid #e0e0e0;
                    border-radius: 10px;
                    padding: 8px 4px;
                    font-size: 14px;
                    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
                }
                QMenu::item {
                    padding: 10px 20px;
                    margin: 2px 6px;
                    border-radius: 6px;
                    color: #333333;
                    font-weight: 500;
                }
                QMenu::item:selected {
                    background-color: #e3f2fd;
                    color: #1976D2;
                }
                QMenu::separator {
                    height: 1px;
                    background: #e9ecef;
                    margin: 6px 12px;
                }
            """)
            
            # 菜单项 - 智能复制邮箱或账号密码
            password = account.get('password', '')
            if password:
                # 有密码：复制邮箱和密码（换行格式）
                copy_email = QAction("📧 复制账密", self)
                copy_email.triggered.connect(lambda: self.copy_to_clipboard(f"{email}\n{password}"))
            else:
                # 无密码：只复制邮箱
                copy_email = QAction("📧 复制邮箱", self)
                copy_email.triggered.connect(lambda: self.copy_to_clipboard(email))
            menu.addAction(copy_email)
            
            # 🔧 修复：优先复制URL格式的WorkosCursorSessionToken（user_xxxx::JWT），其次是JWT格式的access_token
            workos_token = account.get('WorkosCursorSessionToken', '')
            access_token = account.get('access_token', '')
            
            if workos_token:
                copy_token = QAction("🔑 复制Token ", self)
                copy_token.triggered.connect(lambda: self.copy_to_clipboard(workos_token))
                menu.addAction(copy_token)
            elif access_token:
                copy_token = QAction("🔑 复制Token", self)
                copy_token.triggered.connect(lambda: self.copy_to_clipboard(access_token))
                menu.addAction(copy_token)
            
            menu.addSeparator()
            
            # 刷新该账号订阅
            refresh_subscription = QAction("⚡ 快速刷新", self)
            refresh_subscription.triggered.connect(lambda: self.refresh_single_account_subscription(account))
            menu.addAction(refresh_subscription)
            
            
            menu.addSeparator()
            
            # 删除账号选项
            delete_account = QAction("🗑️ 删除账号", self)
            delete_account.triggered.connect(lambda: self.delete_single_account(account))
            menu.addAction(delete_account)
            
            menu.exec(self.accounts_table.mapToGlobal(position))
            
        except Exception as e:
            self.logger.error(f"显示右键菜单失败: {str(e)}")
    
    # ==================== 按钮事件 ====================
    
    
    def select_all_accounts(self):
        """智能全选：无选中时全选，有选中时取消全选"""
        # 检查是否有任何账号被选中
        has_checked = False
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox):
                if checkbox.isChecked():
                    has_checked = True
                    break
        
        # 如果有选中，则取消全选；如果无选中，则全选
        new_state = not has_checked
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox):
                checkbox.setChecked(new_state)
        
        # 更新选中数量显示
        self.update_selected_count()
        self.status_message.emit("✅ 已全选" if new_state else "❌ 已取消全选")
    
    def delete_single_account(self, account):
        """删除单个账号 - 从右键菜单调用"""
        try:
            email = account.get('email', '未知')
            
            # 显示删除确认对话框
            if self._show_delete_confirmation(1):
                if self.config.remove_account(email):
                    # 🔥 优化：直接删除对应行，避免重新加载所有账号
                    self._remove_account_from_table(email)
                    self.status_message.emit(f"✅ 成功删除账号: {email}")
                else:
                    self.status_message.emit(f"❌ 删除账号失败: {email}")
                    
        except Exception as e:
            self.logger.error(f"删除账号失败: {str(e)}")
            self.status_message.emit(f"❌ 删除失败: {str(e)}")
    
    def delete_selected_accounts(self):
        """删除选中账号"""
        selected_emails = []
        
        # 获取选中账号
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                email_item = self.accounts_table.item(row, 2)
                if email_item:
                    selected_emails.append(email_item.text())
        
        if not selected_emails:
            self._show_simple_message("请先选择要删除的账号")
            return
        
        # 显示删除确认对话框
        if self._show_delete_confirmation(len(selected_emails)):
            try:
                # 批量删除（只保存一次文件）
                accounts = self.config.load_accounts()
                original_count = len(accounts)
                
                # 过滤掉所有选中的账号
                accounts = [acc for acc in accounts if acc.get('email') not in selected_emails]
                
                # 只保存一次
                self.config.save_accounts(accounts, allow_empty=True)
                
                deleted_count = original_count - len(accounts)
                self.load_accounts()
                self.status_message.emit(f"✅ 成功删除 {deleted_count} 个账号")
                    
            except Exception as e:
                # 创建自定义样式的错误框
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Critical)
                msgbox.setWindowTitle("错误")
                msgbox.setText(f"删除失败: {str(e)}")
                self._apply_msgbox_style(msgbox)
                msgbox.exec()
    
    def toggle_refresh_subscriptions(self):
        """切换刷新状态（开始/停止）"""
        # 检查是否正在刷新
        if self.refresh_thread and self.refresh_thread.isRunning():
            # 正在刷新，点击停止
            self.stop_refresh()
        else:
            # 未在刷新，点击开始
            self.smart_refresh_subscriptions()
    
    def stop_refresh(self):
        """停止刷新"""
        if self.refresh_thread and self.refresh_thread.isRunning():
            self.refresh_thread.stop()
            self.status_message.emit("🛑 正在停止刷新...")
            self.logger.info("🛑 用户请求停止刷新")
            
            # 恢复按钮文字
            if hasattr(self, 'refresh_btn'):
                self.refresh_btn.setText("🔄 刷新")
    
    def smart_refresh_subscriptions(self):
        """并发刷新订阅信息 - 默认刷新全部，大幅提升速度"""
        try:
            
            # 获取所有账号，默认刷新全部（并发高效）
            accounts = self.config.load_accounts()
            
            # 检查是否有选中的账号（可选择性刷新）
            selected_accounts = []
            for row in range(self.accounts_table.rowCount()):
                checkbox = self.accounts_table.cellWidget(row, 0)
                if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    # 🔥 修复：从表格中获取邮箱，而不是使用行索引
                    email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
                    if email_item:
                        email = email_item.text()
                        # 通过邮箱查找对应的账号
                        for acc in accounts:
                            if acc.get('email', '') == email:
                                selected_accounts.append(acc)
                                self.logger.info(f"✅ 选中账号: {email}")
                                break
            
            # 优先级：选中账号 > 全部账号
            accounts_to_refresh = selected_accounts if selected_accounts else accounts
            
            if not accounts_to_refresh:
                self.status_message.emit("⚠️ 没有账号需要刷新")
                return
            
            # 🔥 弹出对话框让用户选择失败后的处理方式
            from PyQt6.QtWidgets import QMessageBox
            msgbox = QMessageBox(self)
            msgbox.setWindowTitle("刷新失败处理方式")
            msgbox.setText("请选择刷新失败账号的处理方式：")
            msgbox.setInformativeText("• 标记：创建时间列显示红色标记\n• 删除：从列表中删除失败的账号")
            msgbox.setIcon(QMessageBox.Icon.Question)
            
            # 添加自定义按钮
            mark_btn = msgbox.addButton("🏷️ 标记失败", QMessageBox.ButtonRole.AcceptRole)
            delete_btn = msgbox.addButton("🗑️ 删除失败", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msgbox.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            
            # 应用样式
            self._apply_msgbox_style(msgbox)
            
            # 显示对话框
            msgbox.exec()
            clicked_button = msgbox.clickedButton()
            
            # 用户点击取消
            if clicked_button == cancel_btn:
                self.status_message.emit("已取消刷新操作")
                return
            
            # 保存用户选择
            if clicked_button == delete_btn:
                self._failed_account_action = "delete"
                self.logger.info("用户选择：刷新失败后删除账号")
            else:  # mark_btn
                self._failed_account_action = "mark"
                self.logger.info("用户选择：刷新失败后标记账号")
            
            # 显示刷新类型提示
            if selected_accounts:
                refresh_type = "选中"
                self.logger.info(f"开始并发刷新选中的 {len(accounts_to_refresh)} 个账号")
            else:
                refresh_type = "全部"
                self.logger.info(f"未选中任何账号，开始并发刷新全部 {len(accounts_to_refresh)} 个账号")
            
            # 修改按钮文字为停止
            if hasattr(self, 'refresh_btn'):
                self.refresh_btn.setText("⏹️ 停止刷新")
            
            # 开始高效并发刷新
            self.start_concurrent_refresh(accounts_to_refresh)
                
        except Exception as e:
            self.logger.error(f"并发刷新订阅失败: {str(e)}")
            self.status_message.emit(f"❌ 并发刷新失败: {str(e)}")
    
    def smart_convert_tokens(self):
        """🚀 智能Token转换 - 后台执行，不卡UI"""
        try:
            # 如果已经在转换，则停止当前转换
            if self.conversion_thread and self.conversion_thread.isRunning():
                self.conversion_thread.stop()
                self.conversion_thread.wait(3000)  # 等待3秒
                self.status_message.emit("⏹️ 已停止之前的转换任务")
                return
            
            self.logger.info("开始智能Token转换...")
            
            accounts = self.config.load_accounts()
            if not accounts:
                self.status_message.emit("⚠️ 没有账号数据")
                return
            
            # 获取选中的账号
            selected_accounts = []
            for row in range(self.accounts_table.rowCount()):
                checkbox = self.accounts_table.cellWidget(row, 0)
                if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    # 🔥 修复：从表格中获取邮箱，而不是使用行索引
                    email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
                    if email_item:
                        email = email_item.text()
                        # 通过邮箱查找对应的账号
                        for acc in accounts:
                            if acc.get('email', '') == email:
                                selected_accounts.append(acc)
                                break
            
            # 优先级：选中账号 > 全部账号
            accounts_to_convert = selected_accounts if selected_accounts else accounts
            
            if not accounts_to_convert:
                self.status_message.emit("⚠️ 没有账号需要转换")
                return
            
            # 显示转换类型提示
            if selected_accounts:
                convert_type = "选中"
                self.logger.info(f"开始转换选中的 {len(accounts_to_convert)} 个账号的token")
            else:
                convert_type = "全部"
                self.logger.info(f"未选中任何账号，开始转换全部 {len(accounts_to_convert)} 个账号的token")
            
            # 启动后台转换线程
            self.start_token_conversion(accounts_to_convert)
                
        except Exception as e:
            self.logger.error(f"启动Token转换失败: {str(e)}")
            self.status_message.emit(f"❌ 启动转换失败: {str(e)}")
    
    def start_token_conversion(self, accounts_to_convert):
        """🚀 启动Token转换后台线程"""
        try:
            # 🔥 取消之前的进度条重置定时器（新操作开始）
            if hasattr(self, '_progress_reset_timer') and self._progress_reset_timer:
                self._progress_reset_timer.stop()
                self._progress_reset_timer = None
            
            # 创建Token转换线程
            self.conversion_thread = TokenConversionThread(accounts_to_convert, self.config)
            
            # 连接信号
            self.conversion_thread.progress_updated.connect(self.on_conversion_progress)  # 🔥 连接进度信号
            self.conversion_thread.conversion_completed.connect(self.on_conversion_completed)
            
            total_count = len(accounts_to_convert)
            account_type = "选中" if any(
                (checkbox := self.accounts_table.cellWidget(row, 0)) and isinstance(checkbox, QCheckBox) and checkbox.isChecked()
                for row in range(self.accounts_table.rowCount())
                if (checkbox := self.accounts_table.cellWidget(row, 0)) and isinstance(checkbox, QCheckBox)
            ) else "全部"
            
            self.status_message.emit(f"🔄 开始后台转换 {total_count} 个{account_type}账号的token...")
            
            # 启动线程
            self.conversion_thread.start()
            
        except Exception as e:
            self.logger.error(f"启动Token转换线程失败: {str(e)}")
            self.status_message.emit(f"❌ 启动转换线程失败: {str(e)}")
    
    @pyqtSlot(int, int, int)
    def on_conversion_completed(self, converted: int, failed: int, skipped: int):
        """Token转换完成回调"""
        try:
            # 🔥 显示完成状态，保留1分钟后再重置
            if hasattr(self, 'operation_progress_bar'):
                self.operation_progress_bar.setValue(100)
                total_processed = converted + failed + skipped
                if failed > 0:
                    self.operation_progress_bar.setFormat(f"⚠️ 转换完成 成功{converted} 失败{failed}")
                elif skipped > 0:
                    self.operation_progress_bar.setFormat(f"✅ 转换完成 {converted}个 跳过{skipped}个")
                else:
                    self.operation_progress_bar.setFormat(f"✅ 转换完成 {converted}/{total_processed}")
                
                # 取消之前的定时器（如果存在）
                if hasattr(self, '_progress_reset_timer') and self._progress_reset_timer:
                    self._progress_reset_timer.stop()
                    self._progress_reset_timer = None
                
                # 1分钟后重置进度条
                from PyQt6.QtCore import QTimer
                self._progress_reset_timer = QTimer()
                self._progress_reset_timer.setSingleShot(True)
                self._progress_reset_timer.timeout.connect(self._reset_progress_bar)
                self._progress_reset_timer.start(60000)  # 60秒
            
            total_processed = converted + failed + skipped
            
            if converted > 0:
                # 转换成功，直接刷新表格（转换线程已经修改了内存中的账号数据）
                self.refresh_table()
                
                if skipped > 0:
                    self.status_message.emit(f"✅ 转换完成！成功{converted}个，跳过{skipped}个（已符合要求）")
                else:
                    self.status_message.emit(f"✅ 转换完成！成功转换 {converted} 个账号的token为session类型")
            elif skipped > 0:
                self.status_message.emit(f"✅ 检查完成！跳过 {skipped} 个账号（已符合要求），无需转换")
            else:
                self.status_message.emit(f"⚠️ 转换完成：无成功转换，失败 {failed} 个")
            
            self.logger.info(f"Token转换完成：成功{converted}，失败{failed}，跳过{skipped}")
            
        except Exception as e:
            self.logger.error(f"转换完成处理失败: {str(e)}")
    
    def start_concurrent_refresh(self, accounts_to_refresh):
        """启动并发刷新（专注于订阅状态刷新）"""
        try:
            # 🔥 清空旧的失败标记列表
            self._failed_accounts_to_mark = []
            
            # 🔥 取消之前的进度条重置定时器（新操作开始）
            if hasattr(self, '_progress_reset_timer') and self._progress_reset_timer:
                self._progress_reset_timer.stop()
                self._progress_reset_timer = None
            
            # 🔥 关键安全措施：刷新前先备份账号数据
            self.logger.info("🔄 刷新前备份账号数据...")
            backup_success = self.config.backup_accounts()
            if backup_success:
                self.status_message.emit("💾 已备份账号数据，开始刷新...")
            else:
                self.logger.warning("⚠️ 备份失败，但继续刷新操作")
            
            # 创建并发刷新线程
            self.refresh_thread = ConcurrentRefreshThread(
                self.cursor_manager, 
                accounts_to_refresh, 
                self
            )
            
            # 连接信号
            self.refresh_thread.progress_updated.connect(self.on_refresh_progress)
            self.refresh_thread.refresh_completed.connect(self.on_refresh_completed)
            self.refresh_thread.account_refreshed.connect(self.on_account_refreshed)
            
            # 显示进度信息
            total_count = len(accounts_to_refresh)
            account_type = "选中" if any(
                checkbox.isChecked() for row in range(self.accounts_table.rowCount())
                if (checkbox := self.accounts_table.cellWidget(row, 0)) and isinstance(checkbox, QCheckBox)
            ) else "全部"
            
            self.status_message.emit(f"🚀 开始并发刷新 {total_count} 个{account_type}账号...")
            
            # 启动线程
            self.refresh_thread.start()
            
        except Exception as e:
            self.logger.error(f"启动并发刷新失败: {str(e)}")
            self.status_message.emit(f"❌ 启动刷新失败: {str(e)}")
    
    @pyqtSlot(int, int, int, str)
    def on_refresh_progress(self, success_count, completed, total, current_email):
        """刷新进度更新 - 实时更新进度条，显示成功/总数"""
        try:
            # 更新进度条
            if hasattr(self, 'operation_progress_bar'):
                progress = int((completed / total) * 100) if total > 0 else 0
                self.operation_progress_bar.setMaximum(100)
                self.operation_progress_bar.setValue(progress)
                # 显示成功数/总数 + 进度百分比
                self.operation_progress_bar.setFormat(f"刷新中 成功{success_count}/{total} ({progress}%)")
        except Exception as e:
            self.logger.error(f"更新刷新进度失败: {str(e)}")
    
    @pyqtSlot(int, int, str)
    def on_conversion_progress(self, completed, total, current_email):
        """Token转换进度更新 - 实时更新进度条"""
        try:
            # 更新进度条
            if hasattr(self, 'operation_progress_bar'):
                progress = int((completed / total) * 100) if total > 0 else 0
                self.operation_progress_bar.setMaximum(100)
                self.operation_progress_bar.setValue(progress)
                self.operation_progress_bar.setFormat(f"转换Token {completed}/{total} ({progress}%)")
        except Exception as e:
            self.logger.error(f"更新转换进度失败: {str(e)}")
    
    @pyqtSlot(int, int, list)
    def on_refresh_completed(self, success_count, total_count, failed_accounts=None):
        """刷新完成处理 - 智能更新UI（批量刷新=全量，单账号=增量）"""
        # 恢复按钮文字
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setText("🔄 刷新")
        
        # 🔥 显示完成状态，保留1分钟后再重置
        if hasattr(self, 'operation_progress_bar'):
            self.operation_progress_bar.setValue(100)
            failed_count = len(failed_accounts) if failed_accounts else 0
            if success_count == total_count:
                self.operation_progress_bar.setFormat(f"✅ 刷新完成 {success_count}/{total_count}")
            else:
                self.operation_progress_bar.setFormat(f"⚠️ 完成 成功{success_count}/{total_count} 失败{failed_count}")
            
            # 取消之前的定时器（如果存在）
            if hasattr(self, '_progress_reset_timer') and self._progress_reset_timer:
                self._progress_reset_timer.stop()
                self._progress_reset_timer = None
            
            # 1分钟后重置进度条
            from PyQt6.QtCore import QTimer
            self._progress_reset_timer = QTimer()
            self._progress_reset_timer.setSingleShot(True)
            self._progress_reset_timer.timeout.connect(self._reset_progress_bar)
            self._progress_reset_timer.start(60000)  # 60秒
        
        # 保存失败账号列表，用于后续标记
        if failed_accounts is None:
            failed_accounts = []
        self._failed_accounts_to_mark = failed_accounts
        
        try:
            # 🔥 优化：如果只刷新1个账号（注册场景），使用增量更新
            if total_count == 1 and hasattr(self, 'refresh_thread') and self.refresh_thread:
                # 获取刷新的账号邮箱
                refreshed_accounts = self.refresh_thread.accounts_to_refresh
                if refreshed_accounts and len(refreshed_accounts) == 1:
                    email = refreshed_accounts[0].get('email', '')
                    if email:
                        self.logger.info(f"🔄 单账号刷新完成，增量更新: {email}")
                        # 使用增量更新
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(100, lambda: self.update_single_account_in_table(email))
                        self.status_message.emit(f"✅ 刷新完成: {success_count}/{total_count}")
                        # 清理线程引用
                        if self.refresh_thread:
                            self.refresh_thread = None
                        return
            
            # 批量刷新：使用全量更新
            from PyQt6.QtCore import QTimer
            
            def delayed_refresh():
                # 暂停UI更新，提升性能
                self.accounts_table.setUpdatesEnabled(False)
                
                try:
                    # 保存当前选中状态
                    selected_emails = set()
                    for row in range(self.accounts_table.rowCount()):
                        checkbox = self.accounts_table.cellWidget(row, 0)
                        if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                            email_item = self.accounts_table.item(row, 2)
                            if email_item:
                                selected_emails.add(email_item.text())
                    
                    # 🔥 关键修复：从文件重新加载账号数据，确保获取最新的刷新结果
                    self.logger.info(f"📋 从文件重新加载数据以刷新UI")
                    accounts = self.config.load_accounts()
                    self.display_accounts(accounts)
                    
                    # 🔥 立即标记失败账号（表格已渲染完成）
                    if hasattr(self, '_failed_accounts_to_mark') and self._failed_accounts_to_mark:
                        self._mark_failed_accounts(self._failed_accounts_to_mark)
                    
                    # 恢复选中状态
                    if selected_emails:
                        for row in range(self.accounts_table.rowCount()):
                            email_item = self.accounts_table.item(row, 2)
                            if email_item and email_item.text() in selected_emails:
                                checkbox = self.accounts_table.cellWidget(row, 0)
                                if checkbox and isinstance(checkbox, QCheckBox):
                                    checkbox.setChecked(True)
                finally:
                    # 恢复UI更新
                    self.accounts_table.setUpdatesEnabled(True)
                
                # 显示完成消息
                if success_count == total_count:
                    self.status_message.emit(f"✅ 并发刷新完成！成功刷新 {success_count} 个账号")
                else:
                    self.status_message.emit(f"⚠️ 刷新完成：成功 {success_count}/{total_count} 个账号")
                    
                self.logger.info(f"并发刷新完成：成功 {success_count}/{total_count}")
            
            # 延迟100ms执行，等待文件保存完成
            QTimer.singleShot(100, delayed_refresh)
            
        except Exception as e:
            self.logger.error(f"刷新完成处理失败: {str(e)}")
            self.status_message.emit(f"❌ 刷新后处理失败: {str(e)}")
        finally:
            # 清理线程引用
            if self.refresh_thread:
                self.refresh_thread = None
    
    def _mark_failed_accounts(self, failed_emails):
        """处理刷新失败的账号（根据用户选择：标记或删除）"""
        try:
            if not failed_emails:
                return
            
            failed_set = set(failed_emails)
            
            # 获取用户选择的处理方式（默认为标记）
            action = getattr(self, '_failed_account_action', 'mark')
            
            # 🔥 标记前临时禁用排序和UI更新，避免标记过程中触发重排
            sorting_was_enabled = self.accounts_table.isSortingEnabled()
            self.accounts_table.setSortingEnabled(False)
            self.accounts_table.setUpdatesEnabled(False)
            
            try:
                if action == 'delete':
                    # 删除模式：从配置和表格中删除失败账号
                    accounts = self.config.load_accounts()
                    original_count = len(accounts)
                    accounts = [acc for acc in accounts if acc.get('email') not in failed_set]
                    deleted_count = original_count - len(accounts)
                
                    if deleted_count > 0:
                        # 保存更新后的账号列表
                        self.config.save_accounts(accounts, allow_empty=True)
                        self.logger.info(f"🗑️ 已从配置文件删除 {deleted_count} 个刷新失败的账号")
                        
                        # 直接从表格中删除对应的行（从后往前删，避免索引变化）
                        for row in range(self.accounts_table.rowCount() - 1, -1, -1):
                            email_item = self.accounts_table.item(row, 2)
                            if email_item and email_item.text() in failed_set:
                                self.accounts_table.removeRow(row)
                        
                        # 更新序号
                        self._update_row_numbers()
                        
                        self.status_message.emit(f"🗑️ 已删除 {deleted_count} 个刷新失败的账号")
                        
                else:
                    # 标记模式：在创建时间列显示红色标记
                    marked_count = 0
                    
                    from PyQt6.QtGui import QColor, QBrush
                    from PyQt6.QtCore import Qt
                    
                    # 遍历表格，在创建时间列标记失败账号
                    for row in range(self.accounts_table.rowCount()):
                        email_item = self.accounts_table.item(row, 2)
                        if email_item and email_item.text() in failed_set:
                            # 获取创建时间列（第3列）的item
                            time_item = self.accounts_table.item(row, 3)
                            if time_item:
                                # 保存原始文本
                                original_text = time_item.text()
                                
                                # 如果还没有失败标记，添加标记
                                if not original_text.startswith("❌ "):
                                    time_item.setText(f"❌ {original_text}")
                                
                                # 设置红色文字和浅红色背景
                                time_item.setForeground(QBrush(QColor(220, 53, 69)))  # 红色文字
                                time_item.setBackground(QBrush(QColor(255, 220, 220)))  # 浅红色背景
                                
                                # 同时为整行设置浅红色背景（更明显）
                                for col in range(self.accounts_table.columnCount()):
                                    item = self.accounts_table.item(row, col)
                                    if item and col != 3:  # 第3列已经单独设置
                                        item.setBackground(QBrush(QColor(255, 240, 240)))  # 更浅的红色背景
                                
                                marked_count += 1
                    
                    if marked_count > 0:
                        self.logger.info(f"🏷️ 已标记 {marked_count} 个刷新失败的账号（创建时间列红色标记）")
                        self.status_message.emit(f"⚠️ 已标记 {marked_count} 个刷新失败的账号")
            
            finally:
                # 恢复排序和UI更新
                if sorting_was_enabled:
                    self.accounts_table.setSortingEnabled(True)
                self.accounts_table.setUpdatesEnabled(True)
                self.accounts_table.viewport().update()
                    
        except Exception as e:
            self.logger.error(f"处理失败账号失败: {str(e)}")
    
    @pyqtSlot(dict)
    def on_account_refreshed(self, account):
        """单个账号刷新完成 - 只更新缓存，不更新UI（避免卡顿）"""
        try:
            # 🔥 关键优化：只更新内存缓存，不触发UI更新
            # UI更新统一在 on_refresh_completed 中批量进行
            email = account.get('email', '')
            user_id = account.get('user_id', '')
            
            if self.current_displayed_accounts:
                for i, acc in enumerate(self.current_displayed_accounts):
                    if (user_id and acc.get('user_id') == user_id) or (email and acc.get('email') == email):
                        # 只更新缓存数据，不刷新UI
                        self.current_displayed_accounts[i].update(account)
                        break
        except Exception as e:
            self.logger.error(f"更新缓存失败: {str(e)}")
    
    def export_accounts(self):
        """导出账号 - 智能选择导出范围，导出完整数据（包括标签、备注等所有信息）"""
        try:
            # 获取选中的账号邮箱
            selected_emails = []
            for row in range(self.accounts_table.rowCount()):
                checkbox = self.accounts_table.cellWidget(row, 0)
                if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    email_item = self.accounts_table.item(row, 2)
                    if email_item:
                        selected_emails.append(email_item.text())
            
            all_accounts = self.config.load_accounts()
            
            # 智能选择导出范围
            if selected_emails:
                # 有选中账号：询问用户是否只导出选中的
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Question)
                msgbox.setWindowTitle("导出范围选择")
                msgbox.setText(f"检测到您选中了 {len(selected_emails)} 个账号\n\n请选择导出范围：")
                
                # 应用统一样式
                self._apply_msgbox_style(msgbox)
                
                # 添加自定义按钮，简化描述
                selected_btn = msgbox.addButton("✅ 导出选中", QMessageBox.ButtonRole.YesRole)
                all_btn = msgbox.addButton("📦 导出全部", QMessageBox.ButtonRole.NoRole)
                cancel_btn = msgbox.addButton("❌ 取消", QMessageBox.ButtonRole.RejectRole)
                
                # 设置默认按钮
                msgbox.setDefaultButton(selected_btn)
                
                # 执行对话框
                msgbox.exec()
                clicked_button = msgbox.clickedButton()
                
                if clicked_button == cancel_btn:
                    return
                elif clicked_button == selected_btn:
                    # 导出选中账号
                    accounts_to_export = [
                        account for account in all_accounts 
                        if account.get('email') in selected_emails
                    ]
                    export_type = "selected"
                    file_prefix = f"cursor_accounts_selected_{len(accounts_to_export)}accounts"
                else:
                    # 导出全部账号
                    accounts_to_export = all_accounts
                    export_type = "all"
                    file_prefix = f"cursor_accounts_all_{len(accounts_to_export)}accounts"
            else:
                # 没有选中账号：直接导出全部
                accounts_to_export = all_accounts
                export_type = "all"
                file_prefix = f"cursor_accounts_all_{len(accounts_to_export)}accounts"
            
            if not accounts_to_export:
                # 创建自定义样式的提示框
                info_msgbox = QMessageBox(self)
                info_msgbox.setIcon(QMessageBox.Icon.Information)
                info_msgbox.setWindowTitle("提示")
                info_msgbox.setText("没有账号可以导出")
                self._apply_msgbox_style(info_msgbox)
                info_msgbox.exec()
                return
            
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getSaveFileName(
                self, f"导出{'选中' if export_type == 'selected' else '全部'}账号", 
                f"{file_prefix}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
                "JSON文件 (*.json)"
            )
            
            if file_path:
                # 加载标签和备注信息
                from ..utils.tag_manager import get_tag_manager
                tag_manager = get_tag_manager()
                remarks = self.config.load_remarks()
                
                # 转换为标准完整格式，包含所有信息
                standard_accounts = []
                
                for account in accounts_to_export:
                    email = account.get('email', '')
                    
                    # 构建标准格式的账号数据（包含账号所有原始字段）
                    standard_account = {
                        "email": email,
                        "password": account.get('password', ''),
                        "auth_info": {
                            "cursorAuth/cachedSignUpType": "Auth_0",
                            "cursorAuth/cachedEmail": email,
                            "cursorAuth/accessToken": account.get('access_token', ''),
                            "cursorAuth/refreshToken": account.get('refresh_token', ''),
                            "WorkosCursorSessionToken": account.get('WorkosCursorSessionToken', '')
                        },
                        "register_time": account.get('register_time', account.get('created_at', '')),
                        "registerTimeStamp": account.get('registerTimeStamp', 0),
                        "machine_info": account.get('machine_info', {
                            "telemetry.machineId": "",
                            "telemetry.macMachineId": "",
                            "telemetry.devDeviceId": "",
                            "telemetry.sqmId": "",
                            "system.machineGuid": ""
                        }),
                        "modelUsage": account.get('modelUsage', {
                            "used": 0,
                            "total": 100
                        }),
                        "system_type": account.get('system_type', 'windows'),
                        "daysRemainingOnTrial": account.get('daysRemainingOnTrial', account.get('trialDaysRemaining', 0)),
                        "membershipType": account.get('membershipType', 'free'),
                        "trialEligible": account.get('trialEligible', False),
                        "tokenValidity": not account.get('token_expired', False),
                        "subscriptionUpdatedAt": account.get('subscriptionUpdatedAt', 0),
                        "subscriptionStatus": account.get('subscriptionStatus', 'unknown'),
                        "trialDaysRemaining": account.get('trialDaysRemaining', account.get('daysRemainingOnTrial', 0))
                    }
                    
                    # 添加标签信息
                    account_tags = tag_manager.get_account_tags(email)
                    if account_tags:
                        standard_account["tags"] = [tag.tag_id for tag in account_tags]
                    
                    # 添加备注信息
                    if email in remarks and remarks[email]:
                        standard_account["remark"] = remarks[email]
                    
                    # 添加其他所有可能的字段（确保导出完整数据）
                    for key, value in account.items():
                        if key not in standard_account and key not in ['access_token', 'refresh_token', 'created_at']:
                            standard_account[key] = value
                    
                    standard_accounts.append(standard_account)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(standard_accounts, f, ensure_ascii=False, indent=2)
                
                export_desc = "选中" if export_type == "selected" else "全部"
                self.status_message.emit(f"✅ 成功导出 {len(standard_accounts)} 个{export_desc}账号（完整数据）")
                
        except Exception as e:
            # 创建自定义样式的错误框
            msgbox = QMessageBox(self)
            msgbox.setIcon(QMessageBox.Icon.Critical)
            msgbox.setWindowTitle("错误")
            msgbox.setText(f"导出失败: {str(e)}")
            self._apply_msgbox_style(msgbox)
            msgbox.exec()
    
    
    def show_import_dialog(self):
        """显示导入对话框"""
        try:
            # 通过parent调用主窗口的导入对话框方法
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'show_unified_import_dialog'):
                main_window = main_window.parent()
            
            if main_window and hasattr(main_window, 'show_unified_import_dialog'):
                main_window.show_unified_import_dialog()
            else:
                # 如果找不到主窗口方法，直接创建对话框
                from .three_tab_import_dialog import ThreeTabImportDialog
                dialog = ThreeTabImportDialog(self, self.config)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    # 🚀 快速刷新已在worker线程中完成，无需重复加载
                    # self.load_accounts()  # 不再需要，已通过quick_refresh_accounts完成
                    self.status_message.emit("账号导入完成")
                    
        except Exception as e:
            self.logger.error(f"打开导入对话框失败: {str(e)}")
            # 创建自定义样式的错误框
            msgbox = QMessageBox(self)
            msgbox.setIcon(QMessageBox.Icon.Critical)
            msgbox.setWindowTitle("错误")
            msgbox.setText(f"打开导入对话框失败: {str(e)}")
            self._apply_msgbox_style(msgbox)
            msgbox.exec()
    
    # ==================== 账号操作 ====================
    
    def quick_switch_to_next(self):
        """一键换号 - 自动切换到下一个账号（不弹确认框）"""
        try:
            # 获取下一个账号
            next_account = self._get_next_account()
            if not next_account:
                self.status_message.emit("⚠️ 没有可切换的下一个账号")
                return
            
            email = next_account.get('email', '未知')
            self.logger.info(f"🔄 一键换号: 自动切换到 {email}")
            
            # 默认选项：重置机器码 + 随机新机器码
            default_options = {
                'reset_machine': True,
                'use_random_machine': True,
                'full_reset': False
            }
            
            # 直接执行切换，不弹对话框，切换成功后删除账号
            self._execute_account_switch(next_account, default_options, delete_after_switch=True)
            
        except Exception as e:
            self.logger.error(f"一键换号失败: {str(e)}")
            self.status_message.emit(f"❌ 一键换号失败: {str(e)}")
    
    def _get_next_account(self):
        """获取下一个账号（按表格顺序） - 一键换号性能优化"""
        try:
            # 获取当前账号
            current_account = self.cursor_manager.get_current_account()
            if not current_account or not current_account.get('is_logged_in'):
                # 没有当前账号，返回第一个账号
                accounts = self.config.load_accounts()
                return accounts[0] if accounts else None
            
            current_email = current_account.get('email', '')
            
            # 🚀 性能优化：只加载一次配置文件，用字典缓存
            all_accounts = self.config.load_accounts()
            accounts_dict = {acc.get('email'): acc for acc in all_accounts}
            
            # 获取表格中的所有账号（按显示顺序）
            accounts = []
            for row in range(self.accounts_table.rowCount()):
                email_item = self.accounts_table.item(row, 2)  # 邮箱列
                if email_item:
                    email = email_item.text()
                    # 🚀 从字典中查找（O(1)），而不是每次遍历整个列表
                    if email in accounts_dict:
                        accounts.append(accounts_dict[email])
            
            if not accounts:
                return None
            
            # 找到当前账号的位置
            current_index = -1
            for i, acc in enumerate(accounts):
                if acc.get('email') == current_email:
                    current_index = i
                    break
            
            # 返回下一个账号（循环）
            if current_index == -1:
                # 当前账号不在列表中，返回第一个
                return accounts[0]
            else:
                next_index = (current_index + 1) % len(accounts)
                return accounts[next_index]
                
        except Exception as e:
            self.logger.error(f"获取下一个账号失败: {str(e)}")
            return None
    
    def switch_account(self, account):
        """切换账号 - 使用确认对话框"""
        try:
            # 显示账号切换确认对话框
            dialog = UseAccountConfirmationDialog(account, self)
            dialog.confirmed.connect(lambda options: self._execute_account_switch(account, options))
            dialog.exec()
            
        except Exception as e:
            # 创建自定义样式的错误框
            msgbox = QMessageBox(self)
            msgbox.setIcon(QMessageBox.Icon.Critical)
            msgbox.setWindowTitle("错误")
            msgbox.setText(f"切换账号失败: {str(e)}")
            self._apply_msgbox_style(msgbox)
            msgbox.exec()
    
    def _execute_account_switch(self, account, options, delete_after_switch=False):
        """执行账号切换 - 使用新的 reset_cursor_account 方法
        
        Args:
            account: 账号信息（要切换到的新账号）
            options: 切换选项
            delete_after_switch: 切换成功后是否删除旧账号（一键换号时为True）
        """
        try:
            email = account.get('email', '未知')
            self.status_message.emit(f"🔄 正在切换到账号: {email}")
            self.logger.info(f"开始切换账号: {email}, 选项: {options}, 切换后删除旧账号: {delete_after_switch}")
            
            # 保存切换前的旧账号（用于删除）和删除标志
            if delete_after_switch:
                old_account = self.cursor_manager.get_current_account()
                if old_account and old_account.get('is_logged_in'):
                    self.old_account_to_delete = old_account
                    self.logger.info(f"保存旧账号信息用于删除: {old_account.get('email', '未知')}")
                else:
                    self.old_account_to_delete = None
            else:
                self.old_account_to_delete = None
            
            self.delete_account_after_switch = delete_after_switch
            
            # 使用新的线程执行切换
            self.switch_thread = FlyStyleSwitchThread(self.cursor_manager, account, options)
            self.switch_thread.switch_finished.connect(self.on_switch_finished)
            self.switch_thread.progress_updated.connect(self.on_switch_progress)
            self.switch_thread.start()
            
        except Exception as e:
            self.logger.error(f"执行账号切换失败: {str(e)}")
            self.status_message.emit(f"❌ 切换失败: {str(e)}")
    
    def on_switch_progress(self, progress_message: str):
        """切换进度回调 - 新增方法"""
        self.status_message.emit(progress_message)
    
    def on_switch_finished(self, success: bool, message: str):
        """切换完成回调"""
        # 通知主窗口停止动画
        main_window = self.window()
        if main_window and hasattr(main_window, '_stop_switch_animation'):
            main_window._stop_switch_animation()
        
        if success:
            self.status_message.emit(message)
            
            # 根据标志决定是否删除旧账号（只有一键换号时才删除）
            should_delete = getattr(self, 'delete_account_after_switch', False)
            old_account = getattr(self, 'old_account_to_delete', None)
            
            if should_delete and old_account:
                try:
                    old_email = old_account.get('email', '')
                    if old_email:
                        self.logger.info(f"一键换号成功，删除旧账号: {old_email}")
                        if self.config.remove_account(old_email):
                            self.logger.info(f"旧账号 {old_email} 已从列表中删除")
                            # 刷新账号列表（会自动更新五角星）
                            QTimer.singleShot(100, self.load_accounts)
                        else:
                            self.logger.warning(f"删除旧账号 {old_email} 失败")
                except Exception as e:
                    self.logger.error(f"删除旧账号失败: {str(e)}")
                finally:
                    self.old_account_to_delete = None
                    self.delete_account_after_switch = False
            else:
                # 手动切换不删除账号，只更新五角星
                self.logger.info(f"手动切换账号成功，保留所有账号")
                self.old_account_to_delete = None
                self.delete_account_after_switch = False
                # 只更新五角星，不刷新整个表格
                QTimer.singleShot(50, self._quick_update_switch_buttons)
        else:
            # 创建自定义样式的警告框
            msgbox = QMessageBox(self)
            msgbox.setIcon(QMessageBox.Icon.Warning)
            msgbox.setWindowTitle("切换失败")
            msgbox.setText(message)
            self._apply_msgbox_style(msgbox)
            msgbox.exec()
            
            # 切换失败时清除保存的账号信息和删除标志
            if hasattr(self, 'old_account_to_delete'):
                self.old_account_to_delete = None
            if hasattr(self, 'delete_account_after_switch'):
                self.delete_account_after_switch = False
        
        if self.switch_thread:
            self.switch_thread.deleteLater()
            self.switch_thread = None
    
    def delayed_refresh(self):
        """延迟刷新，更新UI显示（保留用于其他功能调用）"""
        try:
            self.logger.info("开始刷新表格...")
            self.refresh_table()
            self.update_current_account_display()
            self.logger.info("刷新完成")
        except Exception as e:
            self.logger.error(f"刷新失败: {str(e)}")
    
    def _quick_update_switch_buttons(self):
        """快速更新切换按钮（五角星）- 极速模式，不刷新整个表格"""
        try:
            # 获取当前登录的账号
            current_account = self.cursor_manager.get_current_account()
            if not current_account or not current_account.get('is_logged_in'):
                return
            
            current_email = current_account.get('email', '')
            if not current_email:
                return
            
            # 确定切换按钮所在列（与create_switch_button保持一致）
            from ..core.version_config import VersionConfig
            switch_col = 8 if VersionConfig.is_full_version() else 6
            
            # 遍历表格，只更新切换按钮
            row_count = self.accounts_table.rowCount()
            for row in range(row_count):
                email_item = self.accounts_table.item(row, 2)  # 邮箱在第2列
                if not email_item:
                    continue
                
                row_email = email_item.text()
                is_current = (row_email == current_email)
                
                # 获取按钮容器
                container = self.accounts_table.cellWidget(row, switch_col)
                if container:
                    # 查找按钮
                    btn = container.findChild(QPushButton)
                    if btn:
                        if is_current:
                            # 更新为五角星
                            btn.setText("★")
                            btn.setToolTip("⭐ 当前正在使用的账号")
                            btn.setStyleSheet("""
                                QPushButton {
                                    border: none;
                                    border-radius: 12px;
                                    padding: 0px;
                                    font-size: 16px;
                                    width: 24px;
                                    height: 24px;
                                    min-width: 24px;
                                    max-width: 24px;
                                    min-height: 24px;
                                    max-height: 24px;
                                    background: transparent;
                                    color: #dc3545;
                                    text-align: center;
                                }
                                QPushButton:hover {
                                    background: rgba(220, 53, 69, 0.1);
                                }
                                QPushButton:pressed {
                                    background: rgba(220, 53, 69, 0.2);
                                }
                            """)
                        else:
                            # 更新为切换图标
                            btn.setText("🔄")
                            btn.setToolTip("🔄 切换到此账号")
                            btn.setStyleSheet("""
                                QPushButton {
                                    border: none;
                                    border-radius: 12px;
                                    padding: 0px;
                                    font-size: 14px;
                                    width: 24px;
                                    height: 24px;
                                    min-width: 24px;
                                    max-width: 24px;
                                    min-height: 24px;
                                    max-height: 24px;
                                    background: #6c757d;
                                    color: white;
                                    text-align: center;
                                }
                                QPushButton:hover {
                                    background: #5a6268;
                                }
                                QPushButton:pressed {
                                    background: #545b62;
                                }
                            """)
            
            # 同时更新当前账号显示标签
            self.update_current_account_display()
            self.logger.info(f"✅ 快速更新五角星完成: {current_email}")
            
        except Exception as e:
            self.logger.error(f"快速更新五角星失败: {str(e)}")
    
    def open_current_account_homepage(self):
        """打开当前账号的主页"""
        try:
            # 直接从Cursor数据库获取当前账号信息，不依赖我们的账号数据库
            current_account = self.cursor_manager.get_current_account()
            if not current_account:
                self.status_message.emit("❌ 未检测到当前登录账号")
                return
                
            if not current_account.get('is_logged_in'):
                self.status_message.emit("❌ 当前账号未登录")
                return
            
            email = current_account.get('email', '')
            access_token = current_account.get('access_token', '')
            user_id = current_account.get('user_id', '')
            
            # 检查关键信息是否完整
            if not access_token or not user_id:
                self.status_message.emit(f"❌ 当前账号 {email} 缺少有效token，无法打开主页")
                return
            
            # 🔥 直接使用从Cursor数据库获取的信息构造账号对象
            account_for_homepage = {
                'email': email,
                'access_token': access_token,
                'refresh_token': access_token,  # 使用access_token作为refresh_token
                'user_id': user_id,
                'WorkosCursorSessionToken': f"{user_id}::{access_token}"  # 构造WorkosCursorSessionToken
            }
            
            self.status_message.emit(f"🌐 正在为当前账号 {email} 打开主页...")
            self.open_homepage(account_for_homepage)
            
        except Exception as e:
            self.logger.error(f"打开当前账号主页失败: {str(e)}")
            self.status_message.emit(f"❌ 打开当前账号主页失败: {str(e)}")

    def open_homepage(self, account):
        """打开Cursor Dashboard - 正确的cookie注入逻辑"""
        try:
            email = account.get('email', '未知')
            access_token = account.get('access_token', '')
            refresh_token = account.get('refresh_token', '')
            workos_token = account.get('WorkosCursorSessionToken', '')
            
            # 检查是否有任何有效的token
            if not access_token and not refresh_token and not workos_token:
                self.status_message.emit(f"❌ {email} 缺少有效token，无法打开主页")
                # 创建自定义样式的警告框
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Warning)
                msgbox.setWindowTitle("错误")
                msgbox.setText("该账号缺少有效的登录token，无法打开主页")
                self._apply_msgbox_style(msgbox)
                msgbox.exec()
                return
            
            self.status_message.emit(f"🌐 正在为 {email} 打开Dashboard...")
            
            # 使用DrissionPage打开带cookie的浏览器页面
            self._open_dashboard_with_cookies(account)
            
        except Exception as e:
            self.logger.error(f"打开主页失败: {str(e)}")
            self.status_message.emit(f"❌ 打开主页失败: {str(e)}")
    
    def _open_dashboard_with_cookies(self, account):
        """使用DrissionPage打开带cookie的Dashboard - 优化版"""
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            import os, time
            
            # 设置环境变量禁用弹窗
            os.environ.update({
                'EDGE_DISABLE_FIRST_RUN_EXPERIENCE': '1',
                'EDGE_DISABLE_BACKGROUND_MODE': '1',
                'CHROME_DISABLE_FIRST_RUN_EXPERIENCE': '1'
            })
            
            # 🔥 优化：尝试连接已存在的浏览器实例
            browser_reused = False
            browser = None
            
            if self.dashboard_browser:
                try:
                    # 测试浏览器是否还活着
                    if hasattr(self.dashboard_browser, 'latest_tab'):
                        test_tab = self.dashboard_browser.latest_tab  # 测试连接
                        if test_tab and hasattr(test_tab, 'url'):
                            _ = test_tab.url  # 再次确认可用
                            browser = self.dashboard_browser
                            self.logger.info("✅ 复用已存在的浏览器实例")
                            # 创建新标签页
                            browser.new_tab()
                            browser_reused = True
                        else:
                            raise Exception("tab对象无效")
                except Exception as e:
                    self.logger.warning(f"无法复用浏览器实例: {str(e)}, 将创建新实例")
                    # 清理无效的浏览器引用
                    self.dashboard_browser = None
            
            if not browser_reused:
                # 创建新的浏览器实例
                self.logger.info("🚀 创建新的浏览器实例")
                
                # 🔥 优化：使用固定的用户数据目录
                config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'browser_profile')
                os.makedirs(config_dir, exist_ok=True)
                
                co = ChromiumOptions()
                co.headless(False)
                co.set_user_data_path(config_dir)
                
                # 🔥 根据浏览器类型动态分配端口
                browser_config = self.config.config_data.get('browser', {})
                if isinstance(browser_config, dict):
                    browser_path = browser_config.get('path', '')
                else:
                    browser_path = ''
                    self.logger.warning(f"浏览器配置格式错误: {type(browser_config)}, 使用默认浏览器")
                
                if browser_path and 'edge' in browser_path.lower():
                    # Edge浏览器使用auto_port避免端口冲突
                    co.auto_port()
                else:
                    # Chrome等其他浏览器使用固定端口
                    co.set_local_port(9111)
            
                # 🔥 根据配置决定是否使用代理
                if self.config.get_use_proxy():
                    # 启用代理 - 检测并设置系统代理（支持梯子环境）
                    try:
                        import urllib.request
                        proxies = urllib.request.getproxies()
                        if proxies:
                            # 如果检测到代理，设置浏览器使用代理
                            if 'http' in proxies:
                                co.set_argument(f'--proxy-server={proxies["http"]}')
                            elif 'https' in proxies:
                                co.set_argument(f'--proxy-server={proxies["https"]}')
                    except Exception as proxy_error:
                        self.logger.debug(f"代理检测失败: {str(proxy_error)}")
                else:
                    # 禁用代理 - 使用Chrome标准参数
                    co.set_argument('--no-proxy-server')
                
                # 核心防弹窗参数 - 增强版
                args = [
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-features=PrivacySandboxSettings4',
                    '--disable-sync',
                    '--disable-background-sync',
                    '--disable-features=CookiesWithoutSameSiteMustBeSecure',
                    '--disable-features=msEdgeEnablePriceHistory',
                    '--disable-features=msImportDataConsentDialog',
                    '--inprivate',  # Edge无痕模式，跳过隐私设置
                ]
                for arg in args:
                    co.set_argument(arg)
                
                # 设置配置的浏览器路径
                browser_config = self.config.config_data.get('browser', {})
                if isinstance(browser_config, dict):
                    browser_path = browser_config.get('path', '')
                    if browser_path and os.path.exists(browser_path):
                        co.set_browser_path(browser_path)
                        self.logger.info(f"使用配置的浏览器: {browser_path}")
                else:
                    self.logger.warning(f"浏览器配置格式错误，使用默认浏览器")
                
                # 创建浏览器并处理
                browser = ChromiumPage(addr_or_opts=co)
                browser.set.auto_handle_alert(True)
                
                # 保存浏览器实例引用
                self.dashboard_browser = browser
            
            # 获取token - 添加类型检查
            if not isinstance(account, dict):
                self.logger.error(f"account参数类型错误: {type(account)}")
                self.status_message.emit(f"❌ 账号数据格式错误")
                return
            
            workos_token = account.get('WorkosCursorSessionToken', '')
            if not workos_token:
                self.status_message.emit(f"❌ {account.get('email', '未知')} 缺少token信息")
                return
            
            final_token = workos_token.replace('::', '%3A%3A') if '::' in workos_token else workos_token
            
            # 🔥 优化：获取当前活动标签页
            # 注意：latest_tab 在某些情况下可能返回字符串（tab ID），需要用 get_tab() 获取对象
            try:
                latest_tab_id = browser.latest_tab
                if isinstance(latest_tab_id, str):
                    # 如果返回的是字符串ID，使用get_tab获取实际对象
                    tab = browser.get_tab(latest_tab_id)
                else:
                    # 如果返回的就是tab对象，直接使用
                    tab = latest_tab_id
            except Exception as e:
                self.logger.warning(f"获取latest_tab失败: {str(e)}, 使用默认tab")
                tab = browser.get_tab()  # 获取默认tab
            
            # 验证 tab 对象是否有效
            if not tab or not hasattr(tab, 'get'):
                self.logger.error(f"浏览器tab对象无效: type={type(tab)}, value={tab}")
                self.status_message.emit(f"❌ 浏览器标签页获取失败")
                return
            
            # 先跳转到空白页面，建立域上下文
            tab.get("about:blank")
            
            # 注入cookie到cursor.com域
            tab.set.cookies([{
                'name': 'WorkosCursorSessionToken',
                'value': final_token,
                'domain': '.cursor.com',
                'path': '/',
                'secure': True,
                'httpOnly': True
            }])
            
            # 然后导航到dashboard
            tab.get("https://cursor.com/dashboard")
            
            self.status_message.emit(f"✅ 已为 {account.get('email', '未知')} 打开Dashboard")
            
        except Exception as e:
            error_msg = str(e)
            if "not enough values to unpack" in error_msg:
                self.status_message.emit("❌ DrissionPage版本兼容性问题，请更新DrissionPage")
            elif "port" in error_msg or "timeout" in error_msg:
                self.status_message.emit("❌ 浏览器端口被占用或启动超时")
            else:
                self.status_message.emit(f"❌ 打开Dashboard失败: {error_msg}")
            self.logger.error(f"打开Dashboard失败: {str(e)}")
    
    def toggle_refresh_tokens(self):
        """刷新Token按钮点击处理"""
        # 检查是否正在刷新
        if hasattr(self, '_is_refreshing_tokens') and self._is_refreshing_tokens:
            # 🔥 立即设置停止标志，所有浏览器将立即关闭
            self._should_stop_refresh = True
            self._is_refreshing_tokens = False
            self.status_message.emit("🛑 正在停止并关闭所有浏览器...")
            self.logger.warning("⚠️ 用户请求停止，立即关闭所有浏览器")
            # 立即恢复按钮
            self._reset_refresh_token_button()
            return
        
        # 开始刷新
        self.start_refresh_tokens()
    
    def start_refresh_tokens(self):
        """开始刷新Token - 优化版：避免主线程阻塞"""
        import threading
        from ..utils.session_token_converter import SessionTokenConverter
        
        # 标记正在刷新
        self._is_refreshing_tokens = True
        self._should_stop_refresh = False
        
        # 更新按钮为停止状态
        self.refresh_token_btn.setText("⏹️ 停止刷新")
        self.refresh_token_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        
        # 🔥 优化：收集选中的邮箱列表（不在这里加载账号数据）
        selected_emails = []
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                email_item = self.accounts_table.item(row, 2)
                if email_item:
                    selected_emails.append(email_item.text())
        
        def refresh_worker():
            """刷新Token工作线程 - 所有IO操作都在后台线程"""
            try:
                # 🔥 在后台线程加载账号数据，避免阻塞主线程
                all_accounts = self.config.load_accounts()
                
                # 🔥 根据选中的邮箱筛选账号
                if selected_emails:
                    selected_accounts = [acc for acc in all_accounts if acc.get('email') in selected_emails]
                else:
                    selected_accounts = all_accounts
                
                total = len(selected_accounts)
                self.logger.info(f"🔑 开始刷新Token，共 {total} 个账号")
                self.status_message.emit(f"🔑 开始检测需要转换的账号...")
                
                # 先筛选需要转换的账号，显示统计
                need_convert = 0
                already_valid_count = 0
                need_convert_list = []  # 记录需要转换的账号
                
                for acc in selected_accounts:
                    token = acc.get('access_token', '')
                    workos_token = acc.get('WorkosCursorSessionToken', '')
                    email = acc.get('email', '未知')
                    token_len = len(token) if token else 0
                    
                    # 判断是否需要转换（与session_token_converter.py保持一致）
                    if not token:
                        already_valid_count += 1
                    elif token_len == 413:
                        # 长度413的是有效的session token，跳过
                        already_valid_count += 1
                    elif workos_token:
                        # 有workos_token且不是413长度，需要转换
                        need_convert += 1
                        need_convert_list.append(f"{email} (长度{token_len})")
                    else:
                        # 没有workos_token，无法转换，跳过
                        already_valid_count += 1
                
                # 只输出汇总信息
                self.logger.info(f"📊 扫描完成: 总数{total}, 需转换{need_convert}, 已有效{already_valid_count}")
                
                if need_convert == 0:
                    msg = f"✅ 所有选中账号Token都是有效格式（共{total}个，无需转换）"
                    self.logger.info(msg)
                    self.status_message.emit(msg)
                    return
                
                self.status_message.emit(f"🔄 开始转换Token：共{total}个账号，需转换{need_convert}个...")
                
                # 完全不更新中间进度，避免UI卡顿
                def progress_cb(current, total_pending, email, status):
                    """进度回调函数 - 静默版，完全不更新UI"""
                    # 不发送任何UI更新信号，避免卡顿
                    pass
                
                # 定义停止检查函数
                def should_stop():
                    return self._should_stop_refresh
                
                # 使用统一的批量转换方法
                converter = SessionTokenConverter(self.config)
                results = converter.batch_convert_accounts(
                    accounts=selected_accounts,
                    config=self.config,
                    progress_callback=progress_cb,
                    stop_flag=should_stop
                )
                
                # 显示结果
                converted = results.get('converted', 0)
                failed = results.get('failed', 0)
                skipped = results.get('skipped', 0)
                failed_accounts = results.get('failed_accounts', [])
                
                self.logger.info(f"📊 Token刷新完成: 成功 {converted} 个，失败 {failed} 个，跳过 {skipped} 个")
                
                # 🔥 保存失败账号列表，用于UI标记
                if failed_accounts:
                    self._failed_accounts_to_mark = failed_accounts
                    self.logger.info(f"⚠️ 有 {len(failed_accounts)} 个账号转换失败，将标记显示")
                    self.status_message.emit(
                        f"⚠️ Token刷新完成！成功 {converted} 个，失败 {failed} 个（已标记），跳过 {skipped} 个"
                    )
                else:
                    self._failed_accounts_to_mark = []
                    self.status_message.emit(
                        f"✅ Token刷新完成！成功 {converted} 个，失败 {failed} 个，跳过 {skipped} 个"
                    )
                
                # 🔥 使用信号刷新UI（确保在主线程执行）
                self.refresh_ui_signal.emit()
                
            except Exception as e:
                self.logger.error(f"刷新Token失败: {str(e)}")
                import traceback
                self.logger.error(f"详细错误:\n{traceback.format_exc()}")
                self.status_message.emit(f"❌ Token刷新失败: {str(e)}")
            finally:
                # 🔥 最终清理：确保所有Chrome进程都被关闭
                try:
                    self._cleanup_chrome_processes()
                except Exception as cleanup_error:
                    self.logger.warning(f"清理Chrome进程失败: {str(cleanup_error)}")
                
                # 🔥 恢复按钮 - 使用信号确保在主线程执行
                self._is_refreshing_tokens = False
                self.logger.info("🔄 发送恢复按钮信号")
                self.reset_refresh_btn_signal.emit()
        
        # 在后台线程执行
        threading.Thread(target=refresh_worker, daemon=True).start()
    
    @pyqtSlot()
    def _reset_refresh_token_button(self):
        """恢复刷新Token按钮状态（槽函数）"""
        try:
            self.refresh_token_btn.setEnabled(True)
            self.refresh_token_btn.setText("🔑 刷新Token")
            # 恢复初始的紫色样式
            self.refresh_token_btn.setStyleSheet("""
                QPushButton {
                    background-color: #8b5cf6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-weight: 500;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #7c3aed;
                }
                QPushButton:pressed {
                    background-color: #6d28d9;
                }
                QPushButton:focus {
                    outline: none;
                }
                QPushButton:disabled {
                    background-color: #6c757d;
                    opacity: 0.5;
                }
            """)
            self.logger.info("✅ 刷新Token按钮已恢复")
        except Exception as e:
            self.logger.error(f"恢复按钮失败: {str(e)}")
    
    @pyqtSlot()
    def _refresh_without_losing_selection(self):
        """刷新账号列表但保持选中状态"""
        try:
            # 1. 保存当前选中的邮箱列表
            selected_emails = set()
            for row in range(self.accounts_table.rowCount()):
                checkbox = self.accounts_table.cellWidget(row, 0)
                if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    email_item = self.accounts_table.item(row, 2)
                    if email_item:
                        selected_emails.add(email_item.text())
            
            # 2. 重新加载账号列表（会自动更新账号总数）
            self.load_accounts()
            
            # 3. 恢复选中状态
            if selected_emails:
                restored_count = 0
                for row in range(self.accounts_table.rowCount()):
                    email_item = self.accounts_table.item(row, 2)
                    if email_item and email_item.text() in selected_emails:
                        checkbox = self.accounts_table.cellWidget(row, 0)
                        if checkbox and isinstance(checkbox, QCheckBox):
                            checkbox.setChecked(True)
                            restored_count += 1
            
            # 4. 标记失败账号
            if hasattr(self, '_failed_accounts_to_mark') and self._failed_accounts_to_mark:
                self._mark_failed_accounts(self._failed_accounts_to_mark)
                self.logger.info(f"🎨 已标记 {len(self._failed_accounts_to_mark)} 个失败账号")
                # 清空标记列表
                self._failed_accounts_to_mark = []
                
        except Exception as e:
            self.logger.error(f"刷新并保持选中状态失败: {str(e)}")
            # 失败时使用普通刷新
            self.load_accounts()
    
    @pyqtSlot()
    def _reset_bind_card_button(self):
        """恢复批量绑卡按钮状态（槽函数）"""
        try:
            # 仅在完整版且按钮存在时恢复
            if hasattr(self, 'batch_bind_card_btn'):
                self.batch_bind_card_btn.setEnabled(True)
                self.batch_bind_card_btn.setText("💳 批量绑卡")
                # 恢复初始的橙色样式
                self.batch_bind_card_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f59e0b;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 0 16px;
                        font-weight: 500;
                        font-size: 13px;
                    }
                    QPushButton:hover {
                        background-color: #d97706;
                    }
                    QPushButton:pressed {
                        background-color: #b45309;
                    }
                    QPushButton:focus {
                        outline: none;
                    }
                    QPushButton:disabled {
                        background-color: #6c757d;
                        opacity: 0.5;
                    }
                """)
                self.logger.info("✅ 批量绑卡按钮已恢复")
            else:
                self.logger.debug("跳过恢复绑卡按钮（精简版）")
        except Exception as e:
            self.logger.error(f"恢复绑卡按钮失败: {str(e)}")
    
    def toggle_batch_bind_cards(self):
        """切换批量绑卡状态（开始/停止）"""
        # 检查是否正在运行
        if hasattr(self, '_is_batch_binding') and self._is_batch_binding:
            # 正在运行，点击停止
            self.stop_batch_bind_cards()
        else:
            # 未运行，点击开始
            self.batch_bind_cards()
    
    def _open_screenshots_folder(self):
        """打开截图保存目录"""
        import subprocess
        import platform
        
        screenshot_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'screenshots')
        os.makedirs(screenshot_dir, exist_ok=True)
        
        try:
            if platform.system() == 'Windows':
                os.startfile(screenshot_dir)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', screenshot_dir])
            else:  # Linux
                subprocess.run(['xdg-open', screenshot_dir])
            self.status_message.emit(f"📂 已打开截图目录: {screenshot_dir}")
        except Exception as e:
            self.logger.error(f"打开截图目录失败: {str(e)}")
            self.status_message.emit(f"❌ 打开截图目录失败: {str(e)}")
    
    def stop_batch_bind_cards(self):
        """停止批量绑卡 - 第一操作：立即关闭绑卡功能打开的浏览器"""
        if hasattr(self, '_is_batch_binding') and self._is_batch_binding:
            self.logger.info("🛑 用户请求停止批量绑卡")
            self.status_message.emit("🛑 正在停止批量绑卡...")
            
            # 🔥 第一操作：立即强制关闭绑卡功能打开的浏览器
            if hasattr(self, '_batch_bind_browser') and self._batch_bind_browser:
                try:
                    self.logger.info("🛑 [优先] 正在强制关闭绑卡浏览器...")
                    self._batch_bind_browser.quit()
                    self._batch_bind_browser = None
                    self.status_message.emit("✅ 绑卡浏览器已关闭")
                    self.logger.info("✅ 绑卡浏览器已强制关闭")
                except Exception as e:
                    self.logger.error(f"关闭绑卡浏览器失败: {str(e)}")
            
            # 设置停止标志（让后台线程停止）
            self._is_batch_binding = False
            
            # 取消所有正在执行的任务
            if hasattr(self, '_batch_bind_executor') and self._batch_bind_executor:
                try:
                    self.logger.info("🛑 正在取消所有绑卡任务...")
                    self._batch_bind_executor.shutdown(wait=False, cancel_futures=True)
                    self._batch_bind_executor = None
                    self.logger.info("✅ 所有任务已取消")
                except Exception as e:
                    self.logger.error(f"取消任务失败: {str(e)}")
            
            # 🔥 使用信号恢复按钮
            self.logger.info("🔄 发送恢复绑卡按钮信号（停止操作）")
            self.reset_bind_card_btn_signal.emit()
            self.status_message.emit("✅ 批量绑卡已停止")
    
    def batch_bind_cards(self):
        """批量绑卡 - 支持并发，为选中的账号执行绑卡操作"""
        import threading
        import time
        import random
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton, QMessageBox
        
        self.logger.info(f"⏱️ 用户点击批量绑卡按钮")
        
        # 获取所有选中的账号
        selected_accounts = []
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                # 获取邮箱
                email_item = self.accounts_table.item(row, 2)
                if email_item:
                    email = email_item.text()
                    # 通过邮箱查找账号
                    accounts = self.config.load_accounts()
                    for acc in accounts:
                        if acc.get('email') == email:
                            selected_accounts.append(acc)
                            break
        
        if not selected_accounts:
            self.status_message.emit("⚠️ 请选择账号")
            self._show_simple_message("请选择需要绑卡的账号")
            return
        
        # 🔍 检查可用银行卡数量
        from ..services.email_service.register_config_manager import RegisterConfigManager
        from ..services.email_service.card_manager import CardManager
        
        try:
            register_config = RegisterConfigManager()
            card_manager = CardManager(register_config, lambda msg: self.logger.debug(msg))
            available_cards = card_manager.get_available_cards_count()
            
            self.logger.info(f"📊 银行卡检查：选中{len(selected_accounts)}个账号，可用银行卡{available_cards}张")
            
            # 如果银行卡不足，警告用户
            if available_cards < len(selected_accounts):
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Warning)
                msgbox.setWindowTitle("银行卡数量不足")
                msgbox.setText(f"可用银行卡只有 {available_cards} 张，但您选中了 {len(selected_accounts)} 个账号")
                msgbox.setInformativeText(
                    f"建议：\n"
                    f"1. 减少选中账号数量至 {available_cards} 个以内\n"
                    f"2. 前往【自动注册】页面添加更多银行卡\n"
                    f"3. 或重置已使用/问题卡状态\n\n"
                    f"是否继续？（只能为前 {available_cards} 个账号绑卡）"
                )
                msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msgbox.setDefaultButton(QMessageBox.StandardButton.No)
                self._apply_msgbox_style(msgbox)
                
                if msgbox.exec() != QMessageBox.StandardButton.Yes:
                    self.status_message.emit(f"❌ 已取消批量绑卡（银行卡不足）")
                    return
                
                # 用户选择继续，截断账号列表
                selected_accounts = selected_accounts[:available_cards]
                self.logger.info(f"⚠️ 用户选择继续，截断为前{len(selected_accounts)}个账号")
                self.status_message.emit(f"⚠️ 银行卡不足，仅为前 {len(selected_accounts)} 个账号绑卡")
            
            elif available_cards == 0:
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Critical)
                msgbox.setWindowTitle("无可用银行卡")
                msgbox.setText("当前没有可用的银行卡")
                msgbox.setInformativeText(
                    "请前往【自动注册】页面添加银行卡，\n"
                    "或重置已使用/问题卡状态后再试。"
                )
                self._apply_msgbox_style(msgbox)
                msgbox.exec()
                self.status_message.emit("❌ 无可用银行卡")
                return
        except Exception as e:
            self.logger.error(f"检查银行卡数量失败: {str(e)}")
            # 检查失败不阻塞流程，继续执行
        
        # 弹出绑卡配置对话框
        from PyQt6.QtWidgets import QButtonGroup, QRadioButton
        
        config_dialog = QDialog(self)
        config_dialog.setWindowTitle("批量绑卡配置")
        config_dialog.setFixedSize(450, 280)  # 简化后缩小尺寸
        config_dialog.setModal(True)
        
        layout = QVBoxLayout(config_dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel(f"📊 共选中 {len(selected_accounts)} 个账号")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1976d2;")
        layout.addWidget(title_label)
        
        # 模式选择
        mode_row = QHBoxLayout()
        mode_label = QLabel("绑卡模式:")
        mode_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        mode_row.addWidget(mode_label)
        
        mode_group = QButtonGroup()
        serial_radio = QRadioButton("串行")
        parallel_radio = QRadioButton("并行")
        parallel_radio.setChecked(True)
        
        mode_group.addButton(serial_radio)
        mode_group.addButton(parallel_radio)
        mode_row.addWidget(serial_radio)
        mode_row.addWidget(parallel_radio)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        
        # 无头模式
        headless_row = QHBoxLayout()
        headless_label = QLabel("无头模式:")
        headless_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        headless_row.addWidget(headless_label)

        headless_checkbox = QCheckBox("启用（后台运行，隐藏窗口）")
        headless_checkbox.setToolTip("启用后，浏览器在后台运行，不显示界面。建议搭配较大的窗口尺寸与UA优化。")
        headless_row.addWidget(headless_checkbox)
        headless_row.addStretch()
        layout.addLayout(headless_row)

        # 并发数配置（只在并行模式显示）
        concurrent_row = QHBoxLayout()
        concurrent_label = QLabel("并发浏览器数:")
        concurrent_label.setStyleSheet("font-size: 13px;")
        concurrent_row.addWidget(concurrent_label)
        
        concurrent_spinbox = QSpinBox()
        concurrent_spinbox.setRange(1, 10)
        concurrent_spinbox.setValue(min(5, len(selected_accounts)))
        concurrent_spinbox.setStyleSheet("font-size: 13px; min-width: 60px;")
        concurrent_spinbox.setToolTip("同时运行的浏览器数量，每个浏览器独立无痕模式，互不干扰")
        concurrent_row.addWidget(concurrent_spinbox)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        
        # 根据模式启用/禁用并发数控件
        def update_concurrent_state():
            if parallel_radio.isChecked():
                concurrent_label.setEnabled(True)
                concurrent_spinbox.setEnabled(True)
            else:
                concurrent_label.setEnabled(False)
                concurrent_spinbox.setEnabled(False)
        
        serial_radio.toggled.connect(update_concurrent_state)
        parallel_radio.toggled.connect(update_concurrent_state)
        update_concurrent_state()
        
        # 按钮
        button_row = QHBoxLayout()
        button_row.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(config_dialog.reject)
        button_row.addWidget(cancel_btn)
        
        confirm_btn = QPushButton("开始绑卡")
        confirm_btn.clicked.connect(config_dialog.accept)
        confirm_btn.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold;")
        button_row.addWidget(confirm_btn)
        layout.addLayout(button_row)
        
        # 显示对话框
        if config_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        # 获取配置
        is_parallel = parallel_radio.isChecked()
        max_concurrent = concurrent_spinbox.value() if is_parallel else 1
        enable_headless = headless_checkbox.isChecked()
        
        def batch_bind_worker():
            """批量绑卡工作线程 - 支持串行和并行模式"""
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from ..services.email_service.register_config_manager import RegisterConfigManager
            from ..services.email_service.card_manager import CardManager
            
            self.logger.info(f"⏱️ 批量绑卡线程已启动")
            
            try:
                # 设置标志位，表示正在执行批量绑卡
                self._is_batch_binding = True
                
                # 修改按钮文字为停止
                if hasattr(self, 'batch_bind_card_btn'):
                    self.batch_bind_card_btn.setText("⏹️ 停止绑卡")
                
                total = len(selected_accounts)
                success_count = 0
                failed_count = 0
                
                self.logger.info(f"⏱️ 初始化配置...")
                
                # 创建银行卡分配锁
                card_allocation_lock = threading.Lock()
                
                # 初始化注册配置和银行卡管理器（全局共享）
                register_config = RegisterConfigManager()
                
                self.logger.info(f"⏱️ 配置初始化完成")
                
                # 显示进度条并初始化为0/总数
                self.batch_progress_signal.emit(0, 0, total, True)
                
                # 根据模式显示不同的开始信息
                if is_parallel:
                    self.status_message.emit(f"🚀 开始并行绑卡，共 {total} 个账号，并发 {max_concurrent} 个浏览器")
                else:
                    self.status_message.emit(f"🚀 开始串行绑卡，共 {total} 个账号")
                
                from DrissionPage import ChromiumPage, ChromiumOptions
                import traceback
                
                browser = None
                
                try:
                    if is_parallel:
                        # 🔥 并行模式：每个账号使用独立的浏览器实例（无痕模式，Cookie隔离）
                        # 真正的并发执行，多个浏览器同时运行
                        executor = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="BindCard")
                        
                        # 保存executor引用
                        self._batch_bind_executor = executor
                        
                        future_to_account = {}
                        
                        try:
                            # 提交所有任务，每个任务使用独立浏览器（真正并发）
                            for idx, account in enumerate(selected_accounts):
                                # 计算错开延迟：每个任务延迟 0.05 秒（仅避免系统调用冲突）
                                stagger_delay = idx * 0.05
                                
                                future = executor.submit(
                                    self._bind_card_with_separate_browser,
                                    account, 
                                    card_allocation_lock, 
                                    register_config, 
                                    idx + 1,
                                    total,
                                    enable_headless,
                                    stagger_delay  # 轻微错开，实现真并发
                                )
                                future_to_account[future] = account
                            
                            self.logger.info(f"已提交 {len(future_to_account)} 个并行绑卡任务（独立浏览器，真并发）")
                            
                            # 收集结果
                            for future in as_completed(future_to_account):
                                if not self._is_batch_binding:
                                    self.logger.info("🛑 检测到停止信号")
                                    break
                                
                                account = future_to_account[future]
                                email = account.get('email', '未知')
                                
                                try:
                                    result = future.result()
                                    if result:
                                        success_count += 1
                                        self.status_message.emit(f"✅ {email} 绑卡成功 [{success_count + failed_count}/{total}]")
                                    else:
                                        failed_count += 1
                                        self.status_message.emit(f"❌ {email} 绑卡失败 [{success_count + failed_count}/{total}]")
                                    
                                    self.batch_progress_signal.emit(success_count + failed_count, success_count, total, True)
                                    
                                except Exception as e:
                                    failed_count += 1
                                    self.logger.error(f"{email} 绑卡异常: {str(e)}")
                                    self.status_message.emit(f"❌ {email} 绑卡异常: {str(e)}")
                                    self.batch_progress_signal.emit(success_count + failed_count, success_count, total, True)
                        
                        finally:
                            executor.shutdown(wait=True)
                            self.logger.info(f"所有并行任务已完成")
                    
                    else:
                        # 串行模式：创建共享浏览器，逐个处理
                        try:
                            # 创建浏览器实例
                            self.logger.info(f"⏱️ 准备创建浏览器实例...")
                            self.status_message.emit(f"🌐 正在启动浏览器...")
                            
                            co = ChromiumOptions()
                            co.set_argument('--disable-gpu')
                            co.set_argument('--disable-dev-shm-usage')
                            co.set_argument('--window-size=1280,900')
                            co.set_argument('--incognito')  # 无痕模式
                            
                            if enable_headless:
                                # 动态获取真实UA（和browser_manager.py相同的逻辑）
                                ua = self._get_user_agent_for_headless()
                                if not ua:
                                    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                                # 剔除HeadlessChrome标识
                                ua = ua.replace("HeadlessChrome", "Chrome")
                                co.set_user_agent(ua)
                                co.headless(True)
                                self.status_message.emit("🌐 已启用无头模式")
                                self.logger.debug(f"串行浏览器无头模式UA: {ua[:60]}...")
                            
                            co.auto_port()
                            
                            browser = ChromiumPage(addr_or_opts=co)
                            self._batch_bind_browser = browser
                            
                            self.status_message.emit(f"✅ 浏览器已启动")
                            self.logger.info(f"✅ 浏览器创建成功")
                            
                        except Exception as browser_create_error:
                            error_msg = f"浏览器创建失败: {str(browser_create_error)}"
                            self.logger.error(error_msg)
                            self.logger.error(traceback.format_exc())
                            self.status_message.emit(f"❌ {error_msg}")
                            return
                        
                        # 串行处理每个账号
                        for index, account in enumerate(selected_accounts, 1):
                            if not self._is_batch_binding:
                                self.logger.info("🛑 检测到停止信号，退出串行绑卡")
                                self.status_message.emit("🛑 批量绑卡已停止")
                                break
                            
                            email = account.get('email', '未知')
                            self.status_message.emit(f"💳 [{index}/{total}] 正在为 {email} 绑卡...")
                            
                            # 使用默认标签页（第一个账号）或创建新标签页
                            use_default_tab = (index == 1)
                            result = self._bind_card_in_tab(browser, account, card_allocation_lock, register_config, 1, use_default_tab)
                            
                            if result:
                                success_count += 1
                                self.status_message.emit(f"✅ [{index}/{total}] {email} 绑卡成功")
                            else:
                                failed_count += 1
                                self.status_message.emit(f"❌ [{index}/{total}] {email} 绑卡失败")
                            
                            # 更新进度
                            self.batch_progress_signal.emit(index, success_count, total, True)
                            
                            # 串行模式下，每个账号之间等待一下
                            if index < total:
                                wait_time = random.uniform(1, 2)
                                time.sleep(wait_time)
                
                finally:
                    # 清理executor引用
                    if hasattr(self, '_batch_bind_executor'):
                        self._batch_bind_executor = None
                    
                    # 所有任务完成后关闭浏览器
                    if browser:
                        try:
                            browser.quit()
                            self.status_message.emit(f"🔄 浏览器已关闭")
                            self.logger.info(f"浏览器已正常关闭")
                        except Exception as e:
                            self.logger.error(f"关闭浏览器失败: {str(e)}")
                    
                    # 清理浏览器引用
                    if hasattr(self, '_batch_bind_browser'):
                        self._batch_bind_browser = None
                
                # 显示最终统计
                self.status_message.emit(f"✅ 批量绑卡完成！总计 {total} 个，成功 {success_count} 个，失败 {failed_count} 个")
                
                # 最终进度条显示完成状态
                self.batch_progress_signal.emit(total, success_count, total, True)
                
                # 保存当前选中状态
                selected_emails = []
                for row in range(self.accounts_table.rowCount()):
                    checkbox = self.accounts_table.cellWidget(row, 0)
                    if checkbox and checkbox.isChecked():
                        email_item = self.accounts_table.item(row, 2)
                        if email_item:
                            selected_emails.append(email_item.text())
                
                # 刷新UI显示
                from PyQt6.QtCore import QTimer
                
                def refresh_and_restore():
                    self.refresh_table()
                    # 恢复选中状态
                    for row in range(self.accounts_table.rowCount()):
                        email_item = self.accounts_table.item(row, 2)
                        if email_item and email_item.text() in selected_emails:
                            checkbox = self.accounts_table.cellWidget(row, 0)
                            if checkbox:
                                checkbox.setChecked(True)
                    self.logger.info(f"✅ 已恢复 {len(selected_emails)} 个账号的选中状态")
                
                QTimer.singleShot(100, refresh_and_restore)
                self.status_message.emit("🔄 刷新账号列表...")
                
            except Exception as e:
                self.logger.error(f"批量绑卡失败: {str(e)}")
                self.status_message.emit(f"❌ 批量绑卡失败: {str(e)}")
            finally:
                # 清除标志位，允许下次执行
                self._is_batch_binding = False
                
                # 清理引用（防止内存泄漏）
                if hasattr(self, '_batch_bind_browser'):
                    self._batch_bind_browser = None
                if hasattr(self, '_batch_bind_executor'):
                    self._batch_bind_executor = None
                
                # 🔥 立即恢复按钮状态
                self.logger.info("🔄 发送恢复绑卡按钮信号")
                self.reset_bind_card_btn_signal.emit()
                
                # 保持进度条显示30秒后隐藏
                time.sleep(30)
                self.batch_progress_signal.emit(0, 0, 0, False)
        
        # 在后台线程执行
        self.logger.info(f"⏱️ 准备启动批量绑卡后台线程...")
        bind_thread = threading.Thread(target=batch_bind_worker, daemon=True)
        bind_thread.start()
        self.logger.info(f"⏱️ 批量绑卡后台线程已启动")
    
    def _get_user_agent_for_headless(self):
        """获取UserAgent（无头模式专用）- 和browser_manager.py相同的逻辑"""
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            
            # 创建临时浏览器获取UA
            temp_co = ChromiumOptions()
            temp_co.headless(True)
            temp_browser = ChromiumPage(temp_co)
            user_agent = temp_browser.run_js("return navigator.userAgent")
            temp_browser.quit()
            
            return user_agent
        except Exception as e:
            self.logger.debug(f"获取user agent失败: {str(e)}")
            return None
    
    def _bind_card_with_separate_browser(self, account, card_lock, register_config, task_id, total_tasks, enable_headless, delay_seconds=0):
        """
        使用独立浏览器实例进行绑卡（每个账号一个浏览器，完全隔离）
        真正的并发执行，多个浏览器同时运行，仅轻微错开启动避免系统调用冲突
        """
        from ..services.email_service.card_manager import CardManager
        from DrissionPage import ChromiumPage, ChromiumOptions
        import time
        import traceback
        import os
        
        email = account.get('email', '未知')
        card_manager = None
        local_browser = None  # 使用局部变量，不污染self.dashboard_browser
        
        try:
            # 轻微错开启动（避免系统调用冲突，不影响并发性能）
            if delay_seconds > 0:
                self.logger.debug(f"任务{task_id} - {email} 轻微延迟 {delay_seconds:.2f} 秒启动")
                time.sleep(delay_seconds)
            
            # 检查停止信号
            if not self._is_batch_binding:
                return False
            
            self.logger.info(f"🚀 任务{task_id}/{total_tasks} - {email} 开始绑卡")
            self.status_message.emit(f"🚀 任务{task_id}/{total_tasks} - {email} 启动浏览器...")
            
            # 在锁内分配银行卡
            with card_lock:
                card_manager = CardManager(register_config, lambda msg: self.logger.debug(msg))
                card_info = card_manager.get_next_card_info()
                if not card_info:
                    self.logger.warning(f"任务{task_id} - {email} 无可用银行卡")
                    self.status_message.emit(f"❌ 任务{task_id} - {email} 无可用银行卡")
                    return False
                self.logger.info(f"任务{task_id} - {email} 已分配银行卡 ****{card_info['number'][-4:]}")
            
            # 🚀 创建独立的无痕浏览器实例（不使用_open_dashboard_with_cookies以避免并发冲突）
            co = ChromiumOptions()
            co.set_argument('--no-first-run')
            co.set_argument('--no-default-browser-check')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--window-size=1280,900')  # 设置窗口大小，确保页面正常渲染
            co.set_argument('--incognito')  # 无痕模式，确保Cookie隔离
            
            # 禁用代理
            co.set_argument('--no-proxy-server')
            
            if enable_headless:
                # 动态获取真实UA（和browser_manager.py相同的逻辑）
                ua = self._get_user_agent_for_headless()
                if not ua:
                    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                # 剔除HeadlessChrome标识
                ua = ua.replace("HeadlessChrome", "Chrome")
                co.set_user_agent(ua)
                co.headless(True)
                self.logger.debug(f"任务{task_id} - {email} 无头模式UA: {ua[:60]}...")
            
            # 为并行任务分配不同的端口，避免冲突（基础端口9222 + 任务ID * 10）
            port = 9222 + (task_id * 10)
            co.set_local_port(port)
            self.logger.debug(f"任务{task_id} - {email} 使用端口: {port}")
            
            local_browser = ChromiumPage(addr_or_opts=co)
            tab = local_browser.get_tab(1)
            
            self.logger.info(f"✅ 任务{task_id} - {email} 独立浏览器已启动")
            
            # 跳转到空白页（为后续跳转做准备）
            tab.get("about:blank")
            
            # 执行核心绑卡逻辑（直接通过API获取绑卡URL）
            result = self._bind_card_core(tab, account, card_manager, task_id, task_id)
            
            # 根据结果标记银行卡状态
            with card_lock:
                if result == "success":
                    card_manager.mark_card_as_used()
                    self.logger.info(f"任务{task_id} - {email} ✅ 绑卡成功，银行卡已标记为已使用")
                elif result == "failed_in_payment":
                    card_manager.mark_card_as_problematic()
                    self.logger.info(f"任务{task_id} - {email} ⚠️ 进入绑卡页面后失败，银行卡已标记为问题卡")
                else:  # "failed_before_payment"
                    card_manager.release_allocated_card()
                    self.logger.info(f"任务{task_id} - {email} 🔓 未进入绑卡页面，银行卡已释放")
            
            return result == "success"
                
        except Exception as e:
            self.logger.error(f"任务{task_id} - {email} 异常: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            # 释放未使用的银行卡
            if card_manager:
                with card_lock:
                    card_manager.release_allocated_card()
            
            return False
        finally:
            # 关闭独立浏览器实例
            if local_browser:
                try:
                    local_browser.quit()
                    self.logger.info(f"任务{task_id} - {email} 独立浏览器已关闭")
                except Exception as e:
                    self.logger.error(f"任务{task_id} - {email} 关闭浏览器失败: {str(e)}")
    
    def _bind_card_in_tab(self, browser, account, card_lock, register_config, browser_id, use_default_tab=False):
        """
        在已有浏览器中创建新标签页进行绑卡（串行模式）
        串行模式使用共享浏览器，在标签页中直接进行绑卡
        """
        from ..services.email_service.card_manager import CardManager
        import time
        import traceback
        
        email = account.get('email', '未知')
        tab = None
        should_close_tab = True
        card_manager = None
        
        try:
            self.logger.info(f"浏览器#{browser_id} - {email} 开始绑卡流程")
            
            # 在锁内分配银行卡
            with card_lock:
                card_manager = CardManager(register_config, lambda msg: self.logger.debug(msg))
                card_info = card_manager.get_next_card_info()
                
                if not card_info:
                    self.logger.warning(f"浏览器#{browser_id} - {email} 无可用银行卡")
                    self.status_message.emit(f"❌ {email} - 无可用银行卡")
                    return False
                
                self.logger.info(f"浏览器#{browser_id} - {email} 已分配银行卡 ****{card_info['number'][-4:]}")
            
            # 获取或创建标签页
            if use_default_tab:
                tab = browser.latest_tab
                if isinstance(tab, str):
                    tab = browser.get_tab(tab)
                self.logger.info(f"浏览器#{browser_id} - {email} 使用默认标签页")
                should_close_tab = False
            else:
                self.status_message.emit(f"🌐 浏览器#{browser_id} - {email} 创建新标签页...")
                tab = browser.new_tab()
                self.logger.info(f"浏览器#{browser_id} - {email} 新标签页创建成功")
                should_close_tab = True
            
            # 跳转到空白页（为后续跳转做准备）
            tab.get("about:blank")
            
            # 执行核心绑卡逻辑（直接通过API获取绑卡URL）
            result = self._bind_card_core(tab, account, card_manager, browser_id, browser_id)
            
            # 根据结果标记银行卡状态
            with card_lock:
                if result == "success":
                    card_manager.mark_card_as_used()
                    self.logger.info(f"浏览器#{browser_id} - {email} ✅ 绑卡成功，银行卡已标记为已使用")
                elif result == "failed_in_payment":
                    card_manager.mark_card_as_problematic()
                    self.logger.info(f"浏览器#{browser_id} - {email} ⚠️ 进入绑卡页面后失败，银行卡已标记为问题卡")
                else:  # "failed_before_payment"
                    card_manager.release_allocated_card()
                    self.logger.info(f"浏览器#{browser_id} - {email} 🔓 未进入绑卡页面，银行卡已释放")
            
            return result == "success"
                
        except Exception as e:
            import traceback
            self.logger.error(f"浏览器#{browser_id} - {email} 绑卡操作失败: {str(e)}")
            self.logger.error(traceback.format_exc())
            self.status_message.emit(f"❌ 浏览器#{browser_id} - {email} 绑卡失败: {str(e)}")
            
            # 释放未使用的银行卡
            if card_manager:
                with card_lock:
                    card_manager.release_allocated_card()
            
            return False
        finally:
            # 只关闭新创建的标签页，保留默认标签页
            try:
                if tab and should_close_tab:
                    tab.close()
                    self.logger.info(f"浏览器#{browser_id} - {email} 标签页已关闭")
                elif tab and not should_close_tab:
                    self.logger.info(f"浏览器#{browser_id} - {email} 保留默认标签页")
            except Exception as close_error:
                self.logger.error(f"浏览器#{browser_id} - {email} 关闭标签页失败: {str(close_error)}")
    
    def _get_checkout_url(self, account, task_id=1):
        """
        通过API获取绑卡页面URL
        
        Args:
            account: 账号信息
            task_id: 任务ID
            
        Returns:
            tuple: (success, checkout_url)
        """
        import requests
        import json
        
        email = account.get('email', '未知')
        
        try:
            self.logger.info(f"任务{task_id} - {email} 💳 获取绑卡页面URL...")
            
            # 构建Cookie
            workos_token = account.get('WorkosCursorSessionToken', '')
            if not workos_token:
                self.logger.error(f"任务{task_id} - {email} 缺少WorkosCursorSessionToken")
                return False, None
            
            # 处理token格式
            final_token = workos_token.replace('::', '%3A%3A') if '::' in workos_token else workos_token
            full_cookie = f"WorkosCursorSessionToken={final_token}"
            
            checkout_headers = {
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Content-Type": "application/json",
                "Cookie": full_cookie,
                "Origin": "https://cursor.com",
                "Priority": "u=1, i",
                "Referer": "https://cursor.com/dashboard",
                "Sec-Ch-Ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
                "Sec-Ch-Ua-Arch": '"x86"',
                "Sec-Ch-Ua-Bitness": '"64"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Ch-Ua-Platform-Version": '"10.0.0"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            }
            
            checkout_data = {
                "allowAutomaticPayment": True,
                "allowTrial": True,
                "tier": "pro",
            }
            
            self.logger.debug(f"任务{task_id} - {email} 📡 发送POST请求到: https://cursor.com/api/checkout")
            
            checkout_response = requests.post(
                "https://cursor.com/api/checkout",
                headers=checkout_headers,
                json=checkout_data,
                timeout=30
            )
            
            self.logger.debug(f"任务{task_id} - {email} 🔍 绑卡响应状态: {checkout_response.status_code}")
            
            if checkout_response.status_code == 200:
                try:
                    checkout_url = checkout_response.json()
                    self.logger.info(f"任务{task_id} - {email} ✅ 绑卡页面请求成功!")
                    self.logger.debug(f"任务{task_id} - {email} 🔗 绑卡页面URL: {checkout_url[:100]}...")
                    
                    if "checkout.stripe.com" in checkout_url:
                        self.logger.info(f"任务{task_id} - {email} ✅ 检测到Stripe支付页面")
                        return True, checkout_url
                    else:
                        self.logger.warning(f"任务{task_id} - {email} ⚠️ 返回的URL不是预期的Stripe支付页面")
                        return False, None
                        
                except json.JSONDecodeError:
                    self.logger.error(f"任务{task_id} - {email} ⚠️ 响应不是JSON格式: {checkout_response.text[:200]}...")
                    return False, None
            else:
                self.logger.error(f"任务{task_id} - {email} ❌ 绑卡页面请求失败: {checkout_response.status_code}")
                self.logger.debug(f"任务{task_id} - {email} 📄 错误响应: {checkout_response.text[:200]}...")
                return False, None
                
        except Exception as e:
            self.logger.error(f"任务{task_id} - {email} ❌ 绑卡请求异常: {str(e)}")
            return False, None

    def _bind_card_core(self, tab, account, card_manager, task_id=1, browser_id=1):
        """
        核心绑卡逻辑 - 直接通过API获取绑卡URL，简化流程
        
        Args:
            tab: 已打开的标签页对象
            account: 账号信息
            card_manager: 银行卡管理器
            task_id: 任务ID（用于日志）
            browser_id: 浏览器ID（用于日志）
            
        Returns:
            str: 绑卡结果状态
                - "success": 成功进入绑卡页面并绑卡成功
                - "failed_in_payment": 进入绑卡页面但绑卡失败（标记问题卡）
                - "failed_before_payment": 未进入绑卡页面（释放卡片）
        """
        from datetime import datetime
        from ..services.email_service.page_handlers import StripePaymentPageHandler
        from ..services.email_service.page_detector import PageDetector, PageState
        import time
        
        email = account.get('email', '未知')
        
        try:
            # 🚀 直接通过API获取绑卡URL
            self.status_message.emit(f"💳 任务{task_id} - {email} 正在获取绑卡地址...")
            success, checkout_url = self._get_checkout_url(account, task_id)
            
            if not success or not checkout_url:
                self.logger.warning(f"任务{task_id}/浏览器{browser_id} - {email} 获取绑卡URL失败")
                self.status_message.emit(f"⚠️ 任务{task_id} - {email} 获取绑卡地址失败")
                return "failed_before_payment"
            
            self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} ✅ 已获取绑卡URL，准备跳转")
            self.status_message.emit(f"✅ 任务{task_id} - {email} 已获取绑卡地址，正在跳转...")
            
            # 直接跳转到Stripe绑卡页面
            tab.get(checkout_url)
            
            # 等待页面加载并确认进入Stripe页面
            self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} 等待Stripe页面加载...")
            time.sleep(2)  # 给页面加载时间
            
            # 确认已经进入Stripe页面
            page_detector = PageDetector()
            max_wait = 10
            start_time = time.time()
            stripe_detected = False
            
            while time.time() - start_time < max_wait:
                try:
                    current_state = page_detector.analyze_current_page(tab)
                    if current_state == PageState.STRIPE_PAYMENT:
                        stripe_detected = True
                        elapsed = time.time() - start_time
                        self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} ✅ 确认进入Stripe页面（用时{elapsed:.1f}秒）")
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not stripe_detected:
                # 最后再检测一次
                current_state = page_detector.analyze_current_page(tab)
                stripe_detected = (current_state == PageState.STRIPE_PAYMENT)
            
            if stripe_detected:
                self.status_message.emit(f"💳 任务{task_id} - {email} 已进入绑卡页面")
                
                # 等待页面元素完全就绪
                time.sleep(1)
                
                # 调用绑卡处理器
                payment_handler = StripePaymentPageHandler(lambda msg: self.logger.debug(msg))
                success = payment_handler.handle_stripe_payment_page(tab, account, card_manager)
                
                if success:
                    # 更新创建时间
                    success_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    account['created_at'] = success_time
                    
                    # 保存到配置文件
                    accounts = self.config.load_accounts()
                    for acc in accounts:
                        if acc.get('email') == email:
                            acc['created_at'] = success_time
                            self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} 📅 创建时间已更新为: {success_time}")
                            break
                    self.config.save_accounts(accounts)
                    
                    self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} ✅ 绑卡成功")
                    self.status_message.emit(f"✅ 任务{task_id} - {email} 绑卡成功！创建时间: {success_time}")
                    return "success"
                else:
                    self.logger.info(f"任务{task_id}/浏览器{browser_id} - {email} ❌ 进入绑卡页面后绑卡失败")
                    self.status_message.emit(f"❌ 任务{task_id} - {email} 绑卡失败")
                    return "failed_in_payment"
            else:
                self.logger.warning(f"任务{task_id}/浏览器{browser_id} - {email} 跳转后未能确认进入Stripe页面")
                self.status_message.emit(f"⚠️ 任务{task_id} - {email} 未能进入绑卡页面")
                return "failed_before_payment"
                
        except Exception as e:
            import traceback
            self.logger.error(f"任务{task_id}/浏览器{browser_id} - {email} 绑卡操作异常: {str(e)}")
            self.logger.error(traceback.format_exc())
            self.status_message.emit(f"❌ 任务{task_id} - {email} 绑卡失败: {str(e)}")
            return "failed_before_payment"
    
    
    def _cleanup_browser(self, browser):
        """清理浏览器进程，避免程序关闭时卡顿"""
        try:
            if browser:
                self.logger.info("正在清理浏览器进程...")
                browser.quit()
                self.logger.info("✅ 浏览器进程已清理")
        except Exception as e:
            self.logger.warning(f"清理浏览器进程失败: {str(e)}")
    
    def show_account_details(self, account):
        """显示账号详情 - 使用异步加载提升体验"""
        try:
            from .account_detail_dialog import AccountDetailDialog
            
            # 显示进度提示
            email = account.get('email', '未知账号')[:30] + ('...' if len(account.get('email', '')) > 30 else '')
            self.status_message.emit(f"🔍 正在加载账号详情: {email}")
            
            # 创建对话框 - 构造时已经开始异步加载
            dialog = AccountDetailDialog(account, self, self.config)
            
            # 显示对话框 - 即使在加载中也能立即显示基础信息
            dialog.exec()
            
            # 恢复状态消息
            self.status_message.emit("📋 账号详情已关闭")
            
        except Exception as e:
            self.logger.error(f"显示账号详情失败: {str(e)}")
            # 创建自定义样式的错误框
            msgbox = QMessageBox(self)
            msgbox.setIcon(QMessageBox.Icon.Critical)
            msgbox.setWindowTitle("错误")
            msgbox.setText(f"显示详情失败: {str(e)}")
            self._apply_msgbox_style(msgbox)
            msgbox.exec()
            self.status_message.emit("❌ 账号详情加载失败")
    
    
    
    def refresh_single_account_subscription(self, account):
        """刷新单个账号的订阅信息"""
        try:
            email = account.get('email', '未知')
            self.status_message.emit(f"🔄 正在刷新 {email} 的订阅信息...")
            
            # 记录到日志
            self.logger.info(f"开始刷新账号 {email} 的订阅信息")
            
            # 调用真实的订阅刷新API
            if self.cursor_manager.refresh_account_subscription(account):
                # 保存更新后的账号数据
                accounts = self.config.load_accounts()
                for i, acc in enumerate(accounts):
                    if acc.get('email') == email:
                        accounts[i] = account
                        break
                self.config.save_accounts(accounts)
                
                # 刷新表格显示
                self.refresh_table()
                self.status_message.emit(f"✅ {email} 订阅信息刷新成功")
                self.logger.info(f"成功刷新账号 {email} 的订阅信息")
            else:
                self.status_message.emit(f"❌ {email} 订阅信息刷新失败")
                self.logger.warning(f"账号 {email} 订阅刷新失败")
                
        except Exception as e:
            self.logger.error(f"刷新单个账号订阅失败: {str(e)}")
            self.status_message.emit(f"❌ 刷新订阅失败: {str(e)}")
    
    def apply_base_styles(self):
        """应用基础样式表 - 使用固定值，依赖Qt6自动DPI缩放"""
        # 主组件样式
        self.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
            }
        """)
        
        # 如果表格存在，更新表格样式
        if hasattr(self, 'accounts_table'):
            self.accounts_table.setStyleSheet("""
                QTableWidget {
                    background-color: white;
                    border: 1px solid #e9ecef;
                    border-radius: 12px;
                    gridline-color: #f1f3f4;
                    font-size: 13px;
                    selection-background-color: transparent;
                    color: #495057;
                    outline: none;
                }
                QTableWidget::item {
                    padding: 12px 8px;
                    border: none;
                    border-bottom: 1px solid #f8f9fa;
                    text-align: center;
                }
                QTableWidget::item:selected {
                    background: transparent;
                    color: #495057;
                    border: none;
                }
                QTableWidget::item:hover {
                    background: #e8f4fd;
                    color: #1976d2;
                }
                QHeaderView::section {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #f8f9fa, stop: 1 #e9ecef);
                    border: none;
                    border-bottom: 2px solid #dee2e6;
                    border-right: 1px solid #dee2e6;
                    padding: 8px;
                    color: #495057;
                    font-weight: 600;
                    font-size: 11px;
                    text-align: center;
                }
            """)
    
    # ==================== 工具方法 ====================
    
    def update_current_time(self):
        """更新当前时间显示"""
        try:
            from datetime import datetime
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.current_time_label.setText(current_time)
        except Exception as e:
            self.logger.error(f"更新时间显示失败: {str(e)}")
    
    def update_account_count(self):
        """更新账号总数显示"""
        try:
            accounts = self.config.load_accounts()
            count = len(accounts)
            self.account_count_label.setText(f"共 {count} 个账号")
        except Exception as e:
            self.logger.error(f"更新账号总数显示失败: {str(e)}")
            self.account_count_label.setText("共 0 个账号")
    
    def update_selected_count(self):
        """更新选中账号数量显示"""
        try:
            selected_count = 0
            for row in range(self.accounts_table.rowCount()):
                checkbox = self.accounts_table.cellWidget(row, 0)
                if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    selected_count += 1
            
            if selected_count > 0:
                self.selected_count_label.setText(f"已选中 {selected_count} 个")
                self.selected_count_label.setVisible(True)
                # 动态更新全选按钮文字为"取消全选"
                if hasattr(self, 'select_all_btn'):
                    self.select_all_btn.setText("❌ 取消全选")
            else:
                self.selected_count_label.setVisible(False)
                # 动态更新全选按钮文字为"全选"
                if hasattr(self, 'select_all_btn'):
                    self.select_all_btn.setText("✅ 全选")
        except Exception as e:
            self.logger.error(f"更新选中数量显示失败: {str(e)}")
            self.selected_count_label.setVisible(False)
    
    def copy_to_clipboard(self, text: str):
        """复制到剪贴板 - 使用通用工具类"""
        from ..utils.common_utils import CommonUtils
        success = CommonUtils.copy_to_clipboard(text, show_message=True)
        if success:
            self.status_message.emit("已复制到剪贴板")
        else:
            self.status_message.emit("复制失败")
    
    def batch_set_limit(self):
        """批量设置 On-Demand Usage 限额"""
        import threading
        import requests
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton, QRadioButton, QButtonGroup
        
        self.logger.info("💰 用户点击批量设置限额按钮")
        
        # 获取选中的账号
        selected_accounts = []
        for row in range(self.accounts_table.rowCount()):
            checkbox = self.accounts_table.cellWidget(row, 0)
            if checkbox and isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                email_item = self.accounts_table.item(row, 2)
                if email_item:
                    email = email_item.text()
                    accounts = self.config.load_accounts()
                    for acc in accounts:
                        if acc.get('email') == email:
                            selected_accounts.append(acc)
                            break
        
        # 如果没有选中账号，获取所有 Pro 账号
        if not selected_accounts:
            all_accounts = self.config.load_accounts()
            for acc in all_accounts:
                # 判断是否是 Pro 账号
                membership_type = acc.get('membershipType', '').lower()
                individual_type = acc.get('individualMembershipType', '').lower()
                subscription_type = individual_type if individual_type else membership_type
                
                if subscription_type in ['pro', 'professional', 'cursor pro']:
                    selected_accounts.append(acc)
            
            if not selected_accounts:
                self.status_message.emit("⚠️ 未找到 Pro 账号")
                self._show_simple_message("未找到 Pro 账号，请先刷新订阅状态")
                return
            
            self.status_message.emit(f"📊 未选中账号，自动筛选出 {len(selected_accounts)} 个 Pro 账号")
        
        # 弹出配置对话框
        config_dialog = QDialog(self)
        config_dialog.setWindowTitle("设置 On-Demand Usage 限额")
        config_dialog.setFixedSize(450, 250)
        config_dialog.setModal(True)
        
        layout = QVBoxLayout(config_dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel(f"📊 共选中 {len(selected_accounts)} 个账号")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #10b981;")
        layout.addWidget(title_label)
        
        # 操作选择
        mode_group = QButtonGroup()
        
        set_limit_radio = QRadioButton("设置限额")
        set_limit_radio.setChecked(True)
        set_limit_radio.setStyleSheet("font-size: 13px; font-weight: bold;")
        mode_group.addButton(set_limit_radio)
        
        disable_radio = QRadioButton("关闭 On-Demand Usage")
        disable_radio.setStyleSheet("font-size: 13px; font-weight: bold;")
        mode_group.addButton(disable_radio)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(set_limit_radio)
        mode_layout.addWidget(disable_radio)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        # 限额设置
        limit_row = QHBoxLayout()
        limit_label = QLabel("限额金额 (USD):")
        limit_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        limit_row.addWidget(limit_label)
        
        limit_spinbox = QSpinBox()
        limit_spinbox.setRange(1, 10000)
        limit_spinbox.setValue(200)
        limit_spinbox.setStyleSheet("font-size: 13px; min-width: 80px; padding: 4px;")
        limit_row.addWidget(limit_spinbox)
        limit_row.addStretch()
        layout.addLayout(limit_row)
        
        # 提示信息
        info_label = QLabel()
        info_label.setStyleSheet("font-size: 12px; color: #666; padding: 10px; background: #f0fdf4; border-radius: 4px; border-left: 3px solid #10b981;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        def update_info():
            if disable_radio.isChecked():
                info_label.setText("💡 将关闭所有选中账号的 On-Demand Usage 功能")
                limit_label.setEnabled(False)
                limit_spinbox.setEnabled(False)
            else:
                limit = limit_spinbox.value()
                info_label.setText(f"💡 将为所有选中账号设置 ${limit} 的 On-Demand Usage 限额")
                limit_label.setEnabled(True)
                limit_spinbox.setEnabled(True)
        
        set_limit_radio.toggled.connect(update_info)
        disable_radio.toggled.connect(update_info)
        limit_spinbox.valueChanged.connect(update_info)
        update_info()
        
        # 按钮
        button_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(config_dialog.reject)
        cancel_btn.setStyleSheet("background-color: #6c757d; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        button_row.addWidget(cancel_btn)
        
        confirm_btn = QPushButton("确认设置")
        confirm_btn.clicked.connect(config_dialog.accept)
        confirm_btn.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        button_row.addWidget(confirm_btn)
        layout.addLayout(button_row)
        
        # 显示对话框
        if config_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        # 获取配置
        is_disable = disable_radio.isChecked()
        limit_amount = 0 if is_disable else limit_spinbox.value()
        
        def set_limit_worker():
            """设置限额工作线程"""
            try:
                total = len(selected_accounts)
                success_count = 0
                failed_count = 0
                skipped_count = 0
                
                action = "关闭 On-Demand Usage" if is_disable else f"设置限额为 ${limit_amount}"
                self.status_message.emit(f"🚀 开始批量{action}，共 {total} 个账号")
                
                for index, account in enumerate(selected_accounts, 1):
                    email = account.get('email', '未知')
                    
                    # 检查是否有 WorkosCursorSessionToken
                    workos_token = account.get('WorkosCursorSessionToken', '')
                    if not workos_token:
                        self.logger.warning(f"{email} 缺少 WorkosCursorSessionToken，跳过")
                        self.status_message.emit(f"⚠️ [{index}/{total}] {email} - 缺少 Token，跳过")
                        skipped_count += 1
                        continue
                    
                    # 再次检查是否是 Pro 账号
                    membership_type = account.get('membershipType', '').lower()
                    individual_type = account.get('individualMembershipType', '').lower()
                    subscription_type = individual_type if individual_type else membership_type
                    
                    if subscription_type not in ['pro', 'professional', 'cursor pro']:
                        self.logger.warning(f"{email} 不是 Pro 账号 (类型: {subscription_type})，跳过")
                        self.status_message.emit(f"⚠️ [{index}/{total}] {email} - 非 Pro 账号，跳过")
                        skipped_count += 1
                        continue
                    
                    self.status_message.emit(f"💰 [{index}/{total}] 正在为 {email} {action}...")
                    
                    # 调用 API 设置限额
                    result = self._set_hard_limit_api(workos_token, limit_amount, not is_disable)
                    
                    if result.get('success'):
                        success_count += 1
                        self.status_message.emit(f"✅ [{index}/{total}] {email} 设置成功")
                    else:
                        failed_count += 1
                        error_msg = result.get('message', result.get('error', '未知错误'))
                        self.status_message.emit(f"❌ [{index}/{total}] {email} 设置失败: {error_msg[:50]}")
                        self.logger.error(f"{email} 设置限额失败: {error_msg}")
                
                # 显示最终统计
                self.status_message.emit(
                    f"✅ 批量设置完成！总计 {total} 个，"
                    f"成功 {success_count} 个，失败 {failed_count} 个，跳过 {skipped_count} 个"
                )
                
            except Exception as e:
                self.logger.error(f"批量设置限额失败: {str(e)}")
                self.status_message.emit(f"❌ 批量设置限额失败: {str(e)}")
        
        # 在后台线程执行
        self.logger.info("💰 准备启动批量设置限额后台线程...")
        limit_thread = threading.Thread(target=set_limit_worker, daemon=True)
        limit_thread.start()
        self.logger.info("💰 批量设置限额后台线程已启动")
    
    def _set_hard_limit_api(self, workos_token: str, limit_amount: int, enabled: bool = True) -> dict:
        """调用 Cursor API 设置 On-Demand Usage 限额"""
        import requests
        
        try:
            # 构建完整的 cookie
            cookie = f"generaltranslation.locale-routing-enabled=true; NEXT_LOCALE=cn; WorkosCursorSessionToken={workos_token.strip()}"
            
            url = "https://cursor.com/api/dashboard/set-hard-limit"
            headers = {
                "Content-Type": "application/json",
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://cursor.com/cn/dashboard?tab=settings",
                "Origin": "https://cursor.com"
            }
            
            payload = {
                "hardLimit": limit_amount if enabled else 0,
                "noUsageBasedAllowed": not enabled,
                "preserveHardLimitPerUser": False,
                "perUserMonthlyLimitDollars": 0,
                "clearPerUserMonthlyLimitDollars": False
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "status_code": 200,
                    "message": "设置成功"
                }
            else:
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": response.text[:200]
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def delete_account(self, account):
        """删除账号 - 仅删除本地记录"""
        email = account.get('email', '')
        
        # 创建简单的删除确认对话框
        reply = QMessageBox.question(
            self,
            "删除账号",
            f"确定要删除账号 {email} 吗？\n\n注意：仅删除本地记录，不会删除在线账户",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 删除本地记录
                if self.config.remove_account(email):
                    self.load_accounts()
                    self.status_message.emit(f"已删除账号 {email}")
                else:
                    # 创建自定义样式的警告框
                    msgbox = QMessageBox(self)
                    msgbox.setIcon(QMessageBox.Icon.Warning)
                    msgbox.setWindowTitle("失败")
                    msgbox.setText("删除失败")
                    self._apply_msgbox_style(msgbox)
                    msgbox.exec()
            except Exception as e:
                # 创建自定义样式的错误框
                msgbox = QMessageBox(self)
                msgbox.setIcon(QMessageBox.Icon.Critical)
                msgbox.setWindowTitle("错误")
                msgbox.setText(f"删除失败: {str(e)}")
                self._apply_msgbox_style(msgbox)
                msgbox.exec()
    
    def toggle_quick_login(self):
        """切换一键登录状态（开始/停止）"""
        # 检查是否正在登录
        if hasattr(self, 'quick_login_thread') and self.quick_login_thread and self.quick_login_thread.is_alive():
            # 正在登录，点击停止
            self.stop_quick_login()
        else:
            # 未在登录，点击开始
            self.start_quick_login()
    
    def start_quick_login(self):
        """启动一键登录功能"""
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel, QFileDialog
            
            dialog = QDialog(self)
            dialog.setWindowTitle("一键登录 - 邮箱列表")
            dialog.setMinimumWidth(500)
            dialog.setMinimumHeight(450)
            
            layout = QVBoxLayout(dialog)
            
            label = QLabel(
                "<b>📧 请输入要登录的邮箱列表（每行一个）</b><br><br>"
                "<b style='color: #10b981;'>功能说明：</b><ul style='margin: 5px 0;'>"
                "<li>自动登录指定邮箱并保存账号</li>"
                "<li>验证码自动获取（需配置邮箱转发）</li>"
                "<li>登录成功后自动保存到账号列表</li>"
                "<li>不进行绑卡操作，仅获取Token</li>"
                "<li>✅ 已登录的邮箱自动跳过</li>"
                "<li>🛑 支持停止后继续登录</li></ul>"
            )
            label.setWordWrap(True)
            layout.addWidget(label)
            
            text_edit = QTextEdit()
            
            # 检查是否有待登录的邮箱
            pending_emails = self._load_pending_login_emails()
            if pending_emails:
                text_edit.setPlainText('\n'.join(pending_emails))
                self.status_message.emit(f"💡 检测到 {len(pending_emails)} 个待登录邮箱")
            else:
                text_edit.setPlaceholderText("每行一个邮箱，例如:\ntest1@example.com\ntest2@example.com")
            
            layout.addWidget(text_edit)
            
            # 无头模式选择
            from PyQt6.QtWidgets import QCheckBox
            headless_checkbox = QCheckBox("使用无头模式（后台运行，不显示浏览器窗口）")
            headless_checkbox.setChecked(True)
            headless_checkbox.setStyleSheet("font-size: 13px; color: #495057; padding: 8px;")
            layout.addWidget(headless_checkbox)
            
            button_box = QDialogButtonBox()
            import_btn = button_box.addButton("📂 导入文件", QDialogButtonBox.ButtonRole.ActionRole)
            import_btn.clicked.connect(lambda: self._import_emails_from_file(text_edit))
            cancel_btn = button_box.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
            start_btn = button_box.addButton("开始登录", QDialogButtonBox.ButtonRole.AcceptRole)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # 设置按钮样式
            import_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: 500;
                }
                QPushButton:hover { background-color: #5a6268; }
            """)
            
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: 500;
                }
                QPushButton:hover { background-color: #c82333; }
            """)
            
            start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #06b6d4;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: 500;
                }
                QPushButton:hover { background-color: #0891b2; }
            """)
            
            dialog.setStyleSheet("""
                QDialog { background: white; }
                QLabel { font-size: 13px; color: #495057; }
                QTextEdit { border: 1px solid #dee2e6; border-radius: 6px; padding: 8px; font-size: 13px; }
            """)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                email_text = text_edit.toPlainText().strip()
                if not email_text:
                    self.status_message.emit("❌ 未输入任何邮箱")
                    return
                
                email_list = [line.strip() for line in email_text.split('\n') if line.strip() and '@' in line]
                
                if not email_list:
                    self.status_message.emit("❌ 没有有效的邮箱地址")
                    return
                
                # 过滤已登录的邮箱
                email_list = self._filter_logged_emails(email_list)
                
                if not email_list:
                    self.status_message.emit("✅ 所有邮箱都已登录过")
                    return
                
                # 获取无头模式选择
                use_headless = headless_checkbox.isChecked()
                
                self.logger.info(f"✅ 准备登录 {len(email_list)} 个邮箱（无头模式：{use_headless}）")
                self._execute_quick_login(email_list, use_headless)
                
        except Exception as e:
            self.logger.error(f"启动一键登录失败: {str(e)}")
            self.status_message.emit(f"❌ 启动失败: {str(e)}")
    
    def _import_emails_from_file(self, text_edit):
        """从文件导入邮箱"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择邮箱文件", "", "文本文件 (*.txt);;所有文件 (*.*)"
            )
            
            if file_path:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    text_edit.setPlainText(content)
                    
                email_count = len([line for line in content.split('\n') if line.strip() and '@' in line])
                self.status_message.emit(f"✅ 已导入 {email_count} 个邮箱")
        except Exception as e:
            self.logger.error(f"导入邮箱失败: {str(e)}")
            self.status_message.emit(f"❌ 导入失败: {str(e)}")
    
    def _execute_quick_login(self, email_list, use_headless=True):
        """执行批量一键登录"""
        import threading
        
        # 停止标志
        self.quick_login_stop_flag = False
        
        def login_worker():
            try:
                total = len(email_list)
                success_count = 0
                failed_count = 0
                
                mode_text = "无头模式" if use_headless else "有头模式"
                msg = f"🔐 开始一键登录，共 {total} 个邮箱（{mode_text}）..."
                self.status_message.emit(msg)
                self.log_message_signal.emit(msg)
                
                # 创建RegisterConfigManager实例（使用默认路径，与自动注册相同）
                from ..services.email_service.register_config_manager import RegisterConfigManager
                from ..services.email_service.auto_register_engine import AutoRegisterEngine
                
                # 不传config_dir参数，使用默认路径 ~/.xc_cursor/config/
                register_config = RegisterConfigManager()
                
                # 创建引擎，传递正确的配置对象
                engine = AutoRegisterEngine(
                    account_config=self.config,
                    account_manager=self,
                    register_config=register_config  # 传递RegisterConfigManager
                )
                
                # 🔥 保存引擎引用，用于停止时关闭浏览器
                self._current_login_engine = engine
                
                # 设置无头模式
                engine.set_headless_mode(use_headless)
                
                def progress_cb(msg):
                    # 所有详细日志都发送到日志栏
                    self.log_message_signal.emit(msg)
                    # 只有关键消息才发送到状态栏
                    if any(kw in msg for kw in ['开始', '成功', '失败', '完成', '错误', 'Dashboard']):
                        self.status_message.emit(msg)
                
                engine.set_progress_callback(progress_cb)
                
                for idx, email in enumerate(email_list, 1):
                    # 🔥 检查停止标志（优先）
                    if self.quick_login_stop_flag:
                        self.log_message_signal.emit(f"🛑 用户停止，剩余 {total - idx + 1} 个未登录")
                        break
                    
                    # 🔥 更新进度条（使用QTimer确保在主线程执行）
                    progress = int((idx / total) * 100) if total > 0 else 0
                    if hasattr(self, 'operation_progress_bar'):
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(0, lambda p=progress, i=idx, t=total: (
                            self.operation_progress_bar.setMaximum(100),
                            self.operation_progress_bar.setValue(p),
                            self.operation_progress_bar.setFormat(f"登录中 {i}/{t} ({p}%)")
                        ))
                    
                    msg = f"🔐 [{idx}/{total}] 正在登录: {email}"
                    self.status_message.emit(msg)
                    self.log_message_signal.emit(msg)
                    
                    try:
                        success = engine.quick_login_with_email(email)
                        
                        if success:
                            success_count += 1
                            success_msg = f"✅ [{idx}/{total}] {email} 登录成功"
                            self.logger.info(success_msg)
                            self.log_message_signal.emit(success_msg)
                            
                            # 🔥 立即增量更新这个账号（不刷新整个表格）
                            from PyQt6.QtCore import QTimer
                            QTimer.singleShot(0, lambda e=email: self.update_single_account_in_table(e))
                        else:
                            failed_count += 1
                            failed_msg = f"❌ [{idx}/{total}] {email} 登录失败"
                            self.logger.info(failed_msg)
                            self.log_message_signal.emit(failed_msg)
                    
                    except Exception as e:
                        failed_count += 1
                        error_msg = f"❌ [{idx}/{total}] {email} 异常: {str(e)}"
                        self.logger.error(error_msg)
                        self.log_message_signal.emit(error_msg)
                
                # 🔥 重置进度条为待命状态（使用QTimer确保在主线程执行）
                if hasattr(self, 'operation_progress_bar'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: (
                        self.operation_progress_bar.setValue(0),
                        self.operation_progress_bar.setFormat("待命")
                    ))
                
                # 保存未登录的邮箱（用于下次继续）
                self._save_pending_login_emails(email_list[idx:] if self.quick_login_stop_flag else [])
                
                final_msg = f"🎉 一键登录完成！成功 {success_count} 个，失败 {failed_count} 个"
                self.status_message.emit(final_msg)
                self.log_message_signal.emit(final_msg)
                
                # 🔥 优化：不需要刷新UI，因为每个账号登录成功后已经增量更新了
                # 只在最后更新一次账号总数即可
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self.update_account_count)
                
                # 重置停止标志和按钮文字
                self.quick_login_stop_flag = False
                if hasattr(self, 'quick_login_btn'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: self.quick_login_btn.setText("🔐 一键登录"))
                
            except Exception as e:
                error_msg = f"❌ 一键登录失败: {str(e)}"
                self.logger.error(error_msg)
                self.status_message.emit(error_msg)
                self.log_message_signal.emit(error_msg)
        
                # 修改按钮文字
                if hasattr(self, 'quick_login_btn'):
                    self.quick_login_btn.setText("⏹️ 停止登录")
        
        # 保存登录线程引用
        self.quick_login_thread = threading.Thread(target=login_worker, daemon=True)
        self.quick_login_thread.start()
    
    def stop_quick_login(self):
        """停止一键登录 - 第一件事：关闭浏览器"""
        self.quick_login_stop_flag = True
        
        # 🔥 第一步：立即关闭浏览器（最高优先级）
        if hasattr(self, '_current_login_engine') and self._current_login_engine:
            try:
                self.logger.info("🛑 [优先] 正在关闭登录浏览器...")
                self._current_login_engine.stop_registration()  # 这会立即关闭浏览器
                self.logger.info("✅ 登录浏览器已关闭")
            except Exception as e:
                self.logger.error(f"关闭登录浏览器失败: {str(e)}")
        
        self.status_message.emit("🛑 正在停止一键登录...")
        self.log_message_signal.emit("🛑 正在停止一键登录...")
    
    def _mark_email_as_logged_in(self, email: str):
        """标记邮箱为已登录"""
        try:
            config_dir = Path(os.path.expanduser("~")) / '.xc_cursor' / 'config'
            logged_emails_file = config_dir / 'logged_emails.json'
            
            # 加载已登录列表
            logged_emails = set()
            if logged_emails_file.exists():
                with open(logged_emails_file, 'r', encoding='utf-8') as f:
                    logged_emails = set(json.load(f))
            
            # 添加新邮箱
            logged_emails.add(email)
            
            # 保存
            with open(logged_emails_file, 'w', encoding='utf-8') as f:
                json.dump(list(logged_emails), f, ensure_ascii=False, indent=2)
            
            self.logger.debug(f"✅ 标记邮箱为已登录: {email}")
            
        except Exception as e:
            self.logger.error(f"标记邮箱失败: {str(e)}")
    
    def _save_pending_login_emails(self, pending_emails: list):
        """保存待登录的邮箱列表"""
        try:
            if not pending_emails:
                return
            
            config_dir = Path(os.path.expanduser("~")) / '.xc_cursor' / 'config'
            pending_file = config_dir / 'pending_login_emails.json'
            
            with open(pending_file, 'w', encoding='utf-8') as f:
                json.dump(pending_emails, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"💾 保存 {len(pending_emails)} 个待登录邮箱")
            
        except Exception as e:
            self.logger.error(f"保存待登录邮箱失败: {str(e)}")
    
    def _load_pending_login_emails(self) -> list:
        """加载待登录的邮箱列表"""
        try:
            config_dir = Path(os.path.expanduser("~")) / '.xc_cursor' / 'config'
            pending_file = config_dir / 'pending_login_emails.json'
            
            if pending_file.exists():
                with open(pending_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
            
        except Exception as e:
            self.logger.error(f"加载待登录邮箱失败: {str(e)}")
            return []
    
    def _filter_logged_emails(self, email_list: list) -> list:
        """过滤掉已登录的邮箱"""
        try:
            config_dir = Path(os.path.expanduser("~")) / '.xc_cursor' / 'config'
            logged_emails_file = config_dir / 'logged_emails.json'
            
            # 加载已登录列表
            logged_emails = set()
            if logged_emails_file.exists():
                with open(logged_emails_file, 'r', encoding='utf-8') as f:
                    logged_emails = set(json.load(f))
            
            # 过滤
            filtered = [email for email in email_list if email not in logged_emails]
            
            if len(filtered) < len(email_list):
                skipped = len(email_list) - len(filtered)
                self.logger.info(f"🔍 过滤掉 {skipped} 个已登录邮箱")
            
            return filtered
            
        except Exception as e:
            self.logger.error(f"过滤邮箱失败: {str(e)}")
            return email_list
