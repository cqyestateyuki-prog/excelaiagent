"""
Excel 智能体主服务器：集成所有模块，支持 SSE 流式输出和 WebSocket 语音输入
"""
import os
import json
import logging
import asyncio
import re
import uuid
from pathlib import Path
from typing import Optional, Dict, List
from flask import Flask, request, Response, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import threading
from dotenv import load_dotenv

from knowledge_base import KnowledgeBase
from code_generator import CodeGenerator
from data_trace import DataTracer
from execute_python import model_execute_main
from voice_handler import VoiceHandler

# 加载 .env 文件
load_dotenv()

# 配置日志：同时输出到控制台和文件
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "excel_agent.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),  # 输出到文件
        logging.StreamHandler()  # 输出到控制台
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
# 设置文件上传大小限制（100MB）
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
CORS(app)
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25
)

# 全局变量
kb: Optional[KnowledgeBase] = None
code_generator: Optional[CodeGenerator] = None
data_tracer: Optional[DataTracer] = None
voice_handler: Optional[VoiceHandler] = None

def init_components():
    """初始化所有组件"""
    global kb, code_generator, data_tracer, voice_handler
    
    api_key = os.getenv("OPENAI_API_KEY")
    # Excel 文件目录，默认使用项目下的 excel_files 目录
    excel_dir = os.getenv("EXCEL_DIR", "excel_files")
    processed_dir = os.getenv("PROCESSED_DIR", "processed_excel")
    metadata_file = os.getenv("METADATA_FILE", "metadata.json")

    # 确保目录存在
    Path(excel_dir).mkdir(exist_ok=True)
    Path(processed_dir).mkdir(exist_ok=True)
    
    kb = KnowledgeBase(
        excel_dir=excel_dir,
        processed_dir=processed_dir,
        metadata_file=metadata_file,
        api_key=api_key
    )
    
    code_generator = CodeGenerator(api_key=api_key)
    data_tracer = DataTracer()
    voice_handler = VoiceHandler(socketio, api_key=api_key)
    
    logger.info("组件初始化完成")

def to_ret_s_suc(answer: str, finished: int, content_type: str, 
                 content_status: str, chat_id: Optional[str] = None, 
                 response_id: Optional[str] = None) -> str:
    """
    将核心数据格式化为 SSE 事件流
    
    Args:
        answer: 当前数据块的内容
        finished: 标志位，0 表示流仍在进行中，1 表示流已结束
        content_type: 内容类型（code/data/result）
        content_status: 内容状态（start/in_progress/end）
        chat_id: 会话ID
        response_id: 响应ID
        
    Returns:
        SSE 格式的消息字符串
    """
    payload = {
        'answer': answer,
        'finished': finished,
        'content_type': content_type,
        'content_status': content_status,
        'chat_id': chat_id,
        'response_id': response_id,
    }
    
    sse_message = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return sse_message

