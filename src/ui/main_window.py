#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
主窗口 - MY Cursor的主界面
"""

import logging
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QTextEdit,
    QGroupBox, QStatusBar,
    QDialog, QMessageBox, QTabWidget, QFrame, QProgressBar, QMenu
)
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from ..services.cursor_service.cursor_manager import CursorManager


class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self, config):
        """初始化主窗口"""
        super().__init__()
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.cursor_manager = CursorManager(config)
        
        # 窗口拖动相关变量
        self.dragPos = QPoint()
        self.dragging = False
        
        self.init_ui()
        self.setup_connections()
        
        # 🔥 已禁用：定期检查账号状态监控器（不再需要频繁检查）
        # self.setup_auth_monitor()
        
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("MY Cursor - 让智能编程更优雅")
        
        # 设置窗口图标
        self._set_window_icon()
        
        # 保留原生缩放功能，隐藏标题栏但保留边框
        self.setWindowFlags(
            Qt.WindowType.Window | 
            Qt.WindowType.CustomizeWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        
        # 界面尺寸，设计基准尺寸 (增加宽度以完整显示所有列)
        self.base_width = 1000  # 增加宽度以完整显示所有列
        self.base_height = 850  # 调整高度，使界面更加紧凑
        self.setMinimumSize(950, 680)  # 调整最小宽度以完整显示所有列
        self.resize(self.base_width, self.base_height)
        
        
        # 初始化DPI感知和应用基础样式
        self._init_dpi_awareness()
        self.apply_base_styles()
        
        # 创建菜单栏
        self.create_menu_bar()
        
        # 创建中央窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局 - 包含美观的标题栏
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)  # 无边距，让标题栏贴边
        main_layout.setSpacing(0)
        
        # 美观的大标题栏
        title_bar = self.create_custom_title_bar()
        main_layout.addWidget(title_bar)
        
        # 主要内容区域
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(15)
        
        # 顶部工具栏
        toolbar_widget = self.create_toolbar()
        content_layout.addWidget(toolbar_widget)
        
        # 主要内容：账号列表区域
        main_content = self.create_main_content()
        content_layout.addWidget(main_content)
        
        # 将内容区域添加到主布局
        main_layout.addWidget(content_widget)
        
        # 创建状态栏
        self.create_status_bar()
        
        # 显示欢迎信息
        self.show_welcome_info()
    
    
    def _init_dpi_awareness(self):
        """初始化DPI感知 - 使用Qt6内置支持，无需手动计算"""
        # Qt6已在main.py中配置高DPI支持，这里仅记录信息
        try:
            screen = self.screen()
            if screen:
                dpi_ratio = screen.devicePixelRatio()
                logical_dpi = screen.logicalDotsPerInch()
                self.logger.info(f"DPI信息: ratio={dpi_ratio}, dpi={logical_dpi}")
        except Exception as e:
            pass
    
    def apply_base_styles(self):
        """应用基础样式表 - 使用固定值，依赖Qt6自动DPI缩放"""
        base_stylesheet = """
            QGroupBox {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8f9fa);
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin-top: 1ex;
                font-weight: bold;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                color: #495057;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2196F3, stop: 1 #1976D2);
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: bold;
                color: white;
                font-size: 13px;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #1976D2, stop: 1 #1565C0);
            }
            QPushButton:pressed {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #0D47A1, stop: 1 #1565C0);
            }
            QTextEdit {
                background-color: #ffffff;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Monaco', monospace;
                color: #333333;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 2px solid #2196F3;
            }
            QTabWidget::pane {
                border: 2px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                margin-top: -1px;
            }
            QTabBar::tab {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8f9fa, stop: 1 #e9ecef);
                border: 2px solid #dee2e6;
                border-bottom-color: #dee2e6;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 100px;
                padding: 12px 20px;
                margin-right: 2px;
                font-weight: 500;
                color: #495057;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8f9fa);
                border-color: #2196F3;
                border-bottom-color: white;
                color: #2196F3;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #e3f2fd, stop: 1 #bbdefb);
                color: #1976D2;
            }
            QStatusBar {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #ffffff, stop: 1 #f8f9fa);
                border-top: 1px solid #dee2e6;
                color: #6c757d;
                font-size: 11px;
                padding: 4px;
            }
        """
        self.setStyleSheet(base_stylesheet)
    
    # _notify_children_scale_change已删除 - Qt6自动处理子组件DPI缩放
    
    def _set_window_icon(self):
        """设置窗口图标"""
        try:
            import os
            # 尝试多个可能的图标路径
            possible_paths = [
                os.path.join(os.path.dirname(__file__), "..", "..", "resources", "icon.ico"),
                os.path.join(os.path.dirname(__file__), "..", "..", "resources", "icon.png"),
                os.path.join(os.getcwd(), "resources", "icon.ico"),
                os.path.join(os.getcwd(), "resources", "icon.png"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources", "icon.ico")
            ]
            
            for icon_path in possible_paths:
                icon_path = os.path.normpath(icon_path)
                if os.path.exists(icon_path):
                    try:
                        icon = QIcon(icon_path)
                        if not icon.isNull():
                            self.setWindowIcon(icon)
                            self.logger.info(f"成功设置窗口图标: {icon_path}")
                            return
                    except Exception as load_error:
                        self.logger.warning(f"加载图标失败 {icon_path}: {str(load_error)}")
                        continue
            
            self.logger.info("未找到图标文件，使用默认图标")
                
        except Exception as e:
            self.logger.error(f"设置窗口图标异常: {str(e)}")

    def create_custom_title_bar(self) -> QWidget:
        """创建美观的标题栏"""
        title_bar = QFrame()
        title_bar.setFixedHeight(55)  # 适中的标题栏高度
        title_bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8f9fa, stop: 1 #e9ecef);
                border: none;
                border-bottom: 1px solid #dee2e6;
            }
        """)
        
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(20)
        
        # 应用图标（适中尺寸，添加美化效果）
        icon_label = QLabel()
        icon_label.setFixedSize(40, 40)  # 适中的图标大小
        try:
            import os
            # 尝试多个可能的图标路径
            possible_paths = [
                os.path.join(os.path.dirname(__file__), "..", "..", "resources", "icon.png"),
                os.path.join(os.path.dirname(__file__), "..", "..", "resources", "icon.ico"),
                os.path.join(os.getcwd(), "resources", "icon.png"),
                os.path.join(os.getcwd(), "resources", "icon.ico"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources", "icon.png")
            ]
            
            icon_loaded = False
            for icon_path in possible_paths:
                icon_path = os.path.normpath(icon_path)
                if os.path.exists(icon_path):
                    try:
                        pixmap = QPixmap(icon_path)
                        if not pixmap.isNull():
                            # 缩放到合适尺寸
                            scaled_pixmap = pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            icon_label.setPixmap(scaled_pixmap)
                            # 添加圆角边框和美化效果
                            icon_label.setStyleSheet("""
                                QLabel {
                                    background-color: rgba(52, 152, 219, 0.1);
                                    border: 2px solid rgba(52, 152, 219, 0.3);
                                    border-radius: 20px;
                                    padding: 2px;
                                }
                            """)
                            icon_loaded = True
                            self.logger.info(f"成功加载标题栏图标: {icon_path}")
                            break
                    except Exception as load_error:
                        self.logger.warning(f"加载图标失败 {icon_path}: {str(load_error)}")
                        continue
            
            if not icon_loaded:
                # 使用emoji作为备用图标
                icon_label.setText("🎯")
                icon_label.setStyleSheet("""
                    QLabel {
                        font-size: 24px; 
                        color: #3498db;
                        background-color: rgba(52, 152, 219, 0.1);
                        border: 2px solid rgba(52, 152, 219, 0.3);
                        border-radius: 20px;
                        padding: 2px;
                    }
                """)
                self.logger.info("使用备用emoji图标")
                
        except Exception as e:
            icon_label.setText("🎯")
            icon_label.setStyleSheet("""
                QLabel {
                    font-size: 24px; 
                    color: #3498db;
                    background-color: rgba(52, 152, 219, 0.1);
                    border: 2px solid rgba(52, 152, 219, 0.3);
                    border-radius: 20px;
                    padding: 2px;
                }
            """)
            self.logger.error(f"图标加载异常: {str(e)}")
        
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        # 标题文字（适中字体）
        title_label = QLabel("MY Cursor")
        title_label.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                font-size: 22px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title_label)
        
        # 副标题
        subtitle_label = QLabel("让智能编程更优雅")
        subtitle_label.setStyleSheet("""
            QLabel {
                color: #6c757d;
                font-size: 12px;
                font-weight: normal;
                font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
                background: transparent;
                border: none;
                padding: 0px;
                margin-left: 8px;
            }
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(subtitle_label)
        
        # 弹性空间
        layout.addStretch()
        
        # 创建按钮容器，控制按钮间距
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)  # 适中间距
        
        # 简洁纯色圆形窗口控制按钮
        button_size = 20
        
        # 最小化按钮（黄色）
        min_button = QPushButton("")
        min_button.setFixedSize(button_size, button_size)
        min_button.setMaximumSize(button_size, button_size)
        min_button.setMinimumSize(button_size, button_size)
        min_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFC107;
                border: none;
                border-radius: {button_size // 2}px;
                padding: 0px;
                margin: 0px;
                width: {button_size}px;
                height: {button_size}px;
            }}
            QPushButton:hover {{
                background-color: #FFD54F;
            }}
            QPushButton:pressed {{
                background-color: #FF8F00;
            }}
        """)
        min_button.clicked.connect(self.showMinimized)
        min_button.setToolTip("最小化")
        button_layout.addWidget(min_button)
        
        # 最大化/还原按钮（绿色）
        max_button = QPushButton("")
        max_button.setFixedSize(button_size, button_size)
        max_button.setMaximumSize(button_size, button_size)
        max_button.setMinimumSize(button_size, button_size)
        max_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                border: none;
                border-radius: {button_size // 2}px;
                padding: 0px;
                margin: 0px;
                width: {button_size}px;
                height: {button_size}px;
            }}
            QPushButton:hover {{
                background-color: #66BB6A;
            }}
            QPushButton:pressed {{
                background-color: #388E3C;
            }}
        """)
        max_button.clicked.connect(self.toggle_maximize)
        max_button.setToolTip("最大化")
        button_layout.addWidget(max_button)
        self.max_button = max_button
        
        # 关闭按钮（红色）
        close_button = QPushButton("")
        close_button.setFixedSize(button_size, button_size)
        close_button.setMaximumSize(button_size, button_size)
        close_button.setMinimumSize(button_size, button_size)
        close_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #F44336;
                border: none;
                border-radius: {button_size // 2}px;
                padding: 0px;
                margin: 0px;
                width: {button_size}px;
                height: {button_size}px;
            }}
            QPushButton:hover {{
                background-color: #EF5350;
            }}
            QPushButton:pressed {{
                background-color: #D32F2F;
            }}
        """)
        close_button.clicked.connect(self.close)
        close_button.setToolTip("关闭")
        button_layout.addWidget(close_button)
        
        # 将按钮容器添加到主布局
        layout.addWidget(button_container, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # 存储标题栏引用，用于拖动
        self.title_bar = title_bar
        title_bar.mousePressEvent = self.title_bar_mouse_press_event
        title_bar.mouseMoveEvent = self.title_bar_mouse_move_event
        title_bar.mouseReleaseEvent = self.title_bar_mouse_release_event
        title_bar.mouseDoubleClickEvent = self.title_bar_double_click_event
        
        return title_bar
    
    def toggle_maximize(self):
        """切换最大化状态"""
        if self.isMaximized():
            self.showNormal()
            self.max_button.setText("")  # 只保留空心圆，不显示图案
            self.max_button.setToolTip("最大化")
        else:
            self.showMaximized()
            self.max_button.setText("")  # 只保留空心圆，不显示图案
            self.max_button.setToolTip("还原窗口")
    
    def title_bar_mouse_press_event(self, event):
        """标题栏鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragPos = event.globalPosition().toPoint()
            self.dragging = True
            
    def title_bar_mouse_move_event(self, event):
        """标题栏鼠标移动事件"""
        if self.dragging and event.buttons() == Qt.MouseButton.LeftButton:
            # 如果是最大化状态，先还原
            if self.isMaximized():
                self.showNormal()
                # 调整拖动位置
                self.dragPos = QPoint(self.width() // 2, 35)
                
            # 移动窗口
            self.move(self.pos() + event.globalPosition().toPoint() - self.dragPos)
            self.dragPos = event.globalPosition().toPoint()
            
    def title_bar_mouse_release_event(self, event):
        """标题栏鼠标释放事件"""
        self.dragging = False
    
    def title_bar_double_click_event(self, event):
        """标题栏双击事件 - 切换最大化"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()

    def create_menu_bar(self):
        """创建菜单栏 - 简化版，隐藏菜单获得更简洁界面"""
        self.menuBar().setVisible(False)
    
    def create_toolbar(self) -> QWidget:
        """创建顶部工具栏"""
        toolbar = QWidget()
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border: 2px solid #e0e0e0;
                border-radius: 12px;
                padding: 8px;
                min-height: 40px;
            }
        """)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(15, 8, 15, 8)
        
        # 副标题（简化版）
        subtitle_label = QLabel("💡 让智能编程更优雅")
        subtitle_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #2196F3;
                border: none;
                padding: 4px 0px;
            }
        """)
        layout.addWidget(subtitle_label)
        
        layout.addStretch()
        
        # 功能按钮组 - 简化合并版
        
        # 🔄 一键换号按钮
        self.quick_switch_btn = QPushButton("🔄 一键换号")
        self.quick_switch_btn.setToolTip("自动切换到下一个账号（重置机器码）")
        self.quick_switch_btn.clicked.connect(self.quick_switch_account)
        self._style_menu_button(self.quick_switch_btn, "#66BB6A")  # 柔和的绿色
        # 固定按钮尺寸，防止动画时撑大
        self.quick_switch_btn.setFixedWidth(100)
        layout.addWidget(self.quick_switch_btn)
        
        # 导入按钮
        import_btn = QPushButton("📥 导入")
        import_btn.clicked.connect(self.show_import_dialog)
        self._style_menu_button(import_btn, "#4A90E2")  # 蓝色
        layout.addWidget(import_btn)
        
        # 导出按钮
        export_btn = QPushButton("📤 导出")
        export_btn.clicked.connect(self.export_accounts)
        self._style_menu_button(export_btn, "#4A90E2")  # 蓝色
        layout.addWidget(export_btn)
        
        return toolbar
    
    def _style_menu_button(self, btn, color):
        """设置下拉菜单按钮的样式"""
        # 计算hover和pressed颜色
        if color == "#FF8A65":  # 温暖橙色
            hover_color = "#FF7043"
            pressed_color = "#FF5722"
        elif color == "#42A5F5":  # 天空蓝
            hover_color = "#2196F3"
            pressed_color = "#1976D2"
        elif color == "#4A90E2":  # 导入/导出蓝色
            hover_color = "#357ABD"
            pressed_color = "#2C5999"
        elif color == "#FF9800":  # 一键换号橙色（已弃用）
            hover_color = "#F57C00"
            pressed_color = "#E65100"
        elif color == "#66BB6A":  # 一键换号柔和绿色
            hover_color = "#81C784"
            pressed_color = "#4CAF50"
        else:  # 默认灰色
            hover_color = "#5a6268"
            pressed_color = "#545b62"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                font-size: 12px;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 12px;
                margin: 0 2px;
                min-height: 24px;
                max-height: 28px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {pressed_color};
            }}
            QPushButton::menu-indicator {{
                image: none;
                width: 0px;
            }}
        """)
    
    def create_main_content(self) -> QWidget:
        """创建主要内容区域 - 延迟加载重型组件"""
        widget = QWidget()
        # 🎨 确保主内容区域有背景色，避免白屏
        widget.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
            }
        """)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        # 🎨 设置标签页样式，确保有背景
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #c0c0c0;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #f0f0f0;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                border-bottom: none;
            }
        """)
        
        # ⚡ 延迟创建重型组件 - 先创建占位符
        self.account_list_widget = None
        self.auto_register_widget = None
        self.settings_widget = None
        
        # 创建占位符标签页
        placeholder1 = self._create_loading_placeholder("⚡ 正在加载账号管理模块...\n请稍候，正在初始化组件")
        self.tab_widget.addTab(placeholder1, "📋 账号管理")
        
        placeholder2 = self._create_loading_placeholder("🤖 正在加载自动注册模块...\n请稍候，正在准备引擎")
        self.tab_widget.addTab(placeholder2, "🤖 自动注册")
        
        placeholder3 = self._create_loading_placeholder("⚙️ 正在加载设置模块...\n请稍候，正在初始化配置")
        self.tab_widget.addTab(placeholder3, "⚙️ 设置")
        
        # 异步加载重型组件 - 稍微延长一点时间让占位符显示
        QTimer.singleShot(100, self._load_heavy_components)
        
        # 🔥 监听标签页切换事件，优化性能
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        layout.addWidget(self.tab_widget)
        
        return widget
    
    def _create_loading_placeholder(self, text: str) -> QWidget:
        """创建加载占位符"""
        placeholder = QWidget()
        # 🎨 设置占位符背景色
        placeholder.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # 🎯 添加图标
        icon_label = QLabel("⚡")
        icon_label.setStyleSheet("""
            QLabel {
                font-size: 48px;
                color: #4a90e2;
                margin-bottom: 20px;
            }
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        # 📝 文本标签
        label = QLabel(text)
        label.setStyleSheet("""
            QLabel {
                color: #333;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
                margin-bottom: 20px;
                line-height: 1.4;
            }
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)  # 支持换行显示
        layout.addWidget(label)
        
        # 🔄 进度条
        progress = QProgressBar()
        progress.setRange(0, 0)  # 无限进度条
        progress.setMaximumWidth(300)
        progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #e1e5e9;
                border-radius: 5px;
                text-align: center;
                background-color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #4a90e2;
                border-radius: 3px;
            }
        """)
        layout.addWidget(progress)
        
        return placeholder
    
    def _load_heavy_components(self):
        """异步加载重型组件"""
        try:
            self.logger.info("⚡ 开始加载UI组件...")
            
            # 延迟导入重型模块
            from .account_list_widget import AccountListWidget
            from .auto_register_widget import AutoRegisterWidget
            from .settings_widget import SettingsWidget
            
            # 创建重型组件
            self.account_list_widget = AccountListWidget(self.config, self.cursor_manager)
            self.auto_register_widget = AutoRegisterWidget(
                account_manager=self.account_list_widget,
                config=self.config,
                parent=self
            )
            self.settings_widget = SettingsWidget(self.config, self)
            
            # 替换占位符
            self.tab_widget.removeTab(2)  # 移除设置占位符
            self.tab_widget.removeTab(1)  # 移除自动注册占位符
            self.tab_widget.removeTab(0)  # 移除账号管理占位符
            
            self.tab_widget.insertTab(0, self.account_list_widget, "📋 账号管理")
            self.tab_widget.insertTab(1, self.auto_register_widget, "🤖 自动注册")
            self.tab_widget.insertTab(2, self.settings_widget, "⚙️ 设置")
            
            # 🔥 标记：组件已加载
            self._components_loaded = True
            self._last_tab_index = 0  # 当前在账号管理标签页
            
            self.logger.info("✅ UI组件加载完成")
            
            # 🔗 组件加载完成后设置信号连接
            self._setup_delayed_connections()
            
        except Exception as e:
            self.logger.error(f"❌ 加载重型组件失败: {str(e)}")
            # 创建错误占位符
            error_widget = self._create_loading_placeholder(f"加载失败: {str(e)}")
            self.tab_widget.removeTab(0)
            self.tab_widget.insertTab(0, error_widget, "❌ 加载失败")
    
    def _on_tab_changed(self, index):
        """标签页切换事件处理 - 让Qt自己处理切换，不干预"""
        try:
            # 如果组件还没加载完成，不处理
            if not hasattr(self, '_components_loaded') or not self._components_loaded:
                return
            
            # 🔥 避免重复处理同一个标签页
            if hasattr(self, '_last_tab_index') and self._last_tab_index == index:
                return
            
            self._last_tab_index = index
            
            # 🔥 完全不干预表格显示，让Qt的标签页机制自己处理
            # 标签页切换时Qt会自动管理各个页面的绘制，我们的手动操作反而影响性能
            
            if index == 0:
                self.logger.debug("🔄 切换到账号管理")
            elif index == 1:
                self.logger.debug("🔄 切换到自动注册")
            elif index == 2:
                self.logger.debug("🔄 切换到设置")
                
        except Exception as e:
            self.logger.error(f"标签页切换处理失败: {str(e)}")
    
    def _setup_delayed_connections(self):
        """设置延迟信号连接"""
        try:
            # 检查组件是否已加载
            if self.account_list_widget and hasattr(self.account_list_widget, 'status_message'):
                # 账号列表信号连接
                self.account_list_widget.status_message.connect(
                    self.show_status_message
                )
                
                # 连接日志信号到自动注册widget的日志栏
                if hasattr(self.account_list_widget, 'log_message_signal') and self.auto_register_widget and hasattr(self.auto_register_widget, 'add_log'):
                    self.account_list_widget.log_message_signal.connect(
                        self.auto_register_widget.add_log
                    )
                    self.logger.info("✅ 已连接账号管理日志到自动注册日志栏")
                
                # 更新账号统计
                if hasattr(self.account_list_widget, 'update_account_count'):
                    self.account_list_widget.update_account_count()
            
            if self.auto_register_widget and hasattr(self.auto_register_widget, 'status_message'):
                # 自动注册信号连接（如果有的话）
                pass
            
            if self.settings_widget and hasattr(self.settings_widget, 'settings_changed'):
                # 设置变更信号连接 - 使用 Qt.ConnectionType.UniqueConnection 防止重复连接
                try:
                    # 先断开可能存在的连接，避免重复
                    self.settings_widget.settings_changed.disconnect(self.on_settings_changed)
                except:
                    pass  # 如果之前没有连接，会抛出异常，忽略即可
                
                self.settings_widget.settings_changed.connect(self.on_settings_changed)
                self.logger.info("settings_changed 信号已连接")
                
        except Exception as e:
            self.logger.error(f"设置延迟连接失败: {str(e)}")
    
    def create_status_bar(self):
        """创建状态栏 - 防止重叠优化版"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 左侧：状态图标
        self.status_icon = QLabel("🔵")
        self.status_icon.setStyleSheet("color: #007bff; font-size: 12px; margin: 0 3px;")
        self.status_bar.addWidget(self.status_icon)
        
        # 左侧：状态消息显示区域
        self.status_message_label = QLabel("🚀 系统就绪")
        self.status_message_label.setStyleSheet("""
            color: #495057; 
            font-size: 10px; 
            margin: 0 8px;
            min-width: 600px;
        """)
        self.status_bar.addWidget(self.status_message_label)
        
        # 状态栏自动恢复计时器
        self.status_reset_timer = QTimer()
        self.status_reset_timer.setSingleShot(True)
        self.status_reset_timer.timeout.connect(self._reset_status_to_welcome)
        self.default_status_text = "欢迎使用MY Cursor，点击蓝色按钮导入账号"
        
        # 添加弹性空间
        spacer = QLabel("")
        spacer.setStyleSheet("margin: 0;")
        self.status_bar.addWidget(spacer, 1)  # 拉伸因子为1，占据剩余空间
        
        # 右侧：制作者信息（紧凑版）
        author_label = QLabel("制作者：墨鱼 | QQ群：850097941")
        author_label.setStyleSheet("color: #6c757d; font-size: 10px; padding: 2px;")
        self.status_bar.addPermanentWidget(author_label)
        
        # 显示就绪状态
        self.show_status_message("🚀 系统就绪")
        
        # ⚠️ 注意：不要在这里再次调用 _setup_delayed_connections！
        # 信号连接只需要在 _load_heavy_components 中调用一次即可
    
    def setup_connections(self):
        """设置信号连接 - 延迟到组件加载完成后"""
        # ⚠️ 已废弃：信号连接现在在 _load_heavy_components 中直接调用
        # 不需要再次延迟调用，否则会导致重复连接
        pass
    
    def show_status_message(self, message: str):
        """显示状态消息 - 自动恢复默认状态"""
        # 更新状态图标颜色
        if "成功" in message or "完成" in message or "✅" in message:
            self.status_icon.setText("🟢")
            self.status_icon.setStyleSheet("color: #28a745; font-size: 12px; margin: 0 3px;")
        elif "错误" in message or "失败" in message or "❌" in message:
            self.status_icon.setText("🔴")
            self.status_icon.setStyleSheet("color: #dc3545; font-size: 12px; margin: 0 3px;")
        elif "警告" in message or "⚠️" in message:
            self.status_icon.setText("🟡")
            self.status_icon.setStyleSheet("color: #ffc107; font-size: 12px; margin: 0 3px;")
        else:
            self.status_icon.setText("🔵")
            self.status_icon.setStyleSheet("color: #007bff; font-size: 12px; margin: 0 3px;")
        
        # 显示当前消息
        if hasattr(self, 'status_message_label'):
            self.status_message_label.setText(message)
        
        # 重启1秒计时器，10秒后恢复默认状态
        if hasattr(self, 'status_reset_timer'):
            self.status_reset_timer.stop()
            self.status_reset_timer.start(10000)  # 1秒后恢复
    
    def _reset_status_to_welcome(self):
        """恢复状态栏为默认欢迎信息"""
        self.status_icon.setText("🔵")
        self.status_icon.setStyleSheet("color: #007bff; font-size: 12px; margin: 0 3px;")
        if hasattr(self, 'status_message_label') and hasattr(self, 'default_status_text'):
            self.status_message_label.setText(self.default_status_text)
    
    def show_welcome_info(self):
        """显示欢迎信息"""
        self.show_status_message("欢迎使用MY Cursor！点击蓝色按钮导入Token")
    
    def show_unified_import_dialog(self):
        """显示三标签页导入对话框"""
        try:
            from .three_tab_import_dialog import ThreeTabImportDialog
            dialog = ThreeTabImportDialog(self, self.config)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # 刷新账号列表
                self.account_list_widget.load_accounts()
                self.show_status_message("账号导入成功")
            
        except Exception as e:
            self.logger.error(f"打开导入对话框时出错: {str(e)}")
            QMessageBox.critical(self, "错误", f"打开导入对话框时出错: {str(e)}")
    
    def close_cursor_processes(self):
        """关闭所有Cursor进程"""
        try:
            # 显示确认对话框
            reply = QMessageBox.question(
                self, "确认关闭", 
                "确定要关闭所有Cursor进程吗？\n\n这将关闭所有正在运行的Cursor窗口。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.show_status_message("正在关闭Cursor进程...")
                success, message = self.cursor_manager.close_cursor_processes()
                
                if success:
                    self.show_status_message(f"✅ {message}")
                    QMessageBox.information(self, "成功", message)
                else:
                    self.show_status_message(f"❌ {message}")
                    QMessageBox.warning(self, "警告", message)
                    
        except Exception as e:
            self.logger.error(f"关闭Cursor进程失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"关闭Cursor进程失败: {str(e)}")
    
    def quick_switch_account(self):
        """一键换号 - 立即开始动画"""
        try:
            if not hasattr(self, 'account_list_widget') or not self.account_list_widget:
                self.logger.warning("账号列表组件未初始化")
                return
            
            # ✅ 立即启动动画（在耗时操作前）
            self._start_switch_animation()
            
            # ✅ 使用QTimer异步执行换号，确保动画立即显示
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self.account_list_widget.quick_switch_to_next)
            
        except Exception as e:
            self.logger.error(f"一键换号失败: {str(e)}")
            self._stop_switch_animation()
    
    def _start_switch_animation(self):
        """开始切换动画 - 柔和呼吸灯效果"""
        try:
            # ✅ 立即禁用按钮和改变文本
            self.quick_switch_btn.setEnabled(False)
            self.quick_switch_btn.setText("🔄 切换中...")
            
            # ✅ 创建柔和的呼吸灯动画
            self.switch_animation_timer = QTimer()
            self.switch_animation_frame = 0
            
            def animate_button():
                self.switch_animation_frame += 1
                if self.switch_animation_frame % 2 == 0:
                    # 柔和浅色（更容易看清字）
                    self.quick_switch_btn.setStyleSheet("""
                        QPushButton {
                            background-color: #A5D6A7;
                            color: #1B5E20;
                            font-size: 12px;
                            font-weight: bold;
                            border-radius: 6px;
                            padding: 6px 12px;
                            min-width: 84px;
                            max-width: 84px;
                            min-height: 24px;
                            max-height: 28px;
                        }
                    """)
                else:
                    # 柔和深色
                    self.quick_switch_btn.setStyleSheet("""
                        QPushButton {
                            background-color: #81C784;
                            color: #1B5E20;
                            font-size: 12px;
                            font-weight: bold;
                            border-radius: 6px;
                            padding: 6px 12px;
                            min-width: 84px;
                            max-width: 84px;
                            min-height: 24px;
                            max-height: 28px;
                        }
                    """)
            
            # ✅ 立即执行一次动画
            animate_button()
            
            self.switch_animation_timer.timeout.connect(animate_button)
            self.switch_animation_timer.start(400)  # 每400ms呼吸一次，更柔和
            
            # 30秒后自动停止动画（防止卡死）
            QTimer.singleShot(30000, self._stop_switch_animation)
            
        except Exception as e:
            self.logger.error(f"启动动画失败: {str(e)}")
    
    def _stop_switch_animation(self):
        """停止切换动画"""
        try:
            # 停止动画
            if hasattr(self, 'switch_animation_timer'):
                self.switch_animation_timer.stop()
                del self.switch_animation_timer
            
            # 恢复按钮
            self.quick_switch_btn.setEnabled(True)
            self.quick_switch_btn.setText("🔄 一键换号")
            self._style_menu_button(self.quick_switch_btn, "#66BB6A")
            # 恢复固定宽度
            self.quick_switch_btn.setFixedWidth(100)
            
        except Exception as e:
            self.logger.error(f"停止动画失败: {str(e)}")
    
    def show_import_dialog(self):
        """显示导入对话框 - 委托给账号列表widget"""
        if hasattr(self, 'account_list_widget') and self.account_list_widget:
            self.account_list_widget.show_import_dialog()
        else:
            self.show_status_message("⚠️ 账号管理组件未就绪")
    
    def export_accounts(self):
        """导出账号 - 委托给账号列表widget"""
        if hasattr(self, 'account_list_widget') and self.account_list_widget:
            self.account_list_widget.export_accounts()
        else:
            self.show_status_message("⚠️ 账号管理组件未就绪")
    
    def reset_machine_id(self):
        """重置机器码"""
        try:
            # 显示确认对话框
            reply = QMessageBox.question(
                self, "确认重置机器码", 
                "确定要重置机器码吗？\n\n这将：\n• 关闭Cursor进程\n• 生成新的机器码\n• 重置设备标识\n• 重新启动Cursor",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.show_status_message("正在重置机器码...")
                
                # 获取当前账号
                current_account = self.cursor_manager.get_current_account()
                if not current_account:
                    # 如果没有当前账号，创建一个空的账号对象
                    current_account = {'email': 'unknown'}
                
                # 完整的重置流程：关闭Cursor → 重置机器码 → 重启Cursor
                try:
                    # 1. 关闭Cursor进程
                    self.show_status_message("正在关闭Cursor进程...")
                    close_success, close_msg = self.cursor_manager.close_cursor_processes()
                    if close_success:
                        self.show_status_message("✅ 已关闭Cursor进程")
                    else:
                        self.show_status_message(f"⚠️ 关闭Cursor失败: {close_msg}")
                    
                    # 2. 重置机器码（强制生成全新随机机器码）
                    from ..services.cursor_service.xc_cursor_manage import XCCursorManager
                    xc_manager = XCCursorManager(self.config)
                    
                    reset_success, reset_message, _ = xc_manager.reset_machine_ids(
                        progress_callback=lambda msg: self.show_status_message(msg),
                        account_email=current_account.get('email', 'unknown'),
                        force_new=True  # 强制生成全新随机机器码
                    )
                    
                    if reset_success:
                        self.show_status_message("✅ 机器码重置成功")
                        
                        # 3. 重新启动Cursor
                        self.show_status_message("正在重新启动Cursor...")
                        start_success, start_msg = self.cursor_manager.start_cursor_with_workspaces()
                        if start_success:
                            self.show_status_message("✅ Cursor重启成功")
                            QMessageBox.information(self, "成功", "机器码重置成功")
                        else:
                            self.show_status_message(f"⚠️ Cursor重启失败: {start_msg}")
                            QMessageBox.information(self, "成功", 
                                "机器码重置成功\n\n请手动启动Cursor以使用新的机器码")
                    else:
                        self.show_status_message(f"❌ 机器码重置失败")
                        QMessageBox.warning(self, "警告", reset_message)
                        
                except Exception as e:
                    error_msg = f"重置过程出错: {str(e)}"
                    self.show_status_message(f"❌ {error_msg}")
                    QMessageBox.critical(self, "错误", error_msg)
                    
        except Exception as e:
            self.logger.error(f"重置机器码失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"重置机器码失败: {str(e)}")
    
    def complete_reset_cursor(self):
        """完全重置Cursor"""
        try:
            # 显示严重警告对话框
            reply = QMessageBox.warning(
                self, "⚠️ 完全重置警告", 
                "⚠️ 这是一个不可逆的危险操作！\n\n"
                "完全重置将：\n"
                "• 清理所有Cursor文件和缓存\n"
                "确定要继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 二次确认
                confirm = QMessageBox.critical(
                    self, "最后确认", 
                    "🚨 最后确认！\n\n"
                    "这将完全重置Cursor，所有数据将丢失！\n\n"
                    "真的要继续吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if confirm == QMessageBox.StandardButton.Yes:
                    self.show_status_message("正在执行完全重置...")
                    
                    # 获取当前账号（如果有的话）
                    current_account = self.cursor_manager.get_current_account()
                    if not current_account:
                        # 如果没有当前账号，创建一个空的账号对象
                        current_account = {'email': 'unknown'}
                    
                    # 执行完全重置：关闭进程 + 清理文件 + 重启
                    reset_success = False
                    reset_msg = ""
                    
                    try:
                        # 1. 关闭Cursor进程
                        close_success, close_msg = self.cursor_manager.close_cursor_processes()
                        if close_success:
                            self.show_status_message("✅ 已关闭Cursor进程")
                        
                        # 2. 清理Cursor缓存和临时文件
                        self.show_status_message("正在清理Cursor缓存和临时文件...")
                        clean_success, clean_msg = self._clean_cursor_data()
                        if clean_success:
                            self.show_status_message("✅ 已清理Cursor缓存")
                        else:
                            self.show_status_message(f"⚠️ 清理缓存失败: {clean_msg}")
                        
                        # 3. 重启Cursor
                        self.show_status_message("正在重新启动Cursor...")
                        start_success, start_msg = self.cursor_manager.start_cursor_with_workspaces()
                        
                        reset_success = clean_success  # 以清理成功为主要成功标准
                        reset_msg = f"清理: {clean_msg}"
                        if start_success:
                            reset_msg += f" | 重启: {start_msg}"
                        
                    except Exception as reset_error:
                        reset_success = False
                        reset_msg = f"完全重置失败: {str(reset_error)}"
                    
                    if reset_success:
                        self.show_status_message("✅ 完全重置成功")
                        QMessageBox.information(
                            self, "完全重置成功", 
                            "Cursor已完全重置（已清理缓存和历史记录）！\n\n请重新登录账号。"
                        )
                    else:
                        self.show_status_message(f"❌ 完全重置失败")
                        QMessageBox.warning(
                            self, "完全重置失败", 
                            f"完全重置失败：\n{reset_msg}"
                        )
                    
        except Exception as e:
            self.logger.error(f"完全重置失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"完全重置失败: {str(e)}")
    
    def _clean_cursor_data(self):
        """清理Cursor应用数据，包括历史记录和工作区缓存"""
        try:
            import shutil
            cursor_data_dir = self.config.get_cursor_data_dir()
            user_data_path = os.path.join(cursor_data_dir, "User")
            
            cleaned_items = []
            
            # 1. 清空关键目录的内容（不删除目录本身）
            dirs_to_clean = [
                os.path.join(user_data_path, 'History'),
                os.path.join(user_data_path, 'workspaceStorage')
            ]
            
            for dir_path in dirs_to_clean:
                if os.path.exists(dir_path):
                    try:
                        self._clear_directory_contents(dir_path)
                        cleaned_items.append(f"已清空目录: {os.path.basename(dir_path)}")
                        self.logger.info(f"已清空目录: {dir_path}")
                    except Exception as e:
                        self.logger.warning(f"清空目录 {dir_path} 失败: {str(e)}")
            
            # 2. 删除关键数据库文件
            key_files = [
                os.path.join(user_data_path, 'globalStorage', 'state.vscdb'),
                os.path.join(user_data_path, 'globalStorage', 'state.vscdb.backup')
            ]
            
            for file_path in key_files:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        cleaned_items.append(f"已删除文件: {os.path.basename(file_path)}")
                        self.logger.info(f"已删除文件: {file_path}")
                    except Exception as e:
                        self.logger.warning(f"删除文件 {file_path} 失败: {str(e)}")
            
            # 🔥 3. 删除机器码文件（清除trial限制标记）
            machine_id_files = [
                os.path.join(cursor_data_dir, 'machineId'),
                os.path.join(user_data_path, 'globalStorage', 'storage.json')
            ]
            
            for file_path in machine_id_files:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        cleaned_items.append(f"已删除机器码文件: {os.path.basename(file_path)}")
                        self.logger.info(f"已删除机器码文件: {file_path}")
                    except Exception as e:
                        self.logger.warning(f"删除机器码文件 {file_path} 失败: {str(e)}")
            
            if cleaned_items:
                return True, f"已清理 {len(cleaned_items)} 项，包括历史记录和工作区缓存"
            else:
                return True, "没有需要清理的数据"
                
        except Exception as e:
            error_msg = f"清理数据时出错: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def _clear_directory_contents(self, dir_path):
        """清空指定目录下的所有内容（文件和子目录），但不删除目录本身"""
        if not os.path.isdir(dir_path):
            return
        
        for item_name in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item_name)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    import shutil
                    shutil.rmtree(item_path)
            except Exception as e:
                self.logger.warning(f"无法删除 {item_path}: {str(e)}")
    
    def create_separator(self):
        """创建分隔符"""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #ddd; margin: 0 5px;")
        return separator
    
    def create_backup(self):
        """创建用户数据备份"""
        try:
            # 输入备份名称对话框
            from PyQt6.QtWidgets import QInputDialog
            backup_name, ok = QInputDialog.getText(
                self, "创建备份", 
                "请输入备份名称（留空则自动生成）：",
                text=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            
            if ok:
                self.show_status_message("正在创建备份...")
                success, message = self.cursor_manager.create_user_data_backup(backup_name if backup_name.strip() else None)
                
                if success:
                    self.show_status_message("✅ 备份创建成功")
                    QMessageBox.information(
                        self, "备份成功", 
                        "用户数据备份创建成功！"
                    )
                else:
                    self.show_status_message("❌ 备份创建失败")
                    QMessageBox.warning(self, "备份失败", f"备份创建失败：\n{message}")
                    
        except Exception as e:
            self.logger.error(f"创建备份失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"创建备份失败: {str(e)}")
    
    def restore_backup(self):
        """恢复用户数据备份"""
        try:
            # 获取备份列表
            backups = self.cursor_manager.list_user_data_backups()
            
            if not backups:
                QMessageBox.information(self, "提示", "没有找到任何备份。")
                return
            
            # 创建备份选择对话框
            from PyQt6.QtWidgets import QDialog, QListWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
            
            dialog = QDialog(self)
            dialog.setWindowTitle("选择备份")
            dialog.setFixedSize(500, 400)
            
            layout = QVBoxLayout()
            
            # 说明文字
            info_label = QLabel("选择要恢复的备份：\n⚠️ 恢复将覆盖当前的对话记录和设置！")
            info_label.setStyleSheet("color: #E6A23C; font-weight: bold; padding: 10px;")
            layout.addWidget(info_label)
            
            # 备份列表
            backup_list = QListWidget()
            for backup in backups:
                backup_name = backup.get('backup_name', '未知')
                created_at = backup.get('created_at', '未知')
                items = backup.get('items', [])
                
                # 格式化显示
                display_text = f"{backup_name}\n创建时间: {created_at}\n内容: {', '.join(items)}"
                backup_list.addItem(display_text)
                backup_list.item(backup_list.count() - 1).setData(0, backup_name)  # 存储备份名称
            
            layout.addWidget(backup_list)
            
            # 按钮
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            restore_btn = QPushButton("恢复")
            restore_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
            
            def do_restore():
                current_item = backup_list.currentItem()
                if current_item:
                    backup_name = current_item.data(0)
                    
                    # 二次确认
                    reply = QMessageBox.warning(
                        dialog, "确认恢复", 
                        f"确定要恢复备份 '{backup_name}' 吗？\n\n这将覆盖当前的对话记录和设置！",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        dialog.accept()
                        self.show_status_message("正在恢复备份...")
                        
                        # 简化流程：关闭Cursor -> 恢复备份
                        try:
                            # 1. 关闭Cursor进程
                            self.show_status_message("正在关闭Cursor进程...")
                            close_success, close_msg = self.cursor_manager.close_cursor_processes()
                            if close_success:
                                self.show_status_message("✅ 已关闭Cursor进程")
                            else:
                                self.show_status_message(f"⚠️ {close_msg}")
                            
                            # 2. 恢复备份数据
                            self.show_status_message("正在恢复备份数据...")
                            restore_success, restore_msg = self.cursor_manager.backup_manager.restore_backup(backup_name)
                            
                            if restore_success:
                                self.show_status_message("✅ 备份恢复完成")
                                QMessageBox.information(
                                    self, "恢复成功", 
                                    "备份恢复成功！\n\n请手动启动Cursor以查看恢复的内容。"
                                )
                            else:
                                self.show_status_message("❌ 备份恢复失败")
                                QMessageBox.warning(self, "恢复失败", f"备份恢复失败：\n{restore_msg}")
                                
                        except Exception as e:
                            error_msg = f"恢复备份过程出错: {str(e)}"
                            self.show_status_message(f"❌ {error_msg}")
                            QMessageBox.critical(self, "错误", error_msg)
            
            restore_btn.clicked.connect(do_restore)
            button_layout.addWidget(restore_btn)
            
            layout.addLayout(button_layout)
            dialog.setLayout(layout)
            
            dialog.exec()
                    
        except Exception as e:
            self.logger.error(f"恢复备份失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"恢复备份失败: {str(e)}")
    
    
    def refresh_account_list(self):
        """刷新账号列表 - 供自动注册完成后调用"""
        if hasattr(self, 'account_list_widget'):
            self.account_list_widget.load_accounts()
            if hasattr(self.account_list_widget, 'update_account_count'):
                self.account_list_widget.update_account_count()  # 更新统计信息
            self.show_status_message("✅ 账号列表已刷新")
    

    def setup_auth_monitor(self):
        """设置账号状态监控器 - 用于调试延迟失效问题"""
        self.auth_monitor_timer = QTimer()
        self.auth_monitor_timer.timeout.connect(self.check_auth_status)
        self.auth_monitor_timer.start(10000)  # 每10秒检查一次
        self.logger.info("🔍 账号状态监控器已启动（每10秒检查一次）")
        
        # 立即执行一次检查
        self.check_auth_status()
    
    def check_auth_status(self):
        """检查当前账号状态"""
        try:
            current_account = self.cursor_manager.get_current_account()
            
            if current_account:
                email = current_account.get('email', '未知')
                is_logged_in = current_account.get('is_logged_in', False)
                status_text = "✅ 已登录" if is_logged_in else "❌ 未登录"
                
                self.logger.info(f"🔍 状态监控: {status_text} - {email}")
                
                # 不在底部状态栏重复显示当前账号，顶部已有显示
            else:
                self.logger.info("🔍 状态监控: ❌ 未检测到登录账号")
                    
        except Exception as e:
            self.logger.error(f"❌ 账号状态检查失败: {str(e)}")

    def open_settings(self):
        """打开设置标签页"""
        try:
            # 切换到设置标签页
            if hasattr(self, 'tab_widget') and self.tab_widget:
                self.tab_widget.setCurrentIndex(2)  # 设置是第3个标签页（索引2）
            
        except Exception as e:
            self.logger.error(f"打开设置标签页失败: {str(e)}")
    
    def on_settings_changed(self):
        """处理设置变更"""
        try:
            # 通知账号列表组件刷新配置（它会自己重新加载配置）
            if self.account_list_widget and hasattr(self.account_list_widget, 'refresh_config'):
                self.account_list_widget.refresh_config()
            
            # 更新状态栏
            self.show_status_message("✅ 设置已更新")
            
        except Exception as e:
            self.logger.error(f"处理设置变更失败: {str(e)}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止监控器
        if hasattr(self, 'auth_monitor_timer'):
            self.auth_monitor_timer.stop()
        
        # 🔥 清理浏览器进程，避免关闭时卡顿
        try:
            if hasattr(self, 'account_list_widget') and self.account_list_widget:
                if hasattr(self.account_list_widget, 'dashboard_browser') and self.account_list_widget.dashboard_browser:
                    self.logger.info("正在清理浏览器进程...")
                    self.account_list_widget.dashboard_browser.quit()
                    self.account_list_widget.dashboard_browser = None
                    self.logger.info("✅ 浏览器进程已清理")
        except Exception as e:
            self.logger.warning(f"清理浏览器进程失败: {str(e)}")
        
        self.logger.info("MY Cursor 关闭")
        event.accept()
