@echo off
setlocal
cd /d "%~dp0"
rem 本脚本以系统默认编码(GBK)保存, 请勿用UTF-8编辑器改写
set PYTHONIOENCODING=gbk:backslashreplace

echo ============================================================
echo    超星学习通刷课 CLI  -  一键启动
echo    首次启动会引导配置答题AI并做连通性测试
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python, 请安装 Python 3.13+ 并勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)

python -c "import requests, loguru, openai, tqdm, bs4, lxml, pyaes, fontTools, httpx, ddddocr, chardet, tenacity, urllib3" >nul 2>nul
if errorlevel 1 (
    echo [提示] 依赖缺失, 正在安装 requirements.txt ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败, 可尝试: python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)

python main.py %*

echo.
pause
