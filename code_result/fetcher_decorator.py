# -*- coding: utf-8 -*-
import functools

# 全局注册表，存储 publisher/aliases/domains 到函数对象的映射
REGISTERED_ROUTES = {}

def register_api(publisher: str, aliases: list = None, has_api: bool = True, is_reviewed: bool = False, auditor_notes: str = "", scope_limit: str = "ITEM_LEVEL_ONLY"):
    """
    API 插件注册装饰器
    :param publisher: 主平台名称 (如 "Zenodo")
    :param aliases: 平台的同义词、缩写或域名列表 (如 ["CERN Zenodo", "zenodo.org"])
    :param has_api: 是否有可用的 API
    :param is_reviewed: 是否经过人工核验
    :param auditor_notes: 人工审核备注
    :param scope_limit: API 的能力边界
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
            
        wrapper.has_api = has_api
        wrapper.is_reviewed = is_reviewed
        wrapper.auditor_notes = auditor_notes
        wrapper.scope_limit = scope_limit
        
        all_keys = [publisher]
        if aliases:
            all_keys.extend(aliases)
        for key in all_keys:
            if key and isinstance(key, str):
                REGISTERED_ROUTES[key.strip()] = wrapper
                
        return wrapper
    return decorator
