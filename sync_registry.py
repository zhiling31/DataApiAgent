import sys
from fetch_publisher_api import sync_registry_from_plugins

if __name__ == "__main__":
    print("🚀 开始扫描 code_result/fetchers/*.py 并反向同步至 platform_api_registry.json ...")
    sync_registry_from_plugins()
    print("✅ 同步任务已成功执行结束！")
