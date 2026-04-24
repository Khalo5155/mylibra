import re
import json
import os

# 移除所有圆括号内的内容
def clean_tags(s):
    cleaned = re.sub(r'\(.*?\)', '', s).strip()
    cleaned = re.sub(r'\（.*?\）', '', cleaned).strip()
    return cleaned
# 移除所有括号内的内容
def clean_alltags(s):
    cleaned = re.sub(r'\(.*?\)', '', s).strip()
    cleaned = re.sub(r'\（.*?\）', '', cleaned).strip()
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    cleaned = re.sub(r'\【.*?\】', '', cleaned).strip()
    cleaned = re.sub(r'\<.*?\>', '', cleaned).strip()
    cleaned = re.sub(r'\{.*?\}', '', cleaned).strip()
    return cleaned
# 移除前面的连续[tag]
def clean_pretags(s):
    cleaned = re.sub(r'^(\[.*?\])+', '', s).strip()
    return cleaned


# 句子切分
symbol_set = ",.?!:~，。、？！：\n"
def clip_sentence_check(s: str, split_length: int=60, max_split_length: int=120) -> str:
    assert split_length > 20
    if len(s) < split_length:
        return ""
    
    global symbol_set
    for i in range(split_length-10, min(len(s), max_split_length)):
        if s[i] in symbol_set:
            return s[:i+1]
    
    # 处理切片过大（改用空格切分）
    if len(s) >= max_split_length:
        for i in range(max_split_length-1, len(s)):
            if s[i] in " \t\n":
                return s[:i+1]

    return ""


# 保存到json
def save_to_json(data, path:str):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"saved to {path}")
    except Exception as e:
        print(f"failed while saving to: {path}")

# 尾插到jsonl
def append_to_jsonl(data, path):
    with open(path, 'a', encoding='utf-8') as f:
        # 转为一行JSON + 自动换行
        f.write(json.dumps(data, ensure_ascii=False) + '\n')

# 从json读取
def load_json(path:str):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"failed while loading from: {path}")
            return {}
    else:
        print(f"file not found: {path}")
        return {}
