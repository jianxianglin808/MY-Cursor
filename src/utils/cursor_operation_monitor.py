#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cursor操作监控器 - 监控其他换号软件的操作逻辑
用于学习和分析成功的账号切换实现
"""

import sqlite3
import json
import os
import time
import hashlib
import shutil
import threading
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class CursorDatabaseMonitor:
    """SQLite数据库变化监控器"""
    
    def __init__(self, db_path: str, logger=None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)
        self.initial_state = {}
        self.monitoring = False
        self.changes_log = []
        
    def capture_initial_state(self) -> bool:
        """捕获数据库初始状态"""
        try:
            if not os.path.exists(self.db_path):
                self.logger.error(f"数据库文件不存在: {self.db_path}")
                return False
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 获取所有ItemTable数据
            cursor.execute("SELECT key, value FROM ItemTable")
            rows = cursor.fetchall()
            
            self.initial_state = {key: value for key, value in rows}
            conn.close()
            
            self.logger.info(f"✅ 已捕获数据库初始状态: {len(self.initial_state)} 个键值对")
            return True
            
        except Exception as e:
            self.logger.error(f"捕获初始状态失败: {str(e)}")
            return False
    
    def start_monitoring(self):
        """开始监控数据库变化"""
        self.monitoring = True
        self.changes_log = []
        
        def monitor_loop():
            self.logger.info("🔍 开始监控数据库变化...")
            
            while self.monitoring:
                try:
                    current_changes = self.detect_changes()
                    if current_changes:
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        self.changes_log.append({
                            'timestamp': timestamp,
                            'changes': current_changes
                        })
                        
                        self.logger.info(f"📊 [{timestamp}] 检测到 {len(current_changes)} 个变化:")
                        for change in current_changes:
                            self.logger.info(f"  {change['type']}: {change['key']} = {change['new_value'][:50] if change.get('new_value') else 'None'}...")
                    
                    time.sleep(0.5)  # 每0.5秒检查一次
                    
                except Exception as e:
                    self.logger.error(f"监控循环异常: {str(e)}")
                    time.sleep(1)
        
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        self.logger.info("🛑 数据库监控已停止")
    
    def detect_changes(self) -> List[Dict]:
        """检测数据库变化"""
        try:
            if not os.path.exists(self.db_path):
                return []
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT key, value FROM ItemTable")
            rows = cursor.fetchall()
            current_state = {key: value for key, value in rows}
            conn.close()
            
            changes = []
            
            # 检测新增和修改
            for key, value in current_state.items():
                if key not in self.initial_state:
                    changes.append({
                        'type': 'ADDED',
                        'key': key,
                        'new_value': value,
                        'old_value': None
                    })
                elif self.initial_state[key] != value:
                    changes.append({
                        'type': 'MODIFIED',
                        'key': key,
                        'new_value': value,
                        'old_value': self.initial_state[key]
                    })
            
            # 检测删除
            for key in self.initial_state:
                if key not in current_state:
                    changes.append({
                        'type': 'DELETED',
                        'key': key,
                        'new_value': None,
                        'old_value': self.initial_state[key]
                    })
            
            # 更新初始状态为当前状态
            self.initial_state = current_state
            
            return changes
            
        except Exception as e:
            self.logger.error(f"检测变化失败: {str(e)}")
            return []
    
    def get_changes_summary(self) -> Dict:
        """获取变化总结"""
        if not self.changes_log:
            return {"total_changes": 0, "summary": "无变化"}
        
        total_changes = sum(len(log['changes']) for log in self.changes_log)
        
        # 按键分类统计
        key_stats = {}
        for log in self.changes_log:
            for change in log['changes']:
                key = change['key']
                change_type = change['type']
                
                if key not in key_stats:
                    key_stats[key] = {'ADDED': 0, 'MODIFIED': 0, 'DELETED': 0}
                key_stats[key][change_type] += 1
        
        return {
            "total_changes": total_changes,
            "total_logs": len(self.changes_log),
            "key_statistics": key_stats,
            "timeline": self.changes_log
        }


class CursorFileMonitor(FileSystemEventHandler):
    """Cursor配置文件监控器"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.changes_log = []
        
    def on_modified(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        filename = os.path.basename(file_path)
        
        # 只监控关键文件
        if filename in ['storage.json', 'machineId', 'state.vscdb']:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.changes_log.append({
                'timestamp': timestamp,
                'type': 'MODIFIED',
                'file': file_path,
                'filename': filename
            })
            
            self.logger.info(f"📁 [{timestamp}] 文件修改: {filename}")
            
            # 如果是JSON文件，尝试读取内容
            if filename == 'storage.json':
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                    
                    # 记录机器码相关字段
                    machine_fields = {k: v for k, v in content.items() if 'machine' in k.lower() or 'telemetry' in k.lower()}
                    if machine_fields:
                        self.logger.info(f"  机器码字段: {list(machine_fields.keys())}")
                        
                except Exception as e:
                    self.logger.warning(f"读取 {filename} 失败: {str(e)}")
    
    def on_created(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        filename = os.path.basename(file_path)
        
        if filename in ['storage.json', 'machineId', 'state.vscdb']:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.changes_log.append({
                'timestamp': timestamp,
                'type': 'CREATED',
                'file': file_path,
                'filename': filename
            })
            
            self.logger.info(f"📁 [{timestamp}] 文件创建: {filename}")
    
    def on_deleted(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        filename = os.path.basename(file_path)
        
        if filename in ['storage.json', 'machineId', 'state.vscdb']:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.changes_log.append({
                'timestamp': timestamp,
                'type': 'DELETED',
                'file': file_path,
                'filename': filename
            })
            
            self.logger.info(f"📁 [{timestamp}] 文件删除: {filename}")


class CursorOperationMonitor:
    """Cursor操作综合监控器"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.db_path = config.get('cursor', 'db_path')
        
        # 获取Cursor用户数据路径（使用配置中的路径）
        cursor_data_dir = config.get_cursor_data_dir()
        self.user_data_path = os.path.join(cursor_data_dir, "User")
        
        self.db_monitor = CursorDatabaseMonitor(self.db_path, self.logger)
        self.file_monitor = CursorFileMonitor(self.logger)
        self.observer = None
        
    def start_comprehensive_monitoring(self) -> bool:
        """开始综合监控"""
        try:
            self.logger.info("🚀 启动Cursor操作综合监控...")
            
            # 1. 捕获数据库初始状态
            if not self.db_monitor.capture_initial_state():
                return False
            
            # 2. 启动数据库监控
            self.db_monitor.start_monitoring()
            
            # 3. 启动文件系统监控
            self.observer = Observer()
            
            # 监控关键目录
            monitor_paths = [
                os.path.dirname(self.db_path),  # globalStorage目录
                os.path.join(os.getenv("APPDATA", ""), "Cursor"),  # Cursor根目录
            ]
            
            for path in monitor_paths:
                if os.path.exists(path):
                    self.observer.schedule(self.file_monitor, path, recursive=True)
                    self.logger.info(f"📂 监控目录: {path}")
            
            self.observer.start()
            
            self.logger.info("✅ 综合监控已启动，请在另一个软件中执行账号切换操作")
            self.logger.info("📝 监控将记录所有数据库和文件变化")
            
            return True
            
        except Exception as e:
            self.logger.error(f"启动监控失败: {str(e)}")
            return False
    
    def stop_monitoring(self) -> Dict:
        """停止监控并返回结果"""
        try:
            self.logger.info("🛑 停止监控...")
            
            # 停止数据库监控
            self.db_monitor.stop_monitoring()
            
            # 停止文件监控
            if self.observer:
                self.observer.stop()
                self.observer.join()
            
            # 收集监控结果
            db_summary = self.db_monitor.get_changes_summary()
            file_changes = self.file_monitor.changes_log
            
            results = {
                'database_changes': db_summary,
                'file_changes': file_changes,
                'monitoring_duration': time.time()
            }
            
            self.logger.info("📊 监控结果已收集")
            return results
            
        except Exception as e:
            self.logger.error(f"停止监控失败: {str(e)}")
            return {}
    
    def export_monitoring_results(self, results: Dict, output_file: str = None) -> str:
        """导出监控结果到文件"""
        try:
            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"cursor_monitor_results_{timestamp}.json"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📄 监控结果已导出: {output_file}")
            return output_file
            
        except Exception as e:
            self.logger.error(f"导出结果失败: {str(e)}")
            return ""
    
    def analyze_auth_changes(self, results: Dict) -> Dict:
        """分析认证相关的变化"""
        try:
            db_changes = results.get('database_changes', {})
            key_stats = db_changes.get('key_statistics', {})
            
            # 筛选认证相关的键
            # 🔥 修复：移除cursor.前缀字段监控，这些字段会导致冲突
            auth_keys = [
                'cursorAuth/cachedEmail',
                'cursorAuth/accessToken', 
                'cursorAuth/refreshToken',
                'cursorAuth/userId',
                'cursorAuth/cachedSignUpType',
                # 不再监控cursor.前缀字段，这些会导致Cursor检测到冲突
            ]
            
            auth_changes = {}
            for key in auth_keys:
                if key in key_stats:
                    auth_changes[key] = key_stats[key]
            
            # 分析变化模式
            analysis = {
                'auth_field_changes': auth_changes,
                'total_auth_changes': sum(sum(stats.values()) for stats in auth_changes.values()),
                'change_pattern': self._analyze_change_pattern(results, auth_keys)
            }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"分析认证变化失败: {str(e)}")
            return {}
    
    def analyze_machine_id_changes(self, results: Dict) -> Dict:
        """分析机器码相关的变化"""
        try:
            db_changes = results.get('database_changes', {})
            key_stats = db_changes.get('key_statistics', {})
            
            # 筛选机器码相关的键
            machine_keys = [
                'telemetry.devDeviceId',
                'telemetry.macMachineId',
                'telemetry.machineId',
                'telemetry.sqmId',
                'storage.serviceMachineId'
            ]
            
            machine_changes = {}
            for key in machine_keys:
                if key in key_stats:
                    machine_changes[key] = key_stats[key]
            
            # 分析文件变化
            file_changes = results.get('file_changes', [])
            machine_file_changes = [
                change for change in file_changes 
                if change['filename'] in ['storage.json', 'machineId']
            ]
            
            analysis = {
                'machine_field_changes': machine_changes,
                'machine_file_changes': machine_file_changes,
                'total_machine_changes': sum(sum(stats.values()) for stats in machine_changes.values()),
                'change_sequence': self._get_machine_change_sequence(results)
            }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"分析机器码变化失败: {str(e)}")
            return {}
    
    def _analyze_change_pattern(self, results: Dict, target_keys: List[str]) -> List[Dict]:
        """分析变化模式"""
        timeline = results.get('database_changes', {}).get('timeline', [])
        pattern = []
        
        for log_entry in timeline:
            timestamp = log_entry['timestamp']
            changes = log_entry['changes']
            
            relevant_changes = [
                change for change in changes 
                if change['key'] in target_keys
            ]
            
            if relevant_changes:
                pattern.append({
                    'timestamp': timestamp,
                    'changes': relevant_changes
                })
        
        return pattern
    
    def _get_machine_change_sequence(self, results: Dict) -> List[Dict]:
        """获取机器码变化序列"""
        timeline = results.get('database_changes', {}).get('timeline', [])
        file_changes = results.get('file_changes', [])
        
        # 合并数据库和文件变化
        all_changes = []
        
        # 添加数据库变化
        for log_entry in timeline:
            timestamp = log_entry['timestamp']
            for change in log_entry['changes']:
                if any(keyword in change['key'] for keyword in ['telemetry', 'machine', 'device']):
                    all_changes.append({
                        'timestamp': timestamp,
                        'source': 'database',
                        'change': change
                    })
        
        # 添加文件变化
        for file_change in file_changes:
            if file_change['filename'] in ['storage.json', 'machineId']:
                all_changes.append({
                    'timestamp': file_change['timestamp'],
                    'source': 'file',
                    'change': file_change
                })
        
        # 按时间排序
        all_changes.sort(key=lambda x: x['timestamp'])
        
        return all_changes


def create_monitoring_session(config) -> CursorOperationMonitor:
    """创建监控会话"""
    monitor = CursorOperationMonitor(config)
    return monitor


def read_binary_file_as_text(file_path: str, encoding_attempts: List[str] = None) -> Tuple[bool, str]:
    """
    尝试以不同编码读取可能的二进制文件
    
    Args:
        file_path: 文件路径
        encoding_attempts: 尝试的编码列表
        
    Returns:
        Tuple[bool, str]: (是否成功, 文件内容或错误信息)
    """
    if encoding_attempts is None:
        encoding_attempts = ['utf-8', 'gbk', 'latin-1', 'ascii']
    
    for encoding in encoding_attempts:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            return True, content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return False, f"读取文件失败: {str(e)}"
    
    # 如果所有文本编码都失败，尝试二进制读取并转换为十六进制
    try:
        with open(file_path, 'rb') as f:
            binary_content = f.read()
        
        # 如果文件很小，可能是文本文件
        if len(binary_content) < 1024:
            hex_content = binary_content.hex()
            return True, f"二进制内容(hex): {hex_content}"
        else:
            return True, f"二进制文件，大小: {len(binary_content)} 字节"
            
    except Exception as e:
        return False, f"读取二进制文件失败: {str(e)}"


if __name__ == "__main__":
    # 测试读取state.md文件
    state_file = "state.md"
    if os.path.exists(state_file):
        success, content = read_binary_file_as_text(state_file)
        if success:
            print(f"文件内容:\n{content}")
        else:
            print(f"读取失败: {content}")
    else:
        print(f"文件不存在: {state_file}")
