import os
import re
import logging
import base64
import io
import sys
import time
import json, demjson3
import asyncio
import numpy as np
import scipy.io.wavfile as wavfile
import websockets
from websockets.exceptions import ConnectionClosed
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from typing import Generator
from scipy.io import wavfile

# 获取当前脚本所在的目录
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# 导入业务逻辑模块
import STT_LLM_TTS
service = STT_LLM_TTS.ServerFunctions()
from Mcp import is_tool_call, handle_toolcall


# 配置常量
from configs import global_config
IDENTITY = global_config.IDENTITY
API_KEY = global_config.API_KEY
LOCAL_API_KEY = global_config.LOCAL_API_KEY
AES_KEY = global_config.AES_KEY
CURRENT_PORT_NUM = 5000 # 默认端口号，可以通过命令行参数覆盖



# ---------------------------------------------------------------
# --------------------------- 初始化 ---------------------------
# ---------------------------------------------------------------
# ========== 日志配置 ==========
def setup_logger():
    # 确保logs目录存在
    os.makedirs('./logs', exist_ok=True)
    
    # 定义日志格式
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)
    
    # 文件处理器（实时写入）
    file_handler = logging.FileHandler('./logs/serverlog.txt', mode='a', encoding='utf-8', delay=False)
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)
    
    # 配置根日志器
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    file_handler.flush()
    file_handler.stream.reconfigure(line_buffering=True)
    return logger

logger = setup_logger()

# ========== 网络通信配置 ===========
# 计时用
timeStamp = int(time.time())
timeInterval = 1 # 处理请求的最短间隔
def time_check(questTimeStamp: int) -> bool:
    global timeStamp
    if questTimeStamp - timeStamp < timeInterval:
        return False
    timeStamp = questTimeStamp
    return True

# 仿TCP计数（客户端用）
msgCount = -999
last_json_response = None  # 新增全局变量，保持与原逻辑一致

def msgcount_check(clientMsgCount: int) -> bool:
    # 用了websocket之后不会出现重复接收消息的情况了，直接去掉这个判断
    return True

    global msgCount
    # ai 通信的特殊标记
    if clientMsgCount == -6362:
        logger.info(f"特殊标记: client:{clientMsgCount} 白名单处理")
        return True
    if clientMsgCount == msgCount:
        logger.info(f"重复消息: client:{clientMsgCount} vs server:{msgCount}")
        return False
    else:
        msgCount = clientMsgCount
        logger.info(f"消息计数更新: {msgCount}")
        return True

# ========== 初始化加密器 ==========
cipher_tool = global_config.cipher_tool



# ---------------------------------------------------------------
# --------------------------- 工具函数 ---------------------------
# ---------------------------------------------------------------
from utils.tool_funcs import clip_sentence_check, clean_alltags

# 客户端消息解析
async def parse_message(websocket, message_data) -> str:
        # 基础验证
        if not isinstance(message_data, dict):
            await websocket.send(json.dumps({
                'type': 'server_error',
                'error': 'message format must be JSON object'
            }))
            logger.info("parse_message: message format must be JSON object")
            return ''
        
        # 频率和消息计数检查
        if not time_check(int(time.time())):
            response = last_json_response if last_json_response else {
                'type': 'server_error',
                'error': 'query too frequent'
            }
            logger.info("parse_message: query too frequent")
            await websocket.send(json.dumps(response))
            return ''
        
        # 解析客户端消息
        msg_type = message_data.get('type', 'text')
        encrypted_msg = message_data.get('message')
        client_msg_count = message_data.get('msgCount', -999)
        msg_client_role = message_data.get('role')
        if msg_client_role:
            client_role = msg_client_role
        
        if not encrypted_msg:
            await websocket.send(json.dumps({
                'type': 'server_error',
                'error': 'message token cannot be empty'
            }))
            logger.info("parse_message: message token cannot be empty")
            return ''
        
        if not msgcount_check(client_msg_count):
            response = last_json_response if last_json_response else {
                'type': 'server_error',
                'error': 'repeated message count'
            }
            await websocket.send(json.dumps(response))
            logger.info("parse_message: repeated message count")
            return ''
        
        # 解密消息
        decrypted_msg = cipher_tool.decrypt(encrypted_msg)

        return decrypted_msg




