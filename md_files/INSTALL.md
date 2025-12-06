# 安装指南

## 标准安装流程

本项目遵循 Python 开发的标准做法，使用虚拟环境进行依赖管理。

### 1. 创建并激活虚拟环境

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

激活后，命令行会显示 `(venv)` 前缀。

> **说明**: 虚拟环境是 Python 项目的标准做法，所有专业 Python 项目都使用虚拟环境。详见 [虚拟环境说明.md](虚拟环境说明.md)

### 2. 安装系统级音频库（语音功能需要，可选）

如果需要语音输入功能，先安装系统级依赖：

**macOS**:
```bash
brew install portaudio
```

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install portaudio19-dev python3-pyaudio
```

**Windows**:
- 方法1: 使用 pipwin（推荐）
  ```bash
  pip install pipwin
  pipwin install pyaudio
  ```
- 方法2: 下载并安装 [PortAudio](http://files.portaudio.com/download.html)，然后安装 pyaudio

> **说明**: 如未安装语音依赖，系统会自动禁用语音功能；要开启语音，请严格按语音安装步骤完成依赖。

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

> **提示**: 如果步骤2（系统级音频库）安装成功，会自动安装所有依赖包括语音功能。如果跳过步骤2，系统会自动禁用语音功能，其他功能正常。

### 4. 配置环境变量

#### 方法1: 使用 .env 文件（推荐）

在项目根目录创建 `.env` 文件：

```bash
# 复制示例文件
cp .env.example .env

# 编辑 .env 文件，填入实际值
# macOS/Linux:
nano .env
# 或
vim .env

# Windows:
notepad .env
```

`.env` 文件内容示例：

```bash
OPENAI_API_KEY=sk-proj-your-actual-api-key-here
EXCEL_DIR=.
PROCESSED_DIR=processed_excel
METADATA_FILE=metadata.json
PORT=6000
```

> **安全提示**: `.env` 文件已在 `.gitignore` 中，不会被提交到 Git 仓库。

#### 方法2: 使用系统环境变量

**macOS/Linux** (临时，当前终端会话):
```bash
export OPENAI_API_KEY="your-api-key-here"
export EXCEL_DIR="."
export PROCESSED_DIR="processed_excel"
export METADATA_FILE="metadata.json"
export PORT=6000
```

**macOS/Linux** (永久，添加到 shell 配置文件):
```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
echo 'export OPENAI_API_KEY="your-api-key-here"' >> ~/.zshrc
echo 'export PORT=6000' >> ~/.zshrc
source ~/.zshrc
```

**Windows** (临时，当前 CMD 会话):
```cmd
set OPENAI_API_KEY=your-api-key-here
set PORT=6000
```

**Windows** (永久，系统环境变量):
1. 右键"此电脑" → "属性" → "高级系统设置"
2. 点击"环境变量"
3. 在"用户变量"中添加新变量

> **说明**: 推荐使用方法1（.env 文件），便于管理且不会污染系统环境变量。

### 5. 运行系统

```bash
python app.py
```

访问 `http://localhost:6000` 使用前端界面。

---

## 语音功能详细安装说明（可选）

如果你需要语音输入功能，以下是详细的安装步骤：

### macOS

```bash
# 安装 PortAudio
brew install portaudio

# 安装 Python 音频库
pip install pyaudio resampy soundfile
```

### Ubuntu/Debian

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install portaudio19-dev python3-pyaudio

# 安装 Python 音频库
pip install pyaudio resampy soundfile
```

### Windows

1. 下载并安装 [PortAudio](http://files.portaudio.com/download.html)
2. 或者使用预编译的 wheel 文件：
   ```bash
   pip install pipwin
   pipwin install pyaudio
   pip install resampy soundfile
   ```

### 验证安装

安装完成后，可以运行以下命令验证：

```python
python -c "import pyaudio; print('pyaudio 安装成功')"
```

如果出现错误，请检查系统依赖是否正确安装。

## 常见问题

### 1. pyaudio 安装失败

**问题**: `ERROR: Failed to build 'pyaudio'`

**解决方案**:
- macOS: 确保已安装 Xcode Command Line Tools: `xcode-select --install`
- Linux: 安装 `portaudio19-dev` 和 `python3-dev`
- Windows: 使用预编译的 wheel 文件或安装 Visual C++ Build Tools

### 2. SSL 连接错误

**问题**: `SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING]'))`

**解决方案**:
- 检查网络连接
- 尝试使用国内镜像源：
  ```bash
  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```

### 3. 语音功能未启用

**问题**: 系统提示"语音功能未启用"

**解决方案**:
- 如未安装语音依赖，系统会禁用语音功能；要启用语音，请按上文完整安装依赖
- 如需启用，请按照上述步骤安装 `pyaudio` 和相关依赖

## 关于虚拟环境

虚拟环境是 Python 开发的标准做法，所有专业 Python 项目都使用虚拟环境。这不是可选项，而是行业标准。

如果你不熟悉虚拟环境，请阅读 [虚拟环境说明.md](虚拟环境说明.md) 了解为什么以及如何使用。

## 其他虚拟环境工具

### 使用 conda

```bash
# 创建 conda 环境
conda create -n excel_agent python=3.10
conda activate excel_agent

# 安装依赖
pip install -r requirements.txt

# macOS/Linux 安装 PortAudio
conda install -c conda-forge portaudio
pip install pyaudio resampy soundfile
```

## 验证安装

运行以下命令验证系统是否正常工作：

```bash
python -c "from knowledge_base import KnowledgeBase; print('知识库模块正常')"
python -c "from code_generator import CodeGenerator; print('代码生成模块正常')"
python -c "from data_trace import DataTracer; print('数据追溯模块正常')"
```

如果所有模块都能正常导入，说明安装成功！
