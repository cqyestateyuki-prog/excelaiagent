import logging

logger = logging.getLogger(f'2brain.{__name__}')


def chat_excel_code(file_path, question, translation_query, is_need_multi_turn, messages, prompt_parts, html_name):
    logger.info(f'正在处理文件{file_path}')
    prompt = '\n'.join(prompt_parts)
    attention = '''
**Excel数据处理规则集**
1. 基础代码结构要求：
    1.1 必要的导入和设置： 
        - 必要的导入和设置 ```python
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
        - 禁止输出”```python“ 或者”```“。
        - 所有生成的结果都必须通过"print"打印到控制台

2. 数据查询与处理要求：
    2.1 多行数据处理：
        - 生成代码前需要先根据 excel文件 的数据结构判断用户想要查询的数据是处于“某范围内”还是“某个具体值”。
        - 对结果集排序时，必须显式指定`ascending=False`（倒序）或`True`（升序），避免依赖默认排序
    2.2 关键字段处理：
        - 时间字段必须用`pd.to_datetime(..., errors='coerce').dt.normalize()`统一转换，并提取年月日等分量进行比较
        - 对于标识符类字段，建议使用 .astype(str) 进行字符串类型转换，以避免数值格式的意外变化（如前导零丢失、科学计数法显示或精度截断等问题）
        - 数值字段必须用`pd.to_numeric(..., errors='coerce')`转换，避免字符串比较数值
        - 为了确保可以执行数值计算（如求和、比较、聚合和排序等操作），请用"pd.to_numeric(data, errors='coerce')"将数据转换为数值类型后再进行计算，并忽略无法转换的值
    2.3 数据清洗和处理：
        - "DataFrame.fi11na"方法在使用"method"参数时已过时被官方弃用
        - 列名中可能出现的下划线、多个空格等类似的特殊字符需保持结构不变
    2.4 输出规范
        - 批量输出时逐行格式化打印

3. 代码健壮性要求：
    3.1 异常处理
        - 代码需要包含异常处理机制，必须用try-except包裹文件操作和数据处理逻辑
        - 捕获FileNotFoundError、KeyError等常见异常并给出友好提示
        - 打印异常时需包含具体错误信息：print(f"错误详情: {str(e)}")
    3.2 数据校验：
        - 读取数据后立即检查df.empty，避免操作空DataFrame
        - 对关键筛选字段（如"客户名称"）先用df.columns确认存在性
        - 若文件有多个sheet，请为每个符合条件的sheet生成代码

4. 命名规范：
    4.1 变量和函数命名：
        - 如果是想命名一个函数或变量，避免使用符号如#，因为它在很多编程语言中是注释符号，可能会导致语法错误
        - 如果是想命名一个函数或变量，避免使用中文字符，因为可能会导致语法错误
        - 使用有意义的英文变量名，如filtered_df、result_data等

5. 问题拆解原则
    5.1 分析用户需求：
        - 先解析用户问题的关键维度
        - 将自然语言描述转化为对应的pandas操作链
    5.2 防御性编程：
        - 假设原始数据可能存在缺失值、类型混乱或特殊字符
'''
    # content = prompt + question + attention
    attention = attention + f"""    * 如果用户的提问中指出需要形成一个图表结构则需要根据代码输出结果与 "import plotly.graph_objects as go" 生成一个可交互的本地html页面，
      页面名只能为{html_name}，其中go.Figure的mode参数值为"lines+markers+text",
      fig.update_layout的title（需要居中展示）、xaxis_title、yaxis_title不得缺失，X轴的数据需要从小到大进行排序后再绘制图表。"""


def drop_and_merge_excel(excel_info, merged_info):
    system = '''你是一个专业的结构化数据处理AI，具有以下核心能力：
1. 能精确识别Excel工作表中的多级表头结构（包括跨行合并的表头）
2. 能准确区分表单级说明文本（针对整个工作表的说明）和数据行内说明文本（如产品介绍等字段）
3. 严格遵守数据行不可误判为说明文本的原则
4. 对每个工作表进行独立分析，不受其他工作表影响
'''

    prompt = f'''请根据以下数据精确分析每个工作表的结构，分别输出每个表单应该去掉哪几行说明性文本（不包含数据行内说明性文本），哪几行为多级表头：
1. 取消合并单元格后的Excel文件数据：
```
{excel_info}
```
2. 原始合并单元格信息（用于判断表头层级）：
```
{merged_info}
```
输出格式：
[
    {{
        "sheet_name1": {{
            "labels": [行号列表],    # 整个工作表的说明文本行（无则[]）
            "header": [行号列表]     # 多级表头行（至少包含1行）
        }},
        "sheet_name2": {{
            "labels": [行号列表],
            "header": [行号列表]
        }}
    }}
]
注意:
    1. 每个表单，不可受其他表单的影响。
    2. 不一定每个表单都会有说明性文本，判断说明性文本的时候需要判断与表头之间的关系，避免误判数据行为说明性文本，不一定每个表单都有多级表头，没有说明性文本的"labels"输出空列表即可，没有多级表头"header"输出列表类型的单表头即可。
    3. 注意多级表头可能有表头跨多行的情况。
    4. labels列表与header列表中都不可以输出行号以外的值，"labels": [1, 2]表示第一行与第二行，"header": [3]表示第三行。
    5. sheet_name1、sheet_name2等表单名必须和源文件中的表单名保持一致。
    6. 严格遵守输出格式，仅输出结果即可，无需任何其他解释。
示例正确输出：
[
    {{"sheet_name1":
        {{
            "labels": [1, 2],
            "header": [3, 4, 5]
        }}
    }},
    {{"sheet_name2":
        {{
            "labels": [1, 2],
            "header": [3, 4, 5]
        }}
    }},
    {{"sheet_name3":
        {{
            "labels": [],
            "header": [1, 2]
        }}
    }},
    {{"sheet_name4":
        {{
            "labels": [1, 2],
            "header": [3]
        }}
    }}
]
'''
