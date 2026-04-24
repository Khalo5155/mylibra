import asyncio
import websockets
import json
import pyaudio
import wave
import io
import time
from threading import Lock

from configs import global_config
IDENTITY = global_config.IDENTITY
# IDENTITY = "Evil"
tts_speakers = global_config.tts_speakers

# 修复：客户端不能用0.0.0.0，改用127.0.0.1（本地测试）
SERVER_URL = "ws://127.0.0.1:8000/ws/tts"

# 全局变量：保存持久化的websocket连接和锁（保证线程安全）
g_websocket = None
g_ws_lock = Lock()
g_event_loop = None
g_loop_lock = Lock() # 循环操作锁

# 默认参数
# 注意，现在TTS服务是分离开的，相对地址以TTS服务端目录为准
aux_ref_audio_paths = []




# 新增：同步调用异步函数的安全封装（替代 asyncio.run）
def run_async_safe(coro):
    """安全执行异步函数（复用全局循环，不关闭）"""
    loop = get_or_create_event_loop()
    # 使用 loop.create_task + loop.run_until_complete（不关闭循环）
    task = loop.create_task(coro)
    return loop.run_until_complete(task)


# 事件循环管理函数
def get_or_create_event_loop():
    """获取/创建全局事件循环（保证循环未关闭）"""
    global g_event_loop
    with g_loop_lock:
        # 检查循环是否存在/是否已关闭
        if g_event_loop is None or g_event_loop.is_closed():
            # Windows 兼容：强制使用 Selector 策略（避免 Proactor 问题）
            if asyncio.get_event_loop_policy().__class__.__name__ == "WindowsProactorEventLoopPolicy":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            g_event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(g_event_loop)
        return g_event_loop



async def is_websocket_closed(ws):
    if ws is None:
        return True
    return ws.state == websockets.State.CLOSED

async def init_websocket_connection():
    """初始化/复用 WebSocket 连接（带循环检查）"""
    global g_websocket
    get_or_create_event_loop()  # 确保循环可用
    if await is_websocket_closed(g_websocket):
        if g_websocket is not None:
            try:
                await g_websocket.close()
            except:
                pass
        # 新建连接时绑定当前可用的循环
        g_websocket = await websockets.connect(SERVER_URL)
        print("成功建立持久化WebSocket连接:", g_websocket.remote_address)

async def send_tts_request(text, speaker=IDENTITY, retry_count=0):
    """发送TTS请求（修复循环关闭问题）"""
    global g_websocket
    # 限制最大重试次数（避免无限循环）
    MAX_RETRY = 3
    if retry_count >= MAX_RETRY:
        print(f"已重试{MAX_RETRY}次，仍失败，停止重试")
        return None
    # 前置检查：确保循环和连接都可用
    loop = get_or_create_event_loop()
    await init_websocket_connection()
    
    # 构造参数（原有逻辑不变）
    tts_params = {
        "text": text,
        "ref_audio": tts_speakers[speaker]["ref_audio"],
        "prompt_text": tts_speakers[speaker]["prompt_text"],
        "aux_ref_audio_paths": tts_speakers[speaker]["aux_ref_audio_paths"],
        "text_lang": tts_speakers[speaker]["text_lang"],
        "prompt_lang": tts_speakers[speaker]["prompt_lang"],
        "gpt_path": tts_speakers[speaker]["gpt_path"],
        "sovits_path": tts_speakers[speaker]["sovits_path"]
    }
    
    try:
        request_data = json.dumps(tts_params)
        await g_websocket.send(request_data)
        print(f"已发送TTS请求（文本：{text[:20]}...），等待响应...")
        
        t_start = time.perf_counter()
        response = await g_websocket.recv()
        t_cost = time.perf_counter() - t_start
        
        if isinstance(response, str):
            try:
                error_info = json.loads(response)
                print(f"服务端返回错误: {error_info}")
                return None
            except json.JSONDecodeError:
                print(f"服务端返回文本: {response}")
                return None
        elif isinstance(response, bytes):
            print(f"成功接收音频数据（大小：{len(response)}字节，耗时：{t_cost:.2f}秒）")
            return response
        else:
            print(f"未知响应类型: {type(response)}")
            return None
    except websockets.exceptions.ConnectionClosed as e:
        # 打印连接关闭的详细原因（核心！）
        print(f"连接已关闭（代码：{e.code}，原因：{e.reason}），第{retry_count+1}次重试")
        g_websocket = None
        # 重试时递增计数
        return await send_tts_request(text, speaker, retry_count + 1)
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            print("事件循环已关闭，重建循环并重试")
            g_event_loop = None  # 标记循环失效
            get_or_create_event_loop()  # 重建循环
            return await send_tts_request(text, speaker)
    except Exception as e:
        print(f"发送TTS请求失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

async def _async_close_websocket():
    global g_websocket
    if not await is_websocket_closed(g_websocket):
        try:
            await g_websocket.close()
            print("WebSocket 连接已关闭")
        except Exception as e:
            print(f"关闭WebSocket失败: {e}")

def close_websocket():
    """关闭 WebSocket 连接（同步调用）"""
    global g_websocket
    if g_websocket is not None:
        # 异步关闭需要在事件循环中执行
        g_event_loop.run_until_complete(_async_close_websocket())
        g_websocket = None



def play_audio(audio_data: bytes):
    """
    播放WAV格式的音频二进制数据
    """
    try:
        if not audio_data:
            print("错误：音频数据为空")
            return
        
        # 使用pyaudio播放音频
        p = pyaudio.PyAudio()
        
        # 先从二进制数据读取WAV信息
        with wave.open(io.BytesIO(audio_data), 'rb') as wf:
            # 打开音频流
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )
            
            # 分块播放音频
            chunk = 1024
            data = wf.readframes(chunk)
            while data:
                stream.write(data)
                data = wf.readframes(chunk)
            
            # 清理资源
            stream.stop_stream()
            stream.close()
            p.terminate()
        print("音频播放完成！")
    except Exception as e:
        print(f"音频播放失败: {str(e)}")
        import traceback
        traceback.print_exc()

async def get_tts(text, speaker=IDENTITY):
    """获取TTS音频数据（保证循环不被关闭）"""
    loop = get_or_create_event_loop()
    audio_data = await send_tts_request(text, speaker)
    return audio_data

async def server_tts(text, speaker=IDENTITY):
    """
    封装接口：仅传入文本，使用全局默认参数
    """
    response = await get_tts(text, speaker)
    return response

async def tts_and_play(text, speaker=IDENTITY) -> float:
    t0 = time.perf_counter()
    """
    合成语音并播放，返回耗时
    """
    audio_bytes = await get_tts(text, speaker)
    t1 = time.perf_counter()
    if audio_bytes:
        play_audio(audio_bytes)
    else:
        print("未获取到有效音频数据，播放失败")
    return t1-t0

# 测试
if __name__ == "__main__":
    loop = get_or_create_event_loop()
    while True:
        text = input(">>>")
        # 用安全封装替代 asyncio.run
        audio_data = run_async_safe(server_tts(text))
        if audio_data is not None and len(audio_data) > 0:
            play_audio(audio_data)