# ---------------------------------------------------------------
# --------------------------- WebSocket ---------------------------
# ---------------------------------------------------------------
# ========== WebSocket 心跳处理 ==========
async def heartbeat(websocket):
    """心跳检测（正确实现：仅发送ping，不等待pong响应）"""
    try:
        while True:
            await asyncio.sleep(20)  # 每20秒发送一次ping
            # 发送ping（无需等待pong，pong由websockets库自动处理）
            await websocket.ping()
            logger.debug("发送心跳ping")
    except ConnectionClosed:
        # 连接已关闭，正常退出
        raise
    except Exception as e:
        logger.error(f"心跳检测异常: {str(e)}", exc_info=True)
        raise

# ========== WebSocket 普通消息处理（TTS） ==========
async def handle_client_message(websocket, message_data, client_role):
    """处理单条客户端消息"""
    global last_json_response, msgCount
    try:
        # 解析消息
        decrypted_msg = await parse_message(websocket, message_data)
        if not decrypted_msg:
            logger.info(f"WebSocket消息识别错误 (角色: {client_role}): {decrypted_msg}")
            return
        logger.info(f"WebSocket收到消息 (角色: {client_role}): {decrypted_msg}")
        
        # 执行业务逻辑 (LLM + TTS) - 同步转异步
        raw_response_text = await asyncio.to_thread(
            service.get_llm,
            user_input=decrypted_msg,
            user_role=client_role
        )
        # 清理response
        raw_response_text = clean_alltags(raw_response_text)

        if raw_response_text:
            # 生成TTS音频并加密
            audio_base64 = ""
            try:
                # 同步TTS逻辑转异步执行
                audio_data, sample_rate = await service.get_tts(raw_response_text)
                
                if audio_data is not None and len(audio_data) > 0:
                    audio_data = np.array(audio_data)
                    audio_data = np.nan_to_num(audio_data)
                    max_val = np.max(np.abs(audio_data))
                    if max_val > 0:
                        audio_data = audio_data / max_val
                    audio_int16 = (audio_data * 32767).astype(np.int16)
                    
                    with io.BytesIO() as byte_io:
                        wavfile.write(byte_io, sample_rate, audio_int16)
                        wav_bytes = byte_io.getvalue()
                        audio_base64 = cipher_tool.encrypt_binary(wav_bytes)
                    
                    logger.info(f"WebSocket TTS音频加密完成，Base64长度: {len(audio_base64)}")
            except Exception as e:
                logger.error(f"WebSocket TTS生成失败: {str(e)}", exc_info=True)
        else:
            # llm没有回复
            raw_response_text = "Server: No response from llm."
        
        # 构造响应消息
        response_data = {
            'type': 'server_response',
            'status': 'success',
            'response': cipher_tool.encrypt(raw_response_text),
            'role': IDENTITY,
            'audio': audio_base64,
            'context': service.get_context(),
            'msgCount': msgCount
        }
        last_json_response = response_data
        
        # 发送响应给客户端
        await websocket.send(json.dumps(response_data))
            
    except Exception as e:
        logger.error(f"WebSocket消息处理错误: {str(e)}", exc_info=True)
        await websocket.send(json.dumps({
            'type': 'server_error',
            'error': '内部服务器错误',
            'details': str(e)
        }))

