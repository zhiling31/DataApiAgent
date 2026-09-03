import argparse
import os
import json
import re
from datetime import datetime

REGISTRY_FILE = "code_result/platform_api_registry.json"
FETCHERS_DIR = "code_result/fetchers"
DRAFTS_DIR = os.path.join(FETCHERS_DIR, "drafts")
DIFFS_DIR = os.path.join(FETCHERS_DIR, "diffs")

def main():
    parser = argparse.ArgumentParser(description="Approve AI generated drafts, review metadata, and list pending audits.")
    parser.add_argument("--approve", type=str, help="The base name of the plugin to approve (e.g. fetch_xxx or xxx)")
    parser.add_argument("--scope", type=str, choices=["ITEM_LEVEL_ONLY", "CATALOG_LEVEL_ONLY", "BOTH", "NONE"], help="Override the scope limit")
    parser.add_argument("--notes", type=str, help="Human auditor notes")
    parser.add_argument("--list-pending", action="store_true", help="List all publishers awaiting human audit")
    
    args = parser.parse_args()
    
    if not os.path.exists(REGISTRY_FILE):
        print(f"❌ 找不到注册表文件: {REGISTRY_FILE}")
        return

    with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    if args.list_pending:
        drafts = []
        no_api = []
        for pub_name, data in registry.items():
            if data.get("has_pending_draft"):
                drafts.append(pub_name)
            elif not data.get("is_verified") and data.get("human_audit", {}).get("is_reviewed") is False:
                no_api.append(pub_name)
        
        print("\n=== 📊 待办审查报表 ===")
        print(f"\n👉 待审核代码更新 (存在草稿文件) [{len(drafts)} 个]:")
        for p in drafts:
            print(f" - {p}")
            
        print(f"\n👉 待确认无 API 平台 (无代码) [{len(no_api)} 个]:")
        for p in no_api:
            print(f" - {p}")
        print("\n========================\n")
        return

    if args.approve:
        plugin_name = args.approve
        if plugin_name.endswith(".py"):
            plugin_name = plugin_name[:-3]
            
        if not plugin_name.startswith("fetch_"):
            draft_basename = f"fetch_{plugin_name}"
            clean_search = plugin_name
        else:
            draft_basename = plugin_name
            clean_search = plugin_name.replace("fetch_", "")
            
        draft_file = os.path.join(DRAFTS_DIR, f"{draft_basename}.py")
        if not os.path.exists(draft_file):
            print(f"❌ 找不到草稿文件: {draft_file}")
            return
            
        with open(draft_file, 'r', encoding='utf-8') as f:
            draft_content = f.read()
            
        # 核心逻辑修改：从文件中提取 @register_api 里的 publisher
        m_pub = re.search(r'publisher\s*=\s*["\']([^"\']+)["\']', draft_content)
        extracted_publisher = m_pub.group(1) if m_pub else None
            
        found = False
        target_pub_name = None
        target_data = None
        
        # 1. 优先使用提取出的 publisher 进行精确匹配
        if extracted_publisher and extracted_publisher in registry:
            found = True
            target_pub_name = extracted_publisher
            target_data = registry[extracted_publisher]
        else:
            # 2. 降级模糊匹配
            for pub_name, data in registry.items():
                clean_pub = re.sub(r'[^a-zA-Z0-9]', '_', pub_name).lower()
                if clean_pub == clean_search or (extracted_publisher and pub_name.lower() == extracted_publisher.lower()):
                    found = True
                    target_pub_name = pub_name
                    target_data = data
                    break
                
        if not found:
            # 【临时逻辑】从历史注册表文件查找缺失的平台
            # 历史数据审核完了要删的
            print(f"⚠️ 在 {REGISTRY_FILE} 中未能找到匹配的平台记录 (搜索条件: {extracted_publisher or clean_search})")
            print(f"🔄 启动临时逻辑：尝试从 output0728 历史注册表中查找并复制...")
            fallback_json = r"d:\地学\doi\git\output0728\platform_api_registry_0728.json"
            if os.path.exists(fallback_json):
                with open(fallback_json, 'r', encoding='utf-8') as ff:
                    fallback_registry = json.load(ff)
                
                # 同样优先精确匹配
                if extracted_publisher and extracted_publisher in fallback_registry:
                    found = True
                    target_pub_name = extracted_publisher
                    target_data = fallback_registry[extracted_publisher]
                    registry[target_pub_name] = target_data
                    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f_out:
                        json.dump(registry, f_out, indent=4, ensure_ascii=False)
                    print(f"✅ 已成功从历史注册表精确匹配到【{target_pub_name}】并复制到当前注册表！")
                else:
                    for fb_pub_name, fb_data in fallback_registry.items():
                        fb_clean = re.sub(r'[^a-zA-Z0-9]', '_', fb_pub_name).lower()
                        if fb_clean == clean_search or (extracted_publisher and fb_pub_name.lower() == extracted_publisher.lower()):
                            found = True
                            target_pub_name = fb_pub_name
                            target_data = fb_data
                            
                            # 复制到当前 registry 中
                            registry[fb_pub_name] = fb_data
                            with open(REGISTRY_FILE, 'w', encoding='utf-8') as f_out:
                                json.dump(registry, f_out, indent=4, ensure_ascii=False)
                                
                            print(f"✅ 已成功从历史注册表模糊匹配到【{fb_pub_name}】并复制到当前注册表！")
                            break
                        
            if not found:
                print(f"❌ 严重错误：在历史注册表中依然未能找到匹配的平台记录！")
                return
            
        # 智能分流处理：
        prod_file = os.path.join(FETCHERS_DIR, f"{draft_basename}.py")
        diff_file = os.path.join(DIFFS_DIR, f"{draft_basename}.diff")
            
        # 使用正则替换 decorator 里的 is_reviewed=False 为 is_reviewed=True
        draft_content = re.sub(r'is_reviewed=False', 'is_reviewed=True', draft_content, count=1)
        
        # 注入 auditor_notes 和 scope_limit
        if args.notes is not None:
            safe_notes = args.notes.replace('"', '\"')
            draft_content = re.sub(r'auditor_notes="[^"]*"', f'auditor_notes="{safe_notes}"', draft_content, count=1)
            draft_content = re.sub(r"auditor_notes='[^']*'", f'auditor_notes="{safe_notes}"', draft_content, count=1)
        if args.scope is not None:
            safe_scope = args.scope.replace('"', '\"')
            draft_content = re.sub(r'scope_limit="[^"]*"', f'scope_limit="{safe_scope}"', draft_content, count=1)
            draft_content = re.sub(r"scope_limit='[^']*'", f'scope_limit="{safe_scope}"', draft_content, count=1)
            
        with open(prod_file, 'w', encoding='utf-8') as f:
            f.write(draft_content)
            
        print(f"✅ 已成功将审批后的代码覆盖到生产文件: {prod_file}")
        
        os.remove(draft_file)
        print(f"🗑️ 已清理物理草稿文件: {draft_file}")
        if os.path.exists(diff_file):
            os.remove(diff_file)
            print(f"🗑️ 已清理物理差异文件: {diff_file}")

        # 调用 fetch_publisher_api.py 里的反向同步逻辑，自动把 Python 里的改动更新到 json
        import sys
        if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import fetch_publisher_api
        fetch_publisher_api.sync_registry_from_plugins()
            
        print(f"🎉 审批完成！【{target_pub_name}】的最新状态及审计日志已通过 IaC 反向同步至注册表。")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
