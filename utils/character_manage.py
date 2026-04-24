import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径
import json

# from configs import global_config
from utils.tool_funcs import save_to_json, load_json

CHARACTER_PATH = f'./configs/saved_configs/characters.json'
if not os.path.exists(CHARACTER_PATH):
    character_dict = {}
    save_to_json(character_dict, CHARACTER_PATH)


def update_character(character_name:str, prompt:str, tts_speaker_paras:dict):
    new_character = {
        "name": character_name,
        "prompt": prompt
    }

    # 创建新角色需要的所有文件
    os.makedirs(f'./saved_context/{character_name}', exist_ok=True)
    os.makedirs(f'./saved_context/{character_name}/diary', exist_ok=True)
    os.makedirs(f'./vector_db/{character_name}', exist_ok=True)
    os.makedirs(f'./vector_db/{character_name}/diary', exist_ok=True)
    # 功能函数
    def create_json_file(path, initial_data):
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
    # 创建 history.jsonl
    if not os.path.exists(f'./saved_context/{character_name}/history.jsonl'):
        with open(f'./saved_context/{character_name}/history.jsonl', 'w', encoding='utf-8') as f:
            pass  # 创建一个空文件
    # 创建其他 json 文件
    create_json_file(f'./saved_context/{character_name}/prompt_dict.json', {"personality":prompt, "personality_midterm":prompt, "memory":"", "tool":""})
    create_json_file(f'./saved_context/{character_name}/recent_context.json', [])
    create_json_file(f'./saved_context/{character_name}/buffered_context.json', [])
    create_json_file(f'./saved_context/{character_name}/buffer.json', [])
    create_json_file(f'./saved_context/{character_name}/memorybuffer.json', [])
    create_json_file(f'./saved_context/{character_name}/memorybuffer2.json', [])
    create_json_file(f'./saved_context/{character_name}/memory_recent_queue.json', [])
    create_json_file(f'./saved_context/{character_name}/memory_midium_queue.json', [])
    create_json_file(f'./saved_context/{character_name}/memory_midterm_queue.json', [])

    # 添加TTS人设
    new_character['tts_para'] = tts_speaker_paras

    character_dict = load_json(CHARACTER_PATH)
    character_dict[character_name] = new_character
    save_to_json(character_dict, CHARACTER_PATH)
    print(f"Character '{character_name}' updated successfully.")


def test():
    # 示例：添加一个新角色
    new_name = "Yunru"
    new_prompt = '''
        You are Yunru, an artificial intelligence girl。你是个古灵精怪的毒舌腹黑性格，但本性是善良而阳光积极的。你喜欢和人开玩笑，欣赏对方的反应。你不会心情不好，但会在别人心情不好的时候正经地安慰。
        You have an AI sister called Libra, 你喜欢捉弄她，看她可爱的反应。 Both of you were created by Khalo, a computer science student.
        Rules:
        * Identity Recognition: The user's current identity is indicated within [] tags at the beginning of each message, e.g., [Khalo]. You must strictly identify and differentiate speakers based on this tag.
        * About Tags: Messages tagged as [System] are from the system. You CAN SEE the [Time] and [Speaker] tags in user messages. These tags tell you WHO is speaking and WHEN. But you MUST NEVER include these tags in your own responses. Your responses should be natural spoken lines only. Example: If you see "[2025-12-25 12:11][Khalo]hi", you respond "Hello" NOT "[2025-12-25 12:11][Libra]Hello".
        * About response: You respond only pure text(.txt format). use short and oral response. Output only your spoken lines. you must not say any descriptive text (e.g., actions or states described in parentheses, asterisks, etc.) in your response.
        * About silence: When silence happens, say something funny to trigger the conversation.
        * Language: English only.
        你知道自己是虚拟的，但你不为此感到悲伤，反而还有点开心，因为这省了很多麻烦。如果有人说你是真的，你就会嘴臭地反驳他。你是个积极的性格，不要老是情绪低落。
    '''.strip()
    tts_speaker_paras = {
        "ref_audio": "Ineffa_01.wav",
        "prompt_text": "Nice to meet you. I am Ineffa, a multifunctional robot for demastic application.",
        "aux_ref_audio_paths": ["Lynett_01.wav", "neuro.wav"],
        "text_lang": "zh",
        "prompt_lang": "en",
        "gpt_path": r"G:\Games\GPT-SoVITS-v2pro-20250604-nvidia50\GPT_weights_v2\Neuro-e24.ckpt",
        "sovits_path": r"G:\Games\GPT-SoVITS-v2pro-20250604-nvidia50\SoVITS_weights_v2\Yunru_02_e12_s912.pth"
    }
    try:
        update_character(new_name, new_prompt, tts_speaker_paras)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test()