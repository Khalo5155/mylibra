import os
os.environ["PYSOUNDDEVICE_BLOCKING_INIT"] = "0"  # 禁用自动初始化
import time
import sys
import json
import asyncio
from typing import Generator

import LLM, Vdb
import TTS
from STT import microphone_to_text, microphone_to_text_baidu, baidu_speech_recognize, read_audio_to_binary
from LLM_context import get_full_context
from utils.tool_funcs import clean_pretags, clip_sentence_check, clean_alltags

from configs import global_config
IDENTITY = global_config.IDENTITY

from TTS import tts_and_play, run_async_safe
from Mcp import handle_toolcall, is_tool_call


load_context = True

def extract_emotion(s: str):
    if '开心' in s:
        return '开心'
    elif '柔和' in s:
        return '柔和'
    else:
        return '默认'


# 测试
def run_normal():
    LLM.Test_LLM_Initialize()
    rag_service = Vdb.RAGService(_vdb_path = global_config.VDB_DIR)

    while True:
        user_input = input(">>>: ")
        # user_input = microphone_to_text("en-US")
        # user_input = microphone_to_text_baidu("en")
        print(">>>: ", user_input)

        time_llmget = time.perf_counter()
        response = LLM.llm_get(user_input=user_input, user_role="Khalo", rag_service=rag_service)
        # 检查mcp
        istoolcall, mcpJsonRequest = is_tool_call(response.strip())
        if istoolcall:
            print("开始执行mcp")
            # 提取到命令，进入执行
            skill = mcpJsonRequest.get("skill", "")
            params = mcpJsonRequest.get("params", {})
            mcpJsonResponse = asyncio.run(handle_toolcall(skill, params))
            mcpResult = f"Result of toolcall: {json.dumps(mcpJsonResponse)}"
            response = LLM.llm_get(user_input=mcpResult, user_role='System', rag_service=rag_service)
        time_llmget = time.perf_counter()-time_llmget
        print("time_llmget: ", time_llmget)

        if response:
            emotion = extract_emotion(response)
            # response = Test_LLM.cmd_clean(response, "<emotion>", "</emotion>")
            print(response)
            time_tts = tts_and_play(response, IDENTITY)
            print("total time: ", float(time_llmget)+float(time_tts))
            # print("情绪：", emotion)
            # if emotion == "开心":
            #     tts_and_play(response, ref_audio_happy, prompt_text_happy, text_lang, prompt_lang)
            # elif emotion == "柔和":
            #     tts_and_play(response, ref_audio_soft, prompt_text_soft, text_lang, prompt_lang)
            # else:
            #     tts_and_play(response, ref_audio, prompt_text, text_lang, prompt_lang)

