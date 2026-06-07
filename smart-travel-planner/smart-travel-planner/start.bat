@echo off
cd /d "%~dp0"
echo 正在安装依赖...
pip install -r requirements.txt -q
echo.
echo 启动服务中...
echo 打开浏览器访问: http://localhost:8000
echo 按 Ctrl+C 停止服务
echo.
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
pause
