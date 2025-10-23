#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置管理模块
"""

import json
import os
import sys
import logging
import shutil
import threading
from typing import List, Dict, Optional


class Config:
    """配置管理类"""
    
    def __init__(self):
        """初始化配置管理器"""
        self.logger = logging.getLogger(__name__)
        
        # 配置目录使用用户主目录
        self.config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor')
        
        self.config_file = os.path.join(self.config_dir, 'config.json')
        self.accounts_file = os.path.join(self.config_dir, 'accounts.json')
        self.accounts_backup_file = os.path.join(self.config_dir, 'accounts.backup.json')
        self.remarks_file = os.path.join(self.config_dir, 'account_remarks.json')
        
        # 文件锁，防止并发写入冲突
        self._file_lock = threading.Lock()
        
        # 确保配置目录存在
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        
        # 默认配置
        self.default_config = {
            "app": {
                "version": "1.0.0",
                "theme": "dark",
                "auto_save": True
            },
            "cursor": {
                "data_dir": self._get_cursor_data_dir(),
                "db_path": self._get_cursor_db_path()
            },
            "network": {
                "use_proxy": True,  # 默认启用代理（跟随系统环境）
                "proxy_comment": "启用时使用系统代理设置，禁用时强制直连"
            }
        }
        
        # 加载配置
        self.config_data = self._load_config()
        
    def _get_cursor_data_dir(self) -> str:
        """获取Cursor数据目录"""
        if os.name == 'nt':  # Windows
            return os.path.join(os.getenv("APPDATA", ""), "Cursor")
        elif sys.platform == 'darwin':  # macOS
            return os.path.expanduser("~/Library/Application Support/Cursor")
        else:  # Linux
            return os.path.expanduser("~/.config/Cursor")
    
    def _get_cursor_db_path(self) -> str:
        """获取Cursor数据库路径"""
        data_dir = self._get_cursor_data_dir()
        return os.path.join(data_dir, "User", "globalStorage", "state.vscdb")
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    return self._merge_config(self.default_config, config)
            else:
                self._save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            self.logger.error(f"加载配置失败: {str(e)}")
            return self.default_config.copy()
    
    def _merge_config(self, default: dict, user: dict) -> dict:
        """合并配置"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result
    
    def _save_config(self, config_data: dict = None):
        """保存配置文件"""
        try:
            data = config_data or self.config_data
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存配置失败: {str(e)}")
    
    def get(self, section: str, key: str, default=None):
        """获取配置值"""
        try:
            return self.config_data.get(section, {}).get(key, default)
        except Exception:
            return default
    
    def set(self, section: str, key: str, value):
        """设置配置值"""
        try:
            if section not in self.config_data:
                self.config_data[section] = {}
            self.config_data[section][key] = value
            self._save_config()
        except Exception as e:
            self.logger.error(f"设置配置失败: {str(e)}")
    
    def load_accounts(self) -> List[Dict]:
        """加载账号列表 - 增强容错，失败时尝试从备份恢复"""
        # 尝试加载主文件
        try:
            if os.path.exists(self.accounts_file):
                with open(self.accounts_file, 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
                    # 成功加载后，创建备份
                    if accounts:  # 只备份非空数据
                        try:
                            with self._file_lock:
                                shutil.copy2(self.accounts_file, self.accounts_backup_file)
                        except:
                            pass  # 备份失败不影响主流程
                    return accounts
            return []
        except Exception as e:
            self.logger.error(f"加载账号列表失败: {str(e)}")
            
            # 尝试从备份恢复
            if os.path.exists(self.accounts_backup_file):
                try:
                    self.logger.warning("尝试从备份文件恢复账号数据...")
                    with open(self.accounts_backup_file, 'r', encoding='utf-8') as f:
                        accounts = json.load(f)
                        if accounts:
                            # 恢复主文件
                            with self._file_lock:
                                shutil.copy2(self.accounts_backup_file, self.accounts_file)
                            self.logger.info(f"✅ 成功从备份恢复 {len(accounts)} 个账号")
                            return accounts
                except Exception as backup_error:
                    self.logger.error(f"从备份恢复也失败: {str(backup_error)}")
            
            # 如果备份也失败，抛出异常而不是返回空列表
            raise RuntimeError(f"加载账号列表失败，且无法从备份恢复: {str(e)}")
    
    def save_accounts(self, accounts: List[Dict], allow_empty: bool = False) -> bool:
        """保存账号列表 - 原子性保存，避免数据损坏
        
        Args:
            accounts: 账号列表
            allow_empty: 是否允许保存空列表（手动删除等场景设为True）
            
        Returns:
            bool: 是否保存成功
        """
        # 🔥 安全检查：如果要保存的数据为空，且当前有数据，则拒绝保存（除非明确允许）
        if not accounts and not allow_empty:
            try:
                current_accounts = []
                if os.path.exists(self.accounts_file):
                    with open(self.accounts_file, 'r', encoding='utf-8') as f:
                        current_accounts = json.load(f)
                
                if current_accounts:
                    self.logger.error(f"🚨 拒绝保存空列表！当前有 {len(current_accounts)} 个账号，不允许覆盖为空")
                    return False
            except:
                pass  # 如果检查失败，继续执行（允许保存空列表以初始化）
        
        try:
            with self._file_lock:
                # 先写入临时文件
                temp_file = self.accounts_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(accounts, f, indent=4, ensure_ascii=False)
                    # 🔥 强制刷新文件缓冲到磁盘
                    f.flush()
                    os.fsync(f.fileno())
                
                # 验证临时文件可以正确加载
                with open(temp_file, 'r', encoding='utf-8') as f:
                    json.load(f)
                
                # 备份旧文件
                if os.path.exists(self.accounts_file):
                    shutil.copy2(self.accounts_file, self.accounts_backup_file)
                
                # 原子性替换
                if os.name == 'nt':  # Windows
                    # Windows下需要先删除目标文件
                    if os.path.exists(self.accounts_file):
                        os.remove(self.accounts_file)
                    shutil.move(temp_file, self.accounts_file)
                else:  # Unix-like系统支持原子性重命名
                    os.replace(temp_file, self.accounts_file)
                
                self.logger.debug(f"✅ 成功保存 {len(accounts)} 个账号")
                return True
                    
        except Exception as e:
            self.logger.error(f"保存账号列表失败: {str(e)}")
            # 清理临时文件
            temp_file = self.accounts_file + '.tmp'
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            return False
    
    def get_accounts(self) -> List[Dict]:
        """获取账号列表（别名方法，兼容其他模块）"""
        return self.load_accounts()
    
    def set_accounts(self, accounts: List[Dict], allow_empty: bool = False):
        """设置账号列表（别名方法，兼容其他模块）"""
        self.save_accounts(accounts, allow_empty=allow_empty)
    
    def add_account(self, account: Dict) -> bool:
        """添加账号"""
        try:
            accounts = self.load_accounts()
            
            # 🔥 核心修复：确保refresh_token正确性（按照cursor-ideal逻辑）
            access_token = account.get('access_token', '')
            refresh_token = account.get('refresh_token', '')
            
            # 如果refresh_token为空或空字符串，使用access_token（符合cursor-ideal逻辑）
            if not refresh_token or refresh_token.strip() == '':
                if access_token and access_token.strip():
                    account['refresh_token'] = access_token
                    self.logger.info(f"修复账号 {account.get('email', '')} 的refresh_token（设置为access_token）")
                else:
                    self.logger.warning(f"账号 {account.get('email', '')} 的access_token也为空")
            
            # 确保账号有创建时间，但优先保留导入的时间
            if 'created_at' not in account or not account['created_at']:
                # 检查是否有register_time，优先使用它
                if 'register_time' in account and account['register_time']:
                    register_time = account['register_time']
                    # 转换为界面显示格式
                    if len(register_time) > 16:  # YYYY-MM-DD HH:MM:SS 格式
                        account['created_at'] = register_time[:16]  # 截取为 YYYY-MM-DD HH:MM
                    else:
                        account['created_at'] = register_time
                else:
                    # 如果都没有，才使用当前时间
                    from datetime import datetime
                    account['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            
            # 检查是否已存在相同邮箱的账号
            for i, acc in enumerate(accounts):
                if acc.get('email') == account.get('email'):
                    # 智能时间处理：导入时优先使用导入的时间，更新时保留原时间
                    if account.get('email_source') == 'json_import':
                        # 导入操作：使用导入文件中的时间，不保留原有时间
                        pass  # 使用account中已设置的created_at
                    else:
                        # 其他操作：保留原有的创建时间
                        if 'created_at' in acc and acc['created_at']:
                            account['created_at'] = acc['created_at']
                    accounts[i] = account  # 更新现有账号
                    save_success = self.save_accounts(accounts)
                    if save_success:
                        self.logger.info(f"✅ 账号已更新: {account.get('email', '')}")
                    else:
                        self.logger.error(f"❌ 账号更新保存失败: {account.get('email', '')}")
                    return save_success
            
            # 添加新账号
            accounts.append(account)
            save_success = self.save_accounts(accounts)
            if save_success:
                self.logger.info(f"✅ 新账号已添加: {account.get('email', '')} (总计: {len(accounts)})")
            else:
                self.logger.error(f"❌ 新账号保存失败: {account.get('email', '')}")
            return save_success
            
        except Exception as e:
            self.logger.error(f"添加账号失败: {str(e)}")
            import traceback
            self.logger.debug(f"详细堆栈:\n{traceback.format_exc()}")
            return False
    
    def update_account(self, account: Dict) -> bool:
        """更新账号信息（根据邮箱匹配）"""
        try:
            accounts = self.load_accounts()
            # 先尝试用user_id匹配，如果没有则用email匹配
            user_id = account.get('user_id', '')
            email = account.get('email', '')
            
            updated = False
            for i, acc in enumerate(accounts):
                # 优先用user_id匹配（更可靠）
                if user_id and acc.get('user_id') == user_id:
                    accounts[i] = account
                    updated = True
                    self.logger.info(f"通过user_id更新账号: {email}")
                    break
                # 否则用email匹配
                elif acc.get('email') == email:
                    accounts[i] = account
                    updated = True
                    self.logger.info(f"通过email更新账号: {email}")
                    break
            
            if updated:
                self.save_accounts(accounts)
                return True
            else:
                self.logger.warning(f"未找到要更新的账号: {email}")
                return False
                
        except Exception as e:
            self.logger.error(f"更新账号失败: {str(e)}")
            return False
    
    def remove_account(self, email: str) -> bool:
        """删除账号"""
        try:
            accounts = self.load_accounts()
            accounts = [acc for acc in accounts if acc.get('email') != email]
            # 手动删除操作，允许保存空列表
            self.save_accounts(accounts, allow_empty=True)
            return True
        except Exception as e:
            self.logger.error(f"删除账号失败: {str(e)}")
            return False
    
    def get_account(self, email: str) -> Optional[Dict]:
        """获取指定邮箱的账号信息"""
        accounts = self.load_accounts()
        for account in accounts:
            if account.get('email') == email:
                return account
        return None
    
    def load_remarks(self) -> Dict[str, str]:
        """加载账号备注信息"""
        try:
            if os.path.exists(self.remarks_file):
                with open(self.remarks_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"加载备注信息失败: {str(e)}")
            return {}
    
    def save_remarks(self, remarks: Dict[str, str]):
        """保存账号备注信息"""
        try:
            with open(self.remarks_file, 'w', encoding='utf-8') as f:
                json.dump(remarks, f, indent=4, ensure_ascii=False)
            self.logger.debug("账号备注信息保存成功")
        except Exception as e:
            self.logger.error(f"保存备注信息失败: {str(e)}")
    
    def get_remarks(self) -> Dict[str, str]:
        """获取备注信息（别名方法，兼容其他模块）"""
        return self.load_remarks()
    
    def set_remarks(self, remarks: Dict[str, str]):
        """设置备注信息（别名方法，兼容其他模块）"""
        self.save_remarks(remarks)
    
    def set_cursor_install_path(self, install_path: str):
        """
        设置Cursor安装路径
        支持两种输入方案：
        1. 目录路径（如 D:/cursor）- 自动查找Cursor.exe并保存完整路径
        2. exe文件路径（如 D:/cursor/Cursor.exe）- 直接保存
        """
        try:
            if not install_path:
                self.logger.warning("安装路径为空")
                return False
            
            # 标准化路径
            install_path = os.path.normpath(install_path)
            
            # 方案1: 如果是exe文件路径，直接保存
            if install_path.lower().endswith('.exe') or (os.path.exists(install_path) and os.path.isfile(install_path)):
                if os.path.exists(install_path):
                    self.config_data['cursor']['install_path'] = install_path
                    self.logger.info(f"✅ Cursor exe路径已设置: {install_path}")
                else:
                    self.logger.warning(f"exe文件不存在: {install_path}")
                    return False
            
            # 方案2: 如果是目录路径，查找Cursor.exe
            elif os.path.isdir(install_path):
                cursor_exe = os.path.join(install_path, 'Cursor.exe' if os.name == 'nt' else 'Cursor')
                if os.path.exists(cursor_exe):
                    self.config_data['cursor']['install_path'] = cursor_exe
                    self.logger.info(f"✅ 从目录 {install_path} 找到并设置Cursor.exe: {cursor_exe}")
                else:
                    # 即使没找到exe，也保存目录路径（兼容旧版）
                    self.config_data['cursor']['install_path'] = install_path
                    self.logger.warning(f"⚠️ 目录 {install_path} 中未找到Cursor.exe，但已保存目录路径")
            else:
                self.logger.warning(f"路径不存在或无效: {install_path}")
                return False
            
            self._save_config()
            
            # 更新相关路径
            self.config_data['cursor']['data_dir'] = self._get_cursor_data_dir()
            self.config_data['cursor']['db_path'] = self._get_cursor_db_path()
            self._save_config()
            
            self.logger.info(f"✅ Cursor路径配置已更新并保存")
            return True
        except Exception as e:
            self.logger.error(f"设置Cursor安装路径失败: {str(e)}")
            return False
    
    def get_cursor_install_path(self) -> str:
        """
        获取Cursor安装路径
        支持两种方案：
        1. 目录路径（如 D:/cursor）- 自动查找目录下的Cursor.exe
        2. exe文件路径（如 D:/cursor/Cursor.exe）- 直接返回
        """
        try:
            # 方案1: 检查完整的可执行文件路径配置
            configured_path = self.config_data.get('cursor', {}).get('install_path', '')
            if configured_path and os.path.exists(configured_path):
                # 如果是exe文件，直接返回
                if configured_path.lower().endswith('.exe') or os.path.isfile(configured_path):
                    self.logger.debug(f"使用配置的exe路径: {configured_path}")
                    return configured_path
                # 如果是目录，在目录下查找Cursor.exe
                elif os.path.isdir(configured_path):
                    cursor_exe = os.path.join(configured_path, 'Cursor.exe' if os.name == 'nt' else 'Cursor')
                    if os.path.exists(cursor_exe):
                        self.logger.debug(f"从配置目录中找到exe: {cursor_exe}")
                        return cursor_exe
            
            # 方案2: 检查安装目录配置（向后兼容）
            install_dir = self.config_data.get('cursor', {}).get('install_directory', '')
            if install_dir and os.path.exists(install_dir):
                cursor_exe = os.path.join(install_dir, 'Cursor.exe' if os.name == 'nt' else 'Cursor')
                if os.path.exists(cursor_exe):
                    # 找到后更新到install_path（统一配置）
                    self.config_data['cursor']['install_path'] = cursor_exe
                    self._save_config()
                    self.logger.debug(f"从install_directory找到exe: {cursor_exe}")
                    return cursor_exe
            
            # 如果没有配置或配置的路径不存在，使用自动检测
            detected_path = self._detect_cursor_install_path()
            if detected_path:
                # 检测到路径后自动保存到配置
                self.config_data['cursor']['install_path'] = detected_path
                self._save_config()
                self.logger.info(f"自动检测到Cursor路径: {detected_path}")
            
            return detected_path
            
        except Exception as e:
            self.logger.error(f"获取Cursor安装路径失败: {str(e)}")
            return ""
    
    def _detect_cursor_install_path(self) -> str:
        """自动检测Cursor安装路径"""
        try:
            possible_paths = []
            
            if os.name == 'nt':  # Windows
                # 常见的Windows安装路径
                possible_paths = [
                    os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "cursor", "Cursor.exe"),
                    os.path.join(os.getenv("PROGRAMFILES", ""), "Cursor", "Cursor.exe"),
                    os.path.join(os.getenv("PROGRAMFILES(X86)", ""), "Cursor", "Cursor.exe"),
                    os.path.join(os.getenv("APPDATA", ""), "Local", "Programs", "cursor", "Cursor.exe"),
                ]
            elif sys.platform == 'darwin':  # macOS
                possible_paths = [
                    "/Applications/Cursor.app/Contents/MacOS/Cursor",
                    os.path.expanduser("~/Applications/Cursor.app/Contents/MacOS/Cursor"),
                ]
            else:  # Linux
                possible_paths = [
                    "/usr/bin/cursor",
                    "/usr/local/bin/cursor",
                    "/opt/cursor/cursor",
                    os.path.expanduser("~/cursor/cursor"),
                    os.path.expanduser("~/.local/bin/cursor"),
                ]
            
            # 检查每个可能的路径
            for path in possible_paths:
                if os.path.exists(path):
                    self.logger.info(f"检测到Cursor安装路径: {path}")
                    return path
            
            # 如果都没找到，返回空字符串
            self.logger.warning("未能自动检测到Cursor安装路径")
            return ""
            
        except Exception as e:
            self.logger.error(f"自动检测Cursor安装路径失败: {str(e)}")
            return ""
    
    def get_cursor_data_dir(self) -> str:
        """获取Cursor数据目录（公开接口）"""
        return self._get_cursor_data_dir()
    
    def get_cursor_db_path(self) -> str:
        """获取Cursor数据库路径（公开接口）"""
        return self._get_cursor_db_path()
    
    def get_use_proxy(self) -> bool:
        """获取是否使用代理设置"""
        if not isinstance(self.config_data, dict):
            self.logger.warning(f"config_data类型错误: {type(self.config_data)}, 返回默认值True")
            return True
        
        network_config = self.config_data.get("network", {})
        if not isinstance(network_config, dict):
            self.logger.warning(f"network配置类型错误: {type(network_config)}, 返回默认值True")
            return True
            
        use_proxy = network_config.get("use_proxy", True)
        return use_proxy
    
    def set_use_proxy(self, use_proxy: bool) -> None:
        """设置是否使用代理"""
        if "network" not in self.config_data:
            self.config_data["network"] = {}
        self.config_data["network"]["use_proxy"] = use_proxy
        self._save_config()
        self.logger.info(f"代理设置已更新: {'启用' if use_proxy else '禁用'}")
    
    def get_manual_verify_mode(self) -> bool:
        """获取是否使用手动验证码模式"""
        manual_verify = self.config_data.get("network", {}).get("manual_verify_mode", False)
        return manual_verify
    
    def set_manual_verify_mode(self, manual_verify: bool) -> None:
        """设置是否使用手动验证码模式"""
        if "network" not in self.config_data:
            self.config_data["network"] = {}
        self.config_data["network"]["manual_verify_mode"] = manual_verify
        self._save_config()
        self.logger.info(f"手动验证码模式已更新: {'启用' if manual_verify else '禁用'}")
    
    def backup_accounts(self) -> bool:
        """手动备份账号数据"""
        try:
            if os.path.exists(self.accounts_file):
                with self._file_lock:
                    # 读取当前账号数据验证其有效性
                    with open(self.accounts_file, 'r', encoding='utf-8') as f:
                        accounts = json.load(f)
                    
                    if accounts:  # 只备份有数据的文件
                        shutil.copy2(self.accounts_file, self.accounts_backup_file)
                        self.logger.info(f"✅ 已备份 {len(accounts)} 个账号到: {self.accounts_backup_file}")
                        return True
                    else:
                        self.logger.warning("⚠️ 当前账号列表为空，跳过备份")
                        return False
            else:
                self.logger.warning("⚠️ 账号文件不存在，无需备份")
                return False
        except Exception as e:
            self.logger.error(f"❌ 备份账号数据失败: {str(e)}")
            return False