max_toolcall_count = 3 # toolcall 连续调用限制
async def handle_stream_once(user_input:str, user_role:str, llmType='deepseek'):
    try:
        # 初始化流式生成器
        # 注意：如果service.get_llm_stream本身是async函数，去掉asyncio.to_thread
        stream_generator = LLM.llm_get_stream(
            user_input=user_input, 
            user_role=user_role,
            llmType=llmType
        )
        
        # 流式接收LLM输出，逐句处理
        buffer_text = ""  # 缓存未切分的文本
        final_text = ""   # 累计最终完整文本
        stream_index = 0  # 流式消息索引（区分同批次不同分片）

        # MCP 格式检测相关
        in_capture_json = False  # 是否正在捕获工具JSON
        bracket_counter = 0      # 检测左右括号是否闭合
        toolcall_count = 0       # 连续 mcp 调用次数

        # 循环迭代流式生成器
        while True:
            # 定义内部函数：同步获取下一个分片，捕获StopIteration
            def _get_next_chunk():
                try:
                    # 尝试获取下一个分片
                    return next(stream_generator), None
                except StopIteration:
                    # 生成器迭代完毕，返回标记而非异常
                    return None, "stop"
                except Exception as e:
                    # 其他异常返回错误信息
                    return None, e
            
            # 获取分片
            chunk, err = _get_next_chunk()
            
            # 处理迭代结束/异常
            if err == "stop":
                print("流式生成器迭代完毕")
                break  # 正常退出循环
            if err is not None:
                print(f"生成器迭代异常: {str(err)}")
                break
            if chunk is None:
                break
            
            # 拼接缓存文本
            buffer_text += chunk
            final_text += chunk
            # print(f"流式接收分片: {chunk}, 缓存文本长度: {len(buffer_text)}")


            # ============================================ 解析mcp调用 ============================================
            if (not in_capture_json) and ("{" in chunk):
                toolcall_count += 1
                print("------------------------------------------------------------toolcall_count update:", toolcall_count)
                in_capture_json = True
                print("[流式MCP] 发现'{'，开始尝试解析json")
                # 如果括号前有句子，截取出去
                tmp_id = final_text.find('{')
                if tmp_id > 0:
                    final_text = final_text[tmp_id:]
                    tmp_text = final_text[:tmp_id]
                    await tts_and_play(tmp_text) # 这里有个问题，如果前面的句子太长导致已经被切分出去的话，这句代码会重复播放前面已经切分过的句子
            if in_capture_json:
                # 更新括号计数
                bracket_counter += chunk.count("{") - chunk.count("}")
                print(f"bracket_counter: {bracket_counter}")
                # 检查是否已有完整命令（括号是否闭合）
                if bracket_counter == 0:
                    # 尝试提取mcp命令
                    istoolcall, mcpJsonRequest = is_tool_call(final_text.strip())
                    mcpResult = ""
                    if istoolcall and toolcall_count <= max_toolcall_count: # 限制连续调用次数
                        print("开始执行mcp")
                        # 提取到命令，进入执行
                        skill = mcpJsonRequest.get("skill", "")
                        params = mcpJsonRequest.get("params", {})
                        mcpJsonResponse = json.loads(await handle_toolcall(skill, params))
                        mcpResult = f"Result of toolcall: {mcpJsonResponse.get('data','No response data')}"
                    elif toolcall_count > max_toolcall_count:
                        # 超过最大连续调用次数
                        print("超出最大连续调用次数限制，拒绝执行mcp")
                        mcpResult = f"Maximum toolcall round exceeded: limit {max_toolcall_count}, now {toolcall_count}. Request denied."
                    else:
                        # 括号闭合但是格式不对
                        print("格式错误，返回执行失败信息")
                        mcpResult = f"Wrong toolcall format, execution failed."
                    # 把结果发给ai，新建一个流式生成器，然后假装无事发生、进入下一个递归
                    # -- 先把上一轮生成器迭代完
                    while True:
                        chunk, err = _get_next_chunk()
                        if err == "stop":
                            break  # 正常退出循环
                        if err is not None:
                            print(f"(in toolcall) 生成器迭代异常: {str(err)}")
                            break
                        if chunk is None:
                            break
                    # 把结果发给ai（获取新的生成器）
                    stream_generator = LLM.llm_get_stream(
                        user_input=mcpResult, 
                        user_role='system',
                        llmType=llmType
                    )
                    # 重置状态
                    print("(in toolcall) Status Reset")
                    buffer_text = ""  # 缓存未切分的文本
                    final_text = ""   # 累计最终完整文本
                    stream_index = 0  # 流式消息索引（区分同批次不同分片）

                    in_capture_json = False  # 是否正在捕获工具JSON
                    bracket_counter = 0      # 检测左右括号是否闭合
                # 拦截 toolcall 命令
                continue
            # ============================================ mcp解析部分结束 ============================================
            

            # 尝试切分完整句子
            clipped_sentence = clip_sentence_check(buffer_text)
            if clipped_sentence:
                # 清理标签
                cleaned_sentence = clean_alltags(clipped_sentence)
                print(f"切分出完整句子: {cleaned_sentence}")
                
                # 生成TTS音频
                if cleaned_sentence:
                    try:
                        await tts_and_play(cleaned_sentence)
                        pass
                    except Exception as e:
                        print(f"流式TTS生成失败: {str(e)}")
                
                # 清空已处理的缓存
                buffer_text = buffer_text[len(clipped_sentence):]
                stream_index += 1

        # ========== 尾处理阶段 ==========
        # 处理剩余未切分的文本（最后一段）
        if buffer_text.strip():
            cleaned_remainder = clean_alltags(buffer_text)
            if cleaned_remainder:
                try:
                    await tts_and_play(cleaned_remainder)
                    pass
                except Exception as e:
                    print(f"流式剩余文本TTS生成失败: {str(e)}")
        else:
            pass
        
        # 无内容处理
        if not final_text:
            pass

        return final_text

    except Exception as e:
        print(f"流式消息处理错误: {str(e)}")

