#!/bin/bash
# 语音功能安装脚本

echo "🎤 Excel 智能体 - 语音功能安装脚本"
echo "=================================="
echo ""

# 检测操作系统
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "检测到 macOS 系统"
    echo ""
    echo "正在安装 PortAudio..."
    if command -v brew &> /dev/null; then
        brew install portaudio
        echo "✅ PortAudio 安装完成"
    else
        echo "❌ 未找到 Homebrew，请先安装 Homebrew:"
        echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
    
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "检测到 Linux 系统"
    echo ""
    echo "正在安装 PortAudio 开发库..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y portaudio19-dev python3-pyaudio
        echo "✅ PortAudio 安装完成"
    elif command -v yum &> /dev/null; then
        sudo yum install -y portaudio-devel
        echo "✅ PortAudio 安装完成"
    else
        echo "❌ 未找到包管理器，请手动安装 portaudio19-dev"
        exit 1
    fi
    
else
    echo "❌ 不支持的操作系统: $OSTYPE"
    echo "请参考 INSTALL.md 手动安装"
    exit 1
fi

echo ""
echo "正在安装 Python 音频库..."
pip install pyaudio resampy soundfile

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 语音功能安装完成！"
    echo ""
    echo "验证安装..."
    python -c "import pyaudio; print('✅ pyaudio 导入成功')" 2>/dev/null && \
    python -c "import resampy; print('✅ resampy 导入成功')" 2>/dev/null && \
    python -c "import soundfile; print('✅ soundfile 导入成功')" 2>/dev/null && \
    echo "" && \
    echo "🎉 所有语音功能依赖已成功安装！"
else
    echo ""
    echo "❌ Python 库安装失败，请检查错误信息"
    exit 1
fi

