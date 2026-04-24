@echo off
cmd /k "call D:\ProgramData\anaconda3\Scripts\activate.bat D:\ProgramData\anaconda3 && conda activate mylibra && python ./configs/set_global_config.py Yunru && python STT_LLM_TTS.py"