#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cursor补丁模块 - 修改Cursor获取机器ID的方法
通过补丁优化，适配XC-Cursor架构
"""

import logging
import os
import platform
import re
import shutil
import tempfile
import json
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

class CursorPatcher:
    """Cursor补丁类，用于修改Cursor获取机器ID的方法"""

    def __init__(self, config=None):
        """
        初始化Cursor补丁器
        
        Args:
            config: 配置对象，如果为None则使用默认路径
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.system = platform.system()

        # 获取Cursor安装路径
        self.cursor_path = self._get_cursor_installation_path()
        self.pkg_path = None
        self.main_path = None
        # workbench相关逻辑已删除
        
        if self.cursor_path:
            self._initialize_paths()

    def _get_cursor_installation_path(self) -> Optional[str]:
        """获取Cursor安装路径"""
        try:
            # 优先使用配置文件中的路径
            if self.config:
                configured_path = self.config.get_cursor_install_path()
                if configured_path and os.path.exists(configured_path):
                    # 如果配置的是exe文件路径，返回其目录
                    if configured_path.lower().endswith('.exe'):
                        cursor_dir = os.path.dirname(configured_path)
                        self.logger.info(f"使用配置的Cursor安装路径: {cursor_dir}")
                        return cursor_dir
                    # 如果配置的是目录路径，直接返回
                    elif os.path.isdir(configured_path):
                        self.logger.info(f"使用配置的Cursor安装路径: {configured_path}")
                        return configured_path
            
            # 如果没有配置或配置的路径不存在，使用默认检测
            if self.system == "Windows":
                # Windows常见安装路径
                possible_paths = [
                    os.path.expanduser("~/AppData/Local/Programs/cursor"),
                    "C:/Program Files/cursor",
                    "C:/Program Files (x86)/cursor",
                ]
            elif self.system == "Darwin":  # macOS
                possible_paths = [
                    "/Applications/Cursor.app",
                ]
            else:  # Linux
                possible_paths = [
                    "/usr/local/bin/cursor",
                    "/opt/cursor",
                    os.path.expanduser("~/.local/share/cursor"),
                ]

            for path in possible_paths:
                if os.path.exists(path):
                    self.logger.info(f"找到Cursor安装路径: {path}")
                    return path

            self.logger.warning("未找到Cursor安装路径")
            return None
            
        except Exception as e:
            self.logger.error(f"获取Cursor安装路径失败: {str(e)}")
            return None

    def _initialize_paths(self):
        """初始化关键文件路径"""
        try:
            if self.system == "Windows":
                # Windows路径
                resources_path = os.path.join(self.cursor_path, "resources")
                app_path = os.path.join(resources_path, "app")
                
                self.pkg_path = os.path.join(app_path, "package.json")
                
                # 使用新版本Cursor的main.js路径
                self.main_path = os.path.join(app_path, "out", "main.js")
                
                # workbench路径已删除
                        
            elif self.system == "Darwin":  # macOS
                contents_path = os.path.join(self.cursor_path, "Contents")
                resources_path = os.path.join(contents_path, "Resources", "app")
                
                self.pkg_path = os.path.join(resources_path, "package.json")
                
                # 使用新版本Cursor的main.js路径
                self.main_path = os.path.join(resources_path, "out", "main.js")
                    
                # workbench路径已删除
                
            self.logger.info(f"主文件路径: {self.main_path}")
            # workbench路径日志已删除
            
        except Exception as e:
            self.logger.error(f"初始化路径失败: {str(e)}")

    def get_cursor_version(self) -> Optional[str]:
        """获取Cursor版本号"""
        try:
            if not self.pkg_path or not os.path.exists(self.pkg_path):
                return None
                
            with open(self.pkg_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
                version = package_data.get('version', '')
                self.logger.info(f"检测到Cursor版本: {version}")
                return version
                
        except Exception as e:
            self.logger.error(f"获取版本信息失败: {str(e)}")
            return None

    def check_system_requirements(self) -> Tuple[bool, str]:
        """检查系统要求"""
        try:
            if not self.cursor_path:
                return False, "未找到Cursor安装目录"
                
            if not self.main_path or not os.path.exists(self.main_path):
                return False, f"未找到系统数据，请检查是否设置Cusor安装位置"
                
            return True, "系统要求检查通过"
            
        except Exception as e:
            return False, f"系统要求检查失败: {str(e)}"

    def _check_file_already_patched(self, file_path: str) -> bool:
        """检查文件是否已经被补丁过"""
        try:
            if not os.path.exists(file_path):
                return False
                
            with open(file_path, 'r', encoding='utf-8') as f:
                first_line = f.read(100)
                return first_line.startswith('/*XC-Cursor-Patched*/')
                
        except Exception as e:
            self.logger.error(f"检查补丁状态失败: {str(e)}")
            return False

    def patch_main_js(self) -> Tuple[bool, str]:
        """修改main.js文件，绕过机器码检查"""
        try:
            if not self.main_path or not os.path.exists(self.main_path):
                return False, "main.js文件不存在"
                
            if self._check_file_already_patched(self.main_path):
                self.logger.info("main.js已经被补丁过，跳过修改")
                return True, "main.js已经被补丁过"

            # 尝试备份原文件（非关键操作）
            backup_path = self.main_path + ".backup"
            try:
                if not os.path.exists(backup_path):  # 如果备份不存在才创建
                    shutil.copy2(self.main_path, backup_path)
                    self.logger.info(f"已备份main.js到: {backup_path}")
                else:
                    self.logger.info(f"备份文件已存在，跳过备份: {backup_path}")
            except PermissionError as pe:
                self.logger.warning(f"⚠️ 备份失败（权限不足），继续补丁: {str(pe)}")
            except Exception as backup_err:
                self.logger.warning(f"⚠️ 备份失败，继续补丁: {str(backup_err)}")

            # 读取原文件内容
            with open(self.main_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 应用补丁：修改机器码获取函数
            patterns = {
                # 匹配 getMachineId 函数并简化返回逻辑
                r'async getMachineId\(\)\{[^}]*return[^}]*\?\?([^}]+)\}': 
                    r'async getMachineId(){return \1}',
                    
                # 匹配 getMacMachineId 函数并简化返回逻辑  
                r'async getMacMachineId\(\)\{[^}]*return[^}]*\?\?([^}]+)\}': 
                    r'async getMacMachineId(){return \1}',
                    
                # 通用机器码检查绕过
                r'machineId\s*:\s*[^,]+,': 
                    r'machineId:"bypassed-by-xc-cursor",',
            }

            changes_made = 0
            original_content = content

            for pattern, replacement in patterns.items():
                new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
                if new_content != content:
                    content = new_content
                    changes_made += 1
                    self.logger.info(f"应用补丁规则: {pattern[:50]}...")

            if changes_made == 0:
                self.logger.warning("未找到需要修改的机器码检查代码")
                return True, "main.js无需修改"

            # 添加补丁标记并写入文件
            content = "/*XC-Cursor-Patched*/\n" + content
            
            with open(self.main_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self.logger.info(f"main.js补丁成功，应用了{changes_made}个修改")
            return True, f"main.js补丁成功，应用了{changes_made}个修改"

        except PermissionError as pe:
            error_msg = f"main.js补丁失败（权限不足）: {str(pe)}"
            self.logger.warning(error_msg)
            # 权限错误不应该阻止切换流程
            return True, f"⚠️ 补丁跳过（权限不足）"
        except Exception as e:
            error_msg = f"main.js补丁失败: {str(e)}"
            self.logger.error(error_msg)
            # 补丁失败不是致命的，返回成功但带警告
            return True, f"⚠️ 补丁跳过（{str(e)}）"

    def patch_workbench_js(self) -> Tuple[bool, str]:
        """
        🔥 重要修复：完全跳过workbench文件处理
        经过测试，不需要处理workbench文件即可正常工作
        """
        self.logger.info("🚫 跳过workbench文件处理")
        return True, "跳过workbench文件处理"
    
    # workbench相关逻辑已完全删除

    def apply_all_patches(self, progress_callback=None) -> Tuple[bool, str]:
        """
        🔥 简化：应用补丁 - 由于workbench已跳过，等同于patch_main_js
        
        保持方法存在以兼容旧代码调用，但简化实现
        """
        try:
            if progress_callback:
                progress_callback("检查系统要求...")
                
            # 检查系统要求
            check_ok, check_msg = self.check_system_requirements()
            if not check_ok:
                return False, check_msg

            if progress_callback:
                progress_callback("正在应用补丁...")
                
            # 🔥 简化：直接调用main.js补丁，因为workbench已跳过
            success, message = self.patch_main_js()
            
            if progress_callback:
                progress_callback("补丁应用完成")

            if success:
                self.logger.info("✅ 补丁应用成功")
                return True, f"✅ 补丁应用成功: {message}"
            else:
                self.logger.error("❌ 补丁应用失败")  
                return False, f"❌ 补丁应用失败: {message}"

        except Exception as e:
            error_msg = f"应用补丁时发生错误: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def restore_backups(self) -> Tuple[bool, str]:
        """恢复备份文件"""
        try:
            restored_files = []
            
            # 恢复main.js
            main_backup = self.main_path + ".backup"
            if os.path.exists(main_backup):
                shutil.copy2(main_backup, self.main_path)
                restored_files.append("main.js")
                
            # workbench恢复逻辑已删除
            
            if restored_files:
                message = f"已恢复备份: {', '.join(restored_files)}"
                self.logger.info(message)
                return True, message
            else:
                return True, "没有找到备份文件"
                
        except Exception as e:
            error_msg = f"恢复备份失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def get_patch_info(self) -> Dict[str, Any]:
        """获取补丁信息"""
        info = {
            "cursor_path": self.cursor_path,
            "cursor_version": self.get_cursor_version(),
            "main_patched": self._check_file_already_patched(self.main_path) if self.main_path else False,
            # workbench补丁状态检查已删除
            "system": self.system,
        }
        
        return info
