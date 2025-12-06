# Excel Agent – Natural Language Excel Analysis

An Excel-focused AI assistant that turns natural language questions into executable Python analysis code, with robust Excel preprocessing, a searchable knowledge base, data traceability, and optional real‑time voice input.

The web UI is in English; the system supports both Chinese and English queries and Excel content.

---

## Features

### Data & Excel handling
- **Robust Excel preprocessing**
  - Unmerge cells and propagate values
  - Handle multi‑level headers and messy layouts
  - Keep original files intact; write cleaned versions to `processed_excel/`
- **Knowledge base indexing**
  - Scan the `excel_files/` directory for `.xlsx` / `.xls`
  - Extract schema (sheets, columns, dtypes, null counts)
  - Generate per‑file summaries via LLM
  - Persist metadata in `metadata.json`

### Analysis pipeline
- **Natural language understanding**
  - Accepts Chinese and English questions
  - Uses semantic search over the knowledge base to pick relevant files
  - Builds an explicit analysis plan before generating code
- **Code generation & execution**
  - Generates full Python scripts (imports, validation, error handling)
  - Executes code in an isolated Jupyter kernel (`execute_python.py`)
  - Streams generation and execution output to the frontend via **SSE**
  - Auto‑saves charts as Plotly HTML into the `charts/` directory and renders them in the UI
- **Data traceability**
  - Static analysis of generated code to detect which columns / sheets are used
  - Builds a human‑readable traceability report and shows it alongside the summary

### Voice & UI
- **Optional real‑time voice input**
  - Web UI records audio and sends it over WebSocket
  - `voice_handler.py` calls the OpenAI Realtime transcription API (via `realtime_stt.py`)
  - Transcribed text is shown with timestamps and injected into the query box
- **Modern dark UI**
  - Black / deep‑blue “AI dashboard” style
  - Wider natural‑language query textarea
  - Dedicated voice section with Start/Stop controls and transcription feed
  - “Clear Results” also cleans up temporary chart HTML files in `charts/`

---

## Architecture

```text
┌──────────────────────────────┐
│ Frontend (static/index.html) │
│  - Text / voice input        │
│  - SSE result streaming      │
│  - WebSocket voice channel   │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ Flask app (app.py)           │
│  - /api/analyze (SSE)        │
│  - /api/build_index          │
│  - /api/files                │
│  - /charts/<file>            │
│  - Socket.IO: voice_input    │
└───────┬───────────┬──────────┘
        │           │
   ┌────▼───┐  ┌────▼────┐
   │KB      │  │Code gen │
   │(knowledge_base.py)   │
   └────┬───┘  └────┬────┘
        │           │
   ┌────▼────┐  ┌───▼────┐
   │Execute  │  │Trace   │
   │Python   │  │(data_  │
   │(execute │  │ trace) │
   └─────────┘  └────────┘
```

Key Python modules:

- `app.py` – Flask + Socket.IO server, SSE endpoints, and orchestration
- `knowledge_base.py` – indexing, preprocessing, schema extraction, summaries
- `code_generator.py` – analysis planning and Python code generation
- `execute_python.py` – Jupyter kernel execution, chart directory bootstrap
- `data_trace.py` – column usage analysis and trace report formatting
- `dismantle_excel.py` – low‑level Excel preprocessing (unmerge, header fixes)
- `voice_handler.py` – WebSocket voice handling and Realtime API bridge

---

## Setup

### Requirements

- Python **3.10+** (3.13 is tested in this repo)
- A valid **OpenAI API key**
- Recommended: Unix‑like environment (macOS / Linux) for voice features

### Create and activate a virtualenv

```bash
cd excel_agent_2

python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

> Using a virtualenv is the default for professional Python projects.

### Install dependencies

```bash
pip install -U pip
pip install -r requirements.txt
```

### Configure environment variables

Create a `.env` file in the project root (or export vars in your shell):

```bash
OPENAI_API_KEY="sk-xxx"      # required

# Optional – these all have sensible defaults:
EXCEL_DIR="excel_files"
PROCESSED_DIR="processed_excel"
METADATA_FILE="metadata.json"
```

Voice transcription uses the same `OPENAI_API_KEY`. If you don’t need voice, you can leave the extra native audio deps alone; the app will degrade gracefully and disable voice.

---

## Running the app

```bash
source venv/bin/activate        # or equivalent on Windows
python app.py
```

By default the app listens on `http://127.0.0.1:6000` – open that URL in your browser.

Logs are written to `logs/excel_agent.log` (plus console output). This is the first place to look when debugging indexing, analysis or voice issues.

---

## Usage guide

### 1. Upload Excel files

- Drop or click in the **“File Management / Click or drop to upload Excel file”** area.
- Files are saved under `excel_files/`.
- The backend runs the preprocessing pipeline and updates the knowledge base.
- The upload status text shows **uploading → preprocessing/indexing → idle**.

### 2. Build / rebuild the index

