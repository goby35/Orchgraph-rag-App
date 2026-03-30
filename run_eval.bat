@echo off
cd /d D:\Study\uni\25_26\HKII\graphRAG
D:\Study\uni\25_26\HKII\graphRAG\.venv\Scripts\python.exe scripts\eval\eval_extractor.py > C:\Users\ADMIN\AppData\Local\Temp\eval_output.txt 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> C:\Users\ADMIN\AppData\Local\Temp\eval_output.txt
