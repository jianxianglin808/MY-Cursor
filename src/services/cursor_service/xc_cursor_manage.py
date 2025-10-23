#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MY Cursor管理模块 - 处理Cursor相关操作
"""

import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import datetime

import requests

from .cursor_patcher import CursorPatcher


class XCCursorManager:
    """MY Cursor管理类，用于处理Cursor相关操作"""

    def __init__(self, config):
        """
        初始化Cursor管理器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 根据配置确定Cursor数据路径
        cursor_data_dir = config.get_cursor_data_dir()
        cursor_install_path = config.get_cursor_install_path()
        
        self.user_data_path = os.path.join(cursor_data_dir, "User")
        self.storage_path = os.path.join(self.user_data_path, "globalStorage", "storage.json")
        self.machine_id_path = os.path.join(cursor_data_dir, "machineId")
        
        # 设置应用路径（安装路径）
        if cursor_install_path and os.path.exists(cursor_install_path):
            self.app_path = cursor_install_path
        else:
            # 使用默认路径
            if os.name == 'nt':  # Windows
                self.app_path = os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "cursor")
            elif sys.platform == 'darwin':  # macOS
                self.app_path = "/Applications/Cursor.app"
            else:  # Linux
                self.app_path = "/usr/local/bin/cursor"
        
        # 数据库和数据目录
        self.data_dir = self.user_data_path
        self.db_path = os.path.join(self.user_data_path, "globalStorage", "state.vscdb")

        # 获取系统信息
        self.platform = sys.platform

        # 设置系统特定的其他路径
        if self.platform == "win32":  # Windows
            self.updater_path = os.path.join(os.getenv("LOCALAPPDATA", ""), "cursor-updater")
            self.update_yml_path = os.path.join(self.app_path, "resources", "app-update.yml")
            self.product_json_path = os.path.join(self.app_path, "resources", "app", "product.json")
        elif self.platform == "darwin":  # macOS
            self.updater_path = os.path.expanduser("~/Library/Application Support/cursor-updater")
            self.update_yml_path = "/Applications/Cursor.app/Contents/Resources/app-update.yml"
            self.product_json_path = "/Applications/Cursor.app/Contents/Resources/app/product.json"

        # 初始化补丁器
        self.patcher = CursorPatcher(config)
        
        # 账号机器码配置目录
        self.account_machine_id_dir = os.path.join(config.config_dir, "account_machine_ids")

    def _decode_jwt_payload(self, token):
        """
        解码JWT token的payload部分
        
        Args:
            token: JWT token字符串
            
        Returns:
            dict: 解码后的payload，失败时返回None
        """
        try:
            # JWT token由三部分组成：header.payload.signature
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            # 获取payload部分（第二部分）
            payload = parts[1]
            
            # 添加padding如果需要
            padding = len(payload) % 4
            if padding:
                payload += '=' * (4 - padding)
            
            # Base64解码
            decoded_bytes = base64.urlsafe_b64decode(payload)
            
            # 转换为JSON
            payload_data = json.loads(decoded_bytes.decode('utf-8'))
            
            return payload_data
            
        except Exception as e:
            self.logger.warning(f"解码JWT token失败: {str(e)}")
            return None

    def _extract_user_id_from_token(self, token):
        """
        从access token中提取user_id
        
        Args:
            token: 访问令牌
            
        Returns:
            str: 用户ID，失败时返回None
        """
        try:
            payload = self._decode_jwt_payload(token)
            if not payload:
                return None
                
            # 获取sub字段
            sub = payload.get('sub')
            if not sub:
                return None
                
            # 从sub中提取user_id（格式：auth0|user_xxxxx）
            if '|' in sub:
                user_id = sub.split('|', 1)[1]  # 获取|后面的部分
                # 减少重复日志输出，只在第一次或用户ID变化时记录
                if not hasattr(self, '_last_extracted_user_id') or self._last_extracted_user_id != user_id:
                    self.logger.info(f"从token中提取到user_id: {user_id}")
                    self._last_extracted_user_id = user_id
                return user_id
            else:
                # 如果没有|分隔符，直接使用sub作为user_id
                return sub
                
        except Exception as e:
            self.logger.warning(f"从token提取user_id失败: {str(e)}")
            return None

    def reset_machine_ids(self, progress_callback=None, account_email=None, use_existing=False, force_new=False):
        """
        重置Cursor机器ID
        
        Args:
            progress_callback: 进度回调函数，用于显示进度
            account_email: 账号邮箱，如果提供则使用账号专属配置
            use_existing: 是否强制使用已有配置（对应"使用该账号已绑定的机器码"选项）
            force_new: 是否强制生成新配置（对应"随机新机器码"选项）
        
        Returns:
            tuple: (是否成功, 消息, 新ID信息)
        """
        try:
            self.logger.info("开始重置Cursor机器ID...")
            if progress_callback:
                progress_callback("开始重置Cursor机器ID...")

            # 调用统一的重置方法
            success, message, new_ids = self.reset_and_backup_machine_ids(account_email, use_existing, force_new)

            if success:
                # 重置成功后，自动应用补丁（非关键操作）
                self.logger.info("重置成功，开始应用机器ID补丁...")
                if progress_callback:
                    progress_callback("重置成功，开始应用机器ID补丁...")

                try:
                    patch_success, patch_message = self.patcher.apply_all_patches(progress_callback)
                    message += f"；{patch_message}"
                    if "跳过" in patch_message or "⚠️" in patch_message:
                        self.logger.warning(f"补丁应用: {patch_message}")
                    else:
                        self.logger.info(f"补丁应用成功: {patch_message}")
                    if progress_callback:
                        progress_callback(f"{patch_message}")
                except Exception as patch_err:
                    self.logger.warning(f"补丁应用异常（不影响切换）: {str(patch_err)}")
                    if progress_callback:
                        progress_callback(f"⚠️ 补丁跳过")
                # 补丁失败不影响整体重置结果

            return success, message, new_ids

        except Exception as e:
            error_msg = f"重置过程出错: {str(e)}"
            self.logger.error(error_msg)
            if progress_callback:
                progress_callback(error_msg)
            return False, error_msg, None

    def reset_and_backup_machine_ids(self, account_email=None, use_existing=False, force_new=False):
        """
        统一的重置机器ID方法，包含备份功能
        
        Args:
            account_email: 账号邮箱，如果提供则使用账号专属配置
            use_existing: 是否强制使用已有配置（对应"使用该账号已绑定的机器码"选项）
            force_new: 是否强制生成新配置（对应"随机新机器码"选项）
        
        Returns:
            tuple: (是否成功, 消息, 新ID信息)
        """
        try:
            self.logger.info("开始统一重置和备份机器ID...")
            success = True
            messages = []
            new_ids = {}
            critical_failure = False  # 追踪是否有关键失败

            # 1. 备份和重置storage.json（非关键操作）
            storage_success, storage_msg, storage_ids = self._reset_storage_json(account_email, use_existing, force_new)
            if storage_success:
                messages.append("storage.json重置成功")
                new_ids.update(storage_ids)
            else:
                # storage.json失败不是致命的，Cursor会自动创建
                self.logger.warning(f"storage.json重置失败（非致命）: {storage_msg}")
                messages.append(f"⚠️ storage.json跳过（权限问题）")
                success = False  # 标记为部分失败

            # 2. 备份和重置machineId文件（关键操作）
            machine_id_success, machine_id_msg, machine_id_value = self._reset_machine_id_file(account_email, use_existing, force_new)
            if machine_id_success:
                messages.append("machineId文件重置成功")
                new_ids["machineId_file"] = machine_id_value
            else:
                # machineId失败是致命的
                critical_failure = True
                success = False
                messages.append(f"❌ machineId文件重置失败: {machine_id_msg}")

            # 如果有关键失败，直接返回失败
            if critical_failure:
                result_message = "; ".join(messages)
                self.logger.error(f"机器ID重置失败（关键操作失败）: {result_message}")
                return False, f"机器ID重置失败: {result_message}", new_ids

            # 如果提供了账号邮箱且machineId成功，尝试保存账号专属配置
            if account_email and machine_id_success and not force_new:
                # 即使storage.json失败，也可以保存machineId配置
                storage_machine_ids = storage_ids if storage_success else {}
                machine_id_file_value = machine_id_value
                
                save_success = self._save_account_machine_ids(account_email, storage_machine_ids, machine_id_file_value)
                if save_success:
                    self.logger.info(f"已保存账号 {account_email} 的机器码配置")
                else:
                    self.logger.warning(f"保存账号 {account_email} 的机器码配置失败")

            # 返回结果
            result_message = "; ".join(messages)
            if success:
                # 完全成功
                self.logger.info(f"机器ID重置和备份成功: {result_message}")
                return True, "机器ID重置和备份成功", new_ids
            else:
                # 部分成功（storage.json失败但machineId成功）
                self.logger.warning(f"机器ID重置部分成功: {result_message}")
                return True, f"机器ID重置部分成功: {result_message}", new_ids

        except Exception as e:
            error_msg = f"统一重置过程出错: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg, None

    def _reset_storage_json(self, account_email=None, use_existing=False, force_new=False):
        """
        重置和备份storage.json文件
        
        Args:
            account_email: 账号邮箱，如果提供则使用账号专属配置
            use_existing: 是否强制使用已有配置
            force_new: 是否强制生成新配置（忽略已有配置）
        
        Returns:
            tuple: (是否成功, 消息, 新ID信息)
        """
        try:
            # 检查配置文件是否存在
            if not os.path.exists(self.storage_path):
                # 文件不存在，创建默认配置
                self.logger.warning(f"storage.json不存在，创建默认配置: {self.storage_path}")
                os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
                default_config = {}
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)

            # 尝试读取配置文件（带重试机制）
            max_retries = 3
            config = None
            last_error = None
            
            for retry in range(max_retries):
                try:
                    # 读取现有配置
                    self.logger.info(f"读取storage.json配置（尝试 {retry + 1}/{max_retries}）...")
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    break  # 读取成功，跳出重试循环
                    
                except PermissionError as pe:
                    last_error = f"文件权限错误: {str(pe)}"
                    self.logger.warning(f"{last_error}，尝试修改权限...")
                    
                    # 尝试修改文件权限（仅Windows）
                    if os.name == 'nt':
                        try:
                            import subprocess
                            subprocess.run(['icacls', self.storage_path, '/grant', 'Everyone:F'], 
                                         capture_output=True, check=False)
                            time.sleep(0.5)
                        except Exception as perm_error:
                            self.logger.debug(f"修改权限失败: {str(perm_error)}")
                    
                    if retry < max_retries - 1:
                        time.sleep(1)  # 等待后重试
                        
                except json.JSONDecodeError as je:
                    last_error = f"JSON格式错误: {str(je)}"
                    self.logger.warning(f"{last_error}，尝试创建新配置...")
                    config = {}  # 使用空配置
                    break
                    
                except Exception as e:
                    last_error = f"读取失败: {str(e)}"
                    self.logger.warning(f"{last_error}")
                    if retry < max_retries - 1:
                        time.sleep(1)
            
            # 如果所有重试都失败
            if config is None:
                error_msg = f"无法读取storage.json（已重试{max_retries}次）: {last_error}"
                self.logger.error(error_msg)
                return False, error_msg, None

            # 备份现有配置
            try:
                backup_path = f"{self.storage_path}.old"
                self.logger.info(f"备份storage.json到: {backup_path}")
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)
            except Exception as backup_error:
                self.logger.warning(f"备份失败（不影响重置）: {str(backup_error)}")

            # 生成新的ID或使用已有配置
            if use_existing and account_email:
                # 强制使用已有配置
                existing_config = self._load_account_machine_ids(account_email)
                if existing_config and existing_config.get("storage_machine_ids"):
                    self.logger.info(f"强制使用账号 {account_email} 的已有机器码配置")
                    new_ids = existing_config["storage_machine_ids"]
                else:
                    self.logger.warning(f"账号 {account_email} 没有已有配置，将生成新配置")
                    new_ids = self._generate_new_ids(account_email=None, force_new=True)
            else:
                self.logger.info("生成新的机器标识...")
                new_ids = self._generate_new_ids(account_email=account_email, force_new=force_new)

            # 更新配置
            config.update(new_ids)

            # 保存新配置（带重试机制）
            save_success = False
            last_save_error = None
            
            for retry in range(max_retries):
                try:
                    self.logger.info(f"保存storage.json配置（尝试 {retry + 1}/{max_retries}）...")
                    with open(self.storage_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=4)
                    save_success = True
                    break
                    
                except PermissionError as pe:
                    last_save_error = f"文件权限错误: {str(pe)}"
                    self.logger.warning(f"{last_save_error}")
                    
                    # 尝试修改文件权限（仅Windows）
                    if os.name == 'nt' and retry < max_retries - 1:
                        try:
                            import subprocess
                            subprocess.run(['icacls', self.storage_path, '/grant', 'Everyone:F'], 
                                         capture_output=True, check=False)
                            time.sleep(0.5)
                        except Exception as perm_error:
                            self.logger.debug(f"修改权限失败: {str(perm_error)}")
                    
                    if retry < max_retries - 1:
                        time.sleep(1)
                        
                except Exception as e:
                    last_save_error = f"保存失败: {str(e)}"
                    self.logger.warning(f"{last_save_error}")
                    if retry < max_retries - 1:
                        time.sleep(1)
            
            if not save_success:
                error_msg = f"无法保存storage.json（已重试{max_retries}次）: {last_save_error}"
                self.logger.error(error_msg)
                return False, error_msg, None

            self.logger.info("storage.json机器标识重置成功！")
            return True, "storage.json机器标识重置成功", new_ids

        except Exception as e:
            error_msg = f"storage.json重置过程出错: {str(e)}"
            self.logger.error(error_msg)
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
            return False, error_msg, None

    def _reset_machine_id_file(self, account_email=None, use_existing=False, force_new=False):
        """
        重置和备份machineId文件
        
        Args:
            account_email: 账号邮箱，如果提供则使用账号专属配置
            use_existing: 是否强制使用已有配置
            force_new: 是否强制生成新配置（忽略已有配置）
        
        Returns:
            tuple: (是否成功, 消息, 新机器ID)
        """
        try:
            # 检查machineId文件是否存在
            file_exists = os.path.exists(self.machine_id_path)

            # 如果文件存在，先备份
            if file_exists:
                self.logger.info(f"machineId文件存在: {self.machine_id_path}")

                # 读取现有machineId
                with open(self.machine_id_path, "r", encoding="utf-8") as f:
                    old_machine_id = f.read().strip()

                # 备份现有machineId
                backup_path = f"{self.machine_id_path}.old"
                self.logger.info(f"备份machineId到: {backup_path}")
                shutil.copy2(self.machine_id_path, backup_path)
            else:
                self.logger.info(f"machineId文件不存在，将创建新文件")
                # 确保目录存在
                os.makedirs(os.path.dirname(self.machine_id_path), exist_ok=True)

            # 获取或生成新的machineId (UUID格式)
            if use_existing and account_email:
                # 强制使用已有配置
                existing_config = self._load_account_machine_ids(account_email)
                if existing_config and existing_config.get("machine_id_file"):
                    new_machine_id = existing_config["machine_id_file"]
                    self.logger.info(f"强制使用账号 {account_email} 的已有machineId文件值")
                else:
                    new_machine_id = str(uuid.uuid4())
                    self.logger.warning(f"账号 {account_email} 没有已有machineId配置，生成新值")
            else:
                new_machine_id = self._get_account_machine_id_file_value(account_email, force_new=force_new)
            self.logger.info(f"使用machineId: {new_machine_id}")

            # 保存新的machineId
            with open(self.machine_id_path, "w", encoding="utf-8") as f:
                f.write(new_machine_id)

            self.logger.info("machineId文件重置成功！")
            return True, "machineId文件重置成功", new_machine_id

        except Exception as e:
            error_msg = f"machineId文件重置过程出错: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg, None

    def _get_account_machine_id_path(self, account_email):
        """
        获取账号专属机器码配置文件路径
        
        Args:
            account_email: 账号邮箱
            
        Returns:
            str: 配置文件路径
        """
        if not account_email:
            return None
            
        # 确保目录存在
        os.makedirs(self.account_machine_id_dir, exist_ok=True)
        
        # 使用邮箱作为文件名，将@替换为_避免特殊字符问题
        safe_email = account_email.replace('@', '_')
        config_filename = f"{safe_email}.json"
        
        return os.path.join(self.account_machine_id_dir, config_filename)
    
    def _load_account_machine_ids(self, account_email):
        """
        加载账号专属机器码配置
        
        Args:
            account_email: 账号邮箱
            
        Returns:
            dict: 机器码配置，如果不存在则返回None
        """
        try:
            config_path = self._get_account_machine_id_path(account_email)
            if not config_path or not os.path.exists(config_path):
                self.logger.info(f"账号 {account_email} 的机器码配置不存在")
                return None
                
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            self.logger.info(f"已加载账号 {account_email} 的机器码配置")
            return config
            
        except Exception as e:
            self.logger.error(f"加载账号机器码配置失败: {str(e)}")
            return None
    
    def _save_account_machine_ids(self, account_email, storage_machine_ids, machine_id_file_value):
        """
        保存账号专属机器码配置
        
        Args:
            account_email: 账号邮箱
            storage_machine_ids: storage.json中的机器码配置
            machine_id_file_value: machineId文件的值
            
        Returns:
            bool: 是否保存成功
        """
        try:
            config_path = self._get_account_machine_id_path(account_email)
            if not config_path:
                return False
                
            # 添加时间戳和邮箱信息
            config_data = {
                "account_email": account_email,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "storage_machine_ids": storage_machine_ids,
                "machine_id_file": machine_id_file_value
            }
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
                
            self.logger.info(f"已保存账号 {account_email} 的机器码配置")
            return True
            
        except Exception as e:
            self.logger.error(f"保存账号机器码配置失败: {str(e)}")
            return False

    def _generate_new_ids(self, account_email=None, force_new=False):
        """
        生成新的机器ID，支持账号专属配置
        
        Args:
            account_email: 账号邮箱，如果提供则优先使用已保存的配置
            force_new: 是否强制生成新配置（忽略已有配置，用于"随机新机器码"选项）
        
        Returns:
            dict: 新的ID信息
        """
        # 如果强制生成新配置，跳过加载已有配置
        if not force_new and account_email:
            existing_config = self._load_account_machine_ids(account_email)
            if existing_config and existing_config.get("storage_machine_ids"):
                self.logger.info(f"使用账号 {account_email} 的已有机器码配置")
                return existing_config["storage_machine_ids"]
        
        # 生成新的机器码
        if force_new:
            self.logger.info(f"强制生成全新的随机机器码（忽略已有配置）")
        else:
            self.logger.info(f"为账号 {account_email or '通用'} 生成新的机器码")
        
        # 生成新的UUID
        dev_device_id = str(uuid.uuid4())

        # 生成新的machineId (64个字符的十六进制)
        machine_id = hashlib.sha256(os.urandom(32)).hexdigest()

        # 生成新的macMachineId
        # 完全使用随机数生成，不包含任何系统信息
        # 固定格式：64个字符的十六进制字符串
        mac_machine_id = hashlib.sha256(os.urandom(64)).hexdigest()

        # 生成新的sqmId
        sqm_id = "{" + str(uuid.uuid4()).upper() + "}"

        new_ids = {
            "telemetry.devDeviceId": dev_device_id,
            "telemetry.macMachineId": mac_machine_id,
            "telemetry.machineId": machine_id,
            "telemetry.sqmId": sqm_id,
        }
        
        return new_ids

    def _get_account_machine_id_file_value(self, account_email, force_new=False):
        """
        获取账号专属的machineId文件值
        
        Args:
            account_email: 账号邮箱
            force_new: 是否强制生成新值（忽略已有配置）
            
        Returns:
            str: machineId文件值，如果不存在则生成新的
        """
        if not account_email or force_new:
            new_machine_id_file = str(uuid.uuid4())
            if force_new:
                self.logger.info(f"强制生成全新的随机machineId文件值")
            else:
                self.logger.info(f"生成新的machineId文件值")
            return new_machine_id_file
            
        existing_config = self._load_account_machine_ids(account_email)
        if existing_config and existing_config.get("machine_id_file"):
            self.logger.info(f"使用账号 {account_email} 的已有machineId文件值")
            return existing_config["machine_id_file"]
        
        # 生成新的machineId文件值
        new_machine_id_file = str(uuid.uuid4())
        self.logger.info(f"为账号 {account_email} 生成新的machineId文件值")
        return new_machine_id_file

    def generate_account_machine_ids(self, account_email, force_new=False):
        """
        为指定账号生成或获取机器码配置
        
        Args:
            account_email: 账号邮箱
            force_new: 是否强制生成新配置（忽略已有配置）
            
        Returns:
            tuple: (storage_machine_ids, machine_id_file_value)
        """
        if not account_email:
            storage_ids = self._generate_new_ids()
            machine_id_file = str(uuid.uuid4())
            return storage_ids, machine_id_file
            
        # 如果不强制生成新配置，尝试加载已有配置
        if not force_new:
            existing_config = self._load_account_machine_ids(account_email)
            if existing_config and existing_config.get("storage_machine_ids") and existing_config.get("machine_id_file"):
                self.logger.info(f"使用账号 {account_email} 的已有机器码配置")
                return existing_config["storage_machine_ids"], existing_config["machine_id_file"]
        
        # 生成新配置
        self.logger.info(f"为账号 {account_email} 生成新的机器码配置")
        storage_ids = self._generate_new_ids()  # 这里故意不传account_email，确保生成全新配置
        machine_id_file = str(uuid.uuid4())
        self._save_account_machine_ids(account_email, storage_ids, machine_id_file)
        
        return storage_ids, machine_id_file

    def update_auth(self, email=None, access_token=None, refresh_token=None, user_id=None, progress_callback=None, ensure_session_jwt=True):
        """
        更新Cursor的认证信息
        
        Args:
            email: 新的邮箱地址
            access_token: 新的访问令牌
            refresh_token: 新的刷新令牌
            user_id: 用户ID
            progress_callback: 进度回调函数
            
        Returns:
            tuple: (是否成功, 消息)
        """
        conn = None  # 初始化conn变量
        try:
            # 详细日志记录
            if progress_callback:
                progress_callback("🔄 开始更新认证信息...")
            
            self.logger.info(f"开始更新认证信息: email={email}, user_id={user_id}")
            self.logger.info(f"数据库路径: {self.db_path}")
            
            # 检查数据库文件是否存在
            if not os.path.exists(self.db_path):
                error_msg = f"Cursor数据库文件不存在: {self.db_path}"
                self.logger.error(error_msg)
                if progress_callback:
                    progress_callback(f"❌ {error_msg}")
                return False, error_msg
            
            # 验证必需参数
            if not all([email, access_token, user_id]):
                error_msg = f"认证信息不完整: email={bool(email)}, access_token={bool(access_token)}, user_id={bool(user_id)}"
                self.logger.error(error_msg)
                if progress_callback:
                    progress_callback(f"❌ {error_msg}")
                return False, error_msg
            
            # 🔥 修复：检查token类型，只接受session类型JWT
            if ensure_session_jwt and access_token:
                try:
                    # 🔥 修复：使用简单的JWT类型检查
                    payload = self._decode_jwt_payload(access_token)
                    if payload:
                        jwt_type = payload.get('type', 'unknown')
                        if jwt_type == 'web':
                            error_msg = f"⚠️ 检测到无效token，需要转换token"
                            self.logger.warning(error_msg)
                            if progress_callback:
                                progress_callback(error_msg)
                            return False, "请前往设置更新浏览器位置，并点击Token转换"
                        elif jwt_type == 'session':
                            self.logger.info(f"✅ 确认为session类型token，长度: {len(access_token)}")
                            if progress_callback:
                                progress_callback("✅ Token类型验证通过")
                        else:
                            self.logger.warning(f"⚠️ 未知token类型: {jwt_type}")
                    else:
                        self.logger.warning("⚠️ 无法解析JWT token类型")
                except Exception as e:
                    self.logger.warning(f"token类型检查失败: {str(e)}")
            

            # 直接进行数据库操作
            conn = sqlite3.connect(self.db_path)
            # 开始事务
            conn.execute("BEGIN TRANSACTION")
            cursor = conn.cursor()
            
            self.logger.info("已连接到数据库，开始更新认证信息...")

            # 检查ItemTable表是否存在
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ItemTable'")
                if not cursor.fetchone():
                    error_msg = "数据库表ItemTable不存在，请先运行一次Cursor以初始化数据库"
                    self.logger.error(error_msg)
                    if progress_callback:
                        progress_callback(f"❌ {error_msg}")
                    conn.close()
                    return False, error_msg
            except Exception as check_err:
                error_msg = f"检查数据库表失败: {str(check_err)}"
                self.logger.error(error_msg)
                if progress_callback:
                    progress_callback(f"❌ {error_msg}")
                conn.close()
                return False, error_msg

            # 🔥 修复：添加session类型token所需的特殊字段
            from datetime import datetime
            current_time = datetime.now().isoformat()
            
            updates = [
                ("cursorAuth/cachedSignUpType", "Auth_0"),  # 登录状态
                ("cursorAuth/cachedEmail", email),
                ("cursorAuth/accessToken", access_token),
                ("cursorAuth/refreshToken", refresh_token),
                ("cursorAuth/userId", user_id),
                # 🔥 新增：session类型token的必要字段
                ("cursorAuth/onboardingDate", current_time),  # 添加onboarding时间
                ("cursorAuth/stripeMembershipType", "pro")  # 默认会员类型，后续通过API更新
            ]
            # 要删除的key
            delete_keys = [
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
                "__$__targetStorageMarker"
            ]

            for key in delete_keys:
                try:
                    cursor.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
                except Exception as del_err:
                    self.logger.warning(f"删除键 {key} 失败: {str(del_err)}")

            for key, value in updates:
                try:
                    # 检查键是否存在
                    check_query = "SELECT COUNT(*) FROM ItemTable WHERE key = ?"
                    cursor.execute(check_query, (key,))
                    if cursor.fetchone()[0] == 0:
                        # 键不存在，插入新记录
                        insert_query = "INSERT INTO ItemTable (key, value) VALUES (?, ?)"
                        cursor.execute(insert_query, (key, value))
                    else:
                        # 键已存在，更新值
                        update_query = "UPDATE ItemTable SET value = ? WHERE key = ?"
                        cursor.execute(update_query, (value, key))
                except Exception as update_err:
                    self.logger.error(f"更新键 {key} 失败: {str(update_err)}")
                    raise  # 认证信息更新失败是致命的

            # 提交事务
            conn.commit()
            
            # 🔍 验证写入是否成功 - 立即读取验证
            cursor.execute("SELECT value FROM ItemTable WHERE key = ?", ("cursorAuth/cachedEmail",))
            written_email = cursor.fetchone()
            cursor.execute("SELECT value FROM ItemTable WHERE key = ?", ("cursorAuth/accessToken",))
            written_access_token = cursor.fetchone()
            cursor.execute("SELECT value FROM ItemTable WHERE key = ?", ("cursorAuth/refreshToken",))
            written_refresh_token = cursor.fetchone()
            cursor.execute("SELECT value FROM ItemTable WHERE key = ?", ("cursorAuth/userId",))
            written_user_id = cursor.fetchone()
            cursor.execute("SELECT value FROM ItemTable WHERE key = ?", ("cursorAuth/cachedSignUpType",))
            written_status = cursor.fetchone()
            
            conn.close()

            # 验证写入结果
            verification_passed = True
            if not written_email or written_email[0] != email:
                self.logger.error(f"邮箱写入验证失败: 期望={email}, 实际={written_email[0] if written_email else 'None'}")
                verification_passed = False
            if not written_access_token or written_access_token[0] != access_token:
                self.logger.error(f"access_token写入验证失败: 期望前20字符={access_token[:20]}, 实际前20字符={written_access_token[0][:20] if written_access_token else 'None'}")
                verification_passed = False
            if not written_refresh_token or written_refresh_token[0] != refresh_token:
                self.logger.error(f"refresh_token写入验证失败: 期望前20字符={refresh_token[:20]}, 实际前20字符={written_refresh_token[0][:20] if written_refresh_token else 'None'}")
                verification_passed = False
            if not written_user_id or written_user_id[0] != user_id:
                self.logger.error(f"user_id写入验证失败: 期望={user_id}, 实际={written_user_id[0] if written_user_id else 'None'}")
                verification_passed = False
            if not written_status or written_status[0] != "Auth_0":
                self.logger.error(f"登录状态写入验证失败: 期望=Auth_0, 实际={written_status[0] if written_status else 'None'}")
                verification_passed = False

            # 显示结果
            if verification_passed:
                message = f"认证信息更新并验证成功: {email}"
                self.logger.info(f"认证信息更新成功: email={email}, user_id={user_id}")
                self.logger.info(f"数据库验证通过: 所有认证字段写入正确")
            else:
                message = f"认证信息写入有异常: {email}"
                self.logger.warning(f"认证信息写入验证发现问题，但数据库操作已提交")
            
            if progress_callback:
                progress_callback(f"✅ {message}")
            
            return True, message

        except Exception as e:
            # 回滚事务，只有在conn已定义的情况下
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass

            error_msg = f"更新认证信息时出错: {str(e)}"
            if progress_callback:
                progress_callback(f"❌ {error_msg}")
            else:
                self.logger.error(error_msg)
            return False, error_msg

    def get_account_info(self):
        """
        获取当前认证信息（带缓存优化）
        
        Returns:
            dict: 包含账号基本信息的字典
        """
        # ⚡ 性能优化：添加缓存（1秒有效期）
        import time
        cache_ttl = 1.0  # 缓存1秒
        current_time = time.time()
        
        if hasattr(self, '_account_info_cache'):
            cache_data, cache_time = self._account_info_cache
            if current_time - cache_time < cache_ttl:
                return cache_data
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # ⚡ 性能优化：使用一次查询代替3次查询
            cursor.execute("""
                SELECT key, value FROM ItemTable 
                WHERE key IN ('cursorAuth/cachedEmail', 'cursorAuth/accessToken', 'cursorAuth/cachedSignUpType')
            """)
            results = cursor.fetchall()
            conn.close()
            
            # 解析结果
            data_map = {key: value for key, value in results}
            email = data_map.get('cursorAuth/cachedEmail')
            token = data_map.get('cursorAuth/accessToken')
            status = data_map.get('cursorAuth/cachedSignUpType')

            # 始终从JWT token中解析user_id，不使用数据库中存储的值
            user_id = None
            if token:
                user_id = self._extract_user_id_from_token(token)
                if user_id:
                    # 减少重复日志，只在第一次或账号变化时记录
                    if not hasattr(self, '_last_logged_user_id') or self._last_logged_user_id != user_id:
                        self.logger.info(f"从JWT token中解析到user_id: {user_id}")
                        self._last_logged_user_id = user_id
                else:
                    self.logger.warning("无法从JWT token中解析user_id")

            result = {
                'email': email,
                'token': token,
                'user_id': user_id,
                'status': status,
                'is_logged_in': status == "Auth_0" and email and token
            }
            
            # ⚡ 缓存结果
            self._account_info_cache = (result, current_time)
            return result

        except Exception as e:
            self.logger.error(f"获取账号信息失败: {str(e)}")
            return {
                'email': None,
                'token': None,
                'user_id': None,
                'status': None,
                'is_logged_in': False,
                'error': str(e)
            }

    def apply_machine_id_patch(self, progress_callback=None, skip_permission_check=False):
        """
        应用机器ID补丁，修改Cursor获取机器ID的方法（跳过workbench）

        Args:
            progress_callback: 进度回调函数
            skip_permission_check: 是否跳过权限检查

        Returns:
            tuple: (是否成功, 消息)
        """
        self.logger.info("开始应用机器ID补丁...")
        try:
            # 只应用main.js补丁，跳过workbench
            return self.patcher.patch_main_js()
        except Exception as e:
            error_msg = f"应用机器ID补丁失败: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def apply_account(self, email, access_token, refresh_token, user_id, progress_callback=None, cursor_manager=None, options=None):
        """
        应用账号到Cursor - 完整的应用流程（包含关闭和重启Cursor）
        
        Args:
            email: 邮箱
            access_token: 访问令牌
            refresh_token: 刷新令牌
            user_id: 用户ID
            progress_callback: 进度回调函数
            cursor_manager: Cursor管理器实例，用于关闭和重启Cursor
            options: 切换选项，包含use_existing_machine等设置
            
        Returns:
            tuple: (是否成功, 消息)
        """
        try:
            self.logger.info(f"正在应用账号: {email}...")

            # 1. 关闭Cursor进程
            if cursor_manager:
                if progress_callback:
                    progress_callback("正在关闭Cursor进程...")
                close_success, close_msg = cursor_manager.close_cursor_processes()
                if close_success:
                    if progress_callback:
                        progress_callback("✅ 已关闭Cursor进程")
                else:
                    if progress_callback:
                        progress_callback(f"⚠️ 关闭Cursor失败: {close_msg}")
            
            # 2. 重置机器码
            if progress_callback:
                progress_callback("正在重置机器码...")
            
            # 根据用户选择决定是否使用已有机器码或强制生成新机器码
            use_existing = options and options.get('use_existing_machine', False)
            use_random = options and options.get('use_random_machine', False)
            reset_success, reset_message, _ = self.reset_machine_ids(
                progress_callback=progress_callback,
                account_email=email,  # 传递账号邮箱，使用账号专属配置
                use_existing=use_existing,  # 传递是否使用已有配置的选项
                force_new=use_random  # 传递是否强制生成新配置的选项
            )

            if not reset_success:
                if progress_callback:
                    progress_callback(f"重置机器码失败: {reset_message}")
                return False, f"重置机器码失败: {reset_message}"

            # 3. 更新认证数据
            if progress_callback:
                progress_callback("正在更新认证信息...")
            auth_success, auth_message = self.update_auth(
                email=email,
                access_token=access_token,
                refresh_token=refresh_token,
                user_id=user_id,
                progress_callback=progress_callback
            )

            if auth_success:
                # 4. 应用补丁（非关键操作）
                if progress_callback:
                    progress_callback("正在应用机器ID补丁...")
                try:
                    patch_success, patch_message = self.apply_machine_id_patch(
                        progress_callback=progress_callback,
                        skip_permission_check=True
                    )
                    if "跳过" in patch_message or "⚠️" in patch_message:
                        self.logger.warning(f"补丁: {patch_message}")
                    if progress_callback:
                        progress_callback(patch_message)
                except Exception as patch_err:
                    self.logger.warning(f"补丁应用异常（不影响切换）: {str(patch_err)}")
                    if progress_callback:
                        progress_callback("⚠️ 补丁跳过")
                # 补丁失败不影响整体流程

                # 5. 最终验证：确保所有操作都完成
                if progress_callback:
                    progress_callback("🔍 最终验证账号切换结果...")
                
                # 🚀 优化：减少文件系统操作等待时间（一键换号专用优化）
                import time
                time.sleep(0.2)  # 进一步优化到0.2秒
                
                # 验证认证信息是否真正写入成功
                final_account_info = self.get_account_info()
                if (final_account_info.get('email') == email and 
                    final_account_info.get('user_id') == user_id and
                    final_account_info.get('token')):  # 验证token存在
                    
                    if progress_callback:
                        progress_callback("✅ 账号切换数据验证通过")
                    
                    # 6. 重新启动Cursor
                    if cursor_manager:
                        if progress_callback:
                            progress_callback("⏳ 等待系统稳定，准备重启Cursor...")
                        
                        # 🚀 优化：减少系统稳定等待时间（一键换号专用优化）
                        time.sleep(0.3)  # 进一步优化到0.3秒
                        
                        if progress_callback:
                            progress_callback("🚀 正在重新启动Cursor...")
                        start_success, start_msg = cursor_manager.start_cursor_with_workspaces()
                        if start_success:
                            if progress_callback:
                                progress_callback("✅ Cursor重启成功")
                        else:
                            if progress_callback:
                                progress_callback(f"⚠️ Cursor重启失败: {start_msg}")
                            
                    if progress_callback:
                        progress_callback("✅ 账号切换完成")
                    return True, "账号切换成功"
                else:
                    error_msg = "账号切换验证失败，数据库可能未正确更新"
                    if progress_callback:
                        progress_callback(f"❌ {error_msg}")
                    self.logger.error(f"{error_msg}: 期望email={email}, 实际={final_account_info.get('email')}")
                    return False, error_msg
            else:
                if progress_callback:
                    progress_callback(f"更新认证信息失败: {auth_message}")
                return False, f"更新认证信息失败: {auth_message}"

        except Exception as e:
            import traceback
            error_msg = f"应用账号时出错: {str(e)}"
            if progress_callback:
                progress_callback(error_msg)
                progress_callback(traceback.format_exc())
            return False, error_msg
