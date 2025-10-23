#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XC-Cursor 云端数据库设置向导
帮助用户配置和测试云端数据库连接
"""

import os
import sys
import json
import logging
from datetime import datetime

# 添加项目路径
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

try:
    from src.cloud.cloud_db_config import CloudDatabaseConfig, RECOMMENDED_PROVIDERS
    from src.cloud.cloud_activation_manager import CloudActivationManager
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保在项目根目录运行此脚本")
    sys.exit(1)

def print_banner():
    """打印欢迎横幅"""
    print("\n" + "="*60)
    print("🌐 XC-Cursor 云端数据库设置向导")
    print("="*60)
    print("这个工具将帮助您配置云端数据库，实现激活码全球可用！")
    print("\n📋 设置步骤:")
    print("1. 选择云数据库提供商")
    print("2. 配置数据库连接信息")
    print("3. 测试连接")
    print("4. 初始化数据库表")
    print("5. (可选) 迁移本地激活码到云端")
    print("\n" + "="*60 + "\n")

def show_providers():
    """显示推荐的云数据库提供商"""
    print("🌟 推荐的免费云数据库提供商:\n")
    
    for i, (key, info) in enumerate(RECOMMENDED_PROVIDERS.items(), 1):
        print(f"{i}. {info['description']}")
        print(f"   网址: {info['url']}")
        print(f"   主机示例: {info['example_host']}")
        print(f"   端口: {info['port']}")
        print()

def get_database_config():
    """获取用户输入的数据库配置"""
    print("📝 请输入您的数据库连接信息:")
    print("(建议先在云服务商处创建好数据库)\n")
    
    config = {}
    
    # 主机地址
    config['host'] = input("🌐 数据库主机地址: ").strip()
    if not config['host']:
        print("❌ 主机地址不能为空!")
        return None
    
    # 端口
    port_input = input("🔌 端口 (默认3306): ").strip()
    config['port'] = int(port_input) if port_input else 3306
    
    # 用户名
    config['user'] = input("👤 用户名: ").strip()
    if not config['user']:
        print("❌ 用户名不能为空!")
        return None
    
    # 密码
    config['password'] = input("🔑 密码: ").strip()
    if not config['password']:
        print("❌ 密码不能为空!")
        return None
    
    # 数据库名
    config['database'] = input("🗄️ 数据库名: ").strip()
    if not config['database']:
        print("❌ 数据库名不能为空!")
        return None
    
    # 设置默认值
    config['charset'] = 'utf8mb4'
    config['autocommit'] = True
    config['connect_timeout'] = 10
    config['read_timeout'] = 10
    config['write_timeout'] = 10
    
    return config

def save_config(config):
    """保存配置到文件"""
    try:
        config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor')
        os.makedirs(config_dir, exist_ok=True)
        
        config_path = os.path.join(config_dir, 'cloud_db_config.json')
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 配置已保存到: {config_path}")
        return True
        
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        return False

def test_connection(config):
    """测试数据库连接"""
    print("\n🔍 正在测试数据库连接...")
    
    try:
        # 临时保存配置进行测试
        temp_config_path = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'cloud_db_config.json')
        os.makedirs(os.path.dirname(temp_config_path), exist_ok=True)
        
        with open(temp_config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # 测试连接
        manager = CloudActivationManager()
        print("✅ 数据库连接成功!")
        print("✅ 数据库表初始化完成!")
        return True
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("\n💡 可能的解决方案:")
        print("1. 检查网络连接")
        print("2. 确认数据库服务器是否在线")
        print("3. 验证主机地址、端口、用户名、密码是否正确")
        print("4. 确保数据库已创建")
        print("5. 检查防火墙设置")
        return False

def create_test_activation_code():
    """创建测试激活码"""
    try:
        print("\n🎯 创建测试激活码...")
        manager = CloudActivationManager()
        
        result = manager.create_activation_code(
            validity_hours=24,
            remark="云端数据库测试激活码",
            created_by="setup_wizard",
            user_type="normal"
        )
        
        if "error" not in result:
            print(f"✅ 测试激活码创建成功: {result['code']}")
            print(f"📅 有效期: {result['expiry_time']}")
            
            # 立即验证测试
            verify_result = manager.verify_activation_code(result['code'])
            if verify_result.get("success"):
                print("✅ 激活码验证测试通过!")
                return result['code']
            else:
                print(f"❌ 激活码验证失败: {verify_result.get('error')}")
        else:
            print(f"❌ 创建测试激活码失败: {result['error']}")
        
    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
    
    return None

def main():
    """主函数"""
    print_banner()
    
    # 显示推荐提供商
    show_providers()
    
    input("📖 请先在云服务商处创建数据库，然后按回车继续...")
    
    # 获取配置
    config = get_database_config()
    if not config:
        print("❌ 配置无效，退出设置")
        return
    
    print("\n📋 您的配置:")
    print(f"主机: {config['host']}")
    print(f"端口: {config['port']}")
    print(f"用户: {config['user']}")
    print(f"密码: {'*' * len(config['password'])}")
    print(f"数据库: {config['database']}")
    
    confirm = input("\n✅ 确认配置正确? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ 已取消设置")
        return
    
    # 保存配置
    if not save_config(config):
        return
    
    # 测试连接
    if not test_connection(config):
        return
    
    # 创建测试激活码
    test_code = create_test_activation_code()
    
    print("\n🎉 云端数据库设置完成!")
    print("\n📋 下一步:")
    print("1. 重新打包程序以使用云端数据库")
    print("2. 测试新的激活码生成器")
    
    if test_code:
        print(f"\n🔑 您可以使用这个测试激活码验证云端功能: {test_code}")
    
    print("\n✨ 现在您的激活码可以在任何电脑上使用了!")

if __name__ == "__main__":
    main()
