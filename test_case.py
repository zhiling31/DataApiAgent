import sys
import os
import json
import importlib

# 确保能导入 code_result 下的模块
sys.path.append(os.path.join(os.path.dirname(__file__), "code_result"))

def main():
    # 按照 integrated_dataset_agent.py 中的逻辑动态导入
    try:
        IntegratedDataRepoFetcher = importlib.import_module("code_result.fetch_top_dataset_integrated").IntegratedDataRepoFetcher
    except ImportError:
        IntegratedDataRepoFetcher = importlib.import_module("code_result.fetcher_base").IntegratedDataRepoFetcher

    fetcher = IntegratedDataRepoFetcher()
    route_map = fetcher.get_route_map()

    input_data = {
    "doi": "10.4227/11/5587A88805812",
    "dataset_url": "https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.geology%3AG04150;http://www.earthbyte.org/Resources/agegrid2008.html;https://researchdata.edu.au/age-spreading-rates-ocean-crust/673164",
    "doi_landing_page": "https://researchdata.edu.au/age-spreading-rates-ocean-crust/673164",
    "dataset_name": "Age, spreading rates, and spreading asymmetry of the world's ocean crust",
    "version_name": "Version 3",
    "official_websites": [
      "NOAA National Centers for Environmental Information (NCEI)",
      "Research Data Australia",
      "EarthByte"
    ],
    "target_api_name": [
      "NOAA National Centers for Environmental Information (NCEI)"
    ]
  }

    target_apis = input_data.get("target_api_name", [])
    if not target_apis:
        print("Error: target_api_name is empty in input_data")
        return

    api_name = target_apis[0]
    matched_func = route_map.get(api_name)

    if not matched_func:
        print(f"Error: 找不到 API '{api_name}' 对应的执行函数！")
        return

    print(f"==========================================")
    print(f"正在测试 API: {api_name}")
    print(f"对应函数名: {matched_func.__name__}")
    print(f"==========================================")

    try:
        result = matched_func(**input_data)
        print(f"\n执行完成！\n")
        print("返回结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"\n执行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
