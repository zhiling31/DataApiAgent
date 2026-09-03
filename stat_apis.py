import os
import ast
import glob
import json

def main():
    fetchers_dir = r"D:\地学\doi\git\code_result\fetchers"
    output_file = r"D:\地学\doi\git\code_result\api_stats.txt"
    registry_file = r"D:\地学\doi\git\code_result\platform_api_registry.json"
    
    files = glob.glob(os.path.join(fetchers_dir, "*.py"))
    
    has_api_list = []
    no_api_list = []
    
    for f in files:
        basename = os.path.basename(f)
        if basename in ("__init__.py", "fetcher_base.py"):
            continue
            
        with open(f, "r", encoding="utf-8") as file:
            content = file.read()
            
        try:
            tree = ast.parse(content)
        except SyntaxError:
            print(f"语法错误，跳过: {basename}")
            continue
            
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and getattr(dec.func, 'id', '') == 'register_api':
                        publisher = None
                        has_api = None
                        for kw in dec.keywords:
                            if kw.arg == 'publisher' and isinstance(kw.value, ast.Constant):
                                publisher = kw.value.value
                            elif kw.arg == 'has_api' and isinstance(kw.value, ast.Constant):
                                has_api = kw.value.value
                        
                        if publisher is not None and has_api is not None:
                            if has_api:
                                has_api_list.append(publisher)
                            else:
                                no_api_list.append(publisher)
    
    with open(output_file, "w", encoding="utf-8") as out:
        out.write(f"总计: {len(has_api_list) + len(no_api_list)} 个平台\n")
        out.write(f"====================================\n")
        out.write(f"【有可用 API】 (共 {len(has_api_list)} 个):\n")
        for p in sorted(has_api_list):
            out.write(f" - {p}\n")
            
        out.write(f"\n====================================\n")
        out.write(f"【无可用 API / 不合规】 (共 {len(no_api_list)} 个):\n")
        for p in sorted(no_api_list):
            out.write(f" - {p}\n")

    try:
        with open(registry_file, "r", encoding="utf-8") as rf:
            registry = json.load(rf)
            registry_publishers = set(registry.keys())
    except Exception as e:
        print(f"无法读取注册表: {e}")
        registry_publishers = set()

    file_publishers = set(has_api_list + no_api_list)
    registry_only = registry_publishers - file_publishers
    files_only = file_publishers - registry_publishers

    with open(output_file, "a", encoding="utf-8") as out:
        out.write(f"\n====================================\n")
        out.write(f"【注册表有，生产区代码无 (Gap)】 (共 {len(registry_only)} 个):\n")
        for p in sorted(registry_only):
            out.write(f" - {p}\n")
            
        out.write(f"\n====================================\n")
        out.write(f"【注册表无，生产区代码有 (Gap)】 (共 {len(files_only)} 个):\n")
        for p in sorted(files_only):
            out.write(f" - {p}\n")

    print(f"✅ 统计完成，结果已输出到: {output_file}")
    print(f"   有可用 API: {len(has_api_list)} 个")
    print(f"   无可用 API: {len(no_api_list)} 个")

if __name__ == '__main__':
    main()
