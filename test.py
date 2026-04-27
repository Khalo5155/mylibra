import base64
import binascii
import tempfile
import os
import wave
import numpy as np

def read_audio_from_txt(txt_file_path):
    """
    从txt文件中读取音频数据
    支持格式：
    1. 纯Base64编码的WAV数据
    2. 纯十六进制字符串（去掉空格和换行）
    3. 混合格式（如"UklGR..."这样的文本表示）
    """
    with open(txt_file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    
    # 移除所有空白字符（空格、换行、制表符）
    content = ''.join(content.split())
    
    # 方法1：尝试作为Base64解码
    try:
        audio_data = base64.b64decode(content)
        # 验证是否是有效的WAV文件（检查RIFF头）
        if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
            print("✓ 成功解码为Base64格式的WAV数据")
            return audio_data
    except:
        pass
    
    # 方法2：尝试作为十六进制字符串解码
    try:
        audio_data = binascii.unhexlify(content)
        if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
            print("✓ 成功解码为十六进制格式的WAV数据")
            return audio_data
    except:
        pass
    
    # 方法3：如果文本包含"UklGR"这样的WAV文本表示（可能是调试输出）
    if 'UklGR' in content or 'RIFF' in content:
        # 尝试提取十六进制部分（假设是连续的十六进制字符）
        hex_chars = ''.join([c for c in content if c in '0123456789abcdefABCDEF'])
        if len(hex_chars) > 0:
            try:
                audio_data = binascii.unhexlify(hex_chars)
                if audio_data[:4] == b'RIFF' or audio_data[:4] == b'RIFF':
                    print("✓ 成功从文本表示中提取并解码WAV数据")
                    return audio_data
            except:
                pass
    
    raise ValueError("无法识别的音频数据格式。请确保txt文件包含Base64或十六进制编码的WAV数据")

def play_wav_data(audio_data):
    """
    播放WAV音频数据
    需要安装：pip install simpleaudio
    """
    try:
        import simpleaudio as sa
        
        # 将音频数据保存到临时文件（供调试使用）
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmpfile:
            tmpfile.write(audio_data)
            tmp_path = tmpfile.name
        
        print(f"临时文件已保存: {tmp_path}")
        
        # 使用simpleaudio播放
        play_obj = sa.play_buffer(audio_data, 1, 2, 44100)  # 参数可能需要调整
        # 实际上应该从WAV头部读取参数，但为了简化，先这样
        
        print("正在播放音频...")
        play_obj.wait_done()
        print("播放完成")
        
        # 清理临时文件
        os.unlink(tmp_path)
        
    except ImportError:
        print("未安装simpleaudio，尝试使用pydub播放...")
        try:
            from pydub import AudioSegment
            from pydub.playback import play
            
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmpfile:
                tmpfile.write(audio_data)
                tmp_path = tmpfile.name
            
            # 加载并播放
            audio = AudioSegment.from_wav(tmp_path)
            print("正在播放音频...")
            play(audio)
            print("播放完成")
            
            # 清理临时文件
            os.unlink(tmp_path)
            
        except ImportError:
            print("请安装播放库：pip install simpleaudio 或 pip install pydub")
            # 保存到文件供手动播放
            output_file = "output_audio.wav"
            with open(output_file, 'wb') as f:
                f.write(audio_data)
            print(f"音频数据已保存到 {output_file}，请用播放器手动打开")

def get_wav_info(audio_data):
    """
    解析WAV文件信息
    """
    import struct
    
    # 检查RIFF头
    if audio_data[:4] != b'RIFF':
        print("警告：这不是有效的WAV文件")
        return
    
    # 解析基本信息
    sample_rate = struct.unpack('<I', audio_data[24:28])[0]
    num_channels = struct.unpack('<H', audio_data[22:24])[0]
    bits_per_sample = struct.unpack('<H', audio_data[34:36])[0]
    byte_rate = struct.unpack('<I', audio_data[28:32])[0]
    block_align = struct.unpack('<H', audio_data[32:34])[0]
    
    print("\n=== WAV文件信息 ===")
    print(f"采样率: {sample_rate} Hz")
    print(f"声道数: {num_channels}")
    print(f"位深度: {bits_per_sample} bit")
    print(f"比特率: {byte_rate * 8 / 1000:.1f} kbps")
    print(f"数据大小: {len(audio_data)} 字节")
    print("==================\n")

def main():
    # 使用方法：将txt文件路径作为参数，或直接修改变量
    import sys
    
    if len(sys.argv) > 1:
        txt_file = sys.argv[1]
    else:
        # 请修改为你的txt文件路径
        txt_file = "audio_data.txt"  # 👈 修改这里
    
    if not os.path.exists(txt_file):
        print(f"错误：文件 {txt_file} 不存在")
        print("使用方法：python play_audio.py <txt文件路径>")
        return
    
    try:
        # 读取音频数据
        audio_data = read_audio_from_txt(txt_file)
        print(f"成功读取 {len(audio_data)} 字节音频数据")
        
        # 显示WAV信息
        get_wav_info(audio_data)
        
        # 播放音频
        play_wav_data(audio_data)
        
    except Exception as e:
        print(f"错误：{e}")

if __name__ == "__main__":
    main()