@echo off
cd /d "D:\Games\mylibra"
cmd /k "call D:\ProgramData\anaconda3\Scripts\activate.bat  D:\ProgramData\anaconda3 && conda activate mylibra && python diary/auto_trigger.py"