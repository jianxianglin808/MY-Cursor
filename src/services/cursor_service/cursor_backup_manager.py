#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cursor备份管理器 - 备份和恢复对话记录、扩展等用户数据
管理用户数据路径结构，不包括机器码和认证信息
"""

import os
import sys
import json
import shutil
import logging
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from pathlib import Path


class CursorBackupManager:
    """Cursor备份管理器"""
    
    def __init__(self, config=None):
        """初始化备份管理器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 获取Cursor根数据路径和用户数据路径
        if config:
            self.cursor_data_dir = config.get_cursor_data_dir()
            self.user_data_path = os.path.join(self.cursor_data_dir, "User")
        else:
            # 没有配置时使用默认路径
            if os.name == 'nt':  # Windows
                self.cursor_data_dir = os.path.join(os.getenv("APPDATA", ""), "Cursor")
                self.user_data_path = os.path.join(self.cursor_data_dir, "User")
            elif sys.platform == 'darwin':  # macOS
                self.cursor_data_dir = os.path.expanduser("~/Library/Application Support/Cursor")
                self.user_data_path = os.path.join(self.cursor_data_dir, "User")
            else:  # Linux
                self.cursor_data_dir = os.path.expanduser("~/.config/Cursor")
                self.user_data_path = os.path.join(self.cursor_data_dir, "User")
        
        # 备份存储目录
        try:
            self.backup_root = os.path.join(
                config.config_dir if config else os.path.expanduser("~/.xc-cursor"), 
                "backups"
            )
            os.makedirs(self.backup_root, exist_ok=True)
        except Exception as e:
            self.logger.warning(f"初始化备份目录失败: {e}")
            # 使用临时目录作为备份
            self.backup_root = os.path.join(tempfile.gettempdir(), "xc-cursor-backups")
            os.makedirs(self.backup_root, exist_ok=True)
    
    def create_backup(self, backup_name: str = None) -> Tuple[bool, str]:
        """
        创建Cursor用户数据备份
        
        Args:
            backup_name: 备份名称，如果为None则使用时间戳
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            if not backup_name:
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            backup_dir = os.path.join(self.backup_root, backup_name)
            
            if os.path.exists(backup_dir):
                return False, f"备份 {backup_name} 已存在"
            
            os.makedirs(backup_dir, exist_ok=True)
            self.logger.info(f"开始创建备份: {backup_name}")
            
            backed_up_items = []
            
            # 1. 备份对话历史（History目录） - 核心功能
            history_src = os.path.join(self.user_data_path, "History")
            if os.path.exists(history_src):
                history_dst = os.path.join(backup_dir, "History")
                shutil.copytree(history_src, history_dst)
                backed_up_items.append("对话历史")
                self.logger.info("✅ 已备份对话历史")
            
            # 2. 备份工作区存储（workspaceStorage目录） - AI对话上下文
            workspace_storage_src = os.path.join(self.user_data_path, "workspaceStorage")
            if os.path.exists(workspace_storage_src):
                workspace_storage_dst = os.path.join(backup_dir, "workspaceStorage")
                self._safe_copytree(workspace_storage_src, workspace_storage_dst)
                backed_up_items.append("工作区对话")
                self.logger.info("✅ 已备份工作区对话上下文")
            
            # 3. 备份基本用户设置
            settings_src = os.path.join(self.user_data_path, "settings.json")
            if os.path.exists(settings_src):
                settings_dst = os.path.join(backup_dir, "settings.json")
                shutil.copy2(settings_src, settings_dst)
                backed_up_items.append("用户设置")
                self.logger.info("✅ 已备份用户设置")
            
            # 4. 备份键绑定
            keybindings_src = os.path.join(self.user_data_path, "keybindings.json")
            if os.path.exists(keybindings_src):
                keybindings_dst = os.path.join(backup_dir, "keybindings.json")
                shutil.copy2(keybindings_src, keybindings_dst)
                backed_up_items.append("键绑定")
                self.logger.info("✅ 已备份键绑定")
            
            # 5. 备份扩展（仅备份扩展列表，不备份扩展文件）
            extensions_src = os.path.join(self.user_data_path, "extensions")
            if os.path.exists(extensions_src):
                # 只备份扩展的配置文件，不备份整个扩展目录
                extensions_dst = os.path.join(backup_dir, "extensions")
                os.makedirs(extensions_dst, exist_ok=True)
                
                # 备份扩展配置文件
                for item in os.listdir(extensions_src):
                    if item.endswith('.json'):
                        src_file = os.path.join(extensions_src, item)
                        dst_file = os.path.join(extensions_dst, item)
                        try:
                            shutil.copy2(src_file, dst_file)
                        except Exception as e:
                            self.logger.warning(f"无法备份扩展配置 {item}: {e}")
                
                backed_up_items.append("扩展配置")
                self.logger.info("✅ 已备份扩展配置")
            
            # 6. 备份globalStorage数据库（包含对话历史索引和状态）
            global_storage_src = os.path.join(self.user_data_path, "globalStorage")
            if os.path.exists(global_storage_src):
                global_storage_dst = os.path.join(backup_dir, "globalStorage")
                os.makedirs(global_storage_dst, exist_ok=True)
                
                # 备份state.vscdb数据库（包含对话历史索引）
                db_files = ["state.vscdb", "state.vscdb.backup", "state.vscdb-shm", "state.vscdb-wal"]
                for db_file in db_files:
                    db_src = os.path.join(global_storage_src, db_file)
                    if os.path.exists(db_src):
                        try:
                            db_dst = os.path.join(global_storage_dst, db_file)
                            shutil.copy2(db_src, db_dst)
                            self.logger.info(f"✅ 已备份数据库文件: {db_file}")
                        except Exception as e:
                            self.logger.warning(f"备份数据库文件 {db_file} 失败: {e}")
                
                # 备份globalStorage下的其他重要数据
                for item in os.listdir(global_storage_src):
                    item_path = os.path.join(global_storage_src, item)
                    if os.path.isdir(item_path):
                        try:
                            item_dst = os.path.join(global_storage_dst, item)
                            self._safe_copytree(item_path, item_dst)
                        except Exception as e:
                            self.logger.warning(f"备份globalStorage子目录 {item} 失败: {e}")
                
                backed_up_items.append("数据库")
                self.logger.info("✅ 已备份globalStorage数据库")
            
            # 创建备份元数据
            metadata = {
                "backup_name": backup_name,
                "created_at": datetime.now().isoformat(),
                "items": backed_up_items,
                "version": "1.0"
            }
            
            with open(os.path.join(backup_dir, "metadata.json"), 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            message = f"✅ 备份创建成功: {backup_name}\n备份内容: {', '.join(backed_up_items)}"
            self.logger.info(message)
            return True, message
            
        except Exception as e:
            error_msg = f"创建备份失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def restore_backup(self, backup_name: str, exclude_auth: bool = True) -> Tuple[bool, str]:
        """
        恢复Cursor用户数据备份
        
        Args:
            backup_name: 备份名称
            exclude_auth: 是否排除认证信息（默认True）
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            backup_dir = os.path.join(self.backup_root, backup_name)
            
            if not os.path.exists(backup_dir):
                return False, f"备份 {backup_name} 不存在"
            
            # 读取备份元数据
            metadata_file = os.path.join(backup_dir, "metadata.json")
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                self.logger.info(f"恢复备份: {backup_name} (创建于: {metadata.get('created_at')})")
            
            restored_items = []
            
            # 1. 恢复对话历史 - 核心功能
            history_src = os.path.join(backup_dir, "History")
            if os.path.exists(history_src):
                history_dst = os.path.join(self.user_data_path, "History")
                if os.path.exists(history_dst):
                    shutil.rmtree(history_dst)
                shutil.copytree(history_src, history_dst)
                restored_items.append("对话历史")
                self.logger.info("✅ 已恢复对话历史")
            
            # 2. 恢复工作区存储 - AI对话上下文（增量覆盖模式）
            workspace_storage_src = os.path.join(backup_dir, "workspaceStorage")
            if os.path.exists(workspace_storage_src):
                workspace_storage_dst = os.path.join(self.user_data_path, "workspaceStorage")
                try:
                    # 使用增量覆盖而非全删除，保留未备份的工作区
                    self._safe_copytree(workspace_storage_src, workspace_storage_dst)
                    restored_items.append("工作区对话")
                    self.logger.info("✅ 已恢复工作区对话上下文")
                except Exception as e:
                    self.logger.warning(f"恢复工作区存储时出现问题: {e}")
            
            # 3. 恢复用户设置
            settings_src = os.path.join(backup_dir, "settings.json")
            if os.path.exists(settings_src):
                settings_dst = os.path.join(self.user_data_path, "settings.json")
                shutil.copy2(settings_src, settings_dst)
                restored_items.append("用户设置")
                self.logger.info("✅ 已恢复用户设置")
            
            # 4. 恢复键绑定
            keybindings_src = os.path.join(backup_dir, "keybindings.json")
            if os.path.exists(keybindings_src):
                keybindings_dst = os.path.join(self.user_data_path, "keybindings.json")
                shutil.copy2(keybindings_src, keybindings_dst)
                restored_items.append("键绑定")
                self.logger.info("✅ 已恢复键绑定")
            
            # 5. 恢复扩展配置（不恢复扩展文件）
            extensions_src = os.path.join(backup_dir, "extensions")
            if os.path.exists(extensions_src):
                extensions_dst = os.path.join(self.user_data_path, "extensions")
                os.makedirs(extensions_dst, exist_ok=True)
                
                # 只恢复扩展配置文件
                for item in os.listdir(extensions_src):
                    if item.endswith('.json'):
                        src_file = os.path.join(extensions_src, item)
                        dst_file = os.path.join(extensions_dst, item)
                        try:
                            shutil.copy2(src_file, dst_file)
                        except Exception as e:
                            self.logger.warning(f"无法恢复扩展配置 {item}: {e}")
                
                restored_items.append("扩展配置")
                self.logger.info("✅ 已恢复扩展配置")
            
            # 6. 恢复state.vscdb数据库（包含账号信息和对话历史索引）
            global_storage_src = os.path.join(backup_dir, "globalStorage")
            if os.path.exists(global_storage_src):
                backup_db_path = os.path.join(global_storage_src, "state.vscdb")
                current_db_path = os.path.join(self.user_data_path, "globalStorage", "state.vscdb")
                
                # 确保目标目录存在
                os.makedirs(os.path.dirname(current_db_path), exist_ok=True)
                
                if os.path.exists(backup_db_path):
                    # 检查当前数据库是否存在
                    if not os.path.exists(current_db_path):
                        self.logger.warning("⚠️ 当前数据库不存在，请先启动一次Cursor让系统创建数据库")
                        self.logger.info("💡 建议：完全重置后会自动启动Cursor并创建数据库")
                    else:
                        try:
                            # 🔥 新策略：完整替换数据库文件以保持索引完整性，删除机器码让系统重新生成
                            
                            # 1️⃣ 用备份数据库完整替换当前数据库（保持索引和内部状态完整）
                            self.logger.info("正在完整替换数据库文件以保持索引完整性...")
                            
                            # 删除相关文件
                            db_related_files = [
                                current_db_path,
                                current_db_path + ".backup",
                                current_db_path + "-shm",
                                current_db_path + "-wal"
                            ]
                            for file_path in db_related_files:
                                if os.path.exists(file_path):
                                    try:
                                        os.remove(file_path)
                                    except Exception as e:
                                        self.logger.warning(f"删除文件 {file_path} 失败: {e}")
                            
                            # 复制备份数据库及相关文件
                            shutil.copy2(backup_db_path, current_db_path)
                            for suffix in [".backup", "-shm", "-wal"]:
                                backup_file = backup_db_path + suffix
                                if os.path.exists(backup_file):
                                    try:
                                        shutil.copy2(backup_file, current_db_path + suffix)
                                    except Exception as e:
                                        self.logger.debug(f"复制数据库附属文件失败: {e}")
                            
                            # 2️⃣ 删除不想恢复的键（临时数据 + 机器码）
                            current_conn = sqlite3.connect(current_db_path)
                            current_cursor = current_conn.cursor()
                            
                            delete_keys = [
                                # 临时会话和缓存数据
                                "telemetry.currentSessionDate",
                                "workbench.auxiliarybar.pinnedPanels",
                                "notifications.perSourceDoNotDisturbMode",
                                "vscode.typescript-language-features",
                                "editorFontInfo",
                                "workbench.auxiliarybar.placeholderPanels",
                                "workbench.panel.placeholderPanels",
                                "editorOverrideService.cache",
                                "extensionsAssistant/recommendations",
                                "cursorai/serverConfig",
                                "__$__targetStorageMarker",
                                # 🔥 删除机器码让系统重新生成（绕过trial限制）
                                "telemetry.devDeviceId",
                                "telemetry.macMachineId",
                                "telemetry.machineId",
                                "telemetry.sqmId",
                            ]
                            
                            deleted_count = 0
                            for key in delete_keys:
                                current_cursor.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
                                if current_cursor.rowcount > 0:
                                    deleted_count += 1
                            
                            current_conn.commit()
                            
                            # 统计恢复的数据量
                            current_cursor.execute("SELECT COUNT(*) FROM ItemTable")
                            total_count = current_cursor.fetchone()[0]
                            
                            current_conn.close()
                            
                            restored_items.append("数据库（含对话索引）")
                            self.logger.info(f"✅ 已完整恢复数据库（共 {total_count} 项，已删除 {deleted_count} 项机器码和临时数据）")
                        
                        except Exception as e:
                            self.logger.warning(f"恢复数据库失败: {e}")
                            import traceback
                            self.logger.debug(traceback.format_exc())
                else:
                    self.logger.warning("⚠️ 备份中未找到数据库文件")
                
                # 恢复globalStorage下的其他数据（排除数据库文件和认证目录）
                global_storage_dst = os.path.join(self.user_data_path, "globalStorage")
                os.makedirs(global_storage_dst, exist_ok=True)
                
                for item in os.listdir(global_storage_src):
                    item_src = os.path.join(global_storage_src, item)
                    
                    # 跳过数据库文件（已经处理过了）
                    if item.startswith("state.vscdb"):
                        continue
                    
                    # 🔥 跳过机器码文件（避免恢复trial限制标记）
                    if item == "storage.json":
                        self.logger.info(f"跳过机器码文件: {item}")
                        continue
                    
                    if os.path.isdir(item_src):
                        # 跳过认证相关的目录
                        if exclude_auth and 'auth' in item.lower():
                            self.logger.info(f"跳过认证相关目录: {item}")
                            continue
                        try:
                            item_dst = os.path.join(global_storage_dst, item)
                            if os.path.exists(item_dst):
                                shutil.rmtree(item_dst)
                            self._safe_copytree(item_src, item_dst)
                        except Exception as e:
                            self.logger.warning(f"恢复globalStorage子目录 {item} 失败: {e}")
            
            message = f"✅ 备份恢复成功: {backup_name}\n恢复内容: {', '.join(restored_items)}"
            self.logger.info(message)
            return True, message
            
        except Exception as e:
            error_msg = f"恢复备份失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def list_backups(self) -> List[Dict]:
        """
        列出所有备份
        
        Returns:
            List[Dict]: 备份列表
        """
        backups = []
        try:
            if not os.path.exists(self.backup_root):
                return backups
            
            for item in os.listdir(self.backup_root):
                backup_path = os.path.join(self.backup_root, item)
                if os.path.isdir(backup_path):
                    metadata_file = os.path.join(backup_path, "metadata.json")
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, 'r', encoding='utf-8') as f:
                                metadata = json.load(f)
                            backups.append(metadata)
                        except:
                            # 如果元数据文件损坏，使用基本信息
                            stat = os.stat(backup_path)
                            backups.append({
                                "backup_name": item,
                                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                                "items": ["未知"],
                                "version": "unknown"
                            })
            
            # 按创建时间排序
            backups.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
        except Exception as e:
            self.logger.error(f"列出备份失败: {str(e)}")
        
        return backups
    
    def delete_backup(self, backup_name: str) -> Tuple[bool, str]:
        """
        删除备份
        
        Args:
            backup_name: 备份名称
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            backup_dir = os.path.join(self.backup_root, backup_name)
            
            if not os.path.exists(backup_dir):
                return False, f"备份 {backup_name} 不存在"
            
            shutil.rmtree(backup_dir)
            
            message = f"✅ 备份已删除: {backup_name}"
            self.logger.info(message)
            return True, message
            
        except Exception as e:
            error_msg = f"删除备份失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def _backup_database_safe_data(self, backup_dir: str):
        """
        备份数据库中的非敏感数据
        
        Args:
            backup_dir: 备份目录
        """
        try:
            db_path = os.path.join(self.user_data_path, "globalStorage", "state.vscdb")
            if not os.path.exists(db_path):
                return
            
            backup_db_path = os.path.join(backup_dir, "safe_data.json")
            safe_data = {}
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 只备份基本的用户偏好设置
            safe_keys = [
                "workbench.colorTheme",          # 主题
                "editor.fontSize",               # 字体大小
                "editor.fontFamily",             # 字体
                "window.zoomLevel",              # 缩放级别
                "editor.tabSize",                # 制表符大小
                "editor.insertSpaces",           # 插入空格
                "files.autoSave",                # 自动保存
                "editor.wordWrap",               # 自动换行
            ]
            
            for key in safe_keys:
                cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
                result = cursor.fetchone()
                if result:
                    safe_data[key] = result[0]
            
            conn.close()
            
            if safe_data:
                with open(backup_db_path, 'w', encoding='utf-8') as f:
                    json.dump(safe_data, f, indent=2, ensure_ascii=False)
                
                self.logger.info("✅ 已备份数据库安全配置")
            
        except Exception as e:
            self.logger.warning(f"备份数据库安全数据失败: {str(e)}")
    
    def _restore_database_safe_data(self, backup_dir: str):
        """
        恢复数据库中的非敏感数据
        
        Args:
            backup_dir: 备份目录
        """
        try:
            backup_db_path = os.path.join(backup_dir, "safe_data.json")
            if not os.path.exists(backup_db_path):
                return
            
            with open(backup_db_path, 'r', encoding='utf-8') as f:
                safe_data = json.load(f)
            
            db_path = os.path.join(self.user_data_path, "globalStorage", "state.vscdb")
            if not os.path.exists(db_path):
                return
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            for key, value in safe_data.items():
                cursor.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
            
            conn.commit()
            conn.close()
            
            self.logger.info("✅ 已恢复数据库安全配置")
            
        except Exception as e:
            self.logger.warning(f"恢复数据库安全数据失败: {str(e)}")
    
    def get_backup_size(self, backup_name: str) -> str:
        """
        获取备份大小
        
        Args:
            backup_name: 备份名称
            
        Returns:
            str: 备份大小（格式化字符串）
        """
        try:
            backup_dir = os.path.join(self.backup_root, backup_name)
            if not os.path.exists(backup_dir):
                return "0 B"
            
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(backup_dir):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(filepath)
            
            # 格式化大小
            for unit in ['B', 'KB', 'MB', 'GB']:
                if total_size < 1024.0:
                    return f"{total_size:.1f} {unit}"
                total_size /= 1024.0
            return f"{total_size:.1f} TB"
            
        except Exception as e:
            self.logger.error(f"获取备份大小失败: {str(e)}")
            return "未知"
    
    def _safe_copytree(self, src: str, dst: str):
        """
        安全的目录复制，跳过有问题的文件
        
        Args:
            src: 源目录
            dst: 目标目录
        """
        os.makedirs(dst, exist_ok=True)
        
        skipped_count = 0
        copied_count = 0
        
        for root, dirs, files in os.walk(src):
            # 计算相对路径
            rel_path = os.path.relpath(root, src)
            dst_root = os.path.join(dst, rel_path) if rel_path != '.' else dst
            
            # 创建目录
            if not os.path.exists(dst_root):
                try:
                    os.makedirs(dst_root, exist_ok=True)
                except Exception as e:
                    self.logger.warning(f"无法创建目录 {dst_root}: {e}")
                    continue
            
            # 复制文件
            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dst_root, file)
                
                try:
                    # 验证源文件是否真实存在
                    if not os.path.exists(src_file):
                        self.logger.debug(f"跳过不存在的文件: {src_file}")
                        skipped_count += 1
                        continue
                    
                    # 检查路径长度（Windows限制）
                    if len(dst_file) > 260:
                        self.logger.warning(f"跳过路径过长的文件 (长度: {len(dst_file)}): {os.path.basename(src_file)}")
                        skipped_count += 1
                        continue
                    
                    # 检查文件是否可读
                    if not os.access(src_file, os.R_OK):
                        self.logger.warning(f"跳过无读取权限的文件: {src_file}")
                        skipped_count += 1
                        continue
                    
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1
                    
                except FileNotFoundError:
                    self.logger.debug(f"跳过文件（不存在）: {src_file}")
                    skipped_count += 1
                except PermissionError:
                    self.logger.warning(f"跳过文件（权限不足）: {src_file}")
                    skipped_count += 1
                except OSError as e:
                    if e.winerror == 3:  # Windows ERROR_PATH_NOT_FOUND
                        self.logger.debug(f"跳过文件（路径不存在）: {os.path.basename(src_file)}")
                    else:
                        self.logger.warning(f"跳过文件（OS错误）: {os.path.basename(src_file)} - {e}")
                    skipped_count += 1
                except Exception as e:
                    self.logger.warning(f"无法复制文件 {os.path.basename(src_file)}: {e}")
                    skipped_count += 1
                    
        if skipped_count > 0:
            self.logger.info(f"目录复制完成: 成功 {copied_count} 个，跳过 {skipped_count} 个")
        else:
            self.logger.debug(f"目录复制完成: 成功 {copied_count} 个")
