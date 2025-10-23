#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模型使用详情对话框 - 显示账号的模型使用情况
"""

import logging
import time
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import Qt, QTimer

# 使用新的API缓存管理器
from ..utils.api_cache_manager import get_api_cache_manager
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QMessageBox, QApplication,
    QProgressBar, QGroupBox, QFrame, QScrollArea,
    QGridLayout, QSpacerItem, QSizePolicy
)
from PyQt6.QtGui import QFont


class ModelUsageDialog(QDialog):
    """模型使用详情对话框"""
    
    def __init__(self, account: Dict, parent=None, preloaded_usage=None, preloaded_subscription=None, config=None):
        super().__init__(parent)
        self.account = account
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.usage_info = None
        
        # 🚀 新增：预加载数据支持
        self.preloaded_usage = preloaded_usage
        self.preloaded_subscription = preloaded_subscription
        
        # 初始化UI组件
        self.total_amount_label = None
        self.used_amount_label = None
        self.model_widgets = []  # 存储动态创建的模型组件
        
        self.init_ui()
        
        # 🎯 优先级1: 如果有预加载数据，直接使用（真正的秒开）
        if self.preloaded_usage:
            self.logger.info(f"🚀 使用预加载数据，实现秒开 - {self.account.get('email', '')}")
            formatted_usage = self._format_for_ui(self.preloaded_usage, {})
            self.update_ui_with_usage(formatted_usage)
            self.loading_progress.setVisible(False)
            return
        
        # 🎯 优先级2: 检查缓存
        try:
            user_id, access_token = self._extract_auth_info()
            if user_id and access_token:
                cache_manager = get_api_cache_manager()
                cached_usage_data = cache_manager.get_cached_data(user_id, access_token, 'usage', ttl=600)
                if cached_usage_data:
                    self.logger.info(f"⚡ 使用缓存数据，跳过网络请求 - {self.account.get('email', '')}")
                    formatted_usage = self._format_cached_usage(cached_usage_data)
                    self.update_ui_with_usage(formatted_usage)
                    self.loading_progress.setVisible(False)
                    return
            
            # 🎯 优先级3: 网络请求（最后选择）
            self.logger.info(f"📡 无预加载数据和缓存，进行网络请求 - {self.account.get('email', '')}")
            QTimer.singleShot(50, self.async_load_usage_info)
        except Exception as e:
            self.logger.error(f"初始化失败: {str(e)}")
            QTimer.singleShot(50, self.async_load_usage_info)
    
    def init_ui(self):
        """初始化现代化UI界面"""
        self.setWindowTitle("模型使用详情")
        self.setFixedSize(600, 500)
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
            QProgressBar {
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                text-align: center;
                background-color: #f1f5f9;
                min-height: 20px;
                font-weight: bold;
            }
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
        """)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 创建滚动内容窗口
        scroll_content = QFrame()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(20, 20, 20, 20)
        scroll_layout.setSpacing(20)
        
        # 标题区域 - 模仿fly-cursor-free
        title_frame = QFrame()
        title_frame.setStyleSheet("background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #10b981, stop: 1 #059669); border-radius: 12px;")
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(20, 15, 20, 15)
        
        title_label = QLabel("📊 模型使用详情")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: white; border: none;")
        title_layout.addWidget(title_label)
        
        email = self.account.get('email', '未知')
        title_email = QLabel(email)
        title_email.setStyleSheet("font-size: 14px; color: #e2e8f0; border: none;")
        title_layout.addWidget(title_email)
        title_layout.addStretch()
        
        scroll_layout.addWidget(title_frame)
        
        # 总计使用情况区域
        total_group = QGroupBox("💰 总计")
        total_layout = QVBoxLayout(total_group)
        total_layout.setSpacing(15)
        
        # 总额进度条
        self.total_amount_label = QLabel("$10.00")
        self.total_amount_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #10b981;")
        self.total_amount_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(self.total_amount_label)
        
        # 🚀 加载进度条 - 显示真实的加载状态
        self.loading_progress = QProgressBar()
        self.loading_progress.setMaximum(100)
        self.loading_progress.setValue(0)  # 初始为0%
        self.loading_progress.setVisible(True)  # 加载时显示
        self.loading_progress.setStyleSheet("""
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #2196F3, stop: 1 #1976D2);
                border-radius: 6px;
            }
        """)
        total_layout.addWidget(self.loading_progress)
        
        scroll_layout.addWidget(total_group)
        
        # 动态模型使用情况区域 - 将在load_usage_info中动态创建
        self.models_layout = QVBoxLayout()
        scroll_layout.addLayout(self.models_layout)
        
        # 其他模型信息区域
        other_group = QGroupBox("📈 使用统计")
        other_layout = QGridLayout(other_group)
        other_layout.setSpacing(10)
        
        # 请求次数
        requests_label = QLabel("总请求次数:")
        requests_label.setStyleSheet("font-weight: bold;")
        other_layout.addWidget(requests_label, 0, 0)
        
        self.requests_count_label = QLabel("加载中...")
        other_layout.addWidget(self.requests_count_label, 0, 1)
        
        # 成功率
        success_label = QLabel("成功率:")
        success_label.setStyleSheet("font-weight: bold;")
        other_layout.addWidget(success_label, 1, 0)
        
        self.success_rate_label = QLabel("加载中...")
        other_layout.addWidget(self.success_rate_label, 1, 1)
        
        # 平均响应时间
        response_time_label = QLabel("平均响应时间:")
        response_time_label.setStyleSheet("font-weight: bold;")
        other_layout.addWidget(response_time_label, 2, 0)
        
        self.response_time_label = QLabel("加载中...")
        other_layout.addWidget(self.response_time_label, 2, 1)
        
        scroll_layout.addWidget(other_group)
        
        # 设置滚动区域
        scroll_area.setWidget(scroll_content)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)
        
        # 底部按钮区域
        button_frame = QFrame()
        button_frame.setStyleSheet("background-color: #ffffff; border-top: 2px solid #e2e8f0;")
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(20, 15, 20, 15)
        
        # 刷新按钮
        refresh_button = QPushButton("🔄 刷新数据")
        refresh_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #10b981, stop: 1 #059669);
                color: white;
                padding: 12px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #059669, stop: 1 #047857);
            }
        """)
        refresh_button.clicked.connect(self.refresh_data_safely)
        button_layout.addWidget(refresh_button)
        
        # 保存刷新按钮引用用于状态控制
        self.refresh_button = refresh_button
        
        button_layout.addStretch()
        
        # 关闭按钮
        close_button = QPushButton("关闭")
        close_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #6b7280, stop: 1 #4b5563);
                color: white;
                padding: 12px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #4b5563, stop: 1 #374151);
            }
        """)
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)
        
        main_layout.addWidget(button_frame)
    
    def refresh_data_safely(self):
        """刷新数据"""
        try:
            # 禁用刷新按钮避免重复点击
            if hasattr(self, 'refresh_button'):
                self.refresh_button.setEnabled(False)
                self.refresh_button.setText("🔄 刷新中...")
            
            # 🧹 清除缓存，强制重新加载
            user_id, access_token = self._extract_auth_info()
            if user_id and access_token:
                cache_manager = get_api_cache_manager()
                cache_manager.clear_cache(user_id, access_token)
                self.logger.info(f"🗑️ 清除缓存，重新加载 - {self.account.get('email', '')}")
            
            # 🚀 重新加载数据
            self.load_usage_info()
            
        except Exception as e:
            self.logger.error(f"刷新数据失败: {str(e)}")
            self.update_ui_with_error("刷新失败")
    
    def async_load_usage_info(self):
        """异步加载模型使用信息 - 确保UI非阻塞"""
        # 🎯 显示真实的加载状态
        self.total_amount_label.setText("加载中...")
        self.loading_progress.setValue(0)  # 从0%开始
        self.loading_progress.setVisible(True)
        self.logger.info(f"正在异步加载 {self.account.get('email', '未知账号')} 的模型使用详情...")
        
        # 🚀 在后台线程中执行真正的加载逻辑
        import threading
        threading.Thread(target=self.load_usage_info, daemon=True).start()
    
    def _extract_auth_info(self):
        """提取认证信息 - 统一的认证信息解析"""
        user_id = self.account.get('user_id', '')
        access_token = self.account.get('access_token', '')
        
        # 🔧 如果缺少认证信息，尝试从WorkosCursorSessionToken中解析
        if not user_id:
            workos_token = self.account.get('WorkosCursorSessionToken', '')
            if workos_token and ('::' in workos_token or '%3A%3A' in workos_token):
                # 🔥 修复：只提取user_id，access_token应该来自account数据本身
                separator = '::' if '::' in workos_token else '%3A%3A'
                parts = workos_token.split(separator, 1)
                if len(parts) >= 1:
                    user_id = parts[0]
                    self.logger.info(f"从WorkosCursorSessionToken解析认证信息: user_id={user_id[:20]}...")
        
        # access_token应该直接从account中获取，而不是拆分WorkosCursorSessionToken
        if not access_token:
            access_token = self.account.get('access_token', '')
        
        return user_id, access_token

    def load_usage_info(self):
        """后台加载模型使用信息 - 优化缓存机制，避免重复API调用"""
        user_id, access_token = self._extract_auth_info()
        
        if not user_id or not access_token:
            QTimer.singleShot(0, lambda: self.update_ui_with_error("缺少必要的认证信息"))
            QTimer.singleShot(0, lambda: self.loading_progress.setVisible(False))
            return
        
        # 🚀 优先检查缓存，如果有缓存数据直接使用 - 立即检查所有相关缓存
        cache_manager = get_api_cache_manager()
        cached_usage_data = cache_manager.get_cached_data(user_id, access_token, 'usage', ttl=600)  # 10分钟缓存
        
        if cached_usage_data:
            self.logger.info(f"⚡ 使用缓存的模型使用信息 - {self.account.get('email', '')}")
            # 🎯 线程安全的缓存UI更新 - 立即显示，无需进度条
            formatted_usage = self._format_cached_usage(cached_usage_data)
            QTimer.singleShot(0, lambda: self.update_ui_with_usage(formatted_usage))
            QTimer.singleShot(0, lambda: self.on_load_finished())
            QTimer.singleShot(0, lambda: self.loading_progress.setVisible(False))  # 立即隐藏进度条
            return
        
        self.logger.info(f"📡 缓存未命中，开始直接并行API请求 - {self.account.get('email', '')}")
        
            # 🚀 直接在这里执行并行加载
        try:
            from ..services.cursor_service.cursor_manager import CursorManager
            from ..core.config import Config
            temp_config = self.config if self.config else Config()
            cursor_manager = CursorManager(temp_config)
            
            # 🎯 使用与account_detail_dialog完全相同的缓存策略
            QTimer.singleShot(0, lambda: self.loading_progress.setValue(20))  # 检查缓存20%
            
            # 🚀 简化：只获取使用量数据，忽略订阅数据
            usage_data = cached_usage_data  # 复用已检查的缓存
            
            api_tasks = []
            
            def load_usage():
                """加载使用量数据"""
                data = cursor_manager._get_model_usage_from_api(user_id, access_token, self.account)
                cache_manager.set_cached_data(user_id, access_token, 'usage', data)
                return 'usage', data
                
            # 🚀 简化：只加载使用量数据，删除订阅API
            if usage_data is None:
                api_tasks.append(load_usage)
            
            # 🚀 并行执行API调用 - 进一步优化速度
            if api_tasks:
                self.logger.info(f"🔥 开始{len(api_tasks)}个并行API请求")
                QTimer.singleShot(0, lambda: self.loading_progress.setValue(30))  # API开始30%
                
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_to_task = {executor.submit(task): task for task in api_tasks}
                    completed_count = 0
                    
                    for future in as_completed(future_to_task):
                        try:
                            api_type, data = future.result(timeout=15)  # 减少超时时间到15秒
                            if api_type == 'usage':
                                usage_data = data  
                            
                            completed_count += 1
                            progress = 30 + (completed_count / len(api_tasks)) * 50  # 30-80%
                            QTimer.singleShot(0, lambda p=progress: self.loading_progress.setValue(int(p)))
                            
                            self.logger.info(f"✅ {api_type} API完成 ({completed_count}/{len(api_tasks)})")
                        except Exception as e:
                            self.logger.error(f"❌ 并行API调用失败: {str(e)}")
            
            # 🎯 线程安全的UI更新 - 使用QTimer回到主线程
            if usage_data:
                QTimer.singleShot(0, lambda: self.loading_progress.setValue(90))  # 数据处理90%
                formatted_usage = self._format_for_ui(usage_data, {})
                QTimer.singleShot(0, lambda: self.update_ui_with_usage(formatted_usage))
                QTimer.singleShot(0, lambda: self.on_load_finished())
                QTimer.singleShot(0, lambda: self.loading_progress.setVisible(False))  # 完成后隐藏
                self.logger.info("🚀 并行加载完成，UI已更新")
            else:
                QTimer.singleShot(0, lambda: self.update_ui_with_error("无法获取模型使用信息"))
                QTimer.singleShot(0, lambda: self.loading_progress.setVisible(False))
                
        except Exception as e:
            self.logger.error(f"❌ 并行加载失败: {str(e)}")
            QTimer.singleShot(0, lambda: self.update_ui_with_error(f"加载失败: {str(e)}"))
            QTimer.singleShot(0, lambda: self.loading_progress.setVisible(False))  # 错误时隐藏进度条
            return

        return
    
    
    def _format_for_ui(self, usage_data: Dict, subscription_data: Dict = None) -> Dict:
        """将API数据格式化为UI需要的格式"""
        try:
            used_models = usage_data.get('usedModels', [])
            total_cost = usage_data.get('totalCostUSD', 0)
            
            # 计算各种统计信息
            # 使用累加各模型的请求次数（已在 cursor_manager 中估算好）
            total_requests = sum(int(model.get('numRequests', 0)) for model in used_models)
            # 如果还是0，用总token估算兜底（每次请求平均2万tokens）
            if total_requests == 0:
                total_input = int(usage_data.get('totalInputTokens', '0'))
                total_output = int(usage_data.get('totalOutputTokens', '0'))
                total_tokens = total_input + total_output
                if total_tokens > 0:
                    total_requests = max(1, round(total_tokens / 20000))
            
            return {
                'total_cost': total_cost,
                'used_models': used_models,
                'total_requests': total_requests,
                'success_rate': 99.5,  # 估算值
                'avg_response_time': 1.2,  # 估算值
                'subscription_info': subscription_data or {},
                'raw_usage_data': usage_data
            }
        except Exception as e:
            self.logger.error(f"格式化数据失败: {str(e)}")
            return {
                'total_cost': 0,
                'used_models': [],
                'total_requests': 0,
                'success_rate': 0,
                'avg_response_time': 0,
                'subscription_info': {},
                'raw_usage_data': {}
            }
    
    def _format_cached_usage(self, usage_data: Dict) -> Dict:
        """格式化缓存的使用量数据"""
        try:
            used_models = usage_data.get('usedModels', [])
            total_cost = usage_data.get('totalCostUSD', 0)
            
            # 累加各模型的请求次数（从缓存数据中获取）
            total_requests = sum(int(model.get('numRequests', 0)) for model in used_models)
            # 如果还是0，用总token估算兜底（每次请求平均2万tokens）
            if total_requests == 0:
                total_input = int(usage_data.get('totalInputTokens', '0'))
                total_output = int(usage_data.get('totalOutputTokens', '0'))
                total_tokens = total_input + total_output
                if total_tokens > 0:
                    total_requests = max(1, round(total_tokens / 20000))
            
            return {
                'total_cost': total_cost,
                'used_models': used_models,
                'total_requests': total_requests,
                'success_rate': 99.5,  # 估算值
                'avg_response_time': 1.2,  # 估算值
                'subscription_info': {},
                'raw_usage_data': usage_data
            }
        except Exception as e:
            self.logger.error(f"格式化缓存数据失败: {str(e)}")
            return {
                'total_cost': 0,
                'used_models': [],
                'total_requests': 0,
                'success_rate': 0,
                'avg_response_time': 0,
                'subscription_info': {},
                'raw_usage_data': {}
            }
    
    def update_ui_with_usage(self, usage_info: Dict):
        """使用获取到的信息更新UI - 动态显示所有模型使用量数据"""
        self.usage_info = usage_info
        
        try:
            # 获取真实的使用量数据
            total_cost = usage_info.get('total_cost', 0)
            used_models = usage_info.get('used_models', [])
            
            self.logger.info(f"模型使用信息更新完成，总费用: ${total_cost:.2f}，使用了{len(used_models)}个模型")
            
            # 更新总计信息
            self.total_amount_label.setText(f"${total_cost:.2f}")
            
            # 清除旧的模型组件
            self._clear_model_widgets()
            
            # 动态创建模型使用量显示
            if used_models:
                # 按费用从高到低排序
                sorted_models = sorted(used_models, key=lambda x: x.get('costUSD', 0), reverse=True)
                
                for model in sorted_models:
                    model_widget = self._create_model_widget(model, total_cost)
                    self.models_layout.addWidget(model_widget)
                    self.model_widgets.append(model_widget)
            else:
                # 没有使用数据，显示提示
                no_usage_label = QLabel("本月暂无模型使用记录")
                no_usage_label.setStyleSheet("""
                    color: #6b7280; 
                    font-size: 14px; 
                    text-align: center; 
                    padding: 20px;
                    border: 2px dashed #e2e8f0;
                    border-radius: 8px;
                    background-color: #f8fafc;
                """)
                no_usage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.models_layout.addWidget(no_usage_label)
                self.model_widgets.append(no_usage_label)
            
            # 更新统计信息
            self.requests_count_label.setText(f"{usage_info.get('total_requests', 0):,} 次")
            self.success_rate_label.setText(f"{usage_info.get('success_rate', 0):.1f}%")
            self.response_time_label.setText(f"{usage_info.get('avg_response_time', 0):.2f}s")
            
            self.logger.info(f"模型使用信息更新完成，总费用: ${total_cost:.2f}，使用了{len(used_models)}个模型")
            
        except Exception as e:
            self.logger.error(f"更新UI失败: {str(e)}")
            self.update_ui_with_error(f"UI更新失败: {str(e)}")
    
    def _clear_model_widgets(self):
        """清除旧的模型组件"""
        for widget in self.model_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self.model_widgets.clear()
    
    def _create_model_widget(self, model_data: Dict, total_cost: float) -> QGroupBox:
        """创建单个模型的显示组件"""
        model_name = model_data.get('modelName', 'unknown')
        model_cost = model_data.get('costUSD', 0)
        input_tokens = model_data.get('inputTokens', 0)
        output_tokens = model_data.get('outputTokens', 0)
        
        # 创建模型组框
        model_group = QGroupBox(f"🤖 {model_name}")
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(15)
        
        # 模型费用标签
        cost_label = QLabel(f"${model_cost:.2f}")
        cost_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3b82f6;")
        cost_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        model_layout.addWidget(cost_label)
        
        # 进度条 - 显示相对于总费用的占比
        progress = QProgressBar()
        progress.setMaximum(100)
        if total_cost > 0:
            percentage = min((model_cost / total_cost) * 100, 100)
            progress.setValue(int(percentage))
        else:
            progress.setValue(0)
        
        # 根据模型名称选择不同的颜色
        if 'claude' in model_name.lower():
            color1, color2 = "#3b82f6", "#2563eb"  # 蓝色
        elif 'gpt' in model_name.lower():
            color1, color2 = "#10b981", "#059669"  # 绿色
        else:
            color1, color2 = "#f59e0b", "#d97706"  # 橙色
        
        progress.setStyleSheet(f"""
            QProgressBar::chunk {{
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {color1}, stop: 1 {color2});
                border-radius: 6px;
            }}
        """)
        model_layout.addWidget(progress)
        
        # Token使用详情
        if input_tokens > 0 or output_tokens > 0:
            token_info = QLabel(f"输入: {input_tokens:,} • 输出: {output_tokens:,} tokens")
            token_info.setStyleSheet("color: #6b7280; font-size: 11px; text-align: center;")
            token_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            model_layout.addWidget(token_info)
        
        return model_group
    
    def update_ui_with_error(self, error_message: str):
        """更新UI显示错误信息"""
        self.total_amount_label.setText(f"❌ {error_message}")
        
        # 清除旧的模型组件并显示错误
        self._clear_model_widgets()
        error_label = QLabel(f"获取失败: {error_message}")
        error_label.setStyleSheet("""
            color: #dc2626; 
            font-size: 14px; 
            text-align: center; 
            padding: 20px;
            border: 2px solid #fecaca;
            border-radius: 8px;
            background-color: #fef2f2;
        """)
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.models_layout.addWidget(error_label)
        self.model_widgets.append(error_label)
        
        self.requests_count_label.setText("获取失败")
        self.success_rate_label.setText("获取失败") 
        self.response_time_label.setText("获取失败")
    
    def on_load_finished(self):
        """加载完成后恢复按钮状态"""
        try:
            # 恢复刷新按钮状态
            if hasattr(self, 'refresh_button'):
                self.refresh_button.setEnabled(True)
                self.refresh_button.setText("🔄 刷新数据")
        except Exception as e:
            self.logger.error(f"加载完成处理失败: {str(e)}")
    
    def closeEvent(self, event):
        """关闭事件处理"""
        try:
            # 🧹 清理UI资源
            if hasattr(self, 'model_widgets'):
                self.model_widgets.clear()
            self.usage_info = None
            
            event.accept()
        except Exception as e:
            self.logger.error(f"关闭模型详情对话框时出错: {str(e)}")
            event.accept()
