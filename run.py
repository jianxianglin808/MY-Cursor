#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
程序入口文件
用于 PyInstaller 打包和直接运行
"""

import sys
import os
from pathlib import Path

def main():
    """主入口函数"""
    # 设置基础路径
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的环境
        base_path = sys._MEIPASS
    else:
        # 开发环境
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # 添加到 Python 路径
    sys.path.insert(0, base_path)
    sys.path.insert(0, os.path.join(base_path, 'src'))
    
    # Windows 控制台编码处理
    if sys.platform == 'win32':
        try:
            import codecs
            if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
            if sys.stderr is not None and hasattr(sys.stderr, 'buffer'):
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')
        except:
            pass
    
    # 导入并运行主程序
    try:
        from src.ui.main_window import MainWindow
        from src.ui.activation_dialog import ActivationDialog
        from src.services.activation_service.client_config import ClientConfigManager
        from src.core.config import Config
        from PyQt6.QtWidgets import QApplication
        import logging
        
        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        logger = logging.getLogger(__name__)
        logger.info("启动 MY Cursor Manager v12.0.5...")
        
        # 创建应用
        app = QApplication(sys.argv)
        app.setApplicationName("MY Cursor Manager")
        app.setOrganizationName("MY")
        
        # 加载配置
        try:
            config = Config()
            logger.info("配置加载成功")
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
            # 使用默认配置
            config = None
        
        # 检查激活状态
        client_config = ClientConfigManager()
        saved_code = client_config.get_saved_activation_code()
        
        if not saved_code:
            logger.info("首次启动，显示激活对话框")
            activation_dialog = ActivationDialog()
            if activation_dialog.exec():
                logger.info("激活成功")
            else:
                logger.info("激活对话框关闭")
        
        # 创建主窗口
        logger.info("创建主窗口...")
        window = MainWindow(config)
        window.show()
        logger.info("主窗口显示成功")
        
        # 运行应用
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"程序启动失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 显示错误对话框
        try:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "启动错误", f"程序启动失败:\n\n{str(e)}\n\n{traceback.format_exc()}")
        except:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    main()

