"""
代码生成模块：基于用户问题和文件结构生成 Python 代码
"""
import json
import logging
from typing import Dict, List, Optional
from openai import OpenAI

logger = logging.getLogger(f'excel_agent.{__name__}')

def detect_language(text: str) -> str:
    """
    检测文本语言（中文或英文）
    
    Args:
        text: 输入文本
        
    Returns:
        'zh' 表示中文，'en' 表示英文
    """
    # 简单的中文字符检测
    chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
    total_chars = len([c for c in text if c.isalnum() or '\u4e00' <= c <= '\u9fff'])
    
    if total_chars == 0:
        return 'en'  # 默认英文
    
    # 如果中文字符占比超过30%，认为是中文
    if chinese_chars / total_chars > 0.3:
        return 'zh'
    else:
        return 'en'

class CodeGenerator:
    """代码生成器"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化代码生成器
        
        Args:
            api_key: OpenAI API Key
        """
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
    
    def generate_analysis_plan(self, question: str, file_metadata: Dict) -> Dict:
        """
        生成分析计划（方案规划）
        
        Args:
            question: 用户问题
            file_metadata: 文件元数据（包含 schema）
            
        Returns:
            分析计划字典，包含分析步骤说明和语言信息
        """
        try:
            # 检测用户输入语言
            language = detect_language(question)
            logger.info(f"检测到用户输入语言: {language}")
            
            schema = file_metadata.get('schema', {})
            processed_path = file_metadata.get('processed_path', '')
            
            # 构建 schema 描述
            schema_desc = []
            for sheet_name, sheet_info in schema.items():
                columns = sheet_info.get('columns', [])
                if language == 'zh':
                    schema_desc.append(f"工作表 '{sheet_name}' 包含列: {', '.join(columns)}")
                else:
                    schema_desc.append(f"Sheet '{sheet_name}' contains columns: {', '.join(columns)}")
            
            schema_text = "\n".join(schema_desc)
            
            # 根据语言构建 prompt
            if language == 'zh':
                prompt = f"""用户问题: {question}

数据文件结构:
{schema_text}

请分析用户问题，制定一个清晰的分析计划，说明将如何操作数据来回答用户的问题。

输出格式（JSON）:
{{
    "analysis_plan": "详细的分析步骤说明",
    "required_columns": ["列名1", "列名2", ...],
    "operations": ["操作1", "操作2", ...]
}}"""
                system_content = "你是一个专业的数据分析师，擅长制定数据分析计划。请用中文回复。"
                default_plan = "分析数据以回答用户问题"
            else:
                prompt = f"""User question: {question}

Data file structure:
{schema_text}

Please analyze the user's question and create a clear analysis plan explaining how to manipulate the data to answer the user's question.

Output format (JSON):
{{
    "analysis_plan": "Detailed analysis steps",
    "required_columns": ["column1", "column2", ...],
    "operations": ["operation1", "operation2", ...]
}}"""
                system_content = "You are a professional data analyst skilled in creating data analysis plans. Please reply in English."
                default_plan = "Analyze data to answer the user's question"
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            plan = json.loads(response.choices[0].message.content)
            plan['language'] = language  # 添加语言信息
            return plan
        except Exception as e:
            logger.error(f"生成分析计划时出错: {e}", exc_info=True)
            language = detect_language(question)
            default_plan = "分析数据以回答用户问题" if language == 'zh' else "Analyze data to answer the user's question"
            return {
                "analysis_plan": default_plan,
                "required_columns": [],
                "operations": [],
                "language": language
            }
    
    def generate_code(self, question: str, file_metadata: Dict, 
                     analysis_plan: Optional[Dict] = None, language: Optional[str] = None) -> str:
        """
        生成 Python 分析代码
        
        Args:
            question: 用户问题
            file_metadata: 文件元数据
            analysis_plan: 分析计划（可选）
            
        Returns:
            Python 代码字符串
        """
        try:
            # 检测语言（优先使用传入的 language，否则从 question 检测）
            if language is None:
                language = detect_language(question)
            if analysis_plan and 'language' in analysis_plan:
                language = analysis_plan['language']
            logger.info(f"代码生成使用语言: {language}")
            
            schema = file_metadata.get('schema', {})
            processed_path = file_metadata.get('processed_path', '')
            
            # 构建 prompt parts（根据语言）
            prompt_parts = []
            for sheet_name, sheet_info in schema.items():
                columns = sheet_info.get('columns', [])
                dtypes = sheet_info.get('dtypes', {})
                head_sample = sheet_info.get('head_sample', [])
                
                if language == 'zh':
                    sheet_desc = f"工作表: {sheet_name}\n"
                    sheet_desc += f"列名: {', '.join(columns)}\n"
                    sheet_desc += f"数据类型: {', '.join([f'{k}: {v}' for k, v in list(dtypes.items())[:10]])}\n"
                    if head_sample:
                        sheet_desc += f"前5行数据示例:\n{str(head_sample[:2])}\n"
                else:
                    sheet_desc = f"Sheet: {sheet_name}\n"
                    sheet_desc += f"Columns: {', '.join(columns)}\n"
                    sheet_desc += f"Data types: {', '.join([f'{k}: {v}' for k, v in list(dtypes.items())[:10]])}\n"
                    if head_sample:
                        sheet_desc += f"First 5 rows sample:\n{str(head_sample[:2])}\n"
                sheet_desc += "---\n"
                prompt_parts.append(sheet_desc)
            
            # 构建完整 prompt（根据语言）
            full_prompt = "\n".join(prompt_parts)
            if language == 'zh':
                full_prompt += f"\n\n用户问题: {question}\n\n"
                full_prompt += f"数据文件路径: {processed_path}\n\n"
                if analysis_plan:
                    full_prompt += f"分析计划: {analysis_plan.get('analysis_plan', '')}\n\n"
                # 添加语言指示
                full_prompt += "**重要**：用户使用中文提问，请生成代码中的注释和 print 输出使用中文。\n"
                full_prompt += "**图表语言要求**：如果生成图表，图表的 title、xaxis_title、yaxis_title 等所有标签必须使用中文。\n\n"
            else:
                full_prompt += f"\n\nUser question: {question}\n\n"
                full_prompt += f"Data file path: {processed_path}\n\n"
                if analysis_plan:
                    full_prompt += f"Analysis plan: {analysis_plan.get('analysis_plan', '')}\n\n"
                # 添加语言指示
                full_prompt += "**Important**: The user is asking in English, please generate code with comments and print outputs in English.\n"
                full_prompt += "**Chart Language Requirement**: If generating charts, all chart labels including title, xaxis_title, yaxis_title must be in English.\n\n"
            
            # Excel 数据处理规则（保持中文，因为这是技术规则，LLM 能理解）
            full_prompt += """
**Excel数据处理规则集**

1. 基础代码结构要求：
    1.1 必要的导入和设置：
        ```python
        import pandas as pd
        import warnings
        warnings.simplefilter(action='ignore', category=Warning)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', None)
        ```
    1.2 输出格式要求：
        - 只需要输出代码即可，无需额外的解释
        - 输出的代码不要包含任何 Markdown 或代码块标记，仅提供纯文本的 Python 代码
        - 禁止输出"```python" 或者"```"
        - 所有生成的结果都必须通过"print"打印到控制台
        - **重要**：所有 print 语句必须使用 `flush=True` 参数，例如：`print("内容", flush=True)` 或 `print(df, flush=True)`
        - 这是为了确保输出立即显示，不被缓冲

2. 数据查询与处理要求：
    2.1 多行数据处理：
        - 生成代码前需要先根据 excel文件 的数据结构判断用户想要查询的数据是处于"某范围内"还是"某个具体值"
        - 对结果集排序时，必须显式指定`ascending=False`（倒序）或`True`（升序），避免依赖默认排序
    2.2 关键字段处理：
        - 时间字段必须用`pd.to_datetime(..., errors='coerce').dt.normalize()`统一转换，并提取年月日等分量进行比较
        - 对于标识符类字段，建议使用 .astype(str) 进行字符串类型转换，以避免数值格式的意外变化
        - 数值字段必须用`pd.to_numeric(..., errors='coerce')`转换，避免字符串比较数值
        - **重要**：读取数据后，先检查列名：`print("列名:", df.columns.tolist(), flush=True)`，确保列名正确
        - **重要**：如果列名包含 'nan' 或空值，需要先清理列名：`df.columns = [str(col).strip() if pd.notna(col) else f'Column_{i}' for i, col in enumerate(df.columns)]`
    2.3 数据清洗和处理：
        - 列名中可能出现的下划线、多个空格等类似的特殊字符需保持结构不变
        - 读取数据后立即检查：`print(f"数据形状: {df.shape}", flush=True)` 和 `print(f"列名: {df.columns.tolist()}", flush=True)`
        - 如果发现列名有问题（如包含 'nan'），先修复列名再继续分析
    2.4 输出规范：
        - 批量输出时逐行格式化打印
        - **重要**：对于"最高"、"最低"、"排名"、"增长率最高"等明确的问题，必须输出明确的答案
        - 例如：如果问题是"哪个省市增长率最高？"，代码必须输出类似：
          ```python
          print(f"\n答案：{最高增长率的省市}的增长率最高，为{增长率值}%", flush=True)
          ```
        - 对于排序、排名类问题，必须输出前几名及其具体数值
        - 对于对比分析，必须明确指出哪个最大、哪个最小，以及具体数值

3. 代码健壮性要求：
    3.1 异常处理：
        - 代码需要包含异常处理机制，必须用try-except包裹文件操作和数据处理逻辑
        - 捕获FileNotFoundError、KeyError等常见异常并给出友好提示
        - 打印异常时需包含具体错误信息：print(f"错误详情: {str(e)}", flush=True)
    3.2 数据校验：
        - 读取数据后立即检查df.empty，避免操作空DataFrame
        - 对关键筛选字段先用df.columns确认存在性

4. 图表生成要求（**重要：智能判断是否需要生成图表**）：
    - **优先级1：用户明确要求**：
      * 如果用户问题中明确提到"生成图表"、"画图"、"可视化"、"图表"、"chart"、"graph"、"plot"、"可视化"等关键词，**必须**生成图表
      * 例如："生成一个图表"、"画个图看看"、"可视化一下"、"用图表展示"等
    - **优先级2：建议生成图表的情况**（用户未明确要求，但图表有助于理解）：
      * 增长率、趋势分析（如"增长率"、"增长趋势"、"变化趋势"）
      * 数据对比分析（如不同地区、不同时间段、不同类别的对比）
      * 排名、排序分析（如"前10名"、"排名"、"排序"）
      * 统计分析（如分布、占比、比例）
      * 时间序列分析（如按月份、年份、日期分析）
      * 任何涉及多个数值比较的场景
    - **不需要生成图表的情况**（用户未明确要求，且问题简单）：
      * 简单的数据查询（如"查询某个值"、"查找某条记录"）
      * 单一数值计算（如"总和"、"平均值"、"最大值"等单个结果）
      * 数据验证、检查类问题（如"检查数据"、"验证数据"）
      * 简单的数据筛选（如"筛选某个条件的数据"）
      * 如果问题只需要一个简单的答案，不需要可视化
    - **判断原则**：
      1. 如果用户明确要求生成图表，**必须**生成
      2. 如果图表能够帮助用户更好地理解数据关系、趋势或对比，则生成图表
      3. 如果问题只需要一个简单的数值答案，且用户未明确要求，则不需要生成图表
    - 如果判断需要生成图表，使用 plotly 生成相应的图表（柱状图、折线图、饼图等）
    - 图表类型选择：
      * 趋势分析 → 折线图（px.line）
      * 对比分析 → 柱状图（px.bar）
      * 占比分析 → 饼图（px.pie）
      * 排名分析 → 水平柱状图（px.bar, orientation='h'）
      * 时间序列 → 折线图或柱状图
    - 图表标签和标题语言要求（**必须严格遵守**）：
      * **根据用户问题的语言自动适配图表标签和标题的语言**
      * **如果用户问题使用中文，图表的所有标签（title、xaxis_title、yaxis_title、legend等）必须使用中文**
      * **如果用户问题使用英文，图表的所有标签（title、xaxis_title、yaxis_title、legend等）必须使用英文**
      * 数据列名保持原样（如果列名是中文就用中文，如果是英文就用英文）
      * 但图表的标题和轴标签必须与用户问题的语言一致
      * 示例：
        - 中文问题："分析销售额趋势" → 图表 title='销售额趋势图', xaxis_title='日期', yaxis_title='销售额'
        - 英文问题："Analyze sales trend" → 图表 title='Sales Trend', xaxis_title='Date', yaxis_title='Sales'
    - **重要**：不要使用 `fig.show()`，因为这在非交互式环境中会阻塞
    - **重要**：HTML 文件必须保存到 'charts' 目录，文件名使用有意义的名称（基于问题或数据内容，可以使用英文或中文）
    - 使用 `fig.write_html('charts/图表文件名.html')` 保存图表，然后打印文件路径
    - 示例：
      ```python
      import os
      import plotly.express as px
      os.makedirs('charts', exist_ok=True)
      
      # 趋势分析示例（根据数据列名和问题语言选择标题）
      # 如果用户用中文提问，数据列名是中文：
      fig = px.line(df, x='日期', y='销售额', title='销售额趋势图')
      html_file = 'charts/销售额趋势图.html'
      fig.write_html(html_file)
      print(f"图表已保存到: {html_file}", flush=True)
      
      # 如果用户用英文提问，数据列名是英文：
      fig = px.line(df, x='Date', y='Sales', title='Sales Trend')
      html_file = 'charts/sales_trend.html'
      fig.write_html(html_file)
      print(f"Chart saved to: {html_file}", flush=True)
      
      # 对比分析示例
      fig = px.bar(df, x='Region', y='Sales', title='Sales by Region')
      html_file = 'charts/sales_by_region.html'
      fig.write_html(html_file)
      print(f"Chart saved to: {html_file}", flush=True)
      ```

请根据以上规则和用户问题生成**完整、可执行**的 Python 代码。

**重要要求：**
1. 必须生成完整的代码，包括所有必要的导入、数据读取、处理和输出
2. 代码必须可以直接执行，不能只是代码片段
3. 必须包含 try-except 异常处理
4. 必须使用正确的文件路径读取数据
5. 所有结果必须通过 print() 输出

**代码结构示例：**
```python
import pandas as pd
import warnings
warnings.simplefilter(action='ignore', category=Warning)
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)

try:
    # 读取数据
    df = pd.read_excel('文件路径')
    
    # **重要：必须先验证数据**
    print("=" * 50, flush=True)
    print("数据验证信息：", flush=True)
    print(f"数据形状: {df.shape}", flush=True)
    print(f"列名: {df.columns.tolist()}", flush=True)
    print("\n前5行数据：", flush=True)
    print(df.head(), flush=True)
    print("=" * 50, flush=True)
    
    # 检查列名是否有问题
    if any('nan' in str(col).lower() for col in df.columns):
        print("警告：发现无效列名，正在清理...", flush=True)
        df.columns = [str(col).strip() if pd.notna(col) and str(col).lower() != 'nan' else f'Column_{i}' 
                     for i, col in enumerate(df.columns)]
        print(f"清理后的列名: {df.columns.tolist()}", flush=True)
    
    # 数据处理和分析
    # ... 你的分析代码 ...
    
    # 输出结果
    print("\n分析结果:", flush=True)
    # ... 打印结果 ...
    
except Exception as e:
    print(f"发生错误: {str(e)}", flush=True)
    import traceback
    traceback.print_exc()
```

**关键要求：**
1. 读取数据后，**必须**先打印数据形状、列名和前几行数据
2. 如果列名包含 'nan' 或无效值，必须先清理列名
3. 在进行任何计算前，先验证使用的列名是否存在：`if '列名' in df.columns:`
4. 对于数值计算，必须先用 `pd.to_numeric(..., errors='coerce')` 转换，并检查转换后的数据是否合理
5. 如果计算结果异常（如增长率超过1000%），应该检查数据是否正确

现在请生成完整的代码：
"""
            
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "你是一个专业的 Python 数据分析专家，擅长使用 pandas 进行数据分析。你必须生成完整、可执行的 Python 代码。"},
                    {"role": "user", "content": full_prompt}
                ],
                temperature=0.2
            )
            
            raw_code = response.choices[0].message.content.strip()
            logger.info(f"收到原始代码（前200字符）: {raw_code[:200]}")
            
            # 清理代码：移除可能的 markdown 标记
            code = raw_code
            if code.startswith("```python"):
                code = code[9:].strip()
            elif code.startswith("```"):
                code = code[3:].strip()
            if code.endswith("```"):
                code = code[:-3].strip()
            
            code = code.strip()
            
            # 验证代码是否完整
            if not code:
                logger.error("生成的代码为空")
                return f"# 代码生成失败：生成的代码为空\n# 原始输出: {raw_code[:500]}"
            
            if len(code) < 50:
                logger.warning(f"生成的代码过短（{len(code)}字符），可能不完整")
                logger.warning(f"代码内容: {code}")
                # 不直接返回错误，让代码尝试执行，但记录警告
            
            # 检查是否包含必要的导入
            has_pandas = "import pandas" in code or "import pd" in code or "from pandas" in code
            if not has_pandas:
                logger.warning("生成的代码缺少 pandas 导入，尝试添加")
                code = "import pandas as pd\nimport warnings\nwarnings.simplefilter(action='ignore', category=Warning)\npd.set_option('display.max_columns', None)\npd.set_option('display.max_rows', None)\n\n" + code
            
            # 检查是否包含文件读取逻辑
            has_read = "read_excel" in code or "pd.read_excel" in code
            if not has_read:
                logger.warning("生成的代码可能缺少文件读取逻辑")
            
            # 检查是否有 try-except
            if "try:" not in code:
                logger.warning("生成的代码缺少异常处理，尝试添加")
                # 不自动添加，让 LLM 自己生成
            
            logger.info(f"最终代码长度: {len(code)} 字符")
            return code
        except Exception as e:
            logger.error(f"生成代码时出错: {e}", exc_info=True)
            return f"# 代码生成失败: {str(e)}"
    
    def generate_pseudocode(self, code: str) -> str:
        """
        根据 Python 代码生成伪代码
        
        Args:
            code: Python 代码
            
        Returns:
            伪代码字符串
        """
        try:
            prompt = f"""请将以下 Python 代码转换为易于理解的伪代码，用中文描述每个步骤的逻辑。

Python 代码:
```python
{code}
```

请输出伪代码，用中文描述每个步骤。"""
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "你擅长将代码转换为易于理解的伪代码。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            pseudocode = response.choices[0].message.content.strip()
            return pseudocode
        except Exception as e:
            logger.error(f"生成伪代码时出错: {e}", exc_info=True)
            return "伪代码生成失败"


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    
    # 测试代码
    generator = CodeGenerator()
    
    # 模拟文件元数据
    test_metadata = {
        'processed_path': 'test.xlsx',
        'schema': {
            'Sheet1': {
                'columns': ['地区', '销售额', '日期'],
                'dtypes': {'地区': 'object', '销售额': 'float64', '日期': 'datetime64[ns]'},
                'head_sample': [{'地区': '北京', '销售额': 1000, '日期': '2024-01-01'}]
            }
        }
    }
    
    # 生成分析计划
    plan = generator.generate_analysis_plan("分析北京的销售额", test_metadata)
    print("分析计划:", json.dumps(plan, ensure_ascii=False, indent=2))
    
    # 生成代码
    code = generator.generate_code("分析北京的销售额", test_metadata, plan)
    print("\n生成的代码:\n", code)
    
    # 生成伪代码
    pseudocode = generator.generate_pseudocode(code)
    print("\n伪代码:\n", pseudocode)

