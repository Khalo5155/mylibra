import speech_recognition as sr
from pydub import AudioSegment
from aip import AipSpeech
import os

from configs import global_config
# 百度语音识别配置（需替换为你自己的API密钥）
APP_ID = global_config.BDSTT_APP_ID
API_KEY = global_config.BDSTT_API_KEY
SECRET_KEY = global_config.BDSTT_SECRET_KEY

# 初始化百度语音客户端
client = AipSpeech(APP_ID, API_KEY, SECRET_KEY)

def baidu_speech_recognize(audio_data, language="zh"):
    """调用百度语音识别API"""
    try:
        # 识别本地文件
        result = client.asr(audio_data, 'wav', 16000, {
            'dev_pid': 1537 if language == "zh" else 1737,  # 1537=中文普通话，1737=英文
        })
        if result["err_no"] == 0:
            return "".join(result["result"])
        else:
            return f"识别失败：{result['err_msg']}"
    except Exception as e:
        return f"API调用失败：{str(e)}"

def microphone_to_text_baidu(language="zh"):
    """
    麦克风实时语音转文字（百度API版，停止说话后自动结束监听）
    :param language: 识别语言（zh=中文，en=英文）
    :return: 识别后的文字
    """
    # 初始化识别器
    r = sr.Recognizer()
    
    # 调用麦克风（固定16000采样率，适配百度API要求）
    with sr.Microphone(sample_rate=16000) as source:
        print("请说话（停止说话后自动结束）...")
        # 降噪处理（校准环境噪音，关键用于后续静音判断）
        r.adjust_for_ambient_noise(source, duration=1)
        r.energy_threshold = 20
        # 存储监听的音频块
        audio_chunks = []
        # 持续监听，直到检测到静音
        while True:
            try:
                # 短超时监听（0.5秒），检测是否有语音输入
                chunk = r.listen(source, timeout=1.5, phrase_time_limit=10)
                audio_chunks.append(chunk)
            except sr.WaitTimeoutError:
                # 无语音输入时，判断是否已有有效音频块
                if audio_chunks:
                    # 有音频块则结束监听
                    break
                else:
                    # 无音频块则继续等待语音输入
                    continue

    # 无任何音频块的情况
    if not audio_chunks:
        return "未检测到语音输入"

    try:
        # 拼接所有音频块
        combined_audio = sr.AudioData(
            b''.join([chunk.get_raw_data() for chunk in audio_chunks]),
            source.SAMPLE_RATE,
            source.SAMPLE_WIDTH
        )
        print("正在识别语音...")
        # 将拼接后的音频转换为百度需要的WAV格式（16000采样率）
        wav_data = combined_audio.get_wav_data(convert_rate=16000)
        # 调用百度识别API
        result = baidu_speech_recognize(wav_data, language)
        return result
    except sr.UnknownValueError:
        return "无法识别语音内容"
    except Exception as e:
        return f"识别失败：{str(e)}"

def microphone_to_text(language="zh-CN"):
    """
    麦克风实时语音转文字（停止说话后自动结束监听）
    :param language: 识别语言
    :return: 识别后的文字
    """
    # 初始化识别器
    r = sr.Recognizer()
    # 调用麦克风
    with sr.Microphone() as source:
        print("请说话（停止说话后自动结束）...")
        # 降噪处理（校准环境噪音，关键用于后续静音判断）
        r.adjust_for_ambient_noise(source, duration=1)
        r.energy_threshold = 20
        # 存储监听的音频块
        audio_chunks = []
        # 持续监听，直到检测到静音
        while True:
            try:
                # 短超时监听（0.5秒），检测是否有语音输入
                chunk = r.listen(source, timeout=1.5, phrase_time_limit=10)
                audio_chunks.append(chunk)
            except sr.WaitTimeoutError:
                # 无语音输入时，判断是否已有有效音频块
                if audio_chunks:
                    # 有音频块则结束监听
                    break
                else:
                    # 无音频块则继续等待语音输入
                    continue

    # 无任何音频块的情况
    if not audio_chunks:
        return "未检测到语音输入"

    try:
        # 拼接所有音频块
        combined_audio = sr.AudioData(
            b''.join([chunk.get_raw_data() for chunk in audio_chunks]),
            source.SAMPLE_RATE,
            source.SAMPLE_WIDTH
        )
        print("正在识别语音...")
        text = r.recognize_google(combined_audio, language=language)
        return text
    except sr.UnknownValueError:
        return "无法识别语音内容"
    except sr.RequestError as e:
        return f"请求识别服务失败：{e}"

def read_audio_to_binary(audio_path):
    """
    读取指定路径的音频文件，转换为二进制数据供百度ASR使用
    
    Args:
        audio_path (str): 音频文件的完整路径（如：/home/user/test.wav）
    
    Returns:
        bytes: 音频文件的二进制数据；若读取失败返回None
    
    Raises:
        FileNotFoundError: 文件不存在时触发
        PermissionError: 无文件读取权限时触发
        Exception: 其他读取异常
    """
    try:
        # 以二进制只读模式打开文件（关键：'rb'模式保证读取原始二进制）
        with open(audio_path, 'rb') as audio_file:
            # 读取全部二进制内容
            audio_binary = audio_file.read()
            print(f"成功读取音频文件：{audio_path}，文件大小：{len(audio_binary)} 字节")
            return audio_binary
    
    except FileNotFoundError:
        print(f"错误：找不到音频文件 - {audio_path}")
        return None
    except PermissionError:
        print(f"错误：没有权限读取文件 - {audio_path}")
        return None
    except Exception as e:
        print(f"读取音频文件失败：{str(e)}")
        return None


if __name__ == "__main__":
    audio = read_audio_to_binary("./evil.mp3")
    if audio:
        result = baidu_speech_recognize(audio, language="en")
        print(f"识别结果：{result}")
    else:
        print("未能读取音频文件，无法进行识别。")
    exit(0)
    # 示例：麦克风语音转文字（循环执行）
    while True:
        # mic_text = microphone_to_text(language="zh-CN")
        # mic_text = microphone_to_text(language="en-GB")
        mic_text = microphone_to_text_baidu("en")
        print(f"\n麦克风识别结果：{mic_text}\n")