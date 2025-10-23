#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
API缓存管理器 - 统一管理API请求缓存
功能：统一缓存机制，避免重复代码
作者：小纯归来
创建时间：2025年9月
"""

import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ApiCacheManager:
    """API缓存管理器 - 单例模式"""
    
    _instance = None
    _cache = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.cache = {}
        self.default_ttl = 300  # 默认5分钟缓存
    
    def get_cache_key(self, user_id: str, access_token: str, api_type: str) -> str:
        """生成缓存key"""
        return f"{api_type}_{user_id}_{access_token[:10]}"
    
    def get_cached_data(self, user_id: str, access_token: str, api_type: str, ttl: int = None) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            user_id: 用户ID
            access_token: 访问令牌
            api_type: API类型 (subscription, usage等)
            ttl: 缓存有效期，默认300秒
            
        Returns:
            缓存的数据，如果过期或不存在则返回None
        """
        if ttl is None:
            ttl = self.default_ttl
            
        cache_key = self.get_cache_key(user_id, access_token, api_type)
        cached_item = self.cache.get(cache_key)
        
        if cached_item:
            current_time = time.time()
            if (current_time - cached_item['timestamp']) < ttl:
                logger.debug(f"命中缓存: {api_type} for {user_id[:10]}...")
                return cached_item['data']
            else:
                # 缓存过期，删除
                del self.cache[cache_key]
                logger.debug(f"缓存已过期: {api_type} for {user_id[:10]}...")
        
        return None
    
    def set_cached_data(self, user_id: str, access_token: str, api_type: str, data: Any) -> None:
        """
        设置缓存数据
        
        Args:
            user_id: 用户ID
            access_token: 访问令牌
            api_type: API类型 (subscription, usage等)
            data: 要缓存的数据
        """
        cache_key = self.get_cache_key(user_id, access_token, api_type)
        self.cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }
        logger.debug(f"设置缓存: {api_type} for {user_id[:10]}...")
    
    def clear_cache(self, user_id: str = None, access_token: str = None, api_type: str = None) -> None:
        """
        清理缓存
        
        Args:
            user_id: 指定用户ID清理，为None则清理所有
            access_token: 指定令牌清理，为None则清理所有
            api_type: 指定API类型清理，为None则清理所有
        """
        if user_id is None and access_token is None and api_type is None:
            # 清理所有缓存
            self.cache.clear()
            logger.info("清理所有API缓存")
            return
        
        # 有选择地清理缓存
        keys_to_remove = []
        for key in self.cache.keys():
            should_remove = True
            
            if api_type is not None and not key.startswith(f"{api_type}_"):
                should_remove = False
            
            if user_id is not None and access_token is not None:
                expected_prefix = f"{api_type or key.split('_')[0]}_{user_id}_{access_token[:10]}"
                if not key.startswith(expected_prefix):
                    should_remove = False
            
            if should_remove:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.cache[key]
            
        logger.info(f"清理了 {len(keys_to_remove)} 个缓存项")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        stats = {
            'total_items': len(self.cache),
            'expired_items': 0
        }
        
        current_time = time.time()
        for cached_item in self.cache.values():
            if (current_time - cached_item['timestamp']) >= self.default_ttl:
                stats['expired_items'] += 1
        
        return stats
    
    def cleanup_expired(self) -> int:
        """清理过期缓存项"""
        current_time = time.time()
        keys_to_remove = []
        
        for key, cached_item in self.cache.items():
            if (current_time - cached_item['timestamp']) >= self.default_ttl:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.cache[key]
        
        if keys_to_remove:
            logger.info(f"清理了 {len(keys_to_remove)} 个过期缓存项")
        
        return len(keys_to_remove)


# 全局缓存管理器实例
_api_cache_manager = None

def get_api_cache_manager() -> ApiCacheManager:
    """获取全局API缓存管理器实例"""
    global _api_cache_manager
    if _api_cache_manager is None:
        _api_cache_manager = ApiCacheManager()
    return _api_cache_manager


# 兼容性：保持原有的全局缓存变量，但重定向到新的缓存管理器
_api_cache = {}

def _get_legacy_cache():
    """获取兼容性缓存 - 重定向到新的缓存管理器"""
    cache_manager = get_api_cache_manager()
    return cache_manager.cache

# 重定向旧的全局缓存到新的管理器
import sys
current_module = sys.modules[__name__]
setattr(current_module, '_api_cache', property(_get_legacy_cache))
