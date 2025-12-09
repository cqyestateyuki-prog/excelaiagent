"""数据追溯模块：分析生成的代码使用了哪些数据列"""
import ast
import re
import logging
from typing import Dict, List, Set, Optional

logger = logging.getLogger(f'excel_agent.{__name__}')

class DataTracer:
    """数据追溯器：分析代码中使用的数据列"""
    
    def __init__(self):
        self.used_columns: Set[str] = set()
        self.column_info: Dict[str, Dict] = {}
    
    def trace_code(self, code: str, metadata: Dict) -> Dict:
        """
        追溯代码中使用的数据列
        
        Args:
            code: 生成的 Python 代码
            metadata: Excel 文件的元数据，包含列信息
            
        Returns:
            追溯结果字典，包含：
            - used_columns: 使用的列名列表
            - column_info: 列信息字典（列名 -> {sheet, dtype}）
            - total_columns_used: 使用的列总数
        """
        self.used_columns.clear()
        self.column_info.clear()
        
        try:
            tree = ast.parse(code)
            self._visit_node(tree, metadata)
        except SyntaxError as e:
            logger.warning(f"代码语法错误，无法追溯: {e}")
            return {
                'used_columns': [],
                'column_info': {},
                'total_columns_used': 0
            }
        
        used_columns = sorted(list(self.used_columns))
        
        return {
            'used_columns': used_columns,
            'column_info': self.column_info,
            'total_columns_used': len(used_columns)
        }
    
    def _visit_node(self, node: ast.AST, metadata: Dict):
        """递归访问 AST 节点"""
        if isinstance(node, ast.Name):
            self._check_column_name(node.id, metadata)
        elif isinstance(node, ast.Attribute):
            # 处理 df.column_name 或 df['column_name'] 的情况
            if isinstance(node.value, ast.Name):
                var_name = node.value.id
                if var_name in ['df', 'data', 'df_merged']:
                    attr_name = node.attr
                    self._check_column_name(attr_name, metadata)
        elif isinstance(node, ast.Subscript):
            # 处理 df['column_name'] 的情况
            if isinstance(node.value, ast.Name):
                var_name = node.value.id
                if var_name in ['df', 'data', 'df_merged']:
                    if isinstance(node.slice, ast.Constant):
                        col_name = node.slice.value
                        if isinstance(col_name, str):
                            self._check_column_name(col_name, metadata)
                    elif isinstance(node.slice, ast.Index):  # Python < 3.9
                        if isinstance(node.slice.value, ast.Constant):
                            col_name = node.slice.value.value
                            if isinstance(col_name, str):
                                self._check_column_name(col_name, metadata)
                    elif isinstance(node.slice, ast.Str):  # Python < 3.8
                        col_name = node.slice.s
                        if isinstance(col_name, str):
                            self._check_column_name(col_name, metadata)
        
        # 递归访问子节点
        for child in ast.iter_child_nodes(node):
            self._visit_node(child, metadata)
    
    def _check_column_name(self, name: str, metadata: Dict):
        """检查名称是否是数据列名"""
        # 从 metadata 中查找列信息
        sheets = metadata.get('sheets', {})
        
        for sheet_name, sheet_data in sheets.items():
            columns = sheet_data.get('columns', [])
            for col_info in columns:
                col_name = col_info.get('name', '')
                if col_name == name:
                    self.used_columns.add(name)
                    # 保存列信息
                    if name not in self.column_info:
                        self.column_info[name] = {
                            'sheet': sheet_name,
                            'dtype': col_info.get('dtype', '未知')
                        }
                    break
    
    def extract_columns_from_code(self, code: str, schema: Dict) -> Set[str]:
        """
        从代码中提取使用的数据列
        
        Args:
            code: Python 代码
            schema: 文件结构信息
            
        Returns:
            使用的列名集合
        """
        used_columns = set()
        
        try:
            # 方法1: 使用 AST 解析代码
            try:
                tree = ast.parse(code)
                used_columns.update(self._extract_from_ast(tree, schema))
            except SyntaxError:
                logger.warning("代码语法错误，使用正则表达式提取")
            
            # 方法2: 使用正则表达式提取列名引用
            used_columns.update(self._extract_from_regex(code, schema))
            
        except Exception as e:
            logger.error(f"提取列名时出错: {e}", exc_info=True)
        
        return used_columns
    
    def _extract_from_ast(self, tree: ast.AST, schema: Dict) -> Set[str]:
        """从 AST 中提取列名"""
        columns = set()
        
        # 收集所有可能的列名
        all_columns = set()
        for sheet_info in schema.values():
            all_columns.update(sheet_info.get('columns', []))
        
        class ColumnVisitor(ast.NodeVisitor):
            def __init__(self, all_columns):
                self.all_columns = all_columns
                self.found_columns = set()
            
            def visit_Subscript(self, node):
                # 处理 df['column'] 或 df["column"]
                if isinstance(node.value, ast.Name) or isinstance(node.value, ast.Attribute):
                    if isinstance(node.slice, ast.Constant):
                        col_name = str(node.slice.value)
                        if col_name in self.all_columns:
                            self.found_columns.add(col_name)
                    elif isinstance(node.slice, ast.Str):  # Python < 3.8
                        col_name = node.slice.s
                        if col_name in self.all_columns:
                            self.found_columns.add(col_name)
                self.generic_visit(node)
            
            def visit_Attribute(self, node):
                # 处理 df.column 形式
                if isinstance(node.attr, str):
                    if node.attr in self.all_columns:
                        self.found_columns.add(node.attr)
                self.generic_visit(node)
        
        visitor = ColumnVisitor(all_columns)
        visitor.visit(tree)
        return visitor.found_columns
    
    def _extract_from_regex(self, code: str, schema: Dict) -> Set[str]:
        """使用正则表达式提取列名"""
        columns = set()
        
        # 收集所有可能的列名
        all_columns = set()
        for sheet_info in schema.values():
            all_columns.update(sheet_info.get('columns', []))
        
        # 匹配常见的列名引用模式
        patterns = [
            r"df\[['\"]([^'\"]+)['\"]\]",  # df['column']
            r"df\.([a-zA-Z_][a-zA-Z0-9_]*)",  # df.column
            r"['\"]([^'\"]+)['\"]\s*:",  # 字典键或参数名
            r"columns\s*=\s*\[['\"]([^'\"]+)['\"]",  # columns=['column']
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, code)
            for match in matches:
                if match in all_columns:
                    columns.add(match)
        
        # 直接搜索列名（作为字符串）
        for col in all_columns:
            # 避免误匹配，检查列名是否在引号中或作为标识符的一部分
            if re.search(rf"['\"]{re.escape(col)}['\"]", code):
                columns.add(col)
        
        return columns
    
    def trace_data_usage(self, code: str, execution_output: str, 
                         schema: Dict) -> Dict:
        """
        追溯数据使用情况
        
        Args:
            code: 执行的代码
            execution_output: 代码执行输出
            schema: 文件结构信息
            
        Returns:
            包含使用的列、源文件等信息的字典
        """
        used_columns = self.extract_columns_from_code(code, schema)
        
        # 从 schema 中获取列的信息
        column_info = {}
        for sheet_name, sheet_info in schema.items():
            columns = sheet_info.get('columns', [])
            for col in columns:
                if col in used_columns:
                    column_info[col] = {
                        'sheet': sheet_name,
                        'dtype': sheet_info.get('dtypes', {}).get(col, 'unknown')
                    }
        
        return {
            'used_columns': list(used_columns),
            'column_info': column_info,
            'total_columns_used': len(used_columns)
        }
    
    def format_trace_report(self, trace_result: Dict, language: str = 'zh') -> str:
        """
        格式化追溯报告
        
        Args:
            trace_result: 追溯结果
            language: 语言代码，'zh' 表示中文，'en' 表示英文（用于提示文字）
            
        Returns:
            格式化的报告字符串（提示文字根据 language，列名保持原样）
        """
        used_columns = trace_result.get('used_columns', [])
        column_info = trace_result.get('column_info', {})
        
        if language == 'zh':
            if not used_columns:
                return "本次分析未使用任何数据列。"
            
            report = f"本次分析使用了 {len(used_columns)} 个数据列：\n\n"
            
            for col in used_columns:
                info = column_info.get(col, {})
                sheet = info.get('sheet', '未知')
                dtype = info.get('dtype', '未知')
                report += f"- {col} (工作表: {sheet}, 类型: {dtype})\n"
        else:  # English
            if not used_columns:
                return "This analysis did not use any data columns."
            
            report = f"This analysis used {len(used_columns)} data column(s):\n\n"
            
            for col in used_columns:
                info = column_info.get(col, {})
                sheet = info.get('sheet', 'Unknown')
                dtype = info.get('dtype', 'Unknown')
                report += f"- {col} (Sheet: {sheet}, Type: {dtype})\n"
        
        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 测试代码
    tracer = DataTracer()
    
    test_code = """
import pandas as pd
df = pd.read_excel('test.xlsx')
result = df['销售额'].sum()
print(result)
"""
    
    test_metadata = {
        'sheets': {
            'Sheet1': {
                'columns': [
                    {'name': '销售额', 'dtype': 'float64'},
                    {'name': '日期', 'dtype': 'datetime64'},
                    {'name': '产品', 'dtype': 'object'}
                ]
            }
        }
    }
    
    result = tracer.trace_code(test_code, test_metadata)
    print("追溯结果:", result)
    
    report = tracer.format_trace_report(result, language='zh')
    print("\n报告:\n", report)
