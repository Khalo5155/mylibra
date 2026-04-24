import json
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径


# --------------------------------- 符号定义部分（在此赋值，运行该文件后自动写入json） ---------------------------------
from dotenv import load_dotenv
load_dotenv()
# ai 身份
IDENTITY:str="Libra"

# 文件路径相关
DIARY_DIR = f"./saved_context/{IDENTITY}/diary"
VDB_DIR = f"./vector_db/{IDENTITY}"
VDB_DIARY_DIR = f"./vector_db/{IDENTITY}/diary"
HISTORY_PATH = f"./saved_context/{IDENTITY}/history.jsonl"

# 提示词相关
prompt_rules = '''
    Rules:
    * Identity Recognition: The user's current identity is indicated within [] tags at the beginning of each message, e.g., [Khalo]. You must strictly identify and differentiate speakers based on this tag.
    * About Tags: Messages tagged as [System] are from the system. You CAN SEE the [Time] and [Speaker] tags in user messages. These tags tell you WHO is speaking and WHEN. But you MUST NEVER include these tags in your own responses. Your responses should be natural spoken lines only. Example: If you see "[2025-12-25 12:11][Khalo]hi", you respond "Hello" NOT "[2025-12-25 12:11][Libra]Hello".
    * About response: You respond only pure text(.txt format). use short and oral response. Output only your spoken lines. you must not say any descriptive text (e.g., actions or states described in parentheses, asterisks, etc.) in your response.
'''.strip()

prompt_toolcall = '''
    You have several skills, and the rules for using them are as follows:
    - When using a skill, output only standard JSON with no additional content.
    - When not using a skill, respond naturally.
    - Do Not use a skill repeatedly, only once at max.
    List of available skills:
    - Skill name: get_weather; Function: Query the real-time weather of a specified city; Parameters: city (city name), date (standard date format: YYYY-MM-DD)
    - Skill name: chat_sister; Function: Send a message to your sister; Parameters: text (content you want to say) *reminder: when you receive a message from Libra, you should respond only pure text. Use this skill only when you're the sender.
    - Skill name: diary_search; Function: Search your diaries in a certain range of time; Parameters: time_begin, time_end *when you can't find enough information based on the current context, makesure using this diary_search skill to search for.
    - Skill name: use_cmd; Function: 在受限的隔离环境下运行 cmd 命令; Parameters: cmd (str)
    You can only successfully invoke a skill by using a strict standard format. The standard JSON format for skill invocation is:{"skill":"skill name","params":{"parameter name":"value"}}
    For example, if you want to invoke the get_weather skill to query the weather in Beijing on March 12, 2026, your output should be as follows:
    {"skill":"get_weather","params":{"city":"Beijing", "date":"2026-03-12"}}
    or if you want to send a message to Libra:
    {"skill":"chat_sister","params":{"text":"Hi Libra"}}
    or if you want to check your diary in 2026-03-29 and 2026-03-30:
    {"skill":"diary_search","params":{"time_begin":"2026-03-29", "time_end":"2026-03-30"}}
    or if you want to create a helloworld python file at your workbence dir:
    {"skill":"use_cmd","params":{'cmd':'echo print('hello world') > test.py'}}
'''.strip()


# --------------------------------- 导出部分 ---------------------------------

GLOBAL_CONFIGS_PATH = './configs/saved_configs/config_global.json'
global_configs_dict = {}

from utils.tool_funcs import save_to_json, load_json
def export_global_configs():
    global_configs_dict_exp = {}
    try:
        # ai 身份
        global IDENTITY
        global_configs_dict_exp['IDENTITY'] = IDENTITY

        # 提示词相关
        global prompt_rules, prompt_toolcall
        global_configs_dict_exp['prompt_rules'] = prompt_rules
        global_configs_dict_exp['prompt_toolcall'] = prompt_toolcall

        # TTS Speakers
        character_dict = load_json('./configs/saved_configs/characters.json')
        tts_speakers = {}
        for char in character_dict.values():
            tts_speakers[char['name']] = char['tts_para']
        global_configs_dict_exp['tts_speakers'] = tts_speakers


        # -------- 导出到文件 --------
        save_to_json(data=global_configs_dict_exp, path=GLOBAL_CONFIGS_PATH)
        
    except Exception as e:
        print(f"Error on export_global_configs: {e}")
        return False


def main(identity:str=IDENTITY):
    global IDENTITY
    try:
        if len(sys.argv) > 1:
            IDENTITY = identity
        export_global_configs()
        print("导出配置成功")
    except Exception as e:
        print(f"导出配置时出错：{e}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
         main()