async def run_stream():
    LLM.Test_LLM_Initialize()

    while True:
        user_input = input(">>>: ")
        # user_input = microphone_to_text("en-US")
        # user_input = microphone_to_text_baidu("en")
        
        # print("请粘贴/输入多行文本，结束按 Ctrl+D (Linux/Mac) 或 Ctrl+Z (Windows)")
        # user_input = sys.stdin.read()  # 读取所有输入，包括换行

        full_text = await handle_stream_once(user_input=user_input, user_role="Khalo", llmType='deepseek')
        print('-'*50)
        print(IDENTITY+":", full_text)

if __name__ == '__main__':
    asyncio.run(run_stream())
    

# --------------------------
# 供 server.py 调用的专属函数
# --------------------------
class ServerFunctions:
    def __init__(self):
        self.rag_service = None
        self.nameMap = {'user':'[Client]', 'system':'[System]', 'assistant':f'[{global_config.IDENTITY}]'}
        self.llmType = 'deepseek'

    def initialize(self):
        LLM.Test_LLM_Initialize()
        self.rag_service = Vdb.RAGService(_vdb_path=global_config.VDB_DIR)
    
    def set_llm_type(self, llmType:str):
        self.llmType = llmType

    # 非流式
    def get_llm(self, user_input:str, user_role:str='Default', llmType="") -> str:
        time_llmget = time.perf_counter()
        response = LLM.llm_get(
            user_input=user_input,
            user_role=user_role,
            rag_service=self.rag_service,
            llmType=llmType if llmType else self.llmType
        )
        time_llmget = time.perf_counter()-time_llmget
        print("time_llmget: ", time_llmget)

        if response:
            print(response)
        else:
            print("No response from LLM.")
        
        return response
    
    # 流式
    def get_llm_stream(self, user_input:str, user_role:str='Default', llmType="") -> str:
        response = LLM.llm_get_stream(
            user_input=user_input,
            user_role=user_role,
            rag_service=self.rag_service,
            llmType=llmType if llmType else self.llmType
        )
        return response

    async def get_tts(self, text:str):
        time_tts = time.perf_counter()
        bytes = await TTS.server_tts(text)
        time_tts = time.perf_counter() - time_tts
        print("tts time: ", float(time_tts))
        return bytes
    
    def get_stt(self, audio_data, language="en"):
        """调用百度语音识别API"""
        try:
            result = baidu_speech_recognize(audio_data, language)
            return result
        except Exception as e:
            return f"识别失败：{str(e)}"

    def get_context(self, rounds: int=5, encrypt=True) -> list[dict]:
        ''' 返回截取的上下文。默认进行加密。 '''
        full_context = get_full_context()
        if len(full_context) < rounds*2:
            return []
        # 去掉尾部增强提示词
        full_context = full_context[:-1]
        print("get context: ", full_context[-2:])
        res = full_context[-rounds*2:]
        if not encrypt:
            res = [{'role': self.nameMap[item['role']], 'content': clean_pretags(item['content'])} for item in res]
        else:
            res = [{'role': self.nameMap[item['role']], 'content': global_config.cipher_tool.encrypt(clean_pretags(item['content']))} for item in res]
        return res