# ========== WebSocket 流式消息处理（TTS） ==========
max_toolcall_count = 1 # toolcall 连续调用限制
# 端口转发专用的流式处理函数（连接另一个端口，接收分片，执行TTS并发送）
async def handle_client_message_stream_forward(websocket, message_data, client_role, target_port):
    """处理端口转发专用的流式响应：连接目标端口，接收分片，执行TTS并发送"""
    global last_json_response, msgCount
    logger.info(f"开始处理端口转发流式请求: 当前端口 {CURRENT_PORT_NUM} -> 目标端口 {target_port} (角色: {client_role})")
    try:
        # 解析原始消息（复用原有逻辑）
        decrypted_msg = await parse_message(websocket, message_data)
        if not decrypted_msg:
            logger.error(f"转发消息解析失败 (角色: {client_role})")
            return
        logger.info(f"转发请求到端口 {target_port} (角色: {client_role}): {decrypted_msg}")

        # 连接到目标端口的WebSocket
        target_uri = f"ws://localhost:{target_port}/ws/llm-tts?api_key={API_KEY}&client_role={client_role}"
        async with websockets.connect(target_uri) as target_ws:
            # 发送原始请求到目标端口（假设目标端口支持相同消息格式）
            await target_ws.send(json.dumps(message_data))

            # 接收目标端口的流式响应
            stream_index = 0
            while True:
                try:
                    response_str = await asyncio.wait_for(target_ws.recv(), timeout=20)
                    response_data = json.loads(response_str)
                    if response_data.get("onconnect", False):
                        # 跳过响应信息
                        continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"目标端口 {target_port} 连接已关闭")
                    break
                except asyncio.TimeoutError:
                    logger.error(f"接收目标端口响应超时: {target_port}")
                    break
                except Exception as e:
                    logger.error(f"接收目标端口响应失败: {str(e)}")
                    break
                except json.JSONDecodeError:
                    return "fail to decode json response."

                # 发送给原始客户端
                await websocket.send(json.dumps(response_data))
                stream_index += 1

                # 如果是最终分片，结束
                if response_data.get('is_final', False):
                    last_json_response = response_data
                    logger.info(f"转发最终分片 {stream_index-1} 发送完成")
                    break

    except Exception as e:
        logger.error(f"端口转发处理错误: {str(e)}")
        await websocket.send(json.dumps({
            'type': 'server_error',
            'error': '端口转发失败',
            'details': str(e)
        }))
