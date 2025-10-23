"""
标记管理对话框 - 为账户设置标记
功能：选择预设标记、创建自定义标记、预览效果
作者：小纯归来
创建时间：2025年9月
"""

import sys
from typing import List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QCheckBox, QScrollArea, QWidget, QFrame, QMessageBox,
    QColorDialog, QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QFont

from ..utils.tag_manager import TagManager, TagType, AccountTag, get_tag_manager

class TagButton(QPushButton):
    """标记按钮 - 显示标记名称和颜色"""
    
    def __init__(self, tag: AccountTag, is_selected: bool = False):
        super().__init__(tag.display_name)
        self.tag = tag
        self.is_selected = is_selected
        
        # 设置按钮样式
        self.setCheckable(True)
        self.setChecked(is_selected)
        self.setMinimumHeight(35)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.update_style()
        
        # 连接状态变化信号
        self.toggled.connect(self.on_toggled)
    
    def update_style(self):
        """更新按钮样式"""
        if self.isChecked():
            # 选中状态：使用标记颜色作为背景
            style = f"""
                QPushButton {{
                    background-color: {self.tag.color};
                    color: white;
                    border: 2px solid {self.tag.color};
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {self.lighten_color(self.tag.color)};
                }}
            """
        else:
            # 未选中状态：白色背景，彩色边框
            style = f"""
                QPushButton {{
                    background-color: white;
                    color: {self.tag.color};
                    border: 2px solid {self.tag.color};
                    border-radius: 6px;
                    padding: 5px 10px;
                }}
                QPushButton:hover {{
                    background-color: {self.tag.color}22;
                }}
            """
        
        self.setStyleSheet(style)
    
    def lighten_color(self, hex_color: str, factor: float = 1.2) -> str:
        """使颜色变浅"""
        try:
            color = QColor(hex_color)
            h, s, v, a = color.getHsv()
            v = min(255, int(v * factor))
            color.setHsv(h, s, v, a)
            return color.name()
        except:
            return hex_color
    
    def on_toggled(self, checked: bool):
        """处理选中状态变化"""
        self.is_selected = checked
        self.update_style()

# CustomTagDialog 删除，因为我们使用固定的三种标记

class TagManagementDialog(QDialog):
    """标记管理主对话框"""
    
    tags_changed = pyqtSignal()  # 标记变化信号
    
    def __init__(self, account_email: str = None, parent=None):
        super().__init__(parent)
        self.account_email = account_email
        self.tag_manager = get_tag_manager()
        
        self.setWindowTitle(f"标记管理 - {account_email}" if account_email else "标记管理")
        self.setFixedSize(600, 500)
        self.setModal(True)
        
        # 获取当前账户的标记
        self.current_tags = set()
        if account_email:
            current_tag_objects = self.tag_manager.get_account_tags(account_email)
            self.current_tags = {tag.tag_id for tag in current_tag_objects}
        
        self.setup_ui()
        self.load_tags()
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("为账户选择标记")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        if self.account_email:
            email_label = QLabel(f"账户: {self.account_email}")
            email_label.setStyleSheet("color: #666; font-size: 10px;")
            email_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(email_label)
        
        # 标记选择区域（简化版）
        tags_widget = QWidget()
        tags_layout = QVBoxLayout(tags_widget)
        
        # 创建三个标记按钮的容器
        self.tags_container = QGroupBox("选择标记")
        container_layout = QHBoxLayout(self.tags_container)
        container_layout.setSpacing(15)
        
        # 初始化标记按钮列表
        self.tag_buttons = []
        
        # 添加到布局
        tags_layout.addWidget(self.tags_container)
        tags_layout.addStretch()
        layout.addWidget(tags_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 取消和确定按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_tags)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #409eff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66b1ff;
            }
        """)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    
    def load_tags(self):
        """加载标记（简化版）"""
        container_layout = self.tags_container.layout()
        
        # 获取三种标记类型
        tag_types = [TagType.PERSONAL, TagType.EXHAUSTED, TagType.COMMERCIAL]
        
        for tag_type in tag_types:
            tags = self.tag_manager.get_tags_by_type(tag_type)
            for tag in tags:
                is_selected = tag.tag_id in self.current_tags
                button = TagButton(tag, is_selected)
                
                container_layout.addWidget(button)
                self.tag_buttons.append(button)
    
    
    def get_selected_tags(self) -> List[str]:
        """获取所有选中的标记ID"""
        selected_tags = []
        
        # 检查所有标记按钮
        for button in self.tag_buttons:
            if button.isChecked():
                selected_tags.append(button.tag.tag_id)
        
        return selected_tags
    
    def save_tags(self):
        """保存标记"""
        if not self.account_email:
            self.accept()
            return
        
        selected_tag_ids = self.get_selected_tags()
        
        try:
            # 设置账户标记
            success = self.tag_manager.set_account_tags(self.account_email, selected_tag_ids)
            
            if success:
                self.tags_changed.emit()
                QMessageBox.information(self, "成功", "标记设置已保存！")
                self.accept()
            else:
                QMessageBox.critical(self, "错误", "保存标记设置失败！")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")


# 测试代码
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试标记管理对话框
    dialog = TagManagementDialog("test@example.com")
    dialog.show()
    
    sys.exit(app.exec())
