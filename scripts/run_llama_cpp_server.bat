@echo off
setlocal

if "%MODEL_PATH%"=="" set MODEL_PATH=models\llama-3.1-8b-instruct-q4_k_m.gguf
if "%NGL%"=="" set NGL=35
if "%CTX%"=="" set CTX=4096
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8080
if "%LLAMA_CPP_SERVER_BIN%"=="" set LLAMA_CPP_SERVER_BIN=server.exe

echo Starting llama.cpp server...
echo BIN=%LLAMA_CPP_SERVER_BIN%
echo MODEL=%MODEL_PATH%
echo NGL=%NGL%
echo CTX=%CTX%
echo HOST=%HOST%
echo PORT=%PORT%

"%LLAMA_CPP_SERVER_BIN%" -m "%MODEL_PATH%" -ngl %NGL% -c %CTX% --host %HOST% --port %PORT%