# 流式处理主函数（包含mcp解析和TTS生成，适用于本地处理）
async def handle_client_message_stream(websocket, message_data, client_role):
    """处理客户端流式消息请求，逐句生成+TTS+发送"""
    global last_json_response, msgCount
    try:
        # 检查是否需要转发
        target_port = message_data.get('targetPort', '')
        if target_port and isinstance(target_port, int) and target_port != CURRENT_PORT_NUM:
            logger.info(f"检测到端口转发请求: 当前端口 {CURRENT_PORT_NUM} -> 目标端口 {target_port}")
            await handle_client_message_stream_forward(websocket, message_data, client_role, target_port)
            return  # 转发完成后退出，不执行原有逻辑

        # 解析消息文本内容
        decrypted_msg = await parse_message(websocket, message_data)
        logger.info(f"WebSocket流式收到消息 (角色: {client_role}): {decrypted_msg}")

        # 初始化流式生成器
        # 注意：如果service.get_llm_stream本身是async函数，去掉asyncio.to_thread
        stream_generator: Generator = await asyncio.to_thread(
            service.get_llm_stream,
            user_input=decrypted_msg,
            user_role=client_role
        )
        
        # 流式接收LLM输出，逐句处理
        buffer_text = ""  # 缓存未切分的文本
        final_text:str = ""   # 累计最终完整文本
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
            
            # 异步执行获取分片（避免阻塞事件循环）
            chunk, err = await asyncio.to_thread(_get_next_chunk)
            
            # 处理迭代结束/异常
            if err == "stop":
                logger.info("流式生成器迭代完毕")
                break  # 正常退出循环
            if err is not None:
                logger.error(f"生成器迭代异常: {str(err)}", exc_info=True)
                break
            if chunk is None:
                break
            
            # 拼接缓存文本
            buffer_text += chunk
            final_text += chunk
            # logger.info(f"流式接收分片: {chunk}, 缓存文本长度: {len(buffer_text)}")


            # ============================================ 解析mcp调用 ============================================
            if (not in_capture_json) and ("{" in chunk):
                toolcall_count += 1
                print("------------------------------------------------------------toolcall_count update:", toolcall_count)
                in_capture_json = True
                logger.info("[流式MCP] 发现'{'，开始尝试解析json")
                # 如果括号前有句子，截取出来直接发送切片
                tmp_id = final_text.find('{')
                if tmp_id > 0:
                    tmp_text = final_text[:tmp_id]
                    try:
                        audio_data = await service.get_tts(tmp_text)
                        
                        if audio_data is not None and len(audio_data) > 0:
                            audio_base64 = cipher_tool.encrypt_binary(audio_data) if cipher_tool else ""
                            
                            logger.info(f"流式TTS生成完成，句子: {tmp_text[:20]}..., Base64长度: {len(audio_base64)}")
                    except Exception as e:
                        logger.error(f"流式TTS生成失败: {str(e)}", exc_info=True)
                    # 构造并发送流式响应
                    response_data = {
                        'type': 'server_stream_response',
                        'status': 'streaming',
                        'stream_index': stream_index,
                        'is_final': False,
                        'response': cipher_tool.encrypt(cleaned_sentence) if cipher_tool else cleaned_sentence,
                        'full_response': cipher_tool.encrypt(final_text) if cipher_tool else final_text,
                        'role': IDENTITY,
                        'audio': audio_base64,
                        'context': service.get_context() if service else "",
                        'msgCount': msgCount
                    }
                    # 发送
                    await websocket.send(json.dumps(response_data))
                    logger.info(f"流式分片 {stream_index} 发送完成")
                    stream_index += 1

            if in_capture_json:
                # 更新括号计数
                bracket_counter += chunk.count("{") - chunk.count("}")
                logger.info(f"bracket_counter: {bracket_counter}")
                # 检查是否已有完整命令（括号是否闭合）
                if bracket_counter == 0:
                    # 尝试提取mcp命令
                    istoolcall, mcpJsonRequest = is_tool_call(final_text.strip())
                    mcpResult = ""
                    if istoolcall and toolcall_count <= max_toolcall_count: # 限制连续调用次数
                        logger.info("开始执行mcp")
                        # 提取到命令，进入执行
                        skill = mcpJsonRequest.get("skill", "")
                        params = mcpJsonRequest.get("params", {})
                        mcpJsonResponse = json.loads(await handle_toolcall(skill, params))
                        mcpResult = f"Result of toolcall: {mcpJsonResponse.get('data','No response data')}"
                    elif toolcall_count > max_toolcall_count:
                        # 超过最大连续调用次数
                        logger.info("超出最大连续调用次数限制，拒绝执行mcp")
                        mcpResult = f"Maximum toolcall round exceeded: limit {max_toolcall_count}, now {toolcall_count}. Request denied."
                    else:
                        # 括号闭合但是格式不对
                        logger.info("格式错误，返回执行失败信息")
                        mcpResult = f"Wrong toolcall format, execution failed."
                    # 把结果发给ai，新建一个流式生成器，然后假装无事发生、进入下一个递归
                    # -- 先把上一轮生成器迭代完
                    while True:
                        chunk, err = await asyncio.to_thread(_get_next_chunk)
                        if err == "stop":
                            break  # 正常退出循环
                        if err is not None:
                            logger.error(f"(in toolcall) 生成器迭代异常: {str(err)}", exc_info=True)
                            break
                        if chunk is None:
                            break
                    # 把结果发给ai（获取新的生成器）
                    stream_generator: Generator = await asyncio.to_thread(
                        service.get_llm_stream,
                        user_input=mcpResult,
                        user_role="system"
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
            clipped_sentence = clip_sentence_check(buffer_text, split_length=50)
            while clipped_sentence:
                # 清理标签
                cleaned_sentence = clean_alltags(clipped_sentence)
                logger.info(f"切分出完整句子: {cleaned_sentence}")
                
                # 生成TTS音频（同原有逻辑）
                audio_base64 = ""
                if cleaned_sentence:
                    try:
                        audio_data = await service.get_tts(cleaned_sentence)
                        
                        if audio_data is not None and len(audio_data) > 0:
                            audio_base64 = cipher_tool.encrypt_binary(audio_data) if cipher_tool else ""
                            
                            logger.info(f"流式TTS生成完成，句子: {cleaned_sentence[:20]}..., Base64长度: {len(audio_base64)}")
                    except Exception as e:
                        logger.error(f"流式TTS生成失败: {str(e)}", exc_info=True)
                
                # 构造并发送流式响应（同原有逻辑）
                response_data = {
                    'type': 'server_stream_response',
                    'status': 'streaming',
                    'stream_index': stream_index,
                    'is_final': False,
                    'response': cipher_tool.encrypt(cleaned_sentence) if cipher_tool else cleaned_sentence,
                    'full_response': cipher_tool.encrypt(final_text) if cipher_tool else final_text,
                    'role': IDENTITY,
                    'audio': audio_base64,
                    'context': service.get_context() if service else "",
                    'msgCount': msgCount
                }
                # 发送
                await websocket.send(json.dumps(response_data))
                clip_last_sent = time.perf_counter()
                logger.info(f"流式分片 {stream_index} 发送完成")
                stream_index += 1
                
                # 清空已处理的缓存
                buffer_text = buffer_text[len(clipped_sentence):]

                # 检查还有没有下一句
                clipped_sentence = clip_sentence_check(buffer_text)

        # ========== 尾处理阶段 ==========
        # 处理剩余未切分的文本（最后一段）
        if buffer_text.strip():
            cleaned_remainder = clean_alltags(buffer_text)
            audio_base64 = ""
            try:
                audio_data = await service.get_tts(cleaned_remainder)
                
                if audio_data is not None and len(audio_data) > 0:
                    audio_base64 = cipher_tool.encrypt_binary(audio_data) if cipher_tool else ""
            except Exception as e:
                logger.error(f"流式剩余文本TTS生成失败: {str(e)}", exc_info=True)
            
            # 发送最终分片
            clist = service.get_context()
            final_response = {
                'type': 'server_stream_response',
                'status': 'completed',
                'stream_index': stream_index,
                'is_final': True,                    # 标记最终分片
                'response': cipher_tool.encrypt(cleaned_remainder),
                'full_response': cipher_tool.encrypt(final_text),
                'role': IDENTITY,
                'audio': audio_base64,
                'context': clist,
                'msgCount': msgCount
            }
            # 限制最短发送间隔，防止客户端接收乱序
            # time_interval = time.perf_counter() - clip_last_sent
            # if time_interval < clip_send_interval:
            #     time.sleep(clip_send_interval - time_interval)
            # 发送最后的音频
            await websocket.send(json.dumps(final_response))
            last_json_response = final_response
            logger.info(f"流式最终分片 {stream_index} 发送完成，完整文本: {final_text[:50]}...")
            print("Final Clip -- context_list[-2:]:", clist[-2:])
        else:
            # 发送标记Final Clip的空响应
            clist = service.get_context()
            end_response = {
                'type': 'server_stream_response',
                'status': 'completed',
                'stream_index': stream_index,
                'is_final': True,
                'response': cipher_tool.encrypt("[final clip]"),
                'full_response': cipher_tool.encrypt(final_text),
                'role': IDENTITY,
                'audio': "",
                'context': clist,
                'msgCount': msgCount
            }
            await websocket.send(json.dumps(end_response))
            last_json_response = end_response
            logger.info(f"流式 Final Clip 空响应分片 {stream_index} 发送完成，完整文本: {final_text[:50]}...")
            print("Final Clip -- context_list[-2:]:", clist[-2:])
        
        # 无内容处理
        if not final_text:
            empty_response = {
                'type': 'server_stream_response',
                'status': 'completed',
                'is_final': True,
                'response': cipher_tool.encrypt("Server: No response from llm."),
                'full_response': cipher_tool.encrypt("Server: No response from llm."),
                'role': IDENTITY,
                'audio': "",
                'context': service.get_context(),
                'msgCount': msgCount
            }
            await websocket.send(json.dumps(empty_response))
            last_json_response = empty_response
            logger.info(f"流式 无响应分片 {stream_index} 发送完成，完整文本: {final_text[:50]}...")
            print("Empty Clip -- context_list[-2:]:", clist[-2:])

    except Exception as e:
        logger.error(f"WebSocket流式消息处理错误: {str(e)}", exc_info=True)
        await websocket.send(json.dumps({
            'type': 'server_error',
            'error': '内部服务器错误',
            'details': str(e)
        }))

# ========== WebSocket 普通消息处理（纯文本） ==========
# 端口转发专用的处理函数（连接另一个端口，接收并转发返回结果）
async def handle_client_message_text_forward(websocket, message_data, client_role, target_port):
    """处理单条客户端消息"""
    global last_json_response, msgCount
    logger.info(f"开始处理端口转发请求: 当前端口 {CURRENT_PORT_NUM} -> 目标端口 {target_port} (角色: {client_role})")
    try:
        # 解析原始消息（复用原有逻辑）
        decrypted_msg = await parse_message(websocket, message_data)
        if not decrypted_msg:
            logger.error(f"转发消息解析失败 (角色: {client_role})")
            return
        logger.info(f"转发请求到端口 {target_port} (角色: {client_role}): {decrypted_msg}")

        # 连接到目标端口的WebSocket
        target_uri = f"ws://localhost:{target_port}/ws/llm-tts?api_key={API_KEY}&client_role={client_role}"
        async with websockets.connect(target_uri) as target_ws:
            # 发送原始请求到目标端口（假设目标端口支持相同消息格式）
            await target_ws.send(json.dumps(message_data))

            # 接收目标端口的响应
            while True:
                try:
                    response_str = await asyncio.wait_for(target_ws.recv(), timeout=20)
                    response_data = json.loads(response_str)
                    if response_data.get("onconnect", False):
                        # 跳过响应信息
                        continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"目标端口 {target_port} 连接已关闭")
                    break
                except asyncio.TimeoutError:
                    logger.error(f"接收目标端口响应超时: {target_port}")
                    break
                except Exception as e:
                    logger.error(f"接收目标端口响应失败: {str(e)}")
                    break
                except json.JSONDecodeError:
                    return "fail to decode json response."

                # 发送给原始客户端
                await websocket.send(json.dumps(response_data))
                logger.info(f"转发完成")
                break

    except Exception as e:
        logger.error(f"端口转发处理错误: {str(e)}")
        await websocket.send(json.dumps({
            'type': 'server_error',
            'error': '端口转发失败',
            'details': str(e)
        }))
