import os
import json

def process_metadata_files():
    input_dir = r"D:\地学\doi\数据清单\geophysics-Electrical and Electromagnetic Exploration Methods\data"
    output_dir = r"D:\地学\doi\数据清单\geophysics-Electrical and Electromagnetic Exploration Methods\metadata"
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    for filename in os.listdir(input_dir):
        if not filename.endswith(".json"):
            continue
            
        filepath = os.path.join(input_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"Failed to parse {filename}")
                continue
                
        dataset_id = filename.split('-')[0]
        dataset_name = data.get("original_input", {}).get("dataset_name", "")
        doi = data.get("input_summary", {}).get("doi", "")
        
        metadata_sources = data.get("metadata_sources", {})
        
        output_list = []
        
        keys_to_process = ['doi_org', 'datacite_crossref', 'official_api']
        for key in keys_to_process:
            source_val = metadata_sources.get(key)
            
            if not source_val:  # Skip None, empty dict {}, empty list []
                continue
                
            # source_val could be a dict or a list (as specified by user for official_api)
            items_to_process = source_val if isinstance(source_val, list) else [source_val]
            
            for item in items_to_process:
                if not item or not isinstance(item, dict):
                    continue
                
                # Double check that we actually have a source and data
                if "source" not in item and "data" not in item:
                    continue
                    
                source_api = item.get("source", "")
                meta_data = item.get("data")
                
                # special logic if data is a string
                if isinstance(meta_data, str) and meta_data.strip():
                    # Determine file format based on item.get("format")
                    file_format = item.get("format", "txt").lower()
                    
                    # Create the file name: original json filename without extension + format
                    base_filename = os.path.splitext(filename)[0]
                    new_filename = f"{base_filename}.{file_format}"
                    new_filepath = os.path.join(output_dir, new_filename)
                    
                    with open(new_filepath, 'w', encoding='utf-8') as f_out:
                        f_out.write(meta_data)
                    
                    # metadata field becomes the new file name
                    meta_data = new_filename
                
                obj = {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "doi": doi,
                    "source_api": source_api,
                    "metadata": meta_data
                }
                output_list.append(obj)
                
        # Save the output list to a new JSON file in the output directory
        if output_list:
            output_filepath = os.path.join(output_dir, filename)
            with open(output_filepath, 'w', encoding='utf-8') as f_out:
                json.dump(output_list, f_out, ensure_ascii=False, indent=2)
            print(f"Processed and saved: {filename}")
        else:
            print(f"No valid metadata found for {filename}")

if __name__ == "__main__":
    process_metadata_files()
