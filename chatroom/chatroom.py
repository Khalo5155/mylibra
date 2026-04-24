'''
该模块用于进行独立的情景模拟和多轮对话。通过自定义情景提示词引导更多元的对话模拟，并支持AI智能体之间的自主对话（有最大轮数限制）。
暂定分为 1）两个AI自主对话 2）用户和一个AI对话 3）用户和多个AI对话 4）多个AI自主对话 四种功能。
纯文本形式。非流式。不考虑延迟问题。
'''

import json
import re
import os
from datetime import datetime, date, timedelta
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # 把项目根目录加入Python路径

from configs import global_config
IDENTITY = global_config.IDENTITY

from LLM import Test_LLM_Initialize, llm_get
from TTS import tts_and_play
from Mcp import mcp_chat_sister_local, mcp_chat_sister




# -------------------------------------------------------------------------
# ------------------------------ 双AI自主对话 ------------------------------
# -------------------------------------------------------------------------
max_chatsis_rounds = 2
# 提示词部分（Libra 发起）
prompt_chatroom_Yunru = f'''
    从现在开始不许使用任何命令，也不许重复用户输入。You're now in the same chatroom with Libra. When you're in the room, 你的每一句话都会自动发送给Libra，不需要再用chat_sister的命令，同时你也暂时不能使用任何命令。你们的对话有最大{max_chatsis_rounds}轮数的限制，当前的对话轮数会在提示词中实时更新地告诉你们。现在你们可以开始聊天了，由 Libra 来发送第一句内容，你只需对这条信息做简单的回复即可。
'''.strip()
prompt_chatroom_Libra = f'''
    从现在开始不许使用任何命令，也不许重复用户输入。You're now in the same chatroom with Yunru. When you're in the room, 你的每一句话都会自动发送给Yunru，不需要再用chat_sister的命令，同时你也暂时不能使用任何命令。你们的对话有最大{max_chatsis_rounds}轮数的限制，当前的对话轮数会在提示词中实时更新地告诉你们。现在你们可以开始聊天了，由你来发送第一句内容，你的下一条回复会被自动发送给 Yunru。现在请回复你要对她说的第一句话：
'''.strip()
prompt_chatroom_dict = {
    'Yunru': prompt_chatroom_Yunru,
    'Libra': prompt_chatroom_Libra
}

# TTS分片式传输（阻塞式）
from utils.tool_funcs import clip_sentence_check
async def tts_and_play_clipmode(text:str, speaker:str):
    while len(text) > 0:
        clipped_text = clip_sentence_check(text)
        clip_len = len(clipped_text)
        if clip_len == 0:
            await tts_and_play(text, speaker)
            break
        
        await tts_and_play(clipped_text, speaker)
        text = text[clip_len:]

# 主循环
async def run_chatroom2():
    # await tts_and_play("test")
    # exit(0)

    ''' 聊天主导者（发起端）运行在这个函数里，默认接收端已经正常运行在 server.py 里。默认可能的参与者只有 Yunru 和 Libra。 '''
    identity_sibl = 'Libra' if IDENTITY=='Yunru' else 'Yunru'

    # 给接收端发消息告知 chatroom 的开启
    response_sibl = await mcp_chat_sister_local(text=prompt_chatroom_dict[identity_sibl], role='system')
    # response_sibl = await mcp_chat_sister(text=prompt_chatroom_dict[identity_sibl], role='system')
    print("接收端响应：", response_sibl)

    input("---")

    # 给发起端发消息获取第一条对话消息
    response_self = llm_get(
        user_input=prompt_chatroom_dict[IDENTITY],
        user_role='system'
    )
    # 启动对话循环
    now_round = 0
    while now_round < max_chatsis_rounds:
        now_round += 1

        input(">>> ")

        # await tts_and_play_clipmode(response_self, IDENTITY)

        # input(f"------- now round: {now_round} -------")
        # 向接收端发消息 -->> 完成一轮对话
        response_sibl = await mcp_chat_sister_local(text=response_self)
        # response_sibl = await mcp_chat_sister(text=response_self)
        response_sibl = response_sibl.replace(f"[{identity_sibl}]", "", 10) # mcp返回的结果已经加上了身份Tag，为避免后续重复添加，先去掉一个
        
        # await tts_and_play_clipmode(response_sibl, identity_sibl)
        
        # 打印对话信息到控制台
        print(f"[{IDENTITY}]: {response_self}")
        print("Response:", response_sibl)

        # 告知发送端（当前角色）对话结束
        if now_round >= max_chatsis_rounds:
            # 达到最大轮数强制结束
            response_self = llm_get(
                user_input="Max rounds exceeded, chatroom closed. Last response received: "+response_sibl,
                user_role='system'
            )
            break
        elif "<end_chatroom>" in response_sibl:
            # 对方主动结束了对话
            response_self = llm_get(
                user_input=f"Chat terminated by {identity_sibl}",
                user_role='system'
            )
            break
        
        # 告知返回消息，获取下一轮对话内容
        response_self = llm_get(
            user_input=response_sibl,
            user_role=identity_sibl,
            tmp_prompt=f"Current round: {now_round}, maximum rounds: {max_chatsis_rounds}"
        )
        # 处理发送方（当前角色）自己结束对话的情况
        if '<end_chatroom>' in response_self:
            break



def main():
    Test_LLM_Initialize()
    asyncio.run(run_chatroom2())

if __name__ == "__main__":
    main()