# 主函数
async def handle_client_message_text(websocket, message_data, client_role):
    """处理单条客户端消息"""
    global last_json_response, msgCount
    try:
        # 检查是否需要转发
        target_port = message_data.get('targetPort', '')
        if target_port and isinstance(target_port, int) and target_port != CURRENT_PORT_NUM:
            logger.info(f"检测到端口转发请求: 当前端口 {CURRENT_PORT_NUM} -> 目标端口 {target_port}")
            await handle_client_message_text_forward(websocket, message_data, client_role, target_port)
            return  # 转发完成后退出，不执行原有逻辑

        # 解析消息
        decrypted_msg = await parse_message(websocket, message_data)
        if not decrypted_msg:
            logger.info(f"WebSocket消息识别错误 (角色: {client_role}): {decrypted_msg}")
            return
        logger.info(f"WebSocket收到消息 (角色: {client_role}): {decrypted_msg}")
        
        # 获取文本回复
        raw_response_text = await asyncio.to_thread(
            service.get_llm,
            user_input=decrypted_msg,
            user_role=client_role
        )
        # # 清理response
        # raw_response_text = clean_alltags(raw_response_text)
        
        if not raw_response_text:
            # llm没有回复
            raw_response_text = "Server: No response from llm."
        
        # 构造响应消息
        response_data = {
            'type': 'server_response',
            'status': 'success',
            'response': cipher_tool.encrypt(raw_response_text),
            'role': IDENTITY,
            # 'context': service.get_context(),
            'msgCount': msgCount
        }
        last_json_response = response_data
        
        # 发送响应给客户端
        await websocket.send(json.dumps(response_data))
            
    except Exception as e:
        logger.error(f"WebSocket消息处理错误: {str(e)}", exc_info=True)
        await websocket.send(json.dumps({
            'type': 'server_error',
            'error': '内部服务器错误',
            'details': str(e)
        }))

