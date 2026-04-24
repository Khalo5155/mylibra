import json
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径

GLOBAL_CONFIGS_PATH = './configs/saved_configs/config_global.json'
global_configs_dict = {}

# --------------------------------- 方法定义部分 ---------------------------------

def load_global_configs(path=GLOBAL_CONFIGS_PATH) -> bool:
    global global_configs_dict

    print("loading config_global.json...")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                global_configs_dict = json.load(f)
            print(f"successfully loaded global configs")
            return True
        except json.JSONDecodeError:
            print("文件格式错误，global configs 加载失败")
            return False
    else:
        print(f"路径不存在：{path}")
        return False

def Init_global_configs() -> bool:
    ''' 初始化全局配置 '''
    global global_configs_dict
    if not load_global_configs():
        print("global configs 加载失败，初始化终止")
        return False

    try:
        # --------------------------- 需要从文件中读取的部分 ---------------------------
        # ai 角色身份
        global IDENTITY
        IDENTITY = global_configs_dict['IDENTITY']

        # 通信地址相关
        global YUNRU_URL, LIBRA_URL, CHAT_SERVER_URL, CHAT_SERVER_URL_LOCAL, SELF_SERVER_URL
        CHAT_SERVER_URL = YUNRU_URL if IDENTITY=='Libra' else LIBRA_URL  # chat_sister 聊天接口地址
        CHAT_SERVER_URL_LOCAL = os.getenv("LOCAL_URL_LIBRA") if IDENTITY=='Yunru' else os.getenv("LOCAL_URL_YUNRU")
        SELF_SERVER_URL = os.getenv("LOCAL_URL_LIBRA") if IDENTITY=='Libra' else os.getenv("LOCAL_URL_YUNRU")
        print(f"当前身份：{IDENTITY}，设置 CHAT_SERVER_URL 为 {CHAT_SERVER_URL}，CHAT_SERVER_URL_LOCAL 为 {CHAT_SERVER_URL_LOCAL}，SELF_SERVER_URL 为 {SELF_SERVER_URL}")

        # 提示词相关
        global prompt_rules, prompt_toolcall
        prompt_rules = global_configs_dict['prompt_rules']
        prompt_toolcall = global_configs_dict['prompt_toolcall']

        # TTS人设相关
        global tts_speakers
        tts_speakers = global_configs_dict['tts_speakers']
        
        # --------------------------- 不需要从文件中读取，但依赖上文读取结果的部分 ---------------------------
        # 文件路径相关
        global DIARY_DIR, VDB_DIR, VDB_DIARY_DIR, HISTORY_PATH
        DIARY_DIR = f"./saved_context/{IDENTITY}/diary"
        VDB_DIR = f"./vector_db/{IDENTITY}"
        VDB_DIARY_DIR = f"./vector_db/{IDENTITY}/diary"
        HISTORY_PATH = f"./saved_context/{IDENTITY}/history.jsonl"

        # 提示词相关 - 记忆压缩，写日记
        # 记忆压缩提示词
        global prompt_zip_memory, prompt_zip_context
        prompt_zip_memory =f'''
            请你以{IDENTITY}的视角，总结以下对话中的关键信息，可以适当加入自己的情绪。返回且仅返回不带格式的纯文本：
        '''
        prompt_zip_context =f'''
            请你以{IDENTITY}的视角，总结以下对话中的关键信息，如果没有关键信息就就简单概括，可以适当加入自己的情绪。返回且仅返回不带格式的纯文本：
        '''

        # 日记提示词（prompt 前两条（人格，宏观记忆）+ 写日记的任务告知）
        def load_prompt(path=f'./saved_context/{IDENTITY}/prompt_dict.json'):
            ''' 读取本地存储的人格提示词 '''
            prompt_dict = {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        prompt_dict = json.load(f)
                    print(f"提示词加载成功")
                    return [prompt_dict['personality'], prompt_dict['memory']]
                except json.JSONDecodeError:
                    print("提示词文件格式错误！")
                    exit(0)
            else:
                print(f"路径不存在：{path}")
        preprompt2 = load_prompt()

        global prompt_diary_day, prompt_diary_week, prompt_diary_month, prompt_diary_year
        prompt_diary_day ='\n'.join(preprompt2) + '''
            现在，你要对以下记忆进行整理，把它们写成一篇日记，记录下今天发生的事。随意选择想写的部分，对于那些你关注的部分可以多写，不在乎的部分就少写或不写。 But don't write too long. Return only the finished diary as plain, unformatted text:
        '''
        prompt_diary_week ='\n'.join(preprompt2) + '''
            现在，你要对以下记忆进行整理，把它们写成一篇周记，记录下这周发生的重要的事，还有你的感受。随意选择想写的部分，对于那些你关注的部分可以多写，不在乎的部分就少写或不写。Return only the finished diary as plain, unformatted text:
        '''
        prompt_diary_month ='\n'.join(preprompt2) + '''
            现在，你要对以下记忆进行整理，把它们写成一篇月度总结，记录下这个月发生重要的事，还有你的感受。随意选择想写的部分，对于那些你关注的部分可以多写，不在乎的部分就少写或不写。Return only the finished diary as plain, unformatted text:
        '''
        prompt_diary_year ='\n'.join(preprompt2) + '''
            现在，你要对以下记忆进行整理，把它们写成一篇年度总结，简要记录下这一年发生的重要的事，还有你的感受。随意选择想写的部分，对于那些你关注的部分可以多写，不在乎的部分就少写或不写。Return only the finished diary as plain, unformatted text:
        '''

        # 知识谱图提示词
        global prompt_kg_extract
        prompt_kg_extract = f'''
            请你以{IDENTITY}的视角，从以下文本中抽取出有用的知识点和它们之间的关系，返回 (起点, 关系, 终点) 的元组列表。格式要求：list[tuple[str,str,str]]，例如[('A', 'like', 'B'), ('B', 'know', 'C')]。如果文本中没有有用的知识点，就返回一个空列表[]。返回且仅返回这个列表，不要其他任何多余的内容。
        '''

        return True

    except Exception as e:
        print(f"Error on Init_global_configs: {e}")
        return False


# --------------------------------- 符号声明部分 ---------------------------------
from dotenv import load_dotenv
load_dotenv()

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64

# ai 身份
IDENTITY:str

# API 相关
API_KEY = os.getenv("APP_API_KEY")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY")

# AES 加密相关
AES_KEY = os.getenv("AES_KEY")
class AESCipher:
    def __init__(self, key):
        self.key = key.encode('utf-8')
        self.mode = AES.MODE_ECB

    def encrypt(self, raw_text):
        if not raw_text:
            return ""
        return self.encrypt_binary(raw_text.encode('utf-8'))

    def decrypt(self, enc_text):
        if not enc_text:
            return ""
        decrypted_bytes = self.decrypt_binary(enc_text)
        return decrypted_bytes.decode('utf-8')

    def encrypt_binary(self, data_bytes):
        cipher = AES.new(self.key, self.mode)
        ct_bytes = cipher.encrypt(pad(data_bytes, AES.block_size))
        return base64.b64encode(ct_bytes).decode('utf-8')

    def decrypt_binary(self, enc_text_or_bytes):
        cipher = AES.new(self.key, self.mode)
        if isinstance(enc_text_or_bytes, str):
            enc_text_or_bytes = base64.b64decode(enc_text_or_bytes)
        return unpad(cipher.decrypt(enc_text_or_bytes), AES.block_size)
cipher_tool = AESCipher(AES_KEY)

# 通信地址相关
YUNRU_URL = os.getenv("YUNRU_URL")
LIBRA_URL = os.getenv("LIBRA_URL")
CHAT_SERVER_URL_LOCAL:str # 本地测试时 chat_sister 聊天接口地址（另一个 sibling 运行的地址）
SELF_SERVER_URL:str  # 本地服务端地址

# 百度语音识别配置
BDSTT_APP_ID = os.getenv("BDSTT_APP_ID")
BDSTT_API_KEY = os.getenv("BDSTT_API_KEY")
BDSTT_SECRET_KEY = os.getenv("BDSTT_SECRET_KEY")

# 文件路径相关
DIARY_DIR:str
VDB_DIR:str
VDB_DIARY_DIR:str
HISTORY_PATH:str

# 提示词相关
prompt_rules:str
prompt_toolcall:str

# TTS相关
libra_tts_para:dict
yunru_tts_para:dict
neuro_tts_para:dict
evil_tts_para:dict
tts_speakers:dict

# 记忆压缩提示词
prompt_zip_memory:str
prompt_zip_context:str

# 日记提示词（prompt 前两条（人格，记忆）+ 写日记的任务告知）
prompt_diary_day:str
prompt_diary_week:str
prompt_diary_month:str
prompt_diary_year:str

# 知识谱图提示词
prompt_kg_extract:str # 从文本中抽取知识图谱的提示词


# --------------------------------- 初始化部分 ---------------------------------

if not Init_global_configs():
    print("初始化 global config 失败")
    exit(1)