#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
账号详情对话框 - 显示账号的完整信息
集成绑卡详情和tokens使用情况
"""

import logging
import time
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

# 使用新的API缓存管理器
from ..utils.api_cache_manager import get_api_cache_manager
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QMessageBox, QApplication,
    QGroupBox, QFrame, QWidget, QScrollArea, QLineEdit
)


class LoadAccountInfoThread(QThread):
    """加载账户详细信息的线程"""
    
    # 信号定义
    info_loaded = pyqtSignal(dict)  # 信息加载完成，dict包含data_source字段
    error_occurred = pyqtSignal(str)  # 发生错误
    
    def __init__(self, account: Dict, config=None, force_refresh=False):
        super().__init__()
        self.account = account
        self.config = config
        self.force_refresh = force_refresh  # 是否强制刷新
        self.logger = logging.getLogger(__name__)
        self.data_source = 'local'  # 数据来源：local/cache/api
    
    def run(self):
        """运行线程 - 使用正确的API方法并优化缓存"""
        try:
            from ..services.cursor_service.cursor_manager import CursorManager
            
            # 创建临时的cursor_manager来获取详细信息
            from ..core.config import Config
            temp_config = self.config if self.config else Config()  # 使用传入的配置或创建新的
            cursor_manager = CursorManager(temp_config)
            
            user_id = self.account.get('user_id', '')
            access_token = self.account.get('access_token', '')
            email = self.account.get('email', '')
            
            # 🔧 如果缺少认证信息，尝试从WorkosCursorSessionToken中解析
            if not user_id and not access_token:
                workos_token = self.account.get('WorkosCursorSessionToken', '')
                if workos_token and ('::' in workos_token or '%3A%3A' in workos_token):
                    # 🔥 修复：只提取user_id，access_token应该来自account数据本身
                    separator = '::' if '::' in workos_token else '%3A%3A'
                    parts = workos_token.split(separator, 1)
                    if len(parts) >= 1 and not user_id:
                        user_id = parts[0]
                # access_token应该直接从account中获取，而不是拆分WorkosCursorSessionToken
                        self.logger.info(f"从WorkosCursorSessionToken解析认证信息: user_id={user_id[:20]}...")
            
            if not user_id or not access_token:
                self.error_occurred.emit("账号缺少必要的认证信息")
                return
            
            # 根据force_refresh决定是否强制调用API
            usage_data = None
            
            if self.force_refresh:
                # 强制刷新：直接调用API
                self.logger.info("🔄 强制刷新：调用API获取最新用量...")
                cache_manager = get_api_cache_manager()
                usage_data = cursor_manager._get_model_usage_from_api(user_id, access_token, self.account)
                if usage_data:
                    # 更新缓存和account数据
                    cache_manager.set_cached_data(user_id, access_token, 'usage', usage_data)
                    self.account['modelUsageData'] = usage_data
                    self.data_source = 'api'  # 标记为API数据
                    self.logger.info(f"✅ 强制刷新成功: ${usage_data.get('totalCostUSD', 0):.2f}")
                    
                    # 🔥 同时刷新订阅信息，确保数据一致
                    try:
                        cursor_manager.refresh_account_subscription(self.account)
                        self.logger.info("✅ 同步刷新订阅信息成功")
                    except Exception as sub_err:
                        self.logger.warning(f"订阅信息刷新失败: {str(sub_err)}")
                else:
                    self.logger.warning("⚠️ 强制刷新失败")
            else:
                # 正常模式：优先使用本地数据
                usage_data = self.account.get('modelUsageData')
                
                if usage_data:
                    self.data_source = 'local'  # 本地数据
                    self.logger.info(f"📦 使用配置文件中的用量数据: ${usage_data.get('totalCostUSD', 0):.2f}")
                else:
                    # 如果配置文件没有，尝试从缓存读取
                    cache_manager = get_api_cache_manager()
                    usage_data = cache_manager.get_cached_data(user_id, access_token, 'usage', ttl=600)
                    
                    if usage_data:
                        self.data_source = 'cache'  # 缓存数据
                        self.logger.info(f"📦 使用缓存的用量数据: ${usage_data.get('totalCostUSD', 0):.2f}")
                    else:
                        # 最后才调用API（只有在没有任何缓存时）
                        self.data_source = 'api'  # API数据
                        self.logger.info("📡 没有本地数据，开始调用API获取用量...")
                        usage_data = cursor_manager._get_model_usage_from_api(user_id, access_token, self.account)
                        if usage_data:
                            cache_manager.set_cached_data(user_id, access_token, 'usage', usage_data)
                            self.account['modelUsageData'] = usage_data
                            self.logger.info(f"✅ 使用量数据获取成功: ${usage_data.get('totalCostUSD', 0):.2f}")
                        else:
                            self.logger.warning("⚠️ 使用量数据获取失败")
            
            if usage_data:
                # 🚀 简化：使用量数据构建信息
                info = {
                    'email': email,
                    'user_id': user_id,
                    'membership_type': 'pro',  # 默认值，不依赖订阅API
                    'subscription_status': 'active',  # 默认值
                    'trial_days': 0,  # 默认值
                    'usage_data': usage_data,
                    'subscription_data': {},  # 空数据
                    'total_cost': usage_data.get('totalCostUSD', 0) if usage_data else 0,
                    'used_models': usage_data.get('usedModels', []) if usage_data else [],
                    'data_source': self.data_source  # 标记数据来源
                }
                self.info_loaded.emit(info)
            else:
                # 🎯 即使没有使用量数据也返回基本信息
                info = {
                    'email': email,
                    'user_id': user_id,
                    'membership_type': 'pro',
                    'data_source': self.data_source,  # 标记数据来源
                    'subscription_status': 'active', 
                    'trial_days': 0,
                    'usage_data': {},
                    'subscription_data': {},
                    'total_cost': 0,
                    'used_models': []
                }
                self.info_loaded.emit(info)
                
        except Exception as e:
            self.logger.error(f"加载账户信息失败: {str(e)}")
            self.error_occurred.emit(f"加载失败: {str(e)}")


class AccountDetailDialog(QDialog):
    """账号详情对话框"""
    
    def __init__(self, account: Dict, parent=None, config=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        # 确保account是字典类型，避免类型错误
        if not isinstance(account, dict):
            self.logger.error(f"账号数据类型错误: {type(account)}, 期望: dict")
            self.account = {}
        else:
            # 🔥 关键修复：从配置文件重新加载最新数据，确保显示转换后的JWT
            email = account.get('email', '')
            user_id = account.get('user_id', '')
            
            if email and config:
                # 从配置文件重新加载该账号的最新数据
                all_accounts = config.load_accounts()
                fresh_account = None
                
                for acc in all_accounts:
                    if acc.get('email') == email or (user_id and acc.get('user_id') == user_id):
                        fresh_account = acc
                        break
                
                if fresh_account:
                    self.account = fresh_account
                    self.logger.debug(f"✅ 从配置文件重新加载账号数据: {email}")
                else:
                    self.account = account
                    self.logger.warning(f"⚠️ 未找到账号，使用传入数据: {email}")
            else:
                self.account = account
        
        self.load_thread = None
        self.account_info = None
        self.data_source = 'local'  # 记录数据来源：local/cache/api
        self.data_updated = False  # 记录是否调用了API更新数据
        
        # 初始化UI组件（稍后动态更新）
        self.subscription_status_label = None
        self.trial_days_label = None
        self.usage_progress = None
        self.usage_text_label = None
        self.gpt4_progress = None
        self.gpt4_text_label = None
        self.gpt35_text_label = None
        self.customer_email_label = None
        self.subscription_detail_text = None
        self.cost_value_label = None  # 精简版：费用标签引用，用于动态更新
        
        # 精简版：立即显示基本UI，然后懒加载API数据
        self.init_ui()
        self.load_detailed_info()
    
    def _calculate_pro_remaining_days(self, account: Dict) -> Optional[int]:
        """计算Pro账号剩余天数（创建时间 + 14天 - 当前时间）"""
        try:
            from datetime import datetime, timedelta
            
            # 🔥 修复：只使用created_at字段（账号真实创建时间），不使用registerTimeStamp（导入时间）
            created_at = account.get('created_at') or account.get('register_time')
            if not created_at:
                return None
            
            # 解析时间字符串
            try:
                # 处理 "MM-DD HH:MM" 格式（需要补充年份）
                if isinstance(created_at, str):
                    # 如果是短格式（如 "08-28 08:51"），补充当前年份
                    if len(created_at) <= 14 and '-' in created_at[:5]:
                        current_year = datetime.now().year
                        created_at = f"{current_year}-{created_at}"
                    
                    # 解析完整格式
                    if len(created_at) >= 16:  # YYYY-MM-DD HH:MM 或更长
                        created_time = datetime.strptime(created_at[:16], '%Y-%m-%d %H:%M')
                    else:
                        return None
                else:
                    return None
            except Exception as parse_error:
                self.logger.warning(f"时间解析失败 {created_at}: {parse_error}")
                return None
            
            # 计算Pro过期时间（创建时间 + 14天）
            expiry_time = created_time + timedelta(days=14)
            
            # 计算剩余天数
            now = datetime.now()
            days_remaining = (expiry_time - now).days + 1  # +1确保当天算作1天
            
            return max(0, days_remaining)  # 不返回负数
        except Exception as e:
            self.logger.warning(f"计算Pro剩余天数失败: {e}")
            return None
    
    def init_ui(self):
        """初始化现代化UI"""
        self.setWindowTitle("账号详情")
        self.setMinimumSize(850, 420)
        self.setMaximumSize(850, 650)
        self.resize(850, 460)
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
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
        """)
        
        # 主布局（防止重复）
        if self.layout() is None:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(12, 12, 12, 12)
            main_layout.setSpacing(10)
        else:
            main_layout = self.layout()
        
        # 标题区域
        title_frame = QFrame()
        title_frame.setStyleSheet("background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #3b82f6, stop: 1 #1d4ed8); border-radius: 8px;")
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(18, 15, 18, 15)
        
        title_label = QLabel("📋 账号详情")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white; border: none;")
        title_layout.addWidget(title_label)
        
        email = self.account.get('email', '未知')
        title_email = QLabel(email)
        title_email.setStyleSheet("font-size: 13px; color: #e2e8f0; border: none;")
        title_layout.addWidget(title_email)
        title_layout.addStretch()
        
        # 添加刷新按钮
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setFixedSize(80, 32)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 6px;
                color: white;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.5);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        refresh_btn.setToolTip("强制刷新当前账号信息")
        refresh_btn.clicked.connect(self.manual_refresh)
        title_layout.addWidget(refresh_btn)
        
        main_layout.addWidget(title_frame)
        
        # 左右分栏布局（左边：模型使用，右边：基本信息）
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        
        # 创建左右两个布局
        left_layout = QVBoxLayout()   # 基本信息
        right_layout = QVBoxLayout()  # 模型使用情况
        
        # ========== 左侧：基本信息 ==========
        basic_group = QGroupBox("📊 基本信息")
        basic_group.setFixedWidth(435)
        basic_layout = QVBoxLayout(basic_group)
        basic_layout.setSpacing(10)
        basic_layout.setContentsMargins(12, 18, 12, 15)
        basic_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 使用网格布局（3列，方案A优化：值框170px，按钮120px，间距8px）
        password = self.account.get('password', '')
        
        # 第1行：邮箱（3列，深蓝色系，可编辑）
        if password:
            # 账号密码模式：复制账密按钮
            email_row = self.create_editable_grid_row("邮箱", email, "复制账密", lambda: self._copy_to_clipboard(f"{self.email_input.text()}\n{password}"), "#2563eb", "#93c5fd", field_name="email")
        else:
            # 验证码模式：复制邮箱
            email_row = self.create_editable_grid_row("邮箱", email, "复制邮箱", lambda: self._copy_to_clipboard(self.email_input.text()), "#2563eb", "#93c5fd", field_name="email")
        basic_layout.addLayout(email_row)
        
        # 第2行：密码（仅账号密码模式，3列，橙色系）
        if password:
            password_row = self.create_password_grid_row("密码", password, "#f97316", "#fdba74")
            basic_layout.addLayout(password_row)
        
        # 第3行：Session JWT（3列，青色系，可编辑）
        access_token = self.account.get('access_token', '')
        if access_token:
            token_display = f"eyJ...{access_token[-10:]}" if len(access_token) > 20 else access_token
            jwt_row = self.create_editable_grid_row("Session JWT", token_display, "复制", lambda: self._copy_to_clipboard(self.jwt_input.text()), "#0891b2", "#67e8f9", field_name="jwt", full_value=access_token)
            basic_layout.addLayout(jwt_row)
        
        # 第4行：WorkosToken（3列）
        user_id = self.account.get('user_id', '')
        workos_token = self.account.get('WorkosCursorSessionToken', '')
        
        if workos_token:
            full_cookie = workos_token if '%3A%3A' in workos_token or '::' in workos_token else workos_token
            full_cookie = full_cookie.replace('::', '%3A%3A') if '::' in full_cookie else full_cookie
        elif user_id and access_token:
            full_cookie = f"{user_id}%3A%3A{access_token}"
        else:
            full_cookie = "未获取"
        
        if full_cookie != "未获取" and len(full_cookie) > 50:
            separator_pos = full_cookie.find('%3A%3A')
            if separator_pos > 0:
                user_part = full_cookie[:separator_pos]
                token_part = full_cookie[separator_pos + 6:]
                session_display = f"{user_part}%3A%3A...{token_part[-8:]}"
            else:
                session_display = f"{full_cookie[:20]}...{full_cookie[-8:]}"
        else:
            session_display = full_cookie
        
        workos_row = self.create_editable_grid_row("WorkosToken", session_display, "复制", lambda: self._copy_to_clipboard(self.workos_input.text()), "#db2777", "#f9a8d4", field_name="workos", full_value=full_cookie)
        basic_layout.addLayout(workos_row)
        
        # 第5行：令牌有效性（3列）
        token_expired = self.account.get('token_expired', False)
        validity_text = "有效" if not token_expired else "已过期"
        validity_color = "#10b981" if not token_expired else "#ef4444"
        validity_row = self.create_grid_row_2col("令牌有效性", validity_text, validity_color, "#059669", "#6ee7b7")
        basic_layout.addLayout(validity_row)
        
        # 第6行：订阅状态（3列）
        subscription_type = self.account.get('membershipType', 'free')
        trial_days = self.account.get('trialDaysRemaining', self.account.get('daysRemainingOnTrial', 0))
        
        if trial_days > 0:
            status_text = f"试用剩余 {trial_days} 天"
            status_color = "#f59e0b"
        elif subscription_type.lower() in ['pro', 'professional']:
            # 计算Pro剩余天数
            pro_days_remaining = self._calculate_pro_remaining_days(self.account)
            if pro_days_remaining is not None and pro_days_remaining > 0:
                if pro_days_remaining <= 7:
                    status_text = f"Pro会员 (剩余{pro_days_remaining}天)"
                    status_color = "#10b981" if pro_days_remaining > 3 else "#f59e0b" if pro_days_remaining > 1 else "#ef4444"
                else:
                    status_text = "Pro会员"
                    status_color = "#10b981"
            else:
                status_text = "Pro会员"
                status_color = "#10b981"
        else:
            status_text = subscription_type.title() if subscription_type else "未知"
            status_color = "#6b7280"
        
        subscription_row = self.create_grid_row_2col("订阅状态", status_text, status_color, "#7c3aed", "#c4b5fd")
        basic_layout.addLayout(subscription_row)
        
        left_layout.addWidget(basic_group)
        
        # ========== 右侧：模型使用情况（2列网格）==========
        usage_group = QGroupBox("💰 模型使用情况")
        usage_group.setFixedWidth(375)
        usage_layout = QVBoxLayout(usage_group)
        usage_layout.setSpacing(10)
        usage_layout.setContentsMargins(12, 18, 12, 15)
        usage_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 第1行：总费用（2列）
        cost_row = QHBoxLayout()
        cost_row.setSpacing(8)
        
        cost_label_box = QFrame()
        cost_label_box.setFixedSize(165, 45)
        cost_label_box.setStyleSheet("QFrame { background: transparent; border: 1px dashed #dc2626; border-radius: 5px; }")
        cost_label_layout = QHBoxLayout(cost_label_box)
        cost_label_layout.setContentsMargins(0, 0, 0, 0)
        cost_label_text = QLabel("总费用")
        cost_label_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cost_label_text.setStyleSheet("color: #dc2626; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        cost_label_layout.addWidget(cost_label_text)
        cost_row.addWidget(cost_label_box)
        
        # 值框：直接用 QLabel 画边框，避免容器叠加导致双边框
        self.cost_value_label = QLabel("加载中...")
        self.cost_value_label.setFixedSize(175, 45)
        self.cost_value_label.setStyleSheet("background: #fafafa; border: 1px solid #fca5a5; border-radius: 5px; padding-left: 12px; padding-right: 12px; font-size: 16px; font-weight: bold; color: #dc2626;")
        self.cost_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cost_row.addWidget(self.cost_value_label)
        usage_layout.addLayout(cost_row)
        
        # 第2行：请求次数（2列）
        requests_row = QHBoxLayout()
        requests_row.setSpacing(8)
        
        requests_label_box = QFrame()
        requests_label_box.setFixedSize(165, 45)
        requests_label_box.setStyleSheet("QFrame { background: transparent; border: 1px dashed #4f46e5; border-radius: 5px; }")
        requests_label_layout = QHBoxLayout(requests_label_box)
        requests_label_layout.setContentsMargins(0, 0, 0, 0)
        requests_label_text = QLabel("请求次数")
        requests_label_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        requests_label_text.setStyleSheet("color: #4f46e5; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        requests_label_layout.addWidget(requests_label_text)
        requests_row.addWidget(requests_label_box)
        
        # 值框：直接用 QLabel 画边框
        self.requests_value_label = QLabel("加载中...")
        self.requests_value_label.setFixedSize(175, 45)
        self.requests_value_label.setStyleSheet("background: #fafafa; border: 1px solid #a5b4fc; border-radius: 5px; padding-left: 12px; padding-right: 12px; font-size: 13px; color: #1f2937;")
        self.requests_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        requests_row.addWidget(self.requests_value_label)
        usage_layout.addLayout(requests_row)
        
        # 模型列表容器
        self.models_container = QVBoxLayout()
        self.models_container.setSpacing(8)
        self.models_container.setAlignment(Qt.AlignmentFlag.AlignTop)  # 顶部对齐
        usage_layout.addLayout(self.models_container)
        usage_layout.addStretch()
        
        right_layout.addWidget(usage_group)
        
        # 添加到主布局（左：基本信息，右：模型）
        content_layout.addLayout(left_layout)
        content_layout.addLayout(right_layout)
        main_layout.addLayout(content_layout)
        main_layout.addStretch()  # 只在底部拉伸
    
    def create_usage_row(self, label_text: str, value_label_widget, bg_color: str):
        """创建使用情况行（2列，使用已创建的标签widget）"""
        row = QHBoxLayout()
        row.setSpacing(6)
        
        # 标签框
        label_box = QFrame()
        label_box.setFixedSize(100, 35)
        label_box.setStyleSheet(f"QFrame {{ background: {bg_color}; border-radius: 5px; }}")
        label_layout = QHBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet("color: white; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 10px;")
        label_layout.addWidget(label)
        row.addWidget(label_box)
        
        # 值框
        value_box = QFrame()
        value_box.setFixedSize(195, 35)
        value_box.setStyleSheet("QFrame { background: #fafafa; border: 1px solid #d1d5db; border-radius: 5px; }")
        value_layout = QHBoxLayout(value_box)
        value_layout.setContentsMargins(10, 0, 10, 0)
        
        # 配置标签样式
        if label_text == "总费用":
            value_label_widget.setStyleSheet("font-size: 14px; font-weight: bold; color: #dc2626; background: transparent; border: none;")
        else:
            value_label_widget.setStyleSheet("font-size: 12px; color: #1f2937; background: transparent; border: none;")
        value_label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        value_layout.addWidget(value_label_widget)
        value_layout.addStretch()
        row.addWidget(value_box)
        
        return row
    
    def create_grid_row_2col(self, label_text: str, value_text: str, value_color: str = None, label_border_color: str = "#6366f1", value_border_color: str = "#d1d5db"):
        """创建2列网格行（无按钮行，支持自定义边框颜色）"""
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # 标签框（左边第1列）
        label_box = QFrame()
        label_box.setFixedSize(120, 45)
        label_box.setStyleSheet(f"QFrame {{ background: transparent; border: 1px dashed {label_border_color}; border-radius: 5px; }}")
        label_layout = QHBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"color: {label_border_color}; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        label_layout.addWidget(label)
        row.addWidget(label_box)
        
        # 值框（左边第2+3列合并，缩短到278px避免超出边界）
        value_box = QFrame()
        value_box.setFixedSize(280, 45)
        value_box.setStyleSheet(f"QFrame {{ background: #fafafa; border: 1px solid {value_border_color}; border-radius: 5px; }}")
        value_layout = QHBoxLayout(value_box)
        value_layout.setContentsMargins(8, 0, 8, 0)
        value = QLabel(value_text)
        if value_color:
            value.setStyleSheet(f"color: {value_color}; font-weight: bold; font-size: 13px; background: transparent; border: none;")
        else:
            value.setStyleSheet("color: #1f2937; font-size: 13px; background: transparent; border: none;")
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value.setWordWrap(False)
        value_layout.addWidget(value)
        value_layout.addStretch()
        row.addWidget(value_box)
        
        return row
    
    def create_grid_row_3col(self, label_text: str, value_text: str, button_text: str, button_action, label_border_color: str = "#8b5cf6", value_border_color: str = "#d1d5db"):
        """创建3列网格行（有按钮行，支持自定义边框颜色）- 方案A优化布局"""
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # 标签框（左边第1列）
        label_box = QFrame()
        label_box.setFixedSize(120, 45)
        label_box.setStyleSheet(f"QFrame {{ background: transparent; border: 1px dashed {label_border_color}; border-radius: 5px; }}")
        label_layout = QHBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"color: {label_border_color}; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        label_layout.addWidget(label)
        row.addWidget(label_box)
        
        # 值框（左边第2列，缩小到170px）
        value_box = QFrame()
        value_box.setFixedSize(210, 45)
        value_box.setStyleSheet(f"QFrame {{ background: #fafafa; border: 1px solid {value_border_color}; border-radius: 5px; }}")
        value_layout = QHBoxLayout(value_box)
        value_layout.setContentsMargins(10, 0, 10, 0)
        value = QLabel(value_text)
        value.setStyleSheet("color: #1f2937; font-size: 13px; background: transparent; border: none;")
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value.setWordWrap(False)
        value_layout.addWidget(value)
        value_layout.addStretch()
        row.addWidget(value_box)
        
        # 按钮（左边第3列，扩大到120px）
        btn = QPushButton(button_text)
        btn.setFixedSize(60, 45)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3b82f6;
                border: none;
                text-align: left;
                padding: 0px;
                margin: 0px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #2563eb;
                text-decoration: underline;
            }
        """)
        btn.clicked.connect(button_action)
        row.addWidget(btn)
        
        return row
    
    def create_editable_grid_row(self, label_text: str, value_text: str, button_text: str, button_action, label_border_color: str = "#8b5cf6", value_border_color: str = "#d1d5db", field_name: str = "", full_value: str = ""):
        """创建可编辑的3列网格行"""
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # 标签框
        label_box = QFrame()
        label_box.setFixedSize(120, 45)
        label_box.setStyleSheet(f"QFrame {{ background: transparent; border: 1px dashed {label_border_color}; border-radius: 5px; }}")
        label_layout = QHBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"color: {label_border_color}; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        label_layout.addWidget(label)
        row.addWidget(label_box)
        
        # 可编辑值框
        value_input = QLineEdit()
        value_input.setFixedSize(210, 45)
        value_input.setText(full_value if full_value else value_text)
        value_input.setStyleSheet(f"""
            QLineEdit {{
                background: #fafafa;
                border: 1px solid {value_border_color};
                border-radius: 5px;
                padding: 0 10px;
                color: #1f2937;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 2px solid {label_border_color};
                background: #ffffff;
            }}
        """)
        value_input.setPlaceholderText(f"输入{label_text}")
        
        # 保存对应的输入框引用
        if field_name == "email":
            self.email_input = value_input
        elif field_name == "jwt":
            self.jwt_input = value_input
        elif field_name == "workos":
            self.workos_input = value_input
        
        # 编辑完成后自动保存
        value_input.editingFinished.connect(lambda: self._auto_save_field(field_name, value_input.text()))
        
        row.addWidget(value_input)
        
        # 按钮
        btn = QPushButton(button_text)
        btn.setFixedSize(60, 45)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3b82f6;
                border: none;
                text-align: left;
                padding: 0px;
                margin: 0px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #2563eb;
                text-decoration: underline;
            }
        """)
        btn.clicked.connect(button_action)
        row.addWidget(btn)
        
        return row
    
    def create_password_grid_row(self, label_text: str, password: str, label_border_color: str = "#f59e0b", value_border_color: str = "#d1d5db"):
        """创建密码行（3列：标签+值+查看并复制按钮，支持自定义边框颜色）- 方案A优化布局"""
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # 标签框（与其他行统一）
        label_box = QFrame()
        label_box.setFixedSize(120, 45)
        label_box.setStyleSheet(f"QFrame {{ background: transparent; border: 1px dashed {label_border_color}; border-radius: 5px; }}")
        label_layout = QHBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"color: {label_border_color}; font-weight: bold; font-size: 13px; background: transparent; border: none; padding-left: 12px;")
        label_layout.addWidget(label)
        row.addWidget(label_box)
        
        # 值框（缩小到170px）
        value_box = QFrame()
        value_box.setFixedSize(210, 45)
        value_box.setStyleSheet(f"QFrame {{ background: #fafafa; border: 1px solid {value_border_color}; border-radius: 5px; }}")
        value_layout = QHBoxLayout(value_box)
        value_layout.setContentsMargins(10, 0, 10, 0)
        password_label = QLabel("*" * 12)
        password_label.setStyleSheet("color: #1f2937; font-size: 13px; background: transparent; border: none;")
        password_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        password_label.setProperty("is_visible", False)
        password_label.setProperty("real_password", password)
        value_layout.addWidget(password_label)
        value_layout.addStretch()
        row.addWidget(value_box)
        
        # 查看并复制按钮（扩大到120px）
        view_copy_btn = QPushButton("查看并复制")
        view_copy_btn.setFixedSize(60, 45)
        view_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_copy_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3b82f6;
                border: none;
                text-align: left;
                padding: 0px;
                margin: 0px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #2563eb;
                text-decoration: underline;
            }
        """)
        
        def view_and_copy():
            password_label.setText(password)
            password_label.setProperty("is_visible", True)
            self._copy_to_clipboard(password)
        
        view_copy_btn.clicked.connect(view_and_copy)
        row.addWidget(view_copy_btn)
        
        return row
    
    def create_info_box(self, label_text: str, value_text: str, button_text: str = None, color: str = None):
        """创建固定大小的信息框"""
        # 外层容器（固定大小）
        box = QFrame()
        box.setFixedSize(410, 50)  # 固定宽度410，高度50
        box.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
        """)
        
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(10)
        
        # 标签
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(140)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px; background: transparent; border: none;")
        box_layout.addWidget(label)
        
        # 值
        value = QLabel(value_text)
        value.setFixedWidth(150)
        if color:
            value.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px; background: transparent; border: none;")
        else:
            value.setStyleSheet("color: #1f2937; font-size: 14px; background: transparent; border: none;")
        value.setWordWrap(False)
        box_layout.addWidget(value)
        
        # 复制按钮
        if button_text:
            copy_btn = QPushButton(button_text)
            copy_btn.setFixedSize(50, 26)
            copy_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    font-size: 11px;
                    padding: 4px 8px;
                    border: none;
                    border-radius: 4px;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
            copy_btn.clicked.connect(lambda: self._copy_to_clipboard(value_text))
            box_layout.addWidget(copy_btn)
        
        box_layout.addStretch()
        return box
    
    def _get_jwt_type(self, token: str) -> Optional[str]:
        """
        获取JWT token的类型
        
        Args:
            token: JWT token字符串
            
        Returns:
            str: token类型（如"session", "web"等），失败时返回None
        """
        try:
            from ..utils.common_utils import CommonUtils
            payload = CommonUtils.decode_jwt_payload(token)
            return payload.get('type') if payload else None
        except Exception as e:
            self.logger.warning(f"解析JWT type失败: {str(e)}")
            return None
    
    def create_info_box_with_copy(self, label_text: str, display_text: str, copy_text: str, color: str = None):
        """创建固定大小的信息框（带复制功能）"""
        box = QFrame()
        box.setFixedSize(410, 50)
        box.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
        """)
        
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(10)
        
        # 标签
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(140)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px; background: transparent; border: none;")
        box_layout.addWidget(label)
        
        # 值
        value = QLabel(display_text)
        value.setFixedWidth(150)
        if color:
            value.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px; background: transparent; border: none;")
        else:
            value.setStyleSheet("color: #1f2937; font-size: 14px; background: transparent; border: none;")
        value.setWordWrap(False)
        box_layout.addWidget(value)
        
        # 复制按钮
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(50, 26)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                font-size: 11px;
                padding: 4px 8px;
                border: none;
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(copy_text))
        box_layout.addWidget(copy_btn)
        
        box_layout.addStretch()
        return box
    
    def create_info_row_with_copy(self, label_text: str, display_text: str, copy_text: str, color: str = None):
        """创建信息行，支持显示内容和复制内容不同"""
        row_layout = QHBoxLayout()
        
        # 标签（固定宽度180）
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(180)
        label.setStyleSheet("font-weight: bold; color: #374151;")
        row_layout.addWidget(label)
        
        # 值（固定宽度260，超出省略）
        value = QLabel(display_text)
        value.setFixedWidth(260)
        if color:
            value.setStyleSheet(f"color: {color}; font-weight: bold;")
        else:
            value.setStyleSheet("color: #1f2937;")
        value.setWordWrap(False)
        row_layout.addWidget(value)
        
        # 复制按钮
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(50, 28)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                font-size: 11px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(copy_text))
        row_layout.addWidget(copy_btn)
        
        row_layout.addStretch()
        return row_layout
    
    def create_password_box(self, label_text: str, password: str):
        """创建固定大小的密码框（带查看按钮）"""
        box = QFrame()
        box.setFixedSize(410, 50)
        box.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
        """)
        
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(8)
        
        # 标签
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(140)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px; background: transparent; border: none;")
        box_layout.addWidget(label)
        
        # 密码值
        password_label = QLabel("*" * 12)
        password_label.setFixedWidth(100)
        password_label.setStyleSheet("color: #1f2937; font-size: 14px; background: transparent; border: none;")
        password_label.setProperty("is_visible", False)
        password_label.setProperty("real_password", password)
        box_layout.addWidget(password_label)
        
        # 查看按钮
        view_btn = QPushButton("查看")
        view_btn.setFixedSize(45, 26)
        view_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                font-size: 10px;
                padding: 4px;
                border: none;
                border-radius: 4px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        
        def toggle_password():
            is_visible = password_label.property("is_visible")
            if is_visible:
                password_label.setText("*" * 12)
                view_btn.setText("查看")
                password_label.setProperty("is_visible", False)
            else:
                password_label.setText(password)
                view_btn.setText("隐藏")
                password_label.setProperty("is_visible", True)
        
        view_btn.clicked.connect(toggle_password)
        box_layout.addWidget(view_btn)
        
        # 复制按钮
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(45, 26)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                font-size: 10px;
                padding: 4px;
                border: none;
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(password))
        box_layout.addWidget(copy_btn)
        
        box_layout.addStretch()
        return box
    
    def create_password_row(self, label_text: str, password: str):
        """创建密码行，带查看按钮"""
        row_layout = QHBoxLayout()
        
        # 标签（固定宽度120）
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(120)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 12px;")
        row_layout.addWidget(label)
        
        # 密码值（固定宽度180）
        password_label = QLabel("*" * 12)
        password_label.setFixedWidth(180)
        password_label.setStyleSheet("color: #1f2937; font-size: 12px;")
        password_label.setProperty("is_visible", False)
        password_label.setProperty("real_password", password)
        row_layout.addWidget(password_label)
        
        # 查看按钮
        view_btn = QPushButton("查看")
        view_btn.setFixedSize(50, 28)
        view_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                font-size: 11px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        
        def toggle_password():
            is_visible = password_label.property("is_visible")
            if is_visible:
                password_label.setText("*" * 12)
                view_btn.setText("查看")
                password_label.setProperty("is_visible", False)
            else:
                password_label.setText(password)
                view_btn.setText("隐藏")
                password_label.setProperty("is_visible", True)
        
        view_btn.clicked.connect(toggle_password)
        row_layout.addWidget(view_btn)
        
        # 复制按钮
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(50, 28)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                font-size: 11px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(password))
        row_layout.addWidget(copy_btn)
        
        row_layout.addStretch()
        return row_layout
    
    def create_account_password_box(self, label_text: str, email: str, password: str):
        """创建固定大小的账号密码框"""
        box = QFrame()
        box.setFixedSize(410, 50)
        box.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
        """)
        
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(8)
        
        # 标签
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(140)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px; background: transparent; border: none;")
        box_layout.addWidget(label)
        
        # 值
        value = QLabel(email)
        value.setFixedWidth(100)
        value.setStyleSheet("color: #1f2937; font-size: 12px; background: transparent; border: none;")
        value.setWordWrap(False)
        box_layout.addWidget(value)
        
        # 复制账密按钮
        copy_account_btn = QPushButton("复制账密")
        copy_account_btn.setFixedSize(60, 26)
        copy_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                font-size: 10px;
                padding: 4px;
                border: none;
                border-radius: 4px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        copy_account_btn.clicked.connect(lambda: self._copy_to_clipboard(f"{email}\n{password}"))
        box_layout.addWidget(copy_account_btn)
        
        # 复制邮箱按钮
        copy_email_btn = QPushButton("复制")
        copy_email_btn.setFixedSize(45, 26)
        copy_email_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                font-size: 10px;
                padding: 4px;
                border: none;
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_email_btn.clicked.connect(lambda: self._copy_to_clipboard(email))
        box_layout.addWidget(copy_email_btn)
        
        box_layout.addStretch()
        return box
    
    def create_account_password_row(self, label_text: str, email: str, password: str, color: str = None):
        """创建账号密码复制行 - 复制时采用邮箱换行密码格式"""
        row_layout = QHBoxLayout()
        
        # 标签（固定宽度120）
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(120)
        label.setStyleSheet("font-weight: bold; color: #374151; font-size: 12px;")
        row_layout.addWidget(label)
        
        # 值（固定宽度180）
        value = QLabel(email)
        value.setFixedWidth(180)
        if color:
            value.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
        else:
            value.setStyleSheet("color: #1f2937; font-size: 12px;")
        value.setWordWrap(False)
        row_layout.addWidget(value)
        
        # 复制账号密码按钮
        copy_btn = QPushButton("复制账密")
        copy_btn.setFixedSize(60, 28)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-size: 11px;
                padding: 4px 8px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        copy_btn.setToolTip("复制格式：邮箱\\n密码")
        # 复制格式：邮箱换行密码
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(f"{email}\n{password}"))
        row_layout.addWidget(copy_btn)
        
        # 只复制邮箱按钮
        copy_email_btn = QPushButton("复制邮箱")
        copy_email_btn.setFixedSize(60, 28)
        copy_email_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-size: 11px;
                padding: 4px 8px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        copy_email_btn.clicked.connect(lambda: self._copy_to_clipboard(email))
        row_layout.addWidget(copy_email_btn)
        
        row_layout.addStretch()
        return row_layout
    
    def manual_refresh(self):
        """手动刷新 - 强制调用API更新"""
        self.load_detailed_info(force_refresh=True)
    
    def load_detailed_info(self, force_refresh=False):
        """加载详细账户信息 - 优先使用本地数据，除非强制刷新"""
        user_id = self.account.get('user_id', '')
        access_token = self.account.get('access_token', '')
        email = self.account.get('email', '未知')
        
        if not user_id or not access_token:
            self.logger.warning("缺少必要的认证信息，无法获取详细信息")
            return
        
        # 清理可能存在的旧线程
        if hasattr(self, 'load_thread') and self.load_thread and self.load_thread.isRunning():
            self.load_thread.quit()
            self.load_thread.wait()
        
        # 启动后台线程获取详细信息
        self.load_thread = LoadAccountInfoThread(self.account, self.config, force_refresh=force_refresh)
        self.load_thread.info_loaded.connect(self.update_ui_with_info)
        self.load_thread.error_occurred.connect(self.update_ui_with_error)
        self.load_thread.finished.connect(self._on_load_finished)
        self.load_thread.start()
        
        # 显示加载状态
        if force_refresh:
            self.logger.info(f"🔄 正在强制刷新 {email} 的详细信息...")
        else:
            self.logger.info(f"📦 正在加载 {email} 的详细信息（优先使用本地数据）...")
    
    def _on_load_finished(self):
        """线程加载完成时的清理工作"""
        # 移除超时相关清理，简化处理
        pass
    
    def update_ui_with_info(self, info: dict):
        """更新UI显示详细信息"""
        try:
            self.account_info = info
            
            # 记录数据来源
            self.data_source = info.get('data_source', 'local')
            
            # 如果是API或cache数据，标记为已更新
            if self.data_source in ['api', 'cache']:
                self.data_updated = True
                self.logger.info(f"📝 标记数据已更新，来源: {self.data_source}")
            
            # 更新account数据
            if self.account:
                self.account.update(info)
            
            # 1. 更新总费用
            total_cost = info.get('total_cost', 0)
            if hasattr(self, 'cost_value_label') and self.cost_value_label:
                if total_cost > 0:
                    self.cost_value_label.setText(f"${total_cost:.2f}")
                    self.cost_value_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #dc2626;")
                else:
                    self.cost_value_label.setText("$0.00")
                    self.cost_value_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #6b7280;")
            
            # 2. 更新请求次数（从原始usage_data中获取）
            usage_data = info.get('usage_data', {})
            
            # 获取模型列表和token数据
            models = usage_data.get('usedModels', [])
            total_input_tokens = int(usage_data.get('totalInputTokens', '0'))
            total_output_tokens = int(usage_data.get('totalOutputTokens', '0'))
            
            # 累加每个模型的请求次数（已经在cursor_manager中用token估算好了）
            total_requests = 0
            if models:
                total_requests = sum(int(m.get('numRequests', 0)) for m in models)
                self.logger.info(f"总请求次数（累加各模型）: {total_requests}")
            
            # 如果累加结果还是0，用总token估算兜底（每次请求平均2万tokens，更接近实际）
            if total_requests == 0 and (total_input_tokens > 0 or total_output_tokens > 0):
                total_tokens = total_input_tokens + total_output_tokens
                total_requests = max(1, round(total_tokens / 20000))
                self.logger.info(f"总请求次数（总token估算）: {total_requests}")
            
            self.logger.info(f"✅ 最终总请求次数: {total_requests} (input_tokens: {total_input_tokens}, output_tokens: {total_output_tokens})")
            
            if hasattr(self, 'requests_value_label') and self.requests_value_label:
                self.requests_value_label.setText(f"{total_requests:,} 次")
            
            # 3. 更新模型列表
            self._update_models_list(models)
            
            # 缓存数据
            try:
                cache_manager = get_api_cache_manager()
                cache_manager.set_cached_data(
                    self.account.get('user_id', ''), 
                    self.account.get('access_token', ''), 
                    'usage', 
                    usage_data
                )
            except Exception as cache_error:
                self.logger.warning(f"缓存费用数据失败: {cache_error}")
            
        except Exception as e:
            self.logger.error(f"更新UI失败: {str(e)}")
    
    def _update_models_list(self, models: list):
        """更新模型列表显示（2列网格）"""
        try:
            # 清空现有模型
            while self.models_container.count():
                item = self.models_container.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            if not models:
                no_data = QLabel("暂无使用记录")
                no_data.setStyleSheet("color: #9ca3af; font-style: italic; padding: 10px;")
                self.models_container.addWidget(no_data)
                return
            
            # 显示每个模型（2列网格：模型名+费用）
            for i, model in enumerate(models[:10]):
                model_row = QHBoxLayout()
                model_row.setSpacing(8)
                
                # 第1列：模型名称
                model_name_box = QFrame()
                model_name_box.setFixedSize(165, 45)
                model_name_box.setStyleSheet("QFrame { background: transparent; border: 1px solid #f59e0b; border-radius: 5px; }")
                model_name_layout = QHBoxLayout(model_name_box)
                model_name_layout.setContentsMargins(10, 0, 10, 0)
                model_name = QLabel(model.get('name', model.get('modelName', '未知')))
                model_name.setStyleSheet("font-weight: bold; color: #b45309; font-size: 10px; background: transparent; border: none;")
                model_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                model_name_layout.addWidget(model_name)
                model_name_layout.addStretch()
                model_row.addWidget(model_name_box)
                
                # 第2列：费用 + 请求次数
                cost_box = QFrame()
                cost_box.setFixedSize(175, 45)
                cost_box.setStyleSheet("QFrame { background: transparent; border: 1px solid #f43f5e; border-radius: 5px; }")
                cost_layout = QVBoxLayout(cost_box)
                cost_layout.setContentsMargins(10, 4, 10, 4)
                cost_layout.setSpacing(2)
                
                # 费用
                cost = model.get('costInCents', model.get('costCents', 0)) / 100
                cost_label = QLabel(f"${cost:.2f}")
                cost_label.setStyleSheet("color: #be123c; font-weight: bold; font-size: 12px; background: transparent; border: none;")
                cost_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                cost_layout.addWidget(cost_label)
                
                # 请求次数
                requests = model.get('numRequests', 0)
                # 确保是整数类型
                try:
                    requests = int(requests) if requests else 0
                except:
                    requests = 0
                    
                requests_label = QLabel(f"{requests} 次")
                requests_label.setStyleSheet("color: #6b7280; font-size: 10px; background: transparent; border: none;")
                requests_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                cost_layout.addWidget(requests_label)
                
                self.logger.debug(f"模型 {model.get('name', '未知')}: 费用=${cost:.2f}, 请求={requests}次")
                
                model_row.addWidget(cost_box)
                
                self.models_container.addLayout(model_row)
            
            if len(models) > 10:
                more_label = QLabel(f"...还有 {len(models) - 10} 个模型")
                more_label.setStyleSheet("color: #9ca3af; font-size: 11px; font-style: italic; padding: 5px;")
                self.models_container.addWidget(more_label)
                
        except Exception as e:
            self.logger.error(f"更新模型列表失败: {str(e)}")
    
    # 精简版：移除复杂的布局清理方法，不再重建UI
    
    def update_ui_with_error(self, error_msg: str):
        """处理加载错误"""
        self.logger.error(f"加载账户信息失败: {error_msg}")
        # 不显示弹框，只在日志中记录
    
    
    def _copy_to_clipboard(self, text: str):
        """复制文本到剪贴板 - 直接调用通用工具类"""
        from ..utils.common_utils import CommonUtils
        success = CommonUtils.copy_to_clipboard(text, show_message=True)
        if not success:
            self.logger.error("复制到剪贴板失败")
    
    def _auto_save_field(self, field_name: str, new_value: str):
        """自动保存字段变更"""
        try:
            # 确保account不为None（关闭对话框时可能触发）
            if self.account is None or not hasattr(self, 'account'):
                self.logger.debug(f"对话框已关闭，跳过字段 {field_name} 的自动保存")
                return
            
            if not new_value or not new_value.strip():
                self.logger.warning(f"字段 {field_name} 的值为空，跳过保存")
                return
            
            # 更新内存中的account数据
            old_value = None
            if field_name == "email":
                old_value = self.account.get('email', '')
                self.account['email'] = new_value
            elif field_name == "jwt":
                old_value = self.account.get('access_token', '')
                self.account['access_token'] = new_value
                # 注意：只更新 access_token，不影响 WorkosCursorSessionToken
            elif field_name == "workos":
                old_value = self.account.get('WorkosCursorSessionToken', '')
                # 只更新 WorkosCursorSessionToken 字段，保持与 Session JWT 独立
                self.account['WorkosCursorSessionToken'] = new_value
                # 可选：仅当需要时解析user_id（但不修改access_token）
                if '%3A%3A' in new_value or '::' in new_value:
                    separator = '::' if '::' in new_value else '%3A%3A'
                    parts = new_value.split(separator, 1)
                    if len(parts) == 2:
                        self.account['user_id'] = parts[0]
                        self.logger.info(f"从WorkosToken解析user_id: {parts[0][:20]}...")
                        # 注意：不再修改 access_token，保持 Session JWT 独立
            
            # 如果值没有变化，跳过保存
            if old_value == new_value:
                self.logger.debug(f"字段 {field_name} 的值未变化，跳过保存")
                return
            
            # 保存到配置文件
            from ..services.cursor_service.cursor_manager import CursorManager
            from ..core.config import Config
            
            temp_config = self.config if self.config else Config()
            cursor_manager = CursorManager(temp_config)
            
            # 加载所有账号
            accounts = temp_config.load_accounts()
            
            # 查找并更新匹配的账号
            user_id = self.account.get('user_id', '')
            current_email = self.account.get('email', '')
            updated = False
            
            # 匹配逻辑优化：
            # 1. 优先使用 user_id 匹配（最可靠）
            # 2. 如果修改的是 email，使用 old_value（旧邮箱）匹配
            # 3. 否则使用当前的 email 匹配
            for i, acc in enumerate(accounts):
                match = False
                if user_id and acc.get('user_id') == user_id:
                    match = True
                elif field_name == "email" and acc.get('email') == old_value:
                    # 修改邮箱时，用旧邮箱匹配
                    match = True
                elif current_email and acc.get('email') == current_email:
                    # 修改其他字段时，用当前邮箱匹配
                    match = True
                
                if match:
                    # 完整保存整个账号对象，包括所有字段
                    accounts[i] = self.account.copy()  # 使用 copy() 避免引用问题
                    updated = True
                    self.logger.debug(f"找到匹配账号: user_id={user_id}, email={current_email}")
                    break
            
            if updated:
                temp_config.save_accounts(accounts)
                self.logger.info(f"✅ 字段 {field_name} 已自动保存到数据库")
                self.logger.debug(f"   变更: {old_value[:30] if old_value else 'N/A'}... → {new_value[:30]}...")
                
                # 验证保存结果
                saved_accounts = temp_config.load_accounts()
                for acc in saved_accounts:
                    if acc.get('user_id') == user_id or acc.get('email') == current_email:
                        if field_name == "jwt":
                            saved_value = acc.get('access_token', '')
                        elif field_name == "workos":
                            saved_value = acc.get('WorkosCursorSessionToken', '')
                        else:
                            saved_value = acc.get(field_name, '')
                        
                        if saved_value == new_value:
                            self.logger.info(f"✅ 验证成功：数据已正确保存到数据库")
                        else:
                            self.logger.warning(f"⚠️ 验证失败：保存的数据与预期不符")
                        break
            else:
                self.logger.warning(f"未找到匹配的账号，无法保存 {field_name}")
                self.logger.debug(f"   查找条件: user_id={user_id}, email={current_email}")
                
        except Exception as e:
            self.logger.error(f"自动保存字段 {field_name} 失败: {str(e)}")
            QMessageBox.warning(self, "保存失败", f"保存 {field_name} 失败: {str(e)}")
    
    

    def closeEvent(self, event):
        """关闭事件处理 - 保存修改并清理资源"""
        try:
            # 断开输入框信号，避免关闭时触发自动保存
            if hasattr(self, 'email_input') and self.email_input:
                try:
                    self.email_input.editingFinished.disconnect()
                except:
                    pass
            if hasattr(self, 'jwt_input') and self.jwt_input:
                try:
                    self.jwt_input.editingFinished.disconnect()
                except:
                    pass
            if hasattr(self, 'workos_input') and self.workos_input:
                try:
                    self.workos_input.editingFinished.disconnect()
                except:
                    pass
            
            # 保存用户修改的数据
            self._save_modifications()
            
            # 优化线程清理，让API自然完成
            if self.load_thread and self.load_thread.isRunning():
                self.load_thread.quit()
                self.load_thread.wait(3000)  # 延长等待时间到3秒，避免强制终止
            
            # 清理缓存数据
            if hasattr(self, 'account'):
                self.account = None
            
        except Exception as e:
            self.logger.error(f"关闭账号详情对话框时出错: {str(e)}")
        finally:
            # 确保对话框关闭
            event.accept()
    
    def _save_modifications(self):
        """保存用户修改的数据"""
        try:
            modified = False
            
            # 检查邮箱是否修改
            if hasattr(self, 'email_input') and self.email_input:
                new_email = self.email_input.text().strip()
                old_email = self.account.get('email', '')
                if new_email and new_email != old_email:
                    self.account['email'] = new_email
                    modified = True
                    self.logger.info(f"邮箱已修改: {old_email} -> {new_email}")
            
            # 检查JWT是否修改
            if hasattr(self, 'jwt_input') and self.jwt_input:
                new_jwt = self.jwt_input.text().strip()
                old_jwt = self.account.get('access_token', '')
                if new_jwt and new_jwt != old_jwt:
                    self.account['access_token'] = new_jwt
                    modified = True
                    self.logger.info(f"Session JWT已修改")
            
            # 检查WorkosToken是否修改
            if hasattr(self, 'workos_input') and self.workos_input:
                new_workos = self.workos_input.text().strip()
                old_workos = self.account.get('WorkosCursorSessionToken', '')
                if new_workos and new_workos != old_workos:
                    self.account['WorkosCursorSessionToken'] = new_workos
                    modified = True
                    self.logger.info(f"WorkosToken已修改")
            
            # 判断是否需要保存和刷新
            needs_save = modified or self.data_updated
            
            if needs_save and self.config:
                from PyQt6.QtCore import QTimer
                
                # 保存必要的引用，避免闭包中self被清理
                config = self.config
                account = self.account.copy()  # 复制账号数据
                parent = self.parent()
                logger = self.logger
                data_updated = self.data_updated
                
                def async_save_and_refresh():
                    """异步保存并更新，避免阻塞UI"""
                    try:
                        config.update_account(account)
                        logger.info("✅ 账号信息已保存到配置文件")
                        
                        # 🔥 直接更新缓存数据，而不是重新加载文件
                        if parent and hasattr(parent, 'current_displayed_accounts'):
                            email = account.get('email', '')
                            user_id = account.get('user_id', '')
                            for i, acc in enumerate(parent.current_displayed_accounts):
                                if (user_id and acc.get('user_id') == user_id) or (email and acc.get('email') == email):
                                    parent.current_displayed_accounts[i].update(account)
                                    logger.info(f"✅ 详情刷新-更新缓存: {email}")
                                    break
                        
                        # 🔥 更新UI显示（局部更新，不重新加载整个表格）
                        if data_updated and parent and hasattr(parent, '_refresh_without_losing_selection'):
                            logger.info("📝 局部刷新UI（检测到API数据更新）")
                            QTimer.singleShot(50, parent._refresh_without_losing_selection)
                        elif modified:
                            logger.info("📝 字段已修改，静默保存（不刷新UI）")
                    except Exception as e:
                        logger.error(f"异步保存失败: {str(e)}")
                
                # 延迟执行，让对话框立即关闭
                QTimer.singleShot(50, async_save_and_refresh)
            else:
                # 没有修改，直接关闭，不刷新
                self.logger.info("ℹ️ 未检测到修改，直接关闭对话框")
                
        except Exception as e:
            self.logger.error(f"保存修改失败: {str(e)}")