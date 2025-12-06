# 环境变量配置指南

## 快速开始

### 1. 复制示例文件

```bash
cp .env.example .env
```

### 2. 编辑 .env 文件

```bash
# macOS/Linux
nano .env
# 或
vim .env

# Windows
notepad .env
```

### 3. 填入实际值

```bash
OPENAI_API_KEY=sk-proj-your-actual-api-key-here
EXCEL_DIR=.
PROCESSED_DIR=processed_excel
METADATA_FILE=metadata.json
PORT=6000
```

## 环境变量说明

### 必需变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥（必需） | `sk-proj-xxx...` |

### 可选变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `EXCEL_DIR` | Excel 文件目录 | `.` (当前目录) |
| `PROCESSED_DIR` | 处理后文件存储目录 | `processed_excel` |
| `METADATA_FILE` | 元数据文件路径 | `metadata.json` |
| `PORT` | 服务器端口 | `6000` |

## 配置方法对比

### .env 文件（推荐）⭐

**优点**:
- ✅ 项目级别配置，不污染系统环境
- ✅ 便于版本控制（.env.example 可提交）
- ✅ 团队协作友好
- ✅ 不同环境可配置不同文件

**使用**:
```bash
cp .env.example .env
# 编辑 .env 文件
```

### 系统环境变量

**适用场景**:
- 生产环境部署
- Docker 容器
- CI/CD 流程

**macOS/Linux**:
```bash
export OPENAI_API_KEY="your-key"
```

**Windows**:
```cmd
set OPENAI_API_KEY=your-key
```

## 验证配置

运行以下命令验证环境变量是否加载成功：

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('OPENAI_API_KEY:', '已设置' if os.getenv('OPENAI_API_KEY') else '未设置')"
```

## 安全注意事项

1. **不要提交 .env 文件到 Git**
   - `.env` 已在 `.gitignore` 中
   - 只提交 `.env.example` 作为模板

2. **API Key 安全**
   - 不要在代码中硬编码 API Key
   - 不要在公开场合分享 API Key
   - 定期轮换 API Key

3. **生产环境**
   - 使用密钥管理服务（如 AWS Secrets Manager）
   - 使用环境变量注入（如 Docker secrets）
   - 限制 API Key 的权限范围

## 常见问题

### Q: .env 文件不生效？

A: 检查以下几点：
1. 文件是否在项目根目录
2. 文件名是否为 `.env`（注意前面的点）
3. 是否安装了 `python-dotenv`: `pip install python-dotenv`
4. 代码中是否调用了 `load_dotenv()`

### Q: 如何为不同环境配置不同的值？

A: 使用多个 .env 文件：
```bash
.env.development
.env.production
.env.test
```

在代码中指定：
```python
from dotenv import load_dotenv
load_dotenv('.env.production')  # 加载特定环境文件
```

### Q: 环境变量优先级？

A: 系统环境变量 > .env 文件中的值

如果同时设置了系统环境变量和 .env 文件，系统环境变量优先。

