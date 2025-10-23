"""
账户标记管理器 - 手动标记不同用途的账户
功能：预设标记类型、自定义标记、颜色管理
作者：小纯归来
创建时间：2025年9月
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
import json
import os
from datetime import datetime

class TagType(Enum):
    """标记类型 - 试用标记简化版"""
    COMMERCIAL = "commercial"  # 🔥 新增：商用
    EXHAUSTED = "exhausted"    # 用尽

class TagColors:
    """预设标记颜色"""
    COLOR_MAP = {
        TagType.COMMERCIAL: "#409eff",    # 🔥 新增：蓝色 - 商用
        TagType.EXHAUSTED: "#f56c6c",     # 红色 - 用尽
    }
    
    @classmethod
    def get_color(cls, tag_type: TagType) -> str:
        """获取标记颜色"""
        return cls.COLOR_MAP.get(tag_type, "#909399")

class AccountTag:
    """账户标记数据类"""
    
    def __init__(self, 
                 tag_id: str,
                 tag_type: TagType, 
                 display_name: str,
                 color: str = None,
                 description: str = "",
                 created_time: datetime = None):
        self.tag_id = tag_id
        self.tag_type = tag_type
        self.display_name = display_name
        self.color = color or TagColors.get_color(tag_type)
        self.description = description
        self.created_time = created_time or datetime.now()
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "tag_id": self.tag_id,
            "tag_type": self.tag_type.value,
            "display_name": self.display_name,
            "color": self.color,
            "description": self.description,
            "created_time": self.created_time.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AccountTag':
        """从字典创建"""
        return cls(
            tag_id=data["tag_id"],
            tag_type=TagType(data["tag_type"]),
            display_name=data["display_name"],
            color=data["color"],
            description=data.get("description", ""),
            created_time=datetime.fromisoformat(data["created_time"])
        )

class TagManager:
    """标记管理器"""
    
    def __init__(self, config_dir: str = None):
        # 如果未指定配置目录，使用用户主目录
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), '.xc_cursor')
        self.config_dir = config_dir
        self.tags_file = os.path.join(config_dir, "account_tags.json")
        self.account_tags_file = os.path.join(config_dir, "account_tag_mapping.json")
        
        # 确保目录存在
        os.makedirs(config_dir, exist_ok=True)
        
        # 加载数据
        self.tags: Dict[str, AccountTag] = {}
        self.account_tag_mapping: Dict[str, List[str]] = {}  # email -> [tag_ids]
        
        self._load_tags()
        self._load_account_mappings()
        self._ensure_default_tags()
    
    def _load_tags(self):
        """加载标记配置"""
        if os.path.exists(self.tags_file):
            try:
                with open(self.tags_file, 'r', encoding='utf-8') as f:
                    tags_data = json.load(f)
                    for tag_data in tags_data:
                        tag = AccountTag.from_dict(tag_data)
                        self.tags[tag.tag_id] = tag
            except Exception as e:
                print(f"加载标记配置失败: {e}")
    
    def _load_account_mappings(self):
        """加载账户标记映射"""
        if os.path.exists(self.account_tags_file):
            try:
                with open(self.account_tags_file, 'r', encoding='utf-8') as f:
                    self.account_tag_mapping = json.load(f)
            except Exception as e:
                print(f"加载账户标记映射失败: {e}")
    
    def _save_tags(self):
        """保存标记配置"""
        try:
            tags_data = [tag.to_dict() for tag in self.tags.values()]
            with open(self.tags_file, 'w', encoding='utf-8') as f:
                json.dump(tags_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存标记配置失败: {e}")
    
    def _save_account_mappings(self):
        """保存账户标记映射"""
        try:
            with open(self.account_tags_file, 'w', encoding='utf-8') as f:
                json.dump(self.account_tag_mapping, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存账户标记映射失败: {e}")
    
    def _ensure_default_tags(self):
        """确保默认标记存在 - 试用标记简化版"""
        default_tags = [
            ("commercial", TagType.COMMERCIAL, "商用", "商业用途的账户"),  # 🔥 新增
            ("exhausted", TagType.EXHAUSTED, "用尽", "已经用尽配额的账户"),
        ]
        
        for tag_id, tag_type, display_name, description in default_tags:
            if tag_id not in self.tags:
                self.create_tag(tag_id, tag_type, display_name, description=description)
    
    def create_tag(self, tag_id: str, tag_type: TagType, display_name: str, 
                   color: str = None, description: str = "") -> AccountTag:
        """创建新标记"""
        tag = AccountTag(tag_id, tag_type, display_name, color, description)
        self.tags[tag_id] = tag
        self._save_tags()
        return tag
    
    def get_tag(self, tag_id: str) -> Optional[AccountTag]:
        """获取标记"""
        return self.tags.get(tag_id)
    
    def get_all_tags(self) -> List[AccountTag]:
        """获取所有标记"""
        return list(self.tags.values())
    
    def get_tags_by_type(self, tag_type: TagType) -> List[AccountTag]:
        """按类型获取标记"""
        return [tag for tag in self.tags.values() if tag.tag_type == tag_type]
    
    def delete_tag(self, tag_id: str) -> bool:
        """删除标记（同时清理相关映射）"""
        if tag_id in self.tags:
            # 清理所有使用此标记的账户映射
            for email, tag_ids in self.account_tag_mapping.items():
                if tag_id in tag_ids:
                    tag_ids.remove(tag_id)
            
            # 删除标记
            del self.tags[tag_id]
            self._save_tags()
            self._save_account_mappings()
            return True
        return False
    
    def add_tag_to_account(self, email: str, tag_id: str) -> bool:
        """为账户添加标记"""
        if tag_id not in self.tags:
            return False
            
        if email not in self.account_tag_mapping:
            self.account_tag_mapping[email] = []
        
        if tag_id not in self.account_tag_mapping[email]:
            self.account_tag_mapping[email].append(tag_id)
            self._save_account_mappings()
            return True
        return False
    
    def remove_tag_from_account(self, email: str, tag_id: str) -> bool:
        """从账户移除标记"""
        if email in self.account_tag_mapping and tag_id in self.account_tag_mapping[email]:
            self.account_tag_mapping[email].remove(tag_id)
            # 如果没有标记了，删除这个映射
            if not self.account_tag_mapping[email]:
                del self.account_tag_mapping[email]
            self._save_account_mappings()
            return True
        return False
    
    def set_account_tags(self, email: str, tag_ids: List[str]) -> bool:
        """设置账户的所有标记（覆盖原有标记）"""
        # 验证所有tag_id都存在
        for tag_id in tag_ids:
            if tag_id not in self.tags:
                return False
        
        if tag_ids:
            self.account_tag_mapping[email] = tag_ids.copy()
        else:
            # 如果标记列表为空，删除映射
            if email in self.account_tag_mapping:
                del self.account_tag_mapping[email]
        
        self._save_account_mappings()
        return True
    
    def get_account_tags(self, email: str) -> List[AccountTag]:
        """获取账户的所有标记"""
        tag_ids = self.account_tag_mapping.get(email, [])
        return [self.tags[tag_id] for tag_id in tag_ids if tag_id in self.tags]
    
    def get_accounts_with_tag(self, tag_id: str) -> List[str]:
        """获取使用指定标记的所有账户"""
        accounts = []
        for email, tag_ids in self.account_tag_mapping.items():
            if tag_id in tag_ids:
                accounts.append(email)
        return accounts
    
    def get_tag_statistics(self) -> Dict[str, int]:
        """获取标记统计信息"""
        stats = {}
        for tag_id in self.tags.keys():
            stats[tag_id] = len(self.get_accounts_with_tag(tag_id))
        return stats
    
    def format_tags_for_display(self, email: str, max_tags: int = 3) -> List[Dict[str, str]]:
        """格式化标记用于UI显示"""
        tags = self.get_account_tags(email)
        
        display_tags = []
        for i, tag in enumerate(tags[:max_tags]):
            display_tags.append({
                "id": tag.tag_id,
                "name": tag.display_name,
                "color": tag.color,
                "type": tag.tag_type.value
            })
        
        # 如果标记数量超过限制，添加省略号提示
        if len(tags) > max_tags:
            display_tags.append({
                "id": "more",
                "name": f"+{len(tags) - max_tags}",
                "color": "#909399",
                "type": "more"
            })
        
        return display_tags


# 全局标记管理器实例
_tag_manager_instance = None

def get_tag_manager() -> TagManager:
    """获取全局标记管理器实例"""
    global _tag_manager_instance
    if _tag_manager_instance is None:
        _tag_manager_instance = TagManager()
    return _tag_manager_instance


# 测试代码
if __name__ == "__main__":
    # 测试标记系统
    tm = TagManager("test_data")
    
    # 测试创建自定义标记（使用已有的EXHAUSTED类型）
    custom_tag = tm.create_tag("custom1", TagType.EXHAUSTED, "测试用尽", "#ff6b6b", "测试用自定义标记")
    print(f"创建标记: {custom_tag.display_name}")
    
    # 测试为账户添加标记
    test_email = "test@example.com"
    tm.add_tag_to_account(test_email, "active")
    tm.add_tag_to_account(test_email, "development")
    tm.add_tag_to_account(test_email, "high")
    
    # 获取账户标记
    account_tags = tm.get_account_tags(test_email)
    print(f"账户 {test_email} 的标记:")
    for tag in account_tags:
        print(f"  - {tag.display_name} ({tag.color})")
    
    # 获取显示格式
    display_tags = tm.format_tags_for_display(test_email)
    print(f"显示格式: {display_tags}")
    
    # 获取统计信息
    stats = tm.get_tag_statistics()
    print(f"标记统计: {stats}")
