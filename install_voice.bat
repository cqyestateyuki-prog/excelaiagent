@echo off
REM Windows 语音功能安装脚本

echo 🎤 Excel 智能体 - 语音功能安装脚本
echo ==================================
echo.

echo 检测到 Windows 系统
echo.
echo 正在使用 pipwin 安装 pyaudio...
pip install pipwin
if %errorlevel% neq 0 (
    echo ❌ pipwin 安装失败
    pause
    exit /b 1
)

pipwin install pyaudio
if %errorlevel% neq 0 (
    echo ❌ pyaudio 安装失败，请尝试手动安装
    pause
    exit /b 1
)

echo.
echo 正在安装其他音频库...
pip install resampy soundfile

if %errorlevel% equ 0 (
    echo.
    echo ✅ 语音功能安装完成！
    echo.
    echo 验证安装...
    python -c "import pyaudio; print('✅ pyaudio 导入成功')"
    python -c "import resampy; print('✅ resampy 导入成功')"
    python -c "import soundfile; print('✅ soundfile 导入成功')"
    echo.
    echo 🎉 所有语音功能依赖已成功安装！
) else (
    echo.
    echo ❌ 安装失败，请检查错误信息
)

pause