- Use the **“Rebuild Index”** button on the right.
- This:
  - Clears in‑memory metadata
  - Rescans `excel_files/` for `.xlsx` / `.xls`
  - Re‑preprocesses and re‑summarizes all files
- Neither `excel_files/` nor `processed_excel/` are deleted.

### 3. Ask questions in natural language

- Type a question in the **Natural Language Query** textarea, e.g.:
  - “Analyze the yearly growth rate of public budget spending in Ningxia and plot the trend.”
  - “Compare platform price vs cost price by product category.”
- Click **“Run analysis”**.
- The right‑hand panel will stream:
  - The generated Python code
  - Execution output (including printed chart paths)
  - A natural‑language analysis summary
  - A “Data traceability” section listing used columns and sheets
  - Any generated Plotly HTML charts rendered inline

### 4. Use voice input (optional)

- Click **“Start Recording”** in the Voice section, speak your question, then **“Stop Recording”**.
- The browser records and sends audio to the backend over WebSocket.
- On success:
  - The transcription appears in the voice panel with time and language
  - The text is also appended into the main query textarea

> If voice requests consistently time out: your network might block `wss://api.openai.com/v1/realtime`. Try a different network (e.g. mobile hotspot) or disable voice.

### 5. Clear results & temporary charts

- The **“Clear Results”** button:
  - Clears the right‑side result sections
  - Hides the loading indicator
  - Closes any active SSE connection
  - Calls `/api/clear_results` to delete generated HTML files in `charts/`

The knowledge base and processed Excel files are **not** touched.

---

## Project layout

```text
excel_agent_2/
├── app.py               # Flask + Socket.IO server and HTTP/SSE routes
├── code_generator.py    # LLM-based analysis plan + Python code generation
├── data_trace.py        # DataTracer (column usage + trace report)
├── dismantle_excel.py   # Low-level Excel unmerge & header normalization
├── execute_python.py    # Jupyter kernel execution + charts/ bootstrap
├── knowledge_base.py    # KnowledgeBase (indexing, summaries, search)
├── voice_handler.py     # VoiceHandler (WebSocket audio → Realtime API)
├── prompt.py            # Prompt templates / helper text
├── static/
│   └── index.html       # Single-page frontend UI
├── excel_files/         # User-uploaded source Excel files
├── processed_excel/     # Preprocessed Excel copies
├── charts/              # Generated Plotly HTML charts (temporary)
├── logs/
│   └── excel_agent.log  # Server log
├── metadata.json        # Persisted knowledge-base metadata
├── requirements.txt     # Python dependencies
└── README.md            # This document
```

The `realtime voice w6 demo/` directory contains the reference Realtime STT/TTS demos used by `voice_handler.py`. It is not served directly to end‑users.

---

## Notes & best practices

1. **Virtualenv is required** – all commands above assume you’re inside `venv`.
2. **Keep your API key secret** – never commit `.env` or keys to version control.
3. **Excel preprocessing** – if a file fails to preprocess, the system no longer falls back to the raw file; instead you should inspect `logs/excel_agent.log`.
4. **Chart files** – HTML charts in `charts/` are generated automatically and can be deleted at any time (the UI also clears them when you click “Clear Results”).
5. **Performance** – large Excel files or many files can make indexing slow. Prefer to batch uploads, then press “Rebuild Index” once.

---

## Roadmap / ideas

- Support more data sources (CSV, Parquet, SQL)
- Richer visualization templates and dashboards
- Multi‑turn conversational analysis
- Exportable analysis reports (HTML / PDF / Markdown)
- Improved Realtime voice UX and partial results

---

## License

MIT License

---

## Contributions

This is a teaching/demo project; feel free to fork and adapt. Bug fixes and improvements are welcome via pull requests or issues. 

---

## 中文说明（简要）

本项目是一个面向 Excel 的 AI 分析助手，可以：

- 自动预处理复杂 Excel（合并单元格、多级表头），并将处理后的文件保存到 `processed_excel/` 目录，**不会修改原始文件**。
- 构建一个基于 `metadata.json` 的 Excel 知识库：包含每个文件的工作表、列名、数据类型和摘要说明。
- 根据自然语言问题（支持中英文）自动：
  - 选择最相关的 Excel 文件
  - 生成分析计划
  - 生成并执行完整的 Python 分析代码
  - 输出代码、执行结果、分析总结和“数据追溯”报告
- 根据分析代码自动生成 Plotly HTML 图表，保存到 `charts/` 目录并在网页中展示。
- 支持可选的 WebSocket 实时语音输入，将语音转为文本后填入查询框。

### 本地启动步骤（与英文版一致）

```bash
cd excel_agent_2

python -m venv venv
source venv/bin/activate        # Windows 请使用 .\venv\Scripts\Activate.ps1

pip install -U pip
pip install -r requirements.txt

export OPENAI_API_KEY="你的 OpenAI Key"

python app.py
```

然后在浏览器中访问 `http://127.0.0.1:6000` 即可使用 Web 界面。

更多细节（模块职责、接口说明等）请参考上面的英文部分；两种语言内容是一致的，只是表达方式不同。 
