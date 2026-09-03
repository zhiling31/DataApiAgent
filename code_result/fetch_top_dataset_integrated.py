# -*- coding: utf-8 -*-
import os
import glob
import importlib.util
import time
import json
import re
import types
from code_result.fetcher_decorator import REGISTERED_ROUTES

class IntegratedDataRepoFetcher:
    """动态插件装载器主类：零代码注入，自动装载 fetchers/ 目录下所有 @register_api 装饰的方法"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        self._load_all_plugins()

    def _get_with_retry(self, url, headers=None, max_retries=3):
        """通用的 HTTP/2 & TLS 伪装请求重试方法"""
        import requests as std_requests
        try:
            from curl_cffi import requests as cffi_requests
            has_cffi = True
        except ImportError:
            has_cffi = False

        headers = headers or self.headers
        for attempt in range(max_retries):
            try:
                if has_cffi:
                    response = cffi_requests.get(
                        url, headers=headers, timeout=120, allow_redirects=True,
                        verify=False, impersonate="chrome120"
                    )
                else:
                    response = std_requests.get(
                        url, headers=headers, timeout=120, allow_redirects=True, verify=False
                    )
                if response.status_code >= 400:
                    response.raise_for_status()
                return response
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    # 退回到原生 requests 尝试
                    try:
                        fallback_resp = std_requests.get(url, headers=headers, timeout=120, allow_redirects=True, verify=False)
                        if fallback_resp.status_code < 400:
                            return fallback_resp
                        fallback_resp.raise_for_status()
                    except Exception as fallback_e:
                        raise Exception(f"{e} (降级 requests 失败: {fallback_e})")

    def _load_all_plugins(self):
        """动态扫描并加载 code_result/fetchers/ 目录下的所有 fetch_*.py 插件"""
        fetchers_dir = os.path.join(os.path.dirname(__file__), "fetchers")
        if not os.path.exists(fetchers_dir):
            os.makedirs(fetchers_dir, exist_ok=True)
            return

        plugin_files = glob.glob(os.path.join(fetchers_dir, "fetch_*.py"))
        for p_file in plugin_files:
            mod_name = os.path.basename(p_file)[:-3]
            try:
                spec = importlib.util.spec_from_file_location(f"code_result.fetchers.{mod_name}", p_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                print(f"⚠️ 动态加载插件 {mod_name} 失败: {e}")

    def get_route_map(self):
        """将全局注册的函数绑定为当前实例的方法，返回路由映射字典"""
        route_map = {}
        for key, func in REGISTERED_ROUTES.items():
            route_map[key] = types.MethodType(func, self)
        return route_map

    @staticmethod
    def get_api_schema_desc():
        """从动态加载的路由映射中自动生成提示词"""
        fetcher = IntegratedDataRepoFetcher()
        routes = list(fetcher.get_route_map().keys())
        quoted_apis = [f"'{r}'" for r in routes]
        return "可匹配的官网列表：[" + ", ".join(quoted_apis) + "]"