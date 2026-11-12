@echo off
rem WB theme parser, runs on this Windows computer (WB trusts only the local Chrome profile).
rem Takes themes added at <server>/studio/wb/themes and sends the parsed products to the queue server.
rem The server runs separately (docker compose up -d in printflow). For a remote server:
rem   wb_parser.cmd http://SERVER:8090
chcp 65001 >nul
cd /d "%~dp0\..\.."
set PYTHONIOENCODING=utf-8
set API=%~1
if "%API%"=="" set API=http://127.0.0.1:8090
".venv\Scripts\python.exe" -m printflow.scripts.wb_parse_queue --watch --count 20 --search 30 --api %API%
pause
