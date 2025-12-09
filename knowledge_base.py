"""
知识库管理模块：预处理 Excel 文件，提取元数据，建立索引
"""
import os
import json
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from dismantle_excel import main_unmerge_file
from openai import OpenAI
import uuid

logger = logging.getLogger(f'excel_agent.{__name__}')

class KnowledgeBase:
    """知识库管理类"""
    
    def __init__(self, excel_dir: str, processed_dir: str = "processed_excel", 
                 metadata_file: str = "metadata.json", api_key: Optional[str] = None):
        """
        初始化知识库
        
        Args:
            excel_dir: Excel 文件目录
            processed_dir: 处理后的 Excel 文件存储目录
            metadata_file: 元数据文件路径
            api_key: OpenAI API Key
        """
        self.excel_dir = Path(excel_dir)
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(exist_ok=True)
        self.metadata_file = Path(metadata_file)
        self.metadata: Dict = {}
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        
        # 加载已有元数据
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
                logger.info(f"成功加载元数据，共 {len(self.metadata)} 个文件")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"元数据文件损坏，将重新构建: {e}")
                # 备份损坏的文件
                backup_path = self.metadata_file.with_suffix('.json.bak')
                try:
                    import shutil
                    shutil.copy2(self.metadata_file, backup_path)
                    logger.info(f"已备份损坏的元数据文件到: {backup_path}")
                except Exception:
                    pass
                self.metadata = {}
            except Exception as e:
                logger.error(f"加载元数据时出错: {e}", exc_info=True)
                self.metadata = {}
    
    def preprocess_excel(self, file_path: str) -> Optional[str]:
        """
        预处理 Excel 文件：将复杂表格重塑为二维表
        
        Args:
            file_path: Excel 文件路径
            
        Returns:
            处理后的文件路径，失败返回 None
        """
        try:
            file_path = Path(file_path)
            output_path = self.processed_dir / f"processed_{file_path.stem}_{uuid.uuid4().hex[:8]}.xlsx"
            
            logger.info(f"开始预处理文件: {file_path}")
            # 传递 API key 给预处理函数
            api_key = os.getenv("OPENAI_API_KEY")
            result = main_unmerge_file(str(file_path), str(output_path), api_key=api_key)
            
            if result:
                logger.info(f"预处理完成: {output_path}")
                return str(output_path)
            else:
                # 预处理失败，记录详细错误信息，不进行降级处理
                logger.error(f"预处理失败: {file_path}")
                logger.error("请检查：")
                logger.error("1. OpenAI API Key 是否配置正确")
                logger.error("2. 文件格式是否正确")
                logger.error("3. 查看上面的详细错误日志")
                return None
        except Exception as e:
            logger.error(f"预处理 Excel 文件时出错: {e}", exc_info=True)
            return None
    
    def extract_schema(self, file_path: str) -> Dict:
        """
        提取 Excel 文件的结构信息（Schema）
        
        Args:
            file_path: Excel 文件路径
            
        Returns:
            包含表头、数据类型、数据样本的结构信息
        """
        try:
            # 尝试读取，如果失败则尝试不同的 header 设置
            all_sheets_data = None
            try:
                all_sheets_data = pd.read_excel(file_path, sheet_name=None)
            except Exception as e:
                logger.warning(f"使用默认 header 读取失败，尝试 header=None: {e}")
                try:
                    all_sheets_data = pd.read_excel(file_path, sheet_name=None, header=None)
                except Exception as e2:
                    logger.error(f"读取 Excel 文件失败: {e2}")
                    return {}
            
            schema = {}
            
            for sheet_name, df in all_sheets_data.items():
                # 清理列名：处理 nan、空值和 Unnamed
                cleaned_columns = []
                for i, col in enumerate(df.columns):
                    col_str = str(col)
                    # 检查是否是无效列名
                    if (pd.isna(col) or 
                        col_str.lower() == 'nan' or 
                        col_str.lower() == 'none' or
                        'Unnamed' in col_str or
                        col_str.strip() == ''):
                        # 尝试从第一行数据推断列名
                        if len(df) > 0:
                            first_row_val = df.iloc[0, i]
                            if pd.notna(first_row_val) and str(first_row_val).strip() != '':
                                cleaned_columns.append(str(first_row_val).strip())
                            else:
                                cleaned_columns.append(f'Column_{i}')
                        else:
                            cleaned_columns.append(f'Column_{i}')
                    else:
                        cleaned_columns.append(col_str.strip())
                
                # 确保列名唯一
                seen = {}
                unique_columns = []
                for col in cleaned_columns:
                    if col in seen:
                        seen[col] += 1
                        unique_columns.append(f"{col}_{seen[col]}")
                    else:
                        seen[col] = 0
                        unique_columns.append(col)
                
                df.columns = unique_columns
                
                # 如果第一行是列名，删除第一行
                if len(df) > 0 and df.iloc[0, 0] in unique_columns:
                    df = df.iloc[1:].reset_index(drop=True)
                
                # 提取列名
                columns = df.columns.tolist()
                
                # 提取数据类型
                dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
                
                # 提取前5行和后5行作为样本，将 Timestamp 等对象转换为字符串
                def convert_to_serializable(obj):
                    """将 pandas 对象转换为可序列化的格式"""
                    if pd.isna(obj):
                        return None
                    if isinstance(obj, (pd.Timestamp, pd.DatetimeTZDtype)):
                        return str(obj)
                    if isinstance(obj, (pd.Timedelta, pd.TimedeltaIndex)):
                        return str(obj)
                    if hasattr(obj, 'item'):  # numpy 标量
                        return obj.item()
                    return obj
                
                # 转换样本数据
                head_sample = []
                for record in df.head(5).to_dict('records'):
                    head_sample.append({k: convert_to_serializable(v) for k, v in record.items()})
                
                tail_sample = []
                for record in df.tail(5).to_dict('records'):
                    tail_sample.append({k: convert_to_serializable(v) for k, v in record.items()})
                
                # 统计信息，转换 null_counts 中的值
                null_counts = df.isnull().sum().to_dict()
                null_counts_serializable = {k: int(v) for k, v in null_counts.items()}
                
                schema[sheet_name] = {
                    'columns': columns,
                    'dtypes': dtypes,
                    'head_sample': head_sample,
                    'tail_sample': tail_sample,
                    'stats': {
                        'row_count': len(df),
                        'column_count': len(df.columns),
                        'null_counts': null_counts_serializable
                    }
                }
            
            return schema
        except Exception as e:
            logger.error(f"提取 Schema 时出错: {e}", exc_info=True)
            return {}
    
    def generate_summary(self, file_path: str, schema: Dict) -> str:
        """
        使用 LLM 生成文件内容摘要（英文）
        
        Args:
            file_path: Excel 文件路径
            schema: 文件结构信息
            
        Returns:
            文件内容摘要（英文）
        """
        try:
            # 构建 prompt（英文）
            schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
            prompt = f"""Please analyze the following Excel file structure information and generate a concise content summary (50-100 words) describing the main purpose of this file, the data types it contains, and key fields.

File path: {file_path}

Structure information:
{schema_str}

Please output only the summary content in English, without any additional explanations."""
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional data analyst skilled in understanding Excel file structures and content. Always respond in English."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            summary = response.choices[0].message.content.strip()
            return summary
        except Exception as e:
            logger.error(f"生成摘要时出错: {e}", exc_info=True)
            return f"Excel file containing {len(schema)} worksheet(s)"
    
    def build_index(self, force_rebuild: bool = False):
        """
        构建知识库索引：扫描 Excel 目录，预处理文件，提取元数据
        
        Args:
            force_rebuild: 是否强制重建索引
        """
        logger.info("开始构建知识库索引...")
        
        # 获取所有 Excel 文件
        excel_files = list(self.excel_dir.glob("*.xlsx")) + list(self.excel_dir.glob("*.xls"))
        
        if not excel_files:
            logger.warning(f"在目录 {self.excel_dir} 中未找到 Excel 文件")
            return
        
        logger.info(f"找到 {len(excel_files)} 个 Excel 文件")
        
        processed_count = 0
        skipped_count = 0
        error_count = 0
        
        for excel_file in excel_files:
            file_key = str(excel_file.relative_to(self.excel_dir))
            
            # 如果已存在且不强制重建，跳过
            if not force_rebuild and file_key in self.metadata:
                logger.info(f"跳过已处理文件: {excel_file}")
                skipped_count += 1
                continue
            
            logger.info(f"处理文件: {excel_file}")
            
            try:
                # 预处理文件
                processed_path = self.preprocess_excel(str(excel_file))
                if not processed_path:
                    logger.warning(f"预处理失败，跳过文件: {excel_file}")
                    error_count += 1
                    continue
                
                # 提取结构信息
                schema = self.extract_schema(processed_path)
                if not schema:
                    logger.warning(f"提取结构信息失败，跳过文件: {excel_file}")
                    error_count += 1
                    continue
                
                # 生成摘要
                summary = self.generate_summary(str(excel_file), schema)
                
                # 保存元数据
                self.metadata[file_key] = {
                    'original_path': str(excel_file),
                    'processed_path': processed_path,
                    'schema': schema,
                    'summary': summary
                }
                processed_count += 1
                logger.info(f"成功处理文件: {excel_file}")
            except Exception as e:
                logger.error(f"处理文件 {excel_file} 时出错: {e}", exc_info=True)
                error_count += 1
                continue
        
        # 保存元数据到文件
        self.save_metadata()
        
        # 构建结果消息
        total_files = len(excel_files)
        result_message = f"知识库索引构建完成: 成功 {processed_count} 个，跳过 {skipped_count} 个，失败 {error_count} 个，总计 {len(self.metadata)} 个文件"
        logger.info(result_message)
        
        # 如果有错误，抛出异常以便前端显示
        if error_count > 0 and processed_count == 0:
            # 所有文件都处理失败
            raise Exception(f"所有文件处理失败。\n\n处理结果：\n- 成功: {processed_count} 个\n- 失败: {error_count} 个\n- 跳过: {skipped_count} 个\n\n请检查日志文件 logs/excel_agent.log 查看详细错误信息。")
        elif error_count > 0:
            # 部分文件处理失败，记录警告但不抛出异常
            logger.warning(f"部分文件处理失败: {error_count} 个文件")
        
        return result_message
    
    def save_metadata(self):
        """保存元数据到文件"""
        try:
            # 自定义 JSON encoder 处理特殊类型
            class MetadataEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, (pd.Timestamp, pd.DatetimeTZDtype)):
                        return str(obj)
                    if isinstance(obj, (pd.Timedelta, pd.TimedeltaIndex)):
                        return str(obj)
                    if hasattr(obj, 'item'):  # numpy 标量
                        return obj.item()
                    return super().default(obj)
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2, cls=MetadataEncoder)
            logger.info(f"元数据已保存到: {self.metadata_file}")
        except Exception as e:
            logger.error(f"保存元数据时出错: {e}", exc_info=True)
    
    def search_files(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        使用语义搜索定位相关 Excel 文件
        
        Args:
            query: 用户查询
            top_k: 返回前 k 个最相关文件
            
        Returns:
            相关文件列表，每个元素包含文件信息和相关性
        """
        try:
            # 构建所有文件的摘要列表
            summaries = []
            for file_key, meta in self.metadata.items():
                summaries.append({
                    'file_key': file_key,
                    'summary': meta['summary'],
                    'metadata': meta
                })
            
            if not summaries:
                return []
            
            # 使用 LLM 进行语义匹配
            summaries_text = "\n".join([
                f"{i+1}. {s['file_key']}: {s['summary']}"
                for i, s in enumerate(summaries)
            ])
            
            prompt = f"""根据用户的问题，从以下文件摘要中找出最相关的文件（最多 {top_k} 个）。

用户问题: {query}

文件摘要列表:
{summaries_text}

请以 JSON 格式输出，格式如下：
{{
    "relevant_files": [
        {{"file_key": "文件名", "relevance": "相关性说明"}},
        ...
    ]
}}

只输出 JSON，不要包含其他内容。"""
            
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一个专业的数据检索助手，擅长根据用户问题匹配相关数据文件。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(response.choices[0].message.content)
                relevant_files = []
                
                for item in result.get('relevant_files', [])[:top_k]:
                    file_key = item['file_key']
                    if file_key in self.metadata:
                        relevant_files.append({
                            'file_key': file_key,
                            'relevance': item.get('relevance', ''),
                            'metadata': self.metadata[file_key]
                        })
                
                return relevant_files
            except Exception as e:
                logger.error(f"LLM 搜索失败，使用简单匹配: {e}")
                # 如果 LLM 搜索失败，使用简单的关键词匹配
                query_lower = query.lower()
                relevant_files = []
                for s in summaries:
                    if any(word in s['summary'].lower() for word in query_lower.split()):
                        relevant_files.append({
                            'file_key': s['file_key'],
                            'relevance': '关键词匹配',
                            'metadata': s['metadata']
                        })
                        if len(relevant_files) >= top_k:
                            break
                return relevant_files
        except Exception as e:
            logger.error(f"搜索文件时出错: {e}", exc_info=True)
            # 如果搜索失败，返回所有文件
            return [
                {'file_key': k, 'relevance': '', 'metadata': v}
                for k, v in list(self.metadata.items())[:top_k]
            ]
    
    def get_file_metadata(self, file_key: str) -> Optional[Dict]:
        """获取指定文件的元数据"""
        return self.metadata.get(file_key)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    kb = KnowledgeBase(
        excel_dir=".",
        processed_dir="processed_excel",
        metadata_file="metadata.json"
    )
    
    # 构建索引
    kb.build_index(force_rebuild=False)
    
    # 测试搜索
    results = kb.search_files("分析销售额数据", top_k=2)
    print("\n搜索结果:")
    for r in results:
        print(f"- {r['file_key']}: {r['relevance']}")

