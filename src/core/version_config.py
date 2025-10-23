"""
版本配置文件 - 控制完整版和精简版功能
"""

import os

class VersionConfig:
    """版本配置类"""
    
    # 软件版本号
    APP_VERSION = "12.0.5"
    
    # 版本类型：full（完整版）或 lite（精简版）
    VERSION_TYPE = os.getenv('XC_VERSION_TYPE', 'full')
    
    @classmethod
    def is_full_version(cls):
        """是否为完整版"""
        return cls.VERSION_TYPE == 'full'
    
    @classmethod
    def get_version_name(cls):
        """获取版本名称"""
        return "完整版" if cls.is_full_version() else "精简版"
    
    # 功能开关
    @classmethod
    def show_subscription_status(cls):
        """是否显示订阅状态"""
        return cls.is_full_version()
    
    @classmethod
    def show_pro_remarks(cls):
        """是否显示Pro备注"""
        return cls.is_full_version()
    
    @classmethod
    def show_concurrent_refresh(cls):
        """是否显示并发刷新（仅完整版显示）"""
        return cls.is_full_version()
