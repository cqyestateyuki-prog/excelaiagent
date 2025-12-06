# pip install tabulate openpyxl pandas
import json
import logging
import os
import openpyxl
import uuid

import pandas as pd
from openpyxl.utils import get_column_letter
from collections import OrderedDict

logger = logging.getLogger(f'2brain.{__name__}')


def drop_and_merge_excel(excel_info, merged_info, api_key=None):
    """
    使用 LLM 分析 Excel 表头结构，识别说明性文本和多级表头
    
    Args:
        excel_info: 取消合并后的 Excel 前几行数据
        merged_info: 原始合并单元格信息
        api_key: OpenAI API Key
        
    Returns:
        JSON 字符串，包含每个 sheet 的 labels 和 header 配置
    """
    try:
        from openai import OpenAI
        import time
        
        client = OpenAI(api_key=api_key) if api_key else OpenAI()
        
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
'''
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    timeout=60.0
                )
                result = response.choices[0].message.content.strip()
                # 清理可能的 markdown 标记
                result = result.replace('```json', '').replace('```', '').strip()
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"LLM 调用失败，{wait_time}秒后重试 ({attempt + 1}/{max_retries}): {str(e)}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"LLM 调用失败，已重试 {max_retries} 次: {str(e)}")
                    raise
    except Exception as e:
        logger.error(f"分析表头结构失败: {e}", exc_info=True)
        # 返回默认配置：第一行作为表头，不删除任何行
        logger.warning("使用默认配置：第一行作为表头")
        return '{"default": {"labels": [], "header": [1]}}'


def get_excel_data(file_path, head=10):
    try:
        all_sheets_data = pd.read_excel(file_path, sheet_name=None, header=None)
        prompt_parts = []

        for sheet_name, data in all_sheets_data.items():
            data.index = data.index + 1
            excel_col_names = [get_column_letter(i + 1) for i in range(len(data.columns))]
            data.columns = excel_col_names  # 替换默认的 `0, 1, 2...` 为 `A, B, C...`

            # 修复：使用 map 替代 applymap，并处理换行符
            data = data.map(lambda x: str(x).replace('\n', ' ') if isinstance(x, str) else x)

            try:
                sheet_first_rows = data.head(head).to_markdown(index=True)
            except ImportError:
                # 如果没有 tabulate，使用 to_string 作为备选
                logger.warning("tabulate 未安装，使用 to_string 替代")
                sheet_first_rows = data.head(head).to_string(index=True)
            
            sheet_info = f"Sheet: {sheet_name}\n前 {head} 行数据为：\n\n{sheet_first_rows}\n\n---"
            prompt_parts.append(sheet_info)
        return prompt_parts
    except Exception as e:
        logger.error(f"提取prompt：\n{e}", exc_info=True)
        return []  # 返回空列表而不是 None


def unmerge_and_fill_excel(input_path, unmerged_file):
    try:
        logger.info("开始取消所有 Sheet 的合并单元格...")

        # 读取 Excel 文件
        wb = openpyxl.load_workbook(input_path, data_only=True)
        logger.info(f"读取 Excel 文件：{input_path} 完成")

        merged_info = {}  # 用于存储合并单元格信息，按每个 sheet 名称分类

        # 遍历所有 Sheet
        for ws in wb.worksheets:
            logger.info(f"正在处理表单：{ws.title} ...")

            # 收集前7行的合并单元格信息
            sheet_merged_info = []

            # 遍历所有合并单元格
            for merged_range in list(ws.merged_cells.ranges):
                # 获取合并单元格的范围
                min_row, min_col, max_row, max_col = (
                    merged_range.min_row, merged_range.min_col, merged_range.max_row, merged_range.max_col
                )
                value = ws.cell(row=min_row, column=min_col).value  # 获取合并单元格的主值
                logger.info(f"发现合并单元格：{merged_range}, 值：{value}")

                # 只收集前6行的合并单元格信息
                if max_row <= 6:
                    sheet_merged_info.append({
                        "merged_range": str(merged_range),
                        "start_cell": (min_row, min_col),
                        "end_cell": (max_row, max_col),
                        "value": value
                    })

                # 取消合并单元格
                ws.unmerge_cells(start_row=min_row, start_column=min_col, end_row=max_row, end_column=max_col)
                logger.info(f"取消合并单元格：({min_row}, {min_col}) 到 ({max_row}, {max_col})")

                # 填充所有拆分后的单元格
                logger.info(f"填充单元格的值")
                for row in range(min_row, max_row + 1):
                    for col in range(min_col, max_col + 1):
                        ws.cell(row=row, column=col, value=value)

            # 保存当前表单的合并单元格信息
            merged_info[ws.title] = sheet_merged_info
            logger.info(f"表单 {ws.title} 处理完成")

        # 保存处理后的 Excel 文件
        wb.save(unmerged_file)
        logger.info(f"Excel 处理完成，已保存至：{unmerged_file}")
        return unmerged_file, merged_info
    except Exception as e:
        logger.error(f"Excel 处理报错：\n{e}", exc_info=True)


def deduplication_header(drop_file, output_path, header, sheet_name, writer):
    try:
        # 先检查 sheet 是否存在
        excel_file = pd.ExcelFile(drop_file)
        available_sheets = excel_file.sheet_names
        
        if sheet_name not in available_sheets:
            logger.error(f"Sheet '{sheet_name}' 不存在于文件 {drop_file} 中。可用 sheet: {available_sheets}")
            return False
        
        # 读取指定的 Sheet 文件
        logger.info(f"读取表头，header={header}, sheet={sheet_name}")
        df = pd.read_excel(drop_file, sheet_name=sheet_name, header=header, dtype=object)
        
        # 记录读取到的原始列名
        logger.info(f"读取到的原始列名: {df.columns.tolist()[:5]}...")  # 只记录前5个
        
        if len(header) == 1:
            df.columns = [df.columns]
        
        # 去重并拼接表头，参考旧版本的简单逻辑
        new_columns = []
        for idx, col in enumerate(df.columns):
            # 处理多级表头：如果是 tuple，去重；否则转为列表
            if isinstance(col, tuple):
                deduplication_col = list(OrderedDict.fromkeys(col))  # 使用 fromkeys 去重并保持顺序
            else:
                deduplication_col = [col]
            
            # 直接过滤掉包含 'Unnamed' 的部分，然后拼接（参考旧版本逻辑）
            # 但保留空字符串和 NaN，因为它们可能是有效的表头部分（比如多级表头中的空单元格）
            valid_parts = []
            for header_part in deduplication_col:
                header_str = str(header_part)
                # 只过滤掉明确是 'Unnamed' 的，保留其他内容（包括空字符串）
                if 'Unnamed' not in header_str:
                    # 如果非空，添加到有效部分
                    if header_str.strip():
                        valid_parts.append(header_str.strip())
                    # 如果是空字符串，在多级表头中可能是有意义的，但这里先跳过
            
            # 如果过滤后还有有效部分，拼接；否则尝试从数据推断或使用默认列名
            if valid_parts:
                valid_header = '-'.join(valid_parts).strip()
                # 如果拼接后为空（比如全是空格），使用默认列名
                if not valid_header:
                    valid_header = f'Column_{idx}'
            else:
                # 如果所有部分都被过滤掉了，可能是表头行号配置错误
                # 记录警告并使用默认列名
                logger.warning(f"列 {idx} 的所有表头部分都被过滤，原始列名: {deduplication_col}")
                valid_header = f'Column_{idx}'
            
            new_columns.append(valid_header)
        
        # 确保列名唯一：如果有重复，添加后缀
        seen = {}
        unique_columns = []
        for col in new_columns:
            if col in seen:
                seen[col] += 1
                unique_columns.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                unique_columns.append(col)
        
        # 更新 DataFrame 的列名
        df.columns = unique_columns

        # 将处理后的 DataFrame 写入 Excel
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        logger.info(f"成功处理表头，列数: {len(unique_columns)}, 数据行数: {len(df)}")
        return True
    except Exception as e:
        logger.error(f'合并多级表头报错:\n{e}', exc_info=True)
        return False


def drop_rows(final_unmerged, drop_file, labels, sheet_name):
    try:
        # 先检查 sheet 是否存在
        excel_file = pd.ExcelFile(final_unmerged)
        available_sheets = excel_file.sheet_names
        
        if sheet_name not in available_sheets:
            logger.error(f"Sheet '{sheet_name}' 不存在。可用 sheet: {available_sheets}")
            return None
        
        # 读取指定的 Sheet 文件
        df = pd.read_excel(final_unmerged, sheet_name=sheet_name, header=None)

        # 删除指定的行
        df = df.drop(labels, axis=0, errors='ignore')  # errors='ignore' 确保如果没有这些行也不会报错

        # 将修改后的 DataFrame 写入 Excel
        with pd.ExcelWriter(drop_file, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)

        return drop_file
    except Exception as e:
        logger.error(f'删除指定文本行报错:\n{e}', exc_info=True)
        return None


def main_unmerge_file(input_file, output_path, api_key=None):
    """
    主函数：处理复杂表头 Excel 文件
    
    Args:
        input_file: 输入文件路径
        output_path: 输出文件路径
        api_key: OpenAI API Key（可选）
    """
    # 将临时文件创建在临时目录，避免污染项目目录
    import tempfile
    temp_dir = tempfile.gettempdir()
    unmerged_file = None
    
    try:
        # 解除合并文件
        unmerged_file = os.path.join(temp_dir, f"unmerged_file_{uuid.uuid4()}.xlsx")  # 使用临时目录
        try:
            _, merged_info = unmerge_and_fill_excel(input_file, unmerged_file)

            sheet_info = get_excel_data(file_path=unmerged_file)  # 获取每个表单前10行数据（按文档要求）
            if not sheet_info or not isinstance(sheet_info, list):
                logger.error(f"获取 Excel 数据失败，sheet_info 为空或类型错误: {type(sheet_info)}")
                return None
            excel_info = '\n'.join(sheet_info)
            
            # 使用 LLM 分析表头结构
            lable_info = drop_and_merge_excel(excel_info=excel_info,
                                              merged_info=merged_info,
                                              api_key=api_key)  # 根据前10行数据，让大模型指出应该删除的说明性文本以及应该合并的多级表头
            logger.info(f'LLM 分析结果:\n{lable_info}')
            
            # 解析 JSON 结果
            try:
                # 清理可能的 markdown 标记
                cleaned_info = lable_info.replace('```json', '').replace('```', '').strip()
                lable_info_json = json.loads(cleaned_info)
                
                # 统一转换为列表格式：每个元素是 {sheet_name: config} 的字典
                normalized_list = []
                
                if isinstance(lable_info_json, dict):
                    # 如果是字典，检查是否有多个键（可能是多个sheet在一个字典中）
                    if len(lable_info_json) > 1:
                        # 多个sheet在一个字典中，需要拆分成多个字典
                        for k, v in lable_info_json.items():
                            if isinstance(v, dict):
                                normalized_list.append({k: v})
                            else:
                                logger.warning(f"跳过无效的配置项: {k} -> {v}")
                    else:
                        # 单个sheet，直接转换
                        normalized_list = [{k: v} for k, v in lable_info_json.items()]
                elif isinstance(lable_info_json, list):
                    # 如果已经是列表，处理每个元素
                    for item in lable_info_json:
                        if isinstance(item, dict):
                            # 检查字典中是否有多个键
                            if len(item) > 1:
                                # 多个sheet在一个字典中，需要拆分
                                for k, v in item.items():
                                    if isinstance(v, dict):
                                        normalized_list.append({k: v})
                                    else:
                                        logger.warning(f"跳过无效的配置项: {k} -> {v}")
                            else:
                                # 单个sheet，直接添加
                                normalized_list.append(item)
                        else:
                            logger.warning(f"跳过无效的配置项: {item}")
                else:
                    raise ValueError(f"不支持的 JSON 格式: {type(lable_info_json)}")
                
                lable_info_json = normalized_list
                
                if not lable_info_json:
                    raise ValueError("解析后的配置列表为空")
                    
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"解析 LLM 返回的 JSON 失败: {e}")
                logger.error(f"原始内容: {lable_info[:500]}")
                return None

            logger.info(f'JSON转换后处理结果:\n{lable_info_json}')

            # 先获取 unmerged_file 中实际存在的 sheet 名称
            excel_file = pd.ExcelFile(unmerged_file)
            available_sheets = excel_file.sheet_names
            logger.info(f"可用 sheet 列表: {available_sheets}")
            
            # 使用同一个 ExcelWriter 写入所有表单
            sheets_processed = 0
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                # 处理每个 sheet 的配置
                for sheet_config in lable_info_json:
                    # sheet_config 应该是 {sheet_name: config} 格式
                    if not isinstance(sheet_config, dict) or len(sheet_config) != 1:
                        logger.warning(f"跳过无效的配置格式: {sheet_config}")
                        continue
                    
                    sheet_name = list(sheet_config.keys())[0]
                    config = sheet_config[sheet_name]
                    # 验证 sheet 名称是否存在，如果不存在尝试模糊匹配
                    matched_sheet_name = sheet_name
                    if sheet_name not in available_sheets:
                        # 尝试模糊匹配（忽略大小写和空格）
                        for available_sheet in available_sheets:
                            if sheet_name.lower().strip() == available_sheet.lower().strip():
                                matched_sheet_name = available_sheet
                                logger.info(f"Sheet 名称匹配: '{sheet_name}' -> '{matched_sheet_name}'")
                                break
                        
                        if matched_sheet_name not in available_sheets:
                            logger.warning(f"Sheet '{sheet_name}' 不存在于文件中，跳过。可用 sheet: {available_sheets}")
                            continue
                        
                    labels = config.get('labels', [])  # 获取需要删除的行
                    header = config.get('header', [1])  # 获取表头行号，默认第一行
                    
                    if not header:
                        logger.error(f"Sheet '{matched_sheet_name}' 的 header 配置为空，跳过")
                        continue
                    
                    # 调整行号（从1开始转换为从0开始）
                    # 注意：labels 和 header 都是原始文件中的行号（从1开始）
                    labels_idx = []
                    if labels:
                        labels_idx = [max(0, x - 1) for x in labels if x > 0]  # 转换为从0开始的索引
                    
                    # header 行号转换为从0开始，并减去已删除的行数
                    header_idx = []
                    if header:
                        for h in header:
                            if h > 0:
                                h_idx = h - 1  # 转换为从0开始的索引
                                # 计算删除的行中，小于当前 header 行号的数量
                                deleted_before = sum(1 for l in labels_idx if l < h_idx)
                                header_idx.append(max(0, h_idx - deleted_before))
                    else:
                        header_idx = [0]  # 默认第一行作为表头
                    
                    header = header_idx
                    labels = labels_idx
                    
                    # 将临时文件也创建在临时目录
                    drop_file = os.path.join(temp_dir, f'{matched_sheet_name}_modified_{uuid.uuid4()}.xlsx')

                    # 删除指定行
                    drop_result = drop_rows(unmerged_file, drop_file, labels, matched_sheet_name)
                    if not drop_result or not os.path.exists(drop_file):
                        logger.error(f"删除指定行失败或临时文件不存在，跳过 sheet: {matched_sheet_name}, 文件: {drop_file}")
                        continue
                    
                    # 处理表头去重并将结果写入同一个文件
                    header_result = deduplication_header(drop_file, output_path, header, matched_sheet_name, writer)
                    if os.path.exists(drop_file):
                        os.remove(drop_file)
                    if header_result:
                        sheets_processed += 1
                        logger.info(f"处理完毕：{matched_sheet_name} 表单保存至 {output_path}")
                    else:
                        logger.error(f"处理表头失败，跳过 sheet: {matched_sheet_name}")
            
            # 如果没有成功处理任何 sheet，返回 None（不进行降级处理）
            if sheets_processed == 0:
                logger.error("没有成功处理任何 sheet，预处理失败")
                return None
        finally:
            # 确保临时文件被清理
            if unmerged_file and os.path.exists(unmerged_file):
                try:
                    os.remove(unmerged_file)
                    logger.debug(f"已清理临时文件: {unmerged_file}")
                except Exception as cleanup_err:
                    logger.warning(f"清理临时文件失败 {unmerged_file}: {cleanup_err}")
        return output_path
    except Exception as e:
        logger.error(f'拆解复杂表头报错{e}', exc_info=True)
        # 确保异常时也清理临时文件
        if unmerged_file and os.path.exists(unmerged_file):
            try:
                os.remove(unmerged_file)
                logger.debug(f"异常后清理临时文件: {unmerged_file}")
            except Exception as cleanup_err:
                logger.warning(f"异常后清理临时文件失败 {unmerged_file}: {cleanup_err}")
        return None


if __name__ == '__main__':
    input_file = '复杂表头.xlsx'
    # 输出文件路径
    output_path1 = "output_path.xlsx"
    main_unmerge_file(input_file, output_path1)