# ========== WebSocket 连接处理 ==========
async def handle_websocket_connection(websocket, path=''):
    """处理单个WebSocket连接的生命周期（完整稳定版）"""
    heartbeat_task = None
    try:
        # 1. 解析路径和查询参数
        from urllib.parse import urlparse, parse_qs, unquote
        if not path:
            path = websocket.request.path
        parsed_path = urlparse(f"http://localhost{path}")
        pure_path = parsed_path.path
        query_params = parse_qs(parsed_path.query)
        
        # 2. 验证路径
        if pure_path != "/ws/llm-tts":
            logger.warning(f"WebSocket路径不匹配: 实际={pure_path}, 预期=/ws/llm-tts")
            await websocket.close(code=1008, reason="路径不匹配")
            return
        
        # 3. 解析API Key和角色（在url中）
        auth_key = query_params.get('api_key', [None])[0]
        client_role = query_params.get('client_role', ['Unknown'])[0]
        if auth_key: auth_key = unquote(auth_key)
        if client_role: client_role = unquote(client_role)
        
        # 降级到请求头
        if not auth_key:
            auth_key = websocket.request_headers.get('X-API-Key') or websocket.request_headers.get('x-api-key')
        if not client_role:
            client_role = websocket.request_headers.get('client-role') or 'Unknown'
        
        # 4. 认证
        if auth_key != API_KEY:
            logger.warning(f"API Key认证失败: 收到={str(auth_key)}")
            await websocket.close(code=1008, reason="API Key错误")
            return
        
        logger.info(f"WebSocket客户端已连接 - 角色: {client_role}, 路径: {pure_path}, 认证方式: {'URL参数' if query_params.get('api_key') else '请求头'}")
        
        # 5. 发送连接成功消息
        await websocket.send(json.dumps({
            'type': 'server_message',
            'status': 'connected',
            'onconnect': True, # 标记这条消息为连接成功的响应消息
            'message': 'WebSocket连接成功',
            'context': service.get_context(), # 顺带发送上下文
            'role': IDENTITY # 标记当前角色身份
        }))
        
        # 6. 启动心跳（修复后的心跳逻辑）
        heartbeat_task = asyncio.create_task(heartbeat(websocket))
        
        # 7. 处理消息
        while True:
            try:
                # 修改点1-1：使用 recv() 替代 async for，更好地控制异常
                message = await websocket.recv()
            except ConnectionClosed as e:
                # 修改点1-2：在消息接收层面就捕获 ConnectionClosed
                logger.info(f"消息接收时检测到连接关闭 - 代码: {e.code}, 原因: {e.reason or '无'}")
                break  # 跳出循环，让外层的 except 处理
            
            # 修改点1-3：消息解析和处理的异常隔离
            try:
                message_data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    'type': 'server_error',
                    'error': '消息必须是合法JSON'
                }))
                continue
            # 判断是否为纯文本请求
            text_only = message_data.get('textonly', False)
            if text_only:
                logger.info("Got text_only request.")
                await handle_client_message_text(websocket, message_data, client_role)
            # 判断是否为流式请求
            elif message_data.get('mode', 'normal') == 'stream':
                logger.info("Got stream tts request.")
                await handle_client_message_stream(websocket, message_data, client_role)
            else:
                logger.info("Got normal tts request. (非流式先直接不要tts了，改成纯文本)")
                # await handle_client_message(websocket, message_data, client_role)
                await handle_client_message_text(websocket, message_data, client_role)

    except ConnectionClosed as e:
        logger.info(f"WebSocket客户端断开 - 代码: {e.code}, 原因: {e.reason or '无'}")
    except Exception as e:
        logger.error(f"WebSocket连接异常: {str(e)}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="服务器内部错误")
        except:
            pass
    finally:
        # 断开时告诉ai
        # service.get_llm("Connection logged out", "system")
        # 安全取消心跳任务
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                logger.debug("心跳任务已取消")
            except Exception as e:
                logger.error(f"心跳任务清理失败: {str(e)}")




# ---------------------------------------------------------------
# --------------------------- 服务启动 ---------------------------
# ---------------------------------------------------------------
async def main(port_num:int=5000):
    """启动纯 WebSocket 服务"""
    # 初始化业务服务
    service.initialize()
    
    # 配置服务地址和端口
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', port_num))
    global CURRENT_PORT_NUM
    CURRENT_PORT_NUM = port_num # 更新全局端口号
    
    # 启动服务（添加路径匹配支持）
    logger.info(f"WebSocket服务启动中 - {host}:{port} (路径: /ws/llm-tts)")
    async with websockets.serve(
        handle_websocket_connection,  # handler 现在接收 (websocket, path) 参数
        host=host,
        port=port,
        max_size=10*1024*1024  # 10MB最大消息大小
    ):
        await asyncio.Future()  # 保持服务运行

if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            port_arg = int(sys.argv[1])
            logger.info(f"从命令行参数获取端口号: {port_arg}")
        except ValueError:
            logger.warning(f"无效的端口参数 '{sys.argv[1]}', 使用默认端口 5000")
            port_arg = 5000
    if len(sys.argv) > 2:
        try:
            llm_type = str(sys.argv[2]).lower()
            if llm_type in ['deepseek', 'doubao', 'gmn']:
                service.set_llm_type(llm_type)
                logger.info(f"从命令行参数获取LLM类型: {llm_type}")
            else:
                logger.warning(f"无效的LLM类型参数 '{sys.argv[2]}', 使用默认类型 deepseek")
                llm_type = 'deepseek'
        except ValueError:
            logger.warning(f"无效的LLM类型参数 '{sys.argv[2]}', 使用默认类型 deepseek")
            llm_type = 'deepseek'
    # 适配Windows系统的asyncio事件循环
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 启动服务
    asyncio.run(main(port_arg))