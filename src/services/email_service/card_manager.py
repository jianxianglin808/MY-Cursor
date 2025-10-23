#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
银行卡管理器 - 负责银行卡的分配、状态管理和并发控制
从 auto_register_engine.py 拆分出来的银行卡管理功能
"""

import copy
import logging
import threading
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Callable


class CardManager:
    """银行卡管理器 - 统一管理银行卡的分配和状态"""
    
    def __init__(self, register_config, log_callback: Optional[Callable[[str], None]] = None):
        """
        初始化银行卡管理器
        
        Args:
            register_config: 注册配置管理器
            log_callback: 日志回调函数
        """
        self.register_config = register_config
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        
        # 当前分配的银行卡信息
        self.current_card_info = None
        
        # 银行卡分配锁（防止并发冲突）
        self._card_allocation_lock = threading.Lock()
        
        # 银行卡已标记为已使用的标志
        self._card_marked_used = False
        
        # 银行卡配置文件路径
        self._init_card_config_path()
        
    def _init_card_config_path(self):
        """初始化银行卡配置文件路径"""
        if hasattr(self.register_config, 'cards_file'):
            self.cards_file = self.register_config.cards_file
        else:
            # 如果register_config没有cards_file属性，使用默认路径
            config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'config')
            os.makedirs(config_dir, exist_ok=True)
            self.cards_file = Path(config_dir) / 'cards.json'
        
    def _log_progress(self, message: str):
        """记录进度"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def get_next_card_info(self) -> Optional[Dict[str, str]]:
        """
        获取下一个可用的银行卡信息
        只获取不标记，只有成功到达dashboard才标记为已使用
        
        Returns:
            Optional[Dict]: 银行卡信息字典，如果无可用卡则返回None
        """
        # 确保使用共享锁
        lock = getattr(self, '_card_allocation_lock', None)
        if lock is None:
            self.logger.warning("⚠️ 未找到共享锁，创建本地锁（可能影响并发安全性）")
            lock = threading.Lock()
            self._card_allocation_lock = lock
        
        with lock:
            card_list = self.get_card_list()
            if not card_list:
                self._log_progress("❌ 未配置银行卡信息")
                return None
            
            # 查找第一个未使用、未被预占用且非问题卡的卡
            for idx, card in enumerate(card_list):
                card_number = card.get('number', 'unknown')
                is_used = card.get('used', False)
                is_allocated = card.get('allocated', False)
                is_problematic = card.get('problematic', False)
                
                # 调试：记录每张卡的状态
                self.logger.debug(
                    f"📋 卡片#{idx+1} ****{card_number[-4:]}: "
                    f"used={is_used}, allocated={is_allocated}, problematic={is_problematic}"
                )
                
                if not is_used and not is_allocated and not is_problematic:
                    # 先深拷贝保存干净的卡信息，再标记allocated
                    self.current_card_info = copy.deepcopy(card)
                    
                    # 然后标记为已分配（预占用），防止其他线程获取
                    card['allocated'] = True
                    # 保存修改后的列表（包含allocated标记）
                    self.save_card_list(card_list)

                    self._log_progress(f"💳 分配银行卡 #{idx+1} ****{card['number'][-4:]}")
                    self.logger.debug(f"🔍 分配的银行卡: number=****{self.current_card_info['number'][-4:]} cvc={self.current_card_info.get('cvc', '')}")
                    self.logger.debug(f"🔍 卡池状态: allocated=True, used=False")
                    return self.current_card_info
            
            self._log_progress("❌ 所有银行卡已用完或已分配")
            self.logger.warning(f"📊 卡池状态：总计{len(card_list)}张卡，无可用卡")
            return None
    
    def mark_card_as_used(self):
        """标记当前银行卡为已使用"""
        try:
            if not self.current_card_info:
                self.logger.warning("⚠️ 没有当前银行卡信息，无法标记")
                return
                
            # 确保使用正确的共享锁
            lock = getattr(self, '_card_allocation_lock', None)
            if lock is None:
                self.logger.warning("⚠️ 标记银行卡时未找到共享锁，创建本地锁")
                lock = threading.Lock()
                self._card_allocation_lock = lock
            
            with lock:
                card_list = self.get_card_list()
                card_found = False
                target_number = self.current_card_info['number']
                
                for card in card_list:
                    if card.get('number', '') == target_number:
                        card['used'] = True
                        # 清除allocated标记
                        card.pop('allocated', None)
                        card_found = True
                        break
                
                if card_found:
                    self.save_card_list(card_list)
                    
                    # 设置银行卡已标记的状态，防止重复释放
                    self._card_marked_used = True
                    
                    # 计算剩余可用银行卡数量（不包括已分配的）
                    available_count = len([c for c in card_list if not c.get('used', False) and not c.get('allocated', False)])
                    
                    self._log_progress(f"💳 银行卡 ****{target_number[-4:]} 已标记为已使用")
                    self._log_progress(f"📊 剩余可用银行卡: {available_count} 张")
                    
                    self.logger.info(f"✅ 银行卡已标记，跳过重复刷新")
                else:
                    self.logger.warning(f"⚠️ 未找到匹配的银行卡进行标记: {target_number[-4:] if target_number else 'None'}")
        except Exception as e:
            self.logger.error(f"标记银行卡失败: {str(e)}")
    
    def mark_card_as_problematic(self):
        """标记当前银行卡为问题卡（进入绑卡界面但注册失败）"""
        try:
            if not self.current_card_info:
                self.logger.warning("⚠️ 没有当前银行卡信息，无法标记为问题卡")
                return
            
            # 确保使用正确的共享锁
            lock = getattr(self, '_card_allocation_lock', None)
            if lock is None:
                self.logger.warning("⚠️ 标记问题卡时未找到共享锁，创建本地锁")
                lock = threading.Lock()
                self._card_allocation_lock = lock
            
            with lock:
                card_list = self.get_card_list()
                card_found = False
                target_number = self.current_card_info['number']
                
                for card in card_list:
                    if card.get('number', '') == target_number:
                        card['problematic'] = True  # 标记为问题卡
                        card['used'] = True  # 同时标记为已使用
                        card.pop('allocated', None)  # 清除allocated标记
                        card_found = True
                        break
                
                if card_found:
                    self.save_card_list(card_list)
                    self._card_marked_used = True
                    
                    # 计算剩余可用银行卡数量
                    available_count = len([c for c in card_list if not c.get('used', False) and not c.get('allocated', False) and not c.get('problematic', False)])
                    
                    self._log_progress(f"⚠️ 银行卡 ****{target_number[-4:]} 已标记为问题卡")
                    self._log_progress(f"📊 剩余可用银行卡: {available_count} 张")
                else:
                    self.logger.warning(f"⚠️ 未找到匹配的银行卡进行标记: {target_number[-4:] if target_number else 'None'}")
        except Exception as e:
            self.logger.error(f"标记问题卡失败: {str(e)}")
    
    def release_allocated_card(self):
        """释放已分配但未使用的银行卡（用于注册失败但未进入绑卡界面的情况）"""
        try:
            if self.current_card_info and not getattr(self, '_card_marked_used', False):
                # 确保使用正确的共享锁
                lock = getattr(self, '_card_allocation_lock', None)
                if lock is None:
                    self.logger.warning("⚠️ 释放银行卡时未找到共享锁，创建本地锁")
                    lock = threading.Lock()
                    self._card_allocation_lock = lock
                
                with lock:
                    card_list = self.get_card_list()
                    card_found = False
                    target_number = self.current_card_info.get('number', '')
                    
                    for card in card_list:
                        if card.get('number', '') == target_number:
                            # 清除allocated标记，允许其他任务使用
                            card.pop('allocated', None)
                            card_found = True
                            break
                    
                    if card_found:
                        self.save_card_list(card_list)
                        self._log_progress(f"🔓 释放未使用的银行卡 ****{target_number[-4:]}")
                    else:
                        self.logger.warning(f"⚠️ 未找到匹配的银行卡进行释放: {target_number[-4:] if target_number else 'None'}")
        except Exception as e:
            self.logger.error(f"释放银行卡失败: {str(e)}")
    
    def get_card_statistics(self) -> Dict[str, int]:
        """
        获取银行卡统计信息
        
        Returns:
            Dict: 包含总数、已用、可用、已分配等统计信息
        """
        try:
            card_list = self.get_card_list()
            if not card_list:
                return {
                    'total': 0,
                    'used': 0,
                    'allocated': 0,
                    'available': 0
                }
            
            total = len(card_list)
            used = len([c for c in card_list if c.get('used', False)])
            allocated = len([c for c in card_list if c.get('allocated', False)])
            available = len([c for c in card_list if not c.get('used', False) and not c.get('allocated', False)])
            
            return {
                'total': total,
                'used': used,
                'allocated': allocated,
                'available': available
            }
        except Exception as e:
            self.logger.error(f"获取银行卡统计信息失败: {str(e)}")
            return {
                'total': 0,
                'used': 0,
                'allocated': 0,
                'available': 0
            }
    
    def reset_all_card_status(self, reset_used: bool = False, reset_allocated: bool = True, reset_problematic: bool = False):
        """
        重置所有银行卡状态
        
        Args:
            reset_used: 是否重置已使用状态
            reset_allocated: 是否重置已分配状态
            reset_problematic: 是否重置问题卡状态
        """
        try:
            with self._card_allocation_lock:
                card_list = self.get_card_list()
                if not card_list:
                    self._log_progress("❌ 无银行卡信息可重置")
                    return
                
                reset_count = 0
                for card in card_list:
                    modified = False
                    
                    if reset_used and card.get('used', False):
                        card['used'] = False
                        modified = True
                    
                    if reset_allocated and card.get('allocated', False):
                        card.pop('allocated', None)
                        modified = True
                    
                    if reset_problematic and card.get('problematic', False):
                        card['problematic'] = False
                        modified = True
                    
                    if modified:
                        reset_count += 1
                
                if reset_count > 0:
                    self.save_card_list(card_list)
                    self._log_progress(f"🔄 已重置 {reset_count} 张银行卡状态")
                    
                    # 输出重置后的统计信息
                    stats = self.get_card_statistics()
                    self._log_progress(f"📊 重置后统计: 总计{stats['total']}张, 可用{stats['available']}张")
                else:
                    self._log_progress("✅ 无需重置银行卡状态")
                    
        except Exception as e:
            self.logger.error(f"重置银行卡状态失败: {str(e)}")
    
    def validate_card_consistency(self) -> bool:
        """
        验证银行卡数据一致性
        
        Returns:
            bool: 数据是否一致
        """
        try:
            card_list = self.get_card_list()
            if not card_list:
                return True
            
            issues = []
            
            # 检查必要字段
            for i, card in enumerate(card_list):
                if not card.get('number'):
                    issues.append(f"银行卡 {i+1} 缺少卡号")
                if not card.get('expiry'):
                    issues.append(f"银行卡 {i+1} 缺少有效期")
                if not card.get('cvc'):
                    issues.append(f"银行卡 {i+1} 缺少CVC")
                if not card.get('name'):
                    issues.append(f"银行卡 {i+1} 缺少持卡人姓名")
            
            # 检查重复卡号
            card_numbers = [card.get('number', '') for card in card_list]
            duplicates = set([num for num in card_numbers if card_numbers.count(num) > 1 and num])
            if duplicates:
                issues.append(f"发现重复卡号: {list(duplicates)}")
            
            # 检查异常状态
            for i, card in enumerate(card_list):
                if card.get('used', False) and card.get('allocated', False):
                    issues.append(f"银行卡 {i+1} 同时标记为已使用和已分配")
            
            if issues:
                self.logger.warning("⚠️ 银行卡数据一致性检查发现问题:")
                for issue in issues:
                    self.logger.warning(f"  - {issue}")
                return False
            else:
                self.logger.debug("✅ 银行卡数据一致性检查通过")
                return True
                
        except Exception as e:
            self.logger.error(f"银行卡一致性检查失败: {str(e)}")
            return False
    
    def set_shared_lock(self, shared_lock: threading.Lock):
        """
        设置共享锁（用于并行注册场景）
        
        Args:
            shared_lock: 共享的线程锁对象
        """
        self._card_allocation_lock = shared_lock
        self.logger.debug(f"✅ CardManager已设置共享锁: {id(shared_lock)}")
    
    def get_current_card_info(self) -> Optional[Dict[str, str]]:
        """
        获取当前分配的银行卡信息
        
        Returns:
            Optional[Dict]: 当前银行卡信息，如果无则返回None
        """
        return self.current_card_info
    
    def is_card_marked_used(self) -> bool:
        """
        检查当前银行卡是否已标记为已使用
        
        Returns:
            bool: 是否已标记为已使用
        """
        return getattr(self, '_card_marked_used', False)
    
    def clear_current_card(self):
        """清空当前银行卡信息"""
        self.current_card_info = None
        self._card_marked_used = False
    
    def get_card_list(self) -> List[Dict]:
        """获取银行卡列表（直接从配置文件读取）"""
        # 直接从文件读取，避免循环调用
        return self._load_cards_from_file()
    
    def save_card_list(self, cards: List[Dict]) -> bool:
        """保存银行卡列表（直接写入配置文件）"""
        # 直接写入文件，避免循环调用
        return self._save_cards_to_file(cards)
    
    def _load_cards_from_file(self) -> List[Dict]:
        """直接从文件加载银行卡列表"""
        try:
            if self.cards_file.exists():
                with open(self.cards_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('cards', [])
            return []
        except Exception as e:
            self.logger.error(f"加载银行卡文件失败: {str(e)}")
            return []
    
    def _save_cards_to_file(self, cards: List[Dict]) -> bool:
        """直接保存银行卡列表到文件"""
        try:
            data = {
                "cards": cards,
                "description": "银行卡信息列表，按顺序使用，用完标记为废弃",
                "updated_at": datetime.now().isoformat()
            }
            
            with open(self.cards_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"保存银行卡文件失败: {str(e)}")
            return False
    
    def add_cards_from_text(self, cards_text: str) -> bool:
        """
        从文本添加银行卡信息（保留现有状态标记）
        格式：每行一个卡号，格式为 "卡号,到期日,CVC,持卡人姓名"
        
        Args:
            cards_text: 银行卡文本信息
            
        Returns:
            bool: 是否添加成功
        """
        try:
            cards = []
            lines = cards_text.strip().split('\n')
            added_count = 0
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 完全按照文本标记来设置状态，不保留旧状态
                is_used = False
                is_problematic = False
                
                # 检查问题卡标记
                if line.endswith(" (问题卡)"):
                    is_problematic = True
                    is_used = True
                    line = line[:-6]
                elif line.endswith("（问题卡）"):
                    is_problematic = True
                    is_used = True
                    line = line[:-5]
                # 检查已使用标记
                elif line.endswith(" (已使用)"):
                    is_used = True
                    line = line[:-6]
                elif line.endswith("（已使用）"):
                    is_used = True
                    line = line[:-5]
                
                parts = line.split(',')
                if len(parts) >= 3:
                    card_number = parts[0].strip()
                    cvc = parts[2].strip()
                    
                    if is_problematic:
                        self.logger.info(f"检测到问题卡: {card_number}")
                    elif is_used:
                        self.logger.info(f"检测到已使用的银行卡: {card_number}")
                    
                    card_info = {
                        "number": card_number,
                        "expiry": parts[1].strip(),
                        "cvc": cvc,
                        "name": self._generate_random_name(),
                        "address1": "123 Main Street",
                        "city": "New York", 
                        "zip": "10001",
                        "used": is_used,
                        "problematic": is_problematic,
                        "added_at": datetime.now().isoformat()
                    }
                    
                    cards.append(card_info)
                    added_count += 1
            
            if added_count > 0:
                self.save_card_list(cards)
                
                # 统计最终保存的状态（而不是文本标记）
                final_used_count = sum(1 for c in cards if c.get('used', False))
                final_problematic_count = sum(1 for c in cards if c.get('problematic', False))
                final_available_count = sum(1 for c in cards if not c.get('used', False) and not c.get('problematic', False))
                
                self.logger.info(
                    f"成功保存 {added_count} 张银行卡 "
                    f"(可用: {final_available_count}, 已使用: {final_used_count}, 问题卡: {final_problematic_count})"
                )
                return True
            else:
                self.logger.warning("未解析到有效的银行卡信息")
                return False
                
        except Exception as e:
            self.logger.error(f"添加银行卡失败: {str(e)}")
            return False
    
    def _generate_random_name(self) -> str:
        """生成随机的持卡人姓名"""
        first_names = [
            "John", "Jane", "Mike", "Sarah", "David", "Lisa", "Tom", "Anna", 
            "Chris", "Emma", "James", "Mary", "Robert", "Patricia", "Michael",
            "Jennifer", "William", "Linda", "Richard", "Elizabeth", "Joseph",
            "Susan", "Thomas", "Jessica", "Charles", "Nancy", "Christopher",
            "Karen", "Daniel", "Betty", "Matthew", "Helen", "Anthony", "Sandra"
        ]
        
        last_names = [
            "Smith", "Johnson", "Brown", "Davis", "Miller", "Wilson", "Moore",
            "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin",
            "Thompson", "Garcia", "Martinez", "Robinson", "Clark", "Rodriguez",
            "Lewis", "Lee", "Walker", "Hall", "Allen", "Young", "Hernandez",
            "King", "Wright", "Lopez", "Hill", "Scott", "Green", "Adams"
        ]
        
        import random
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        return f"{first_name} {last_name}"
    
    def get_available_cards_count(self) -> int:
        """获取可用银行卡数量（排除已使用、已分配和问题卡）"""
        cards = self.get_card_list()
        return len([card for card in cards if not card.get('used', False) and not card.get('allocated', False) and not card.get('problematic', False)])
