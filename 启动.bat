@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================================
echo    超星学习通刷课 CLI  -  一键启动
echo    运行前请先在 config.ini 的 [tiku] 段配置答题AI
echo ============================================================
echo.

rem 只使用本机已安装的 Python, 不做任何内置运行环境
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python
    echo.
    echo   本程序需要在已安装 Python 3.13 以上版本的电脑上运行。
    echo   请先安装 Python, 安装时务必勾选 "Add python.exe to PATH",
    echo   安装完成后重新打开本窗口再试。
    echo.
    pause
    exit /b 1
)

python -c "import requests, loguru, openai, tqdm, bs4, lxml, pyaes, fontTools, httpx, ddddocr, chardet, tenacity, urllib3" >nul 2>nul
if errorlevel 1 (
    echo [提示] 依赖缺失, 正在安装 requirements.txt ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败, 可尝试:
        echo     python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)

python main.py %*

echo.
pause