def analyze_excel_stream(question: str, chat_id: Optional[str] = None, user_api_key: Optional[str] = None):
    """
    流式分析 Excel 数据（生成器函数）
    
    Args:
        question: 用户问题
        chat_id: 会话ID
        user_api_key: 用户提供的 OpenAI API key（可选，如果提供则使用用户的配额）
        
    Yields:
        SSE 格式的消息
    """
    response_id = f"resp_{hash(question) % 100000}"
    
    # 确定使用的 API key：优先使用用户提供的，否则使用服务器默认的
    api_key_to_use = user_api_key if user_api_key else os.getenv("OPENAI_API_KEY")
    
    # 如果用户提供了 API key，创建新的组件实例使用用户的 API key
    # 否则使用全局组件（使用服务器默认 API key）
    if user_api_key:
        logger.info("使用用户提供的 API key")
        # 创建临时组件实例使用用户的 API key
        # 注意：KnowledgeBase 会从 metadata.json 加载元数据，所以可以复用
        from code_generator import CodeGenerator
        user_code_generator = CodeGenerator(api_key=user_api_key)
        # 对于 KnowledgeBase，我们可以复用全局实例的元数据，但使用用户的 API key 进行搜索和摘要
        # 为了简化，我们创建一个新实例，它会自动加载相同的 metadata.json
        from knowledge_base import KnowledgeBase
        excel_dir = os.getenv("EXCEL_DIR", "excel_files")
        processed_dir = os.getenv("PROCESSED_DIR", "processed_excel")
        metadata_file = os.getenv("METADATA_FILE", "metadata.json")
        user_kb = KnowledgeBase(
            excel_dir=excel_dir,
            processed_dir=processed_dir,
            metadata_file=metadata_file,
            api_key=user_api_key
        )
        # user_kb 会自动从 metadata.json 加载元数据，所以可以正常使用
    else:
        logger.info("使用服务器默认 API key")
        user_code_generator = code_generator
        user_kb = kb
    
    # 清空上一次的分析结果（图表文件）
    try:
        charts_dir = Path('charts')
        if charts_dir.exists() and charts_dir.is_dir():
            for f in charts_dir.glob('*.html'):
                try:
                    f.unlink()
                    logger.debug(f"已删除上一次的图表文件: {f.name}")
                except Exception as e:
                    logger.warning(f"删除图表文件失败 {f}: {e}")
    except Exception as e:
        logger.warning(f"清空上一次结果时出错: {e}")
    
    # 检测用户输入语言（在开始分析之前）
    from code_generator import detect_language
    user_language = detect_language(question)
    logger.info(f"检测到用户输入语言: {user_language}")
    
    try:
        # 阶段1: 文件定位
        if user_language == 'zh':
            locate_msg = "正在定位相关文件..."
        else:
            locate_msg = "Locating relevant files..."
        
        yield to_ret_s_suc(
            answer=locate_msg,
            finished=0,
            content_type='text',
            content_status='start',
            chat_id=chat_id,
            response_id=response_id
        )
        
        relevant_files = user_kb.search_files(question, top_k=1)
        if not relevant_files:
            # user_language 已在上面检测
            
            file_count = len(kb.metadata) if kb.metadata else 0
            if file_count == 0:
                if user_language == 'zh':
                    error_msg = "知识库为空，请先上传 Excel 文件并构建索引。\n\n操作步骤：\n1. 在左侧上传 Excel 文件\n2. 点击'重建索引'按钮"
                else:
                    error_msg = "Knowledge base is empty. Please upload Excel files and build index first.\n\nSteps:\n1. Upload Excel files on the left\n2. Click 'Rebuild Index' button"
            else:
                if user_language == 'zh':
                    error_msg = f"未找到与问题相关的文件。\n\n当前知识库中有 {file_count} 个文件，但无法匹配您的问题。\n\n建议：\n1. 检查问题描述是否准确\n2. 尝试使用更具体的关键词\n3. 点击'重建索引'重新构建索引"
                else:
                    error_msg = f"No relevant files found for your question.\n\nThe knowledge base contains {file_count} file(s), but cannot match your question.\n\nSuggestions:\n1. Check if the question description is accurate\n2. Try using more specific keywords\n3. Click 'Rebuild Index' to rebuild the index"
            
            yield to_ret_s_suc(
                answer=error_msg,
                finished=1,
                content_type='text',
                content_status='end',
                chat_id=chat_id,
                response_id=response_id
            )
            return
        
        file_info = relevant_files[0]
        file_metadata = file_info['metadata']
        
        # 检测用户输入语言（在文件定位之前）
        from code_generator import detect_language
        user_language = detect_language(question)
        
        # 根据语言显示文件定位信息
        if user_language == 'zh':
            file_msg = f"已定位到文件: {file_info['file_key']}\n{file_info.get('relevance', '')}"
        else:
            file_msg = f"Located file: {file_info['file_key']}\n{file_info.get('relevance', '')}"
        
        yield to_ret_s_suc(
            answer=file_msg,
            finished=0,
            content_type='text',
            content_status='in_progress',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 阶段2: 生成分析计划
        if user_language == 'zh':
            plan_msg = "正在生成分析计划..."
        else:
            plan_msg = "Generating analysis plan..."
        
        yield to_ret_s_suc(
            answer=plan_msg,
            finished=0,
            content_type='text',
            content_status='in_progress',
            chat_id=chat_id,
            response_id=response_id
        )
        
        analysis_plan = user_code_generator.generate_analysis_plan(question, file_metadata)
        language = analysis_plan.get('language', 'zh')  # 获取检测到的语言
        
        # 根据语言显示分析计划提示
        if language == 'zh':
            plan_label = "分析计划:"
        else:
            plan_label = "Analysis Plan:"
        
        yield to_ret_s_suc(
            answer=f"{plan_label}\n{analysis_plan.get('analysis_plan', '')}",
            finished=0,
            content_type='text',
            content_status='in_progress',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 阶段3: 生成代码
        yield to_ret_s_suc(
            answer='',
            finished=0,
            content_type='code',
            content_status='start',
            chat_id=chat_id,
            response_id=response_id
        )
        
        code = user_code_generator.generate_code(question, file_metadata, analysis_plan, language=language)
        
        # 流式输出代码（模拟打字机效果）
        code_chunks = [code[i:i+50] for i in range(0, len(code), 50)]
        for chunk in code_chunks:
            yield to_ret_s_suc(
                answer=chunk,
                finished=0,
                content_type='code',
                content_status='in_progress',
                chat_id=chat_id,
                response_id=response_id
            )
        
        yield to_ret_s_suc(
            answer='',
            finished=0,
            content_type='code',
            content_status='end',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 阶段4: 执行代码
        if language == 'zh':
            exec_msg = "正在执行代码..."
        else:
            exec_msg = "Executing code..."
        
        yield to_ret_s_suc(
            answer=exec_msg,
            finished=0,
            content_type='text',
            content_status='in_progress',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 验证代码是否有效
        if code.startswith("# 代码生成失败"):
            yield to_ret_s_suc(
                answer=code,
                finished=0,
                content_type='data',
                content_status='end',
                chat_id=chat_id,
                response_id=response_id
            )
            yield to_ret_s_suc(
                answer="代码生成失败，无法执行。",
                finished=1,
                content_type='text',
                content_status='end',
                chat_id=chat_id,
                response_id=response_id
            )
            return
        
        # 修改代码以使用正确的文件路径
        processed_path = file_metadata.get('processed_path', '')
        if not processed_path:
            yield to_ret_s_suc(
                answer="错误：无法获取处理后的文件路径",
                finished=1,
                content_type='text',
                content_status='end',
                chat_id=chat_id,
                response_id=response_id
            )
            return
        
        # 验证处理后的文件是否存在
        from pathlib import Path
        file_path_obj = Path(processed_path)
        if not file_path_obj.exists():
            error_msg = f"错误：处理后的文件不存在: {processed_path}\n绝对路径: {file_path_obj.resolve()}"
            logger.error(error_msg)
            yield to_ret_s_suc(
                answer=error_msg,
                finished=1,
                content_type='text',
                content_status='end',
                chat_id=chat_id,
                response_id=response_id
            )
            return
        
        logger.info(f"执行代码，文件路径: {processed_path}，文件大小: {file_path_obj.stat().st_size} 字节")
        
        # 替换文件路径
        code_with_path = code.replace("'test.xlsx'", f"'{processed_path}'")
        code_with_path = code_with_path.replace('"test.xlsx"', f'"{processed_path}"')
        
        # 如果代码中没有文件路径，尝试添加
        if processed_path and processed_path not in code_with_path:
            # 检查是否有 read_excel 调用但没有路径
            if "read_excel()" in code_with_path or "read_excel( )" in code_with_path:
                code_with_path = code_with_path.replace("read_excel()", f"read_excel('{processed_path}')")
                code_with_path = code_with_path.replace("read_excel( )", f"read_excel('{processed_path}')")
        
        logger.info(f"代码中 print 语句数: {code_with_path.count('print(')}")
        execution_output = model_execute_main(code_with_path)
        
        yield to_ret_s_suc(
            answer='',
            finished=0,
            content_type='data',
            content_status='start',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 检测执行结果中的图表文件路径
        import re
        # 改进正则表达式以匹配中文文件名和更多格式
        # 匹配 charts/ 开头的路径，支持中文字符、英文字母、数字、下划线、连字符等
        chart_pattern = r'charts/[^\s<>"\'\)\n]+\.html'
        chart_files = re.findall(chart_pattern, execution_output)
        
        # 也检查 charts 目录下是否有新生成的 HTML 文件
        charts_dir = Path('charts')
        if charts_dir.exists():
            existing_charts = [f"charts/{f.name}" for f in charts_dir.glob("*.html")]
            if existing_charts:
                logger.info(f"在 charts 目录下发现 HTML 文件: {existing_charts}")
                # 合并检测到的和目录中的文件
                all_charts = list(set(chart_files + existing_charts))
                chart_files = all_charts
        
        logger.info(f"检测到的图表文件路径: {chart_files}")
        
        # 流式输出执行结果
        output_chunks = [execution_output[i:i+100] for i in range(0, len(execution_output), 100)]
        for chunk in output_chunks:
            yield to_ret_s_suc(
                answer=chunk,
                finished=0,
                content_type='data',
                content_status='in_progress',
                chat_id=chat_id,
                response_id=response_id
            )
        
        yield to_ret_s_suc(
            answer='',
            finished=0,
            content_type='data',
            content_status='end',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 如果有图表文件，发送图表信息
        if chart_files:
            # 去重并只保留存在的文件
            unique_charts = []
            for chart_file in set(chart_files):
                chart_path = Path(chart_file)
                logger.info(f"检查图表文件: {chart_file}, 存在: {chart_path.exists()}, 绝对路径: {chart_path.resolve()}")
                if chart_path.exists():
                    unique_charts.append(chart_file)
            
            logger.info(f"有效的图表文件列表: {unique_charts}")
            if unique_charts:
                chart_data = json.dumps({'charts': unique_charts})
                logger.info(f"发送图表数据: {chart_data}")
                yield to_ret_s_suc(
                    answer=chart_data,
                    finished=0,
                    content_type='chart',
                    content_status='start',
                    chat_id=chat_id,
                    response_id=response_id
                )
        
        # 阶段5: 数据追溯
        schema = file_metadata.get('schema', {})
        trace_result = data_tracer.trace_data_usage(code, execution_output, schema)
        trace_report = data_tracer.format_trace_report(trace_result, language=language)
        
        # 阶段6: 生成总结
        yield to_ret_s_suc(
            answer='',
            finished=0,
            content_type='result',
            content_status='start',
            chat_id=chat_id,
            response_id=response_id
        )
        
        # 使用 LLM 生成总结（根据语言）
        # 增加执行输出长度限制到5000字符，确保包含关键信息
        execution_output_for_summary = execution_output[:5000] if len(execution_output) > 5000 else execution_output
        
        if language == 'zh':
            summary_prompt = f"""用户问题: {question}

执行结果:
{execution_output_for_summary}

请根据执行结果，直接回答用户的问题。如果执行结果中包含数据表格、统计信息或计算结果，请明确指出关键发现，特别是：
1. 直接回答用户问题的答案（例如：哪个省市增长率最高？请明确指出是哪个省市）
2. 关键数据指标和数值
3. 如果有多个结果，请列出最重要的几个

请用中文回复，字数控制在200-300字。"""
            system_content = "你是一个专业的数据分析师，擅长从执行结果中提取关键信息并直接回答用户的问题。请用中文回复，确保回答清晰、准确、直接。"
        else:
            summary_prompt = f"""User question: {question}

Execution results:
{execution_output_for_summary}

Please answer the user's question directly based on the execution results. If the execution results contain data tables, statistics, or calculation results, please clearly identify key findings, especially:
1. Direct answer to the user's question (e.g., which province/city has the highest growth rate? Please clearly state which one)
2. Key data indicators and values
3. If there are multiple results, please list the most important ones

Please reply in English, 200-300 words."""
            system_content = "You are a professional data analyst skilled in extracting key information from execution results and directly answering user questions. Please reply in English, ensuring your answer is clear, accurate, and direct."
        
        from openai import OpenAI
        # 使用用户提供的 API key 或服务器默认的
        client = OpenAI(api_key=api_key_to_use)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": summary_prompt}
            ],
            temperature=0.3
        )
        summary = response.choices[0].message.content.strip()
        
        # 流式输出总结
        summary_chunks = [summary[i:i+50] for i in range(0, len(summary), 50)]
        for chunk in summary_chunks:
            yield to_ret_s_suc(
                answer=chunk,
                finished=0,
                content_type='result',
                content_status='in_progress',
                chat_id=chat_id,
                response_id=response_id
            )
        
        # 输出数据追溯信息
        yield to_ret_s_suc(
            answer=f"\n\n{trace_report}",
            finished=0,
            content_type='result',
            content_status='in_progress',
            chat_id=chat_id,
            response_id=response_id
        )
        
        yield to_ret_s_suc(
            answer='',
            finished=1,
            content_type='result',
            content_status='end',
            chat_id=chat_id,
            response_id=response_id
        )
        
    except Exception as e:
        logger.error(f"分析过程中出错: {e}", exc_info=True)
        yield to_ret_s_suc(
            answer=f"分析过程中出错: {str(e)}",
            finished=1,
            content_type='text',
            content_status='end',
            chat_id=chat_id,
            response_id=response_id
        )

@app.route('/api/analyze', methods=['POST', 'GET'])
def analyze():
    """分析 Excel 数据的 SSE 端点"""
    if request.method == 'GET':
        # 支持 GET 请求（用于 EventSource）
        question = request.args.get('question', '')
        chat_id = request.args.get('chat_id', None)
        user_api_key = request.args.get('api_key', None)  # 用户提供的 API key
    else:
        data = request.json
        question = data.get('question', '')
        chat_id = data.get('chat_id', None)
        user_api_key = data.get('api_key', None)  # 用户提供的 API key
    
    if not question:
        return jsonify({'error': '问题不能为空'}), 400
    
    return Response(
        analyze_excel_stream(question, chat_id, user_api_key=user_api_key),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/build_index', methods=['POST'])
def build_index():
    """重建知识库索引：重新扫描 excel_files 目录中的所有文件并重建索引"""
    try:
        old_file_count = len(kb.metadata) if kb.metadata else 0
        logger.info(f"开始重建索引，当前索引中有 {old_file_count} 个文件")
        
        # 清空现有索引
        kb.metadata = {}
        kb.save_metadata()
        logger.info("已清空现有索引")
        
        # 重新扫描 excel_files 目录并重建索引
        kb.build_index(force_rebuild=True)
        
        new_file_count = len(kb.metadata) if kb.metadata else 0
        logger.info(f"索引重建完成，共索引 {new_file_count} 个文件")
        
        return jsonify({
            'status': 'success', 
            'message': f'索引重建完成！\n\n已重新扫描 excel_files 目录，共索引 {new_file_count} 个文件。'
        })
    except Exception as e:
        logger.error(f"重建索引时出错: {e}", exc_info=True)
        return jsonify({
            'status': 'error', 
            'message': f'重建索引失败: {str(e)}\n\n请查看日志文件 logs/excel_agent.log 获取详细错误信息。'
        }), 500


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传 Excel 文件并更新知识库索引"""
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': '未找到文件字段 file'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': '文件名为空'}), 400

        # 处理文件名：保留原始文件名，但进行安全处理
        original_filename = file.filename
        logger.info(f"接收到上传文件，原始文件名: {original_filename}")
        
        # 尝试使用 secure_filename，但如果结果为空或只有扩展名，使用改进的方法
        safe_filename = secure_filename(original_filename)
        
        # 如果 secure_filename 处理后的文件名无效（为空或只有扩展名），使用改进的方法
        if not safe_filename or safe_filename == '' or ('.' not in safe_filename and '.' in original_filename):
            # 提取扩展名
            ext = Path(original_filename).suffix
            # 使用原始文件名，但替换不安全字符
            # 保留中文字符、字母、数字、点、下划线、连字符
            safe_name = re.sub(r'[^\w\s\u4e00-\u9fff.-]', '_', original_filename)
            safe_name = re.sub(r'\s+', '_', safe_name)  # 空格替换为下划线
            safe_filename = safe_name if safe_name else f"uploaded_file_{uuid.uuid4().hex[:8]}{ext}"
            logger.info(f"文件名处理：原始={original_filename}, 处理后={safe_filename}")
        
        # 确保文件名不为空
        if not safe_filename or safe_filename.strip() == '':
            ext = Path(original_filename).suffix or '.xlsx'
            safe_filename = f"uploaded_file_{uuid.uuid4().hex[:8]}{ext}"
            logger.warning(f"文件名处理后仍为空，使用生成的名称: {safe_filename}")
        
        # 使用与知识库相同的目录
        excel_dir = os.getenv("EXCEL_DIR", "excel_files")
        Path(excel_dir).mkdir(exist_ok=True)
        save_path = Path(excel_dir) / safe_filename
        file.save(str(save_path))

        logger.info(f"文件已保存到: {save_path}")

        # 检查文件是否已存在
        file_key = str(save_path.relative_to(Path(excel_dir)))
        file_already_indexed = file_key in kb.metadata if kb.metadata else False
        
        if file_already_indexed:
            logger.info(f"文件已存在于知识库: {file_key}")
            return jsonify({
                'status': 'info',
                'message': f'文件已存在于知识库中，无需重新索引',
                'filename': safe_filename,
                'saved_path': str(save_path),
                'indexed_files': len(kb.metadata) if kb.metadata else 0
            })

        # 仅增量更新索引（不强制重建），只处理新上传的文件
        try:
            logger.info(f"开始处理并索引文件: {file_key}")
            kb.build_index(force_rebuild=False)
            
            # 检查文件是否成功索引
            file_count = len(kb.metadata) if kb.metadata else 0
            file_indexed = file_key in kb.metadata if kb.metadata else False
            
            if file_indexed:
                return jsonify({
                    'status': 'success',
                    'message': f'文件上传并索引完成！\n\n文件名: {safe_filename}\n知识库中共有 {file_count} 个已索引文件',
                    'filename': safe_filename,
                    'saved_path': str(save_path),
                    'indexed_files': file_count
                })
            else:
                # 文件上传了但索引失败
                return jsonify({
                    'status': 'warning',
                    'message': f'文件上传成功，但索引处理失败。\n\n文件名: {safe_filename}\n\n可能原因：\n1. 文件格式不支持\n2. 文件损坏或无法读取\n3. 预处理过程出错\n\n请检查文件或联系管理员。',
                    'filename': safe_filename,
                    'saved_path': str(save_path),
                    'indexed_files': file_count
                })
        except Exception as e:
            logger.error(f"构建索引时出错: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': f'文件上传成功，但索引构建时发生错误: {str(e)}\n\n请尝试点击"重建索引"按钮手动构建索引。',
                'filename': safe_filename,
                'saved_path': str(save_path)
            }), 200
    except Exception as e:
        logger.error(f"上传文件时出错: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/charts/<path:filename>')
def serve_chart(filename):
    """提供图表文件服务"""
    try:
        from urllib.parse import unquote
        # URL解码文件名（处理中文字符）
        decoded_filename = unquote(filename)
        logger.info(f"请求图表文件: {filename} -> {decoded_filename}")
        
        charts_dir = Path('charts')
        chart_path = charts_dir / decoded_filename
        
        # 安全检查：确保文件在 charts 目录内
        try:
            resolved_chart = chart_path.resolve()
            resolved_charts_dir = charts_dir.resolve()
            if not str(resolved_chart).startswith(str(resolved_charts_dir)):
                logger.warning(f"非法路径访问尝试: {filename}")
                return jsonify({'error': '无效的文件路径'}), 403
        except Exception as e:
            logger.error(f"路径解析错误: {e}")
            return jsonify({'error': '路径解析失败'}), 400
        
        if chart_path.exists() and chart_path.suffix == '.html':
            logger.info(f"提供图表文件: {decoded_filename}")
            return send_from_directory(str(charts_dir), decoded_filename)
        else:
            logger.warning(f"图表文件不存在: {decoded_filename}, 路径: {chart_path}")
            return jsonify({'error': '图表文件不存在'}), 404
    except Exception as e:
        logger.error(f"提供图表文件时出错: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear_results', methods=['POST'])
def clear_results():
    """清空分析结果相关的临时文件（例如生成的图表 HTML）"""
    try:
        charts_dir = Path('charts')
        removed = []
        if charts_dir.exists() and charts_dir.is_dir():
            for f in charts_dir.glob('*.html'):
                try:
                    f.unlink()
                    removed.append(f.name)
                    logger.info(f"已删除图表文件: {f}")
                except Exception as e:
                    logger.warning(f"删除图表文件失败 {f}: {e}")
        return jsonify({
            'status': 'success',
            'message': f'已清空分析结果相关的图表文件，共删除 {len(removed)} 个。'
        })
    except Exception as e:
        logger.error(f"清空结果临时文件时出错: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'清空结果时删除临时文件失败: {str(e)}'
        }), 500

@app.route('/api/files', methods=['GET'])
def list_files():
    """列出所有已索引的文件"""
    try:
        files = [
            {
                'file_key': k,
                'summary': v.get('summary', ''),
                'original_path': v.get('original_path', '')
            }
            for k, v in kb.metadata.items()
        ]
        return jsonify({'files': files})
    except Exception as e:
        logger.error(f"列出文件时出错: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """WebSocket 连接处理"""
    logger.info('WebSocket 客户端已连接')
    emit('connected', {'status': 'connected'})

@socketio.on('voice_input')
def handle_voice_input(data):
    """处理语音输入（通过 WebSocket）"""
    try:
        audio_data = data.get('audio_data')  # base64 编码的音频数据
        session_id = data.get('session_id', 'default')
        audio_format = data.get('audio_format', 'wav')  # 获取音频格式
        
        logger.info(f"收到语音输入请求，session_id: {session_id}, 格式: {audio_format}, 数据长度: {len(audio_data) if audio_data else 0}")
        
        if not audio_data:
            logger.error("音频数据为空")
            emit('error', {'message': '音频数据为空', 'session_id': session_id})
            return
        
        # 在后台线程中处理语音
        def process_voice():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    voice_handler.handle_voice_stream(audio_data, session_id, audio_format)
                )
            except Exception as e:
                logger.error(f"处理语音时出错: {e}", exc_info=True)
                socketio.emit('error', {'message': str(e), 'session_id': session_id})
        
        thread = threading.Thread(target=process_voice)
        thread.daemon = True  # 设置为守护线程
        thread.start()
        
    except Exception as e:
        logger.error(f"处理语音输入时出错: {e}", exc_info=True)
        emit('error', {'message': str(e)})

@socketio.on('text_input')
def handle_text_input(data):
    """处理文本输入（通过 WebSocket）"""
    try:
        question = data.get('question', '')
        if not question:
            emit('error', {'message': '问题不能为空'})
            return
        
        # 在后台线程中执行分析
        def analyze_in_thread():
            try:
                for msg in analyze_excel_stream(question):
                    socketio.emit('analysis_result', {'message': msg})
            except Exception as e:
                logger.error(f"分析时出错: {e}", exc_info=True)
                socketio.emit('error', {'message': str(e)})
        
        thread = threading.Thread(target=analyze_in_thread)
        thread.start()
        
    except Exception as e:
        logger.error(f"处理文本输入时出错: {e}", exc_info=True)
        emit('error', {'message': str(e)})

@app.route('/')
def index():
    """返回前端页面"""
    try:
        return app.send_static_file('index.html')
    except Exception:
        # 如果静态文件不存在，返回简单的 HTML
        return '''
        <!DOCTYPE html>
        <html>
        <head><title>Excel 智能体</title></head>
        <body>
            <h1>Excel 智能体</h1>
            <p>请确保 static/index.html 文件存在</p>
        </body>
        </html>
        '''

if __name__ == '__main__':
    init_components()
    
    # 如果知识库为空或元数据文件不存在，自动构建索引
    metadata_file = Path(os.getenv("METADATA_FILE", "metadata.json"))
    if not kb.metadata or not metadata_file.exists() or len(kb.metadata) == 0:
        logger.info("知识库为空，开始构建索引...")
        try:
            kb.build_index(force_rebuild=False)
            logger.info(f"索引构建完成，共 {len(kb.metadata)} 个文件")
        except Exception as e:
            logger.error(f"构建索引时出错: {e}", exc_info=True)
            logger.warning("索引构建失败，但服务器将继续运行。请手动点击'重建索引'按钮。")
    
    port = int(os.getenv('PORT', 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)

