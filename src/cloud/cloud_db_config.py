#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XC-Cursor 云端数据库配置管理器
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path


class CloudDatabaseConfig:
    """云端数据库配置管理器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config_cache: Optional[Dict[str, Any]] = None
    
    def get_database_config(self) -> Dict[str, Any]:
        """
        获取数据库配置
        优先级: 环境变量 > 配置文件 > 引导用户配置
        """
        if self._config_cache:
            return self._config_cache
        
        # 1. 尝试从环境变量读取
        if self._has_env_config():
            self.logger.info("使用环境变量中的数据库配置")
            self._config_cache = self._get_env_config()
            return self._config_cache
        
        # 2. 尝试从配置文件读取
        config_path = self._get_config_path()
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding='utf-8'))
                if self._is_valid_config(config):
                    self.logger.info(f"使用配置文件: {config_path}")
                    self._config_cache = config
                    return config
            except Exception as e:
                self.logger.warning(f"读取配置文件失败: {e}")
        
        # 3. 抛出友好的错误提示
        raise ValueError(
            "\n" + "="*60 + "\n" +
            "❌ 云端数据库未配置！\n\n" +
            "请选择以下方式之一配置数据库：\n\n" +
            "1️⃣ 设置环境变量：\n" +
            "   - XC_DB_HOST: 数据库主机地址\n" +
            "   - XC_DB_USER: 数据库用户名\n" +
            "   - XC_DB_PASSWORD: 数据库密码\n" +
            "   - XC_DB_NAME: 数据库名称\n\n" +
            "2️⃣ 创建配置文件：\n" +
            f"   路径: {config_path}\n" +
            "   内容示例:\n" +
            json.dumps(self._get_config_template(), indent=2, ensure_ascii=False) + "\n\n" +
            "3️⃣ 运行配置向导：\n" +
            "   python tools/setup_cloud_database.py\n" +
            "="*60
        )
    
    def _has_env_config(self) -> bool:
        """检查是否有环境变量配置"""
        required_vars = ['XC_DB_HOST', 'XC_DB_USER', 'XC_DB_PASSWORD', 'XC_DB_NAME']
        return all(os.getenv(var) for var in required_vars)
    
    def _get_env_config(self) -> Dict[str, Any]:
        """从环境变量获取配置"""
        return {
            'host': os.getenv('XC_DB_HOST'),
            'port': int(os.getenv('XC_DB_PORT', '3306')),
            'user': os.getenv('XC_DB_USER'),
            'password': os.getenv('XC_DB_PASSWORD'),
            'database': os.getenv('XC_DB_NAME'),
            'charset': os.getenv('XC_DB_CHARSET', 'utf8mb4'),
            'autocommit': True,
            'connect_timeout': 10,
            'read_timeout': 10,
            'write_timeout': 10
        }
    
    def _get_config_path(self) -> Path:
        """获取配置文件路径"""
        config_dir = Path.home() / '.xc_cursor'
        return config_dir / 'cloud_db_config.json'
    
    def _is_valid_config(self, config: Dict[str, Any]) -> bool:
        """验证配置是否有效"""
        required_fields = ['host', 'user', 'password', 'database']
        
        # 检查必要字段
        for field in required_fields:
            if not config.get(field):
                return False
        
        # 检查是否使用了占位符
        placeholders = ['your-database-host.com', 'your_username', 'your_password']
        config_values = [config.get('host'), config.get('user'), config.get('password')]
        
        return not any(value in placeholders for value in config_values)
    
    def _get_config_template(self) -> Dict[str, Any]:
        """获取配置模板"""
        return {
            'host': 'db.example.com',
            'port': 3306,
            'user': 'your_username',
            'password': 'your_password',
            'database': 'xc_cursor_db',
            'charset': 'utf8mb4',
            'autocommit': True,
            'connect_timeout': 10,
            'read_timeout': 10,
            'write_timeout': 10
        }
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        保存配置到文件
        
        Args:
            config: 数据库配置
            
        Returns:
            bool: 是否保存成功
        """
        try:
            if not self._is_valid_config(config):
                raise ValueError("配置无效或包含占位符")
            
            config_path = self._get_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            config_path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            
            self.logger.info(f"配置已保存到: {config_path}")
            self._config_cache = config  # 更新缓存
            return True
            
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            return False


# 推荐的免费云数据库服务商
RECOMMENDED_PROVIDERS = {
    "💡 本地测试": {
        "description": "使用本地激活模式，无需数据库",
        "action": "use_local",
        "note": "适合个人使用，激活码仅在本机有效"
    },
    
    "🌟 PlanetScale": {
        "description": "MySQL兼容，免费5GB",
        "url": "https://planetscale.com/",
        "example_host": "aws.connect.psdb.cloud",
        "port": 3306,
        "note": "需要SSL证书，性能优秀"
    },
    
    "🚂 Railway": {
        "description": "PostgreSQL/MySQL，免费500小时/月",
        "url": "https://railway.app/",
        "example_host": "containers-us-west-x.railway.app",
        "port": 3306,
        "note": "部署简单，适合快速开始"
    },
    
    "☁️ Aiven": {
        "description": "MySQL/PostgreSQL，免费1个月试用",
        "url": "https://aiven.io/",
        "example_host": "mysql-xxx.aivencloud.com",
        "port": 3306,
        "note": "专业级服务，功能完整"
    },
    
    "🆓 FreeSQLDatabase": {
        "description": "免费MySQL 5MB",
        "url": "https://www.freesqldatabase.com/",
        "example_host": "sql.freesqldatabase.com",
        "port": 3306,
        "note": "容量小，适合测试"
    }
}