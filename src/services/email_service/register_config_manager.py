#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
注册配置管理器 - 管理域名、银行卡等注册相关配置
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class RegisterConfigManager:
    """注册配置管理器"""
    
    def __init__(self, config_dir: str = None):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置文件目录
        """
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor', 'config')
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.domains_file = self.config_dir / 'domains.json'
        self.cards_file = self.config_dir / 'cards.json'  # 保留银行卡文件路径
        self.email_config_file = self.config_dir / 'email_config.json'
        self.phone_verification_file = self.config_dir / 'phone_verification.json'
        
        self.logger = logging.getLogger(__name__)
        
        # 初始化默认配置
        self._init_default_config()
        
        # 初始化银行卡管理器（向后兼容）
        self._init_card_manager()
    
    def _init_card_manager(self):
        """初始化银行卡管理器"""
        try:
            from .card_manager import CardManager
            self.card_manager = CardManager(register_config=self, log_callback=None)
            
            # 确保银行卡配置文件存在
            if not self.cards_file.exists():
                self._create_default_cards()
                
        except Exception as e:
            self.logger.error(f"初始化银行卡管理器失败: {str(e)}")
            self.card_manager = None
    
    def _create_default_cards(self):
        """创建默认银行卡配置"""
        default_cards = [
            {
                "number": "5598880458332832",
                "expiry": "0530",
                "cvc": "351", 
                "name": self._generate_random_name(),  # 随机生成姓名
                "address1": "123 Main Street",
                "city": "New York",
                "zip": "10001",
                "used": False,
                "description": "示例卡片1"
            }
        ]
        
        self._save_json(self.cards_file, {
            "cards": default_cards,
            "description": "银行卡信息列表，按顺序使用，用完标记为废弃"
        })
        
        self.logger.info("已创建默认银行卡配置")
    
    def _init_default_config(self):
        """初始化默认配置"""
        # 如果配置文件不存在，创建默认配置
        if not self.domains_file.exists():
            self._create_default_domains()
        
        if not self.email_config_file.exists():
            self._create_default_email_config()
        
        if not self.phone_verification_file.exists():
            self._create_default_phone_verification_config()
    
    def _create_default_domains(self):
        """创建默认域名配置"""
        default_domains = [
            "example1.com",
            "example2.com", 
            "example3.com"
        ]
        
        self._save_json(self.domains_file, {
            "domains": default_domains,
            "description": "配置域名列表，注册时随机选择"
        })
        
        self.logger.info("已创建默认域名配置")
    
    def _create_default_email_config(self):
        """创建默认邮箱配置"""
        default_config = {
            "email_type": "temp_mail",  # 邮箱类型: temp_mail(临时邮箱) 或 imap(IMAP邮箱)
            "temp_mail": {
                "enabled": True,
                "api_base": "https://tempmail.plus/api",
                "username": "",  # 完整的临时邮箱地址，例如: testuser@tempmail.plus
                "pin": "",       # tempmail.plus的PIN码
                "epin": ""       # 备用PIN码字段
            },
            "imap_mail": {
                "enabled": False,
                "email": "",           # IMAP邮箱地址，如 your@2925.com 或 your@qq.com
                "password": "",        # 邮箱授权码（不是登录密码）
                "imap_server": "",     # IMAP服务器地址（可留空自动匹配）
                "imap_port": 993,      # IMAP服务器端口
                "use_random_email": True,  # 是否使用随机子邮箱
                "register_email": ""   # 注册邮箱基础地址（用于生成子邮箱）
            }
        }
        
        self._save_json(self.email_config_file, default_config)
        self.logger.info("已创建默认邮箱配置")
    
    def _create_default_phone_verification_config(self):
        """创建默认手机验证配置"""
        default_config = {
            "enabled": False,  # 是否启用手机验证
            "username": "",    # 豪猪平台API账号
            "password": "",    # 豪猪平台API密码
            "project_id": "",  # 项目ID (sid)
            "uid": "",         # 对接码ID（可选，指定使用哪个对接码）
            "api_server": "https://api.haozhuma.com",  # API服务器地址
            "author": "",  # 开发者账号（留空则轮询使用：Aethxz247XCGL, gxka520）
            "max_usage_count": 3,  # 每个号码最大使用次数
            "description": "豪猪接码平台配置，用于自动获取手机号和验证码。author留空时自动轮询多个开发者账号"
        }
        
        self._save_json(self.phone_verification_file, default_config)
        self.logger.info("已创建默认手机验证配置")
    
    def get_domains(self) -> List[str]:
        """获取域名列表"""
        try:
            data = self._load_json(self.domains_file)
            return data.get('domains', [])
        except Exception as e:
            self.logger.error(f"获取域名列表失败: {str(e)}")
            return []
    
    def set_domains(self, domains: List[str]) -> bool:
        """
        设置域名列表
        
        Args:
            domains: 域名列表（支持任意数量，至少1个）
            
        Returns:
            bool: 是否设置成功
        """
        try:
            # 过滤空域名
            valid_domains = [d.strip() for d in domains if d.strip()]
            
            if len(valid_domains) < 1:
                raise ValueError("至少需要配置1个域名")
            
            data = {
                "domains": valid_domains,
                "description": f"配置{len(valid_domains)}个域名，注册时随机选择",
                "updated_at": datetime.now().isoformat()
            }
            
            self._save_json(self.domains_file, data)
            self.logger.info(f"域名配置已更新: {valid_domains}")
            return True
            
        except Exception as e:
            self.logger.error(f"设置域名失败: {str(e)}")
            return False
     
    def get_email_config(self) -> Dict:
        """获取邮箱配置"""
        try:
            return self._load_json(self.email_config_file)
        except Exception as e:
            self.logger.error(f"获取邮箱配置失败: {str(e)}")
            return {}
    
    def set_email_config(self, config: Dict) -> bool:
        """
        设置邮箱配置
        
        Args:
            config: 邮箱配置字典
            
        Returns:
            bool: 是否设置成功
        """
        try:
            self._save_json(self.email_config_file, config)
            self.logger.info("邮箱配置已更新")
            return True
            
        except Exception as e:
            self.logger.error(f"设置邮箱配置失败: {str(e)}")
            return False
    
    def get_phone_verification_config(self) -> Dict:
        """获取手机验证配置"""
        try:
            return self._load_json(self.phone_verification_file)
        except Exception as e:
            self.logger.error(f"获取手机验证配置失败: {str(e)}")
            return {"enabled": False}
    
    def set_phone_verification_config(self, config: Dict) -> bool:
        """
        设置手机验证配置
        
        Args:
            config: 手机验证配置字典
            
        Returns:
            bool: 是否设置成功
        """
        try:
            config['updated_at'] = datetime.now().isoformat()
            self._save_json(self.phone_verification_file, config)
            self.logger.info("手机验证配置已更新")
            return True
            
        except Exception as e:
            self.logger.error(f"设置手机验证配置失败: {str(e)}")
            return False
    
    def get_skip_card_binding(self) -> bool:
        """
        获取是否跳过绑卡配置
        
        Returns:
            bool: 是否跳过绑卡（默认False）
        """
        try:
            if self.cards_file.exists():
                data = self._load_json(self.cards_file)
                return data.get('skip_card_binding', False)
            return False
        except Exception as e:
            self.logger.error(f"获取跳过绑卡配置失败: {str(e)}")
            return False
    
    def set_skip_card_binding(self, skip: bool) -> bool:
        """
        设置是否跳过绑卡
        
        Args:
            skip: 是否跳过绑卡
            
        Returns:
            bool: 是否设置成功
        """
        try:
            # 读取现有配置
            if self.cards_file.exists():
                data = self._load_json(self.cards_file)
            else:
                data = {"cards": []}
            
            # 更新跳过绑卡配置
            data['skip_card_binding'] = skip
            data['updated_at'] = datetime.now().isoformat()
            
            # 保存配置
            self._save_json(self.cards_file, data)
            self.logger.info(f"跳过绑卡配置已更新: {skip}")
            return True
            
        except Exception as e:
            self.logger.error(f"设置跳过绑卡配置失败: {str(e)}")
            return False
    
    def get_use_us_bank(self) -> bool:
        """
        获取是否使用美国银行账户配置
        
        Returns:
            bool: 是否使用美国银行账户（默认False）
        """
        try:
            if self.cards_file.exists():
                data = self._load_json(self.cards_file)
                return data.get('use_us_bank', False)
            return False
        except Exception as e:
            self.logger.error(f"获取使用美国银行账户配置失败: {str(e)}")
            return False
    
    def set_use_us_bank(self, use_us_bank: bool) -> bool:
        """
        设置是否使用美国银行账户
        
        Args:
            use_us_bank: 是否使用美国银行账户
            
        Returns:
            bool: 是否设置成功
        """
        try:
            # 读取现有配置
            if self.cards_file.exists():
                data = self._load_json(self.cards_file)
            else:
                data = {"cards": []}
            
            # 更新使用美国银行账户配置
            data['use_us_bank'] = use_us_bank
            data['updated_at'] = datetime.now().isoformat()
            
            # 保存配置
            self._save_json(self.cards_file, data)
            self.logger.info(f"使用美国银行账户配置已更新: {use_us_bank}")
            return True
            
        except Exception as e:
            self.logger.error(f"设置使用美国银行账户配置失败: {str(e)}")
            return False
    
    def _load_json(self, file_path: Path) -> Dict:
        """加载JSON文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            self.logger.error(f"加载JSON文件失败 {file_path}: {str(e)}")
            return {}
    
    
    def _save_json(self, file_path: Path, data: Dict) -> bool:
        """保存JSON文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"保存JSON文件失败 {file_path}: {str(e)}")
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
    
    # ==================== 银行卡管理适配器方法（向后兼容） ====================
    
    def get_card_list(self) -> List[Dict]:
        """获取银行卡列表（直接读取文件，避免循环调用）"""
        # 直接读取文件，避免通过CardManager造成循环调用
        return self._load_json(self.cards_file).get('cards', [])
    
    def save_card_list(self, cards: List[Dict]) -> bool:
        """保存银行卡列表（直接保存文件，避免循环调用）"""
        # 直接保存文件，避免通过CardManager造成循环调用
        data = {
            "cards": cards,
            "description": "银行卡信息列表，按顺序使用，用完标记为废弃",
            "updated_at": datetime.now().isoformat()
        }
        return self._save_json(self.cards_file, data)
    
    def get_available_cards_count(self) -> int:
        """获取可用银行卡数量（直接计算，避免循环调用）"""
        # 直接计算，避免通过CardManager造成循环调用
        cards = self.get_card_list()
        return len([card for card in cards if not card.get('used', False) and not card.get('allocated', False) and not card.get('problematic', False)])
    
    def add_cards_from_text(self, cards_text: str) -> bool:
        """从文本添加银行卡信息（委托给CardManager）"""
        if self.card_manager:
            return self.card_manager.add_cards_from_text(cards_text)
        else:
            self.logger.error("银行卡管理器未初始化，无法添加银行卡")
            return False
    
    def reset_all_cards(self) -> bool:
        """重置所有银行卡状态（直接操作，避免循环调用）"""
        try:
            cards = self.get_card_list()
            if not cards:
                self.logger.info("❌ 无银行卡信息可重置")
                return True
            
            reset_count = 0
            for card in cards:
                modified = False
                
                if card.get('used', False):
                    card['used'] = False
                    modified = True
                
                if card.get('allocated', False):
                    card.pop('allocated', None)
                    modified = True
                
                if card.get('problematic', False):
                    card['problematic'] = False
                    modified = True
                
                if modified:
                    reset_count += 1
            
            if reset_count > 0:
                success = self.save_card_list(cards)
                if success:
                    self.logger.info(f"🔄 已重置 {reset_count} 张银行卡状态（包括问题卡）")
                    
                    # 统计重置后的状态
                    available = sum(1 for c in cards if not c.get('used', False) and not c.get('problematic', False) and not c.get('allocated', False))
                    self.logger.info(f"📊 重置后可用银行卡: {available} 张")
                    return True
            else:
                self.logger.info("✅ 无需重置银行卡状态")
                return True
                
        except Exception as e:
            self.logger.error(f"重置银行卡状态失败: {str(e)}")
            return False
    
    def validate_card_consistency(self) -> bool:
        """验证银行卡数据一致性（直接检查，避免循环调用）"""
        try:
            cards = self.get_card_list()
            if not cards:
                return True
            
            issues = []
            
            # 检查必要字段
            for i, card in enumerate(cards):
                card_id = f"Card#{i+1}(****{card.get('number', 'unknown')[-4:]})"
                
                if not card.get('number'):
                    issues.append(f"{card_id}: 缺少卡号")
                
                # 检查状态一致性
                used = card.get('used', False)
                allocated = card.get('allocated', False)
                
                # 检查同时有used和allocated标记的情况
                if used and allocated:
                    issues.append(f"{card_id}: 同时标记为used和allocated(应该清除allocated)")
            
            if issues:
                self.logger.warning(f"🔍 银行卡数据一致性检查发现 {len(issues)} 个问题:")
                for issue in issues:
                    self.logger.warning(f"   - {issue}")
                return False
            else:
                self.logger.debug(f"✅ 银行卡数据一致性检查通过: {len(cards)} 张卡片状态正常")
                return True
                
        except Exception as e:
            self.logger.error(f"银行卡一致性检查失败: {str(e)}")
            return False
    


if __name__ == "__main__":
    # 测试代码
    config = RegisterConfigManager()
    print("域名列表:", config.get_domains())
    print("可用银行卡数量:", config.get_available_cards_count())
