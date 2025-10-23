#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
邮件服务模块
负责邮件提取、验证、自动注册等功能
"""

from .email_extractor import EmailExtractor
from .email_verification_handler import EmailVerificationHandler
from .auto_register_engine import AutoRegisterEngine
from .register_config_manager import RegisterConfigManager

__all__ = ['EmailExtractor', 'EmailVerificationHandler', 'AutoRegisterEngine', 'RegisterConfigManager']
