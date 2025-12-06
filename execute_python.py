# pip install jupyter_client
# pip install ipykernel
from jupyter_client.manager import start_new_kernel
import logging
import time

logger = logging.getLogger(f'2brain.{__name__}')


def run_code(code, client):
    """
    执行代码并获取输出结果
    
    关键机制：
    1. 先执行 setup_code 创建 charts 目录
    2. 再执行主代码，通过消息过滤机制只处理主代码的消息
    3. 根据 parent_header.msg_id 区分 setup_code 和主代码的消息
    """
    try:
        logger.info(f"开始执行代码，代码长度: {len(code)} 字符，包含 {code.count('print(')} 个 print 语句")
        
        # 在执行代码前，确保 charts 目录存在
        # 注意：Jupyter kernel 的 stdout 不支持 reconfigure，所以我们依赖代码中的 flush=True
        setup_code = """
import os
import sys
os.makedirs('charts', exist_ok=True)
# 刷新输出缓冲区（虽然 Jupyter 的 OutStream 不支持 reconfigure，但 flush 仍然有效）
sys.stdout.flush()
sys.stderr.flush()
"""
        # 步骤1: 执行 setup_code 创建 charts 目录
        setup_msg_id = client.execute(setup_code)
        time.sleep(0.5)  # 等待 setup_code 完成
        
        # 步骤2: 执行主代码
        msg_id = client.execute(code)
        logger.info(f"代码执行请求已发送，消息ID: {msg_id}")
        
        # 关键：立即开始轮询消息，输出消息可能在 execute_reply 之前就到达

        # 设置超时时间（增加到120秒，因为数据处理可能需要更长时间）
        TIMEOUT = 120
        MAX_ITERATIONS = 2000  # 防止无限循环
        iteration = 0

        # 获取输出结果
        output = []
        error_occurred = False
        execution_complete = False
        
        # 等待执行完成
        execute_reply_received = False
        idle_received = False
        last_output_time = None
        
        while iteration < MAX_ITERATIONS:
            try:
                # 优先处理 iopub 消息（输出、状态等），因为这些消息可能在 execute_reply 之前到达
                try:
                    msg = client.get_iopub_msg(timeout=0.1)  # 使用较短的超时，快速轮询
                    msg_type = msg['header']['msg_type']
                    content = msg['content']
                    parent_msg_id = msg.get('parent_header', {}).get('msg_id', '')
                    
                    # 关键：只处理主代码的消息，忽略 setup_code 的消息
                    # 通过 parent_header.msg_id 区分不同执行请求的消息
                    if parent_msg_id != msg_id:
                        continue  # 跳过 setup_code 或其他消息

                    if msg_type == 'stream':
                        # 处理 stdout 和 stderr 输出
                        stream_name = content.get('name', '')
                        text = content.get('text', '')
                        if text:
                            output.append(text)
                            last_output_time = time.time()
                            logger.debug(f"捕获输出 ({stream_name}): {len(text)} 字符，总长度: {len(''.join(output))} 字符")
                    elif msg_type == 'execute_result':
                        # 处理表达式执行结果（例如：最后一行表达式的值）
                        if 'text/plain' in content.get('data', {}):
                            result_text = content['data']['text/plain']
                            output.append(result_text)
                            last_output_time = time.time()
                            logger.debug(f"捕获执行结果: {len(result_text)} 字符")
                    elif msg_type == 'error':
                        # 捕获执行错误
                        error_occurred = True
                        traceback_lines = content.get('traceback', [])
                        error_msg = '\n'.join(traceback_lines)
                        logger.error(f"执行错误: {error_msg}")
                        output.append(f"ERROR:\n{error_msg}")
                        execution_complete = True
                        break
                    elif msg_type == 'status':
                        # 处理执行状态变化（busy -> idle）
                        execution_state = content.get('execution_state', '')
                        if execution_state == 'idle':
                            # 主代码执行完成，状态变为 idle
                            idle_received = True
                            logger.debug(f"执行状态变为idle，当前输出长度: {len(''.join(output))} 字符")
                            # 如果已经收到 execute_reply，等待一段时间确保所有输出消息都已接收
                            if execute_reply_received:
                                if last_output_time:
                                    # 有输出：等待2秒确保没有更多输出
                                    time_since_last_output = time.time() - last_output_time
                                    if time_since_last_output > 2.0:
                                        execution_complete = True
                                        break
                                else:
                                    # 无输出：等待3秒，可能输出还在路上
                                    logger.warning("收到idle状态但还没有任何输出，等待3秒...")
                                    time.sleep(3.0)
                                    # 再次尝试获取消息
                                    try:
                                        final_msg = client.get_iopub_msg(timeout=1.0)
                                        if final_msg['header']['msg_type'] == 'stream':
                                            stream_text = final_msg['content'].get('text', '')
                                            if stream_text:
                                                output.append(stream_text)
                                                last_output_time = time.time()
                                    except:
                                        pass
                                    execution_complete = True
                                    break
                        elif execution_state == 'error':
                            error_occurred = True
                            logger.error("执行状态为error")
                            execution_complete = True
                            break
                except Exception as e:
                    # 超时或没有消息是正常的，继续检查 shell 消息
                    if "Timeout" not in str(e) and "No message" not in str(e):
                        logger.debug(f"获取iopub消息时出错: {e}")
                
                # 检查是否有执行回复（shell 通道）
                try:
                    reply = client.get_shell_msg(timeout=0.1)
                    reply_type = reply['header']['msg_type']
                    reply_parent_msg_id = reply.get('parent_header', {}).get('msg_id', '')
                    
                    # 关键：只处理主代码的 execute_reply
                    if reply_type == 'execute_reply' and reply_parent_msg_id == msg_id:
                        status = reply['content'].get('status', '')
                        logger.info(f"代码执行回复: 状态={status}")
                        
                        if status == 'ok':
                            execute_reply_received = True
                            # 收到 ok 后，继续等待 iopub 消息（输出可能在 execute_reply 之后到达）
                        elif status == 'error':
                            error_occurred = True
                            error_info = reply['content'].get('traceback', [])
                            if error_info:
                                error_msg = '\n'.join(error_info)
                                output.append(f"ERROR:\n{error_msg}")
                            logger.error(f"代码执行出错: {reply['content']}")
                            execution_complete = True
                            break
                except Exception as e:
                    # 超时或没有消息是正常的，继续循环
                    if "Timeout" not in str(e) and "No message" not in str(e):
                        logger.debug(f"获取shell消息时出错: {e}")
                
                # 如果已经收到 execute_reply 和 idle，且有一段时间没有新消息，认为完成
                if execute_reply_received and idle_received:
                    if last_output_time:
                        time_since_last_output = time.time() - last_output_time
                        if time_since_last_output > 2.0:
                            execution_complete = True
                            break
                    else:
                        # 如果没有收到任何输出，等待3秒后退出
                        logger.warning("收到execute_reply和idle但还没有任何输出，等待3秒...")
                        time.sleep(3.0)
                        # 再次尝试获取剩余消息
                        try:
                            for _ in range(20):
                                final_msg = client.get_iopub_msg(timeout=0.2)
                                if final_msg['header']['msg_type'] == 'stream':
                                    stream_text = final_msg['content'].get('text', '')
                                    if stream_text:
                                        output.append(stream_text)
                                        last_output_time = time.time()
                        except:
                            pass
                        execution_complete = True
                        break
                
                # 防止无限等待：如果已收到 execute_reply 但等待时间过长，也退出
                if execute_reply_received and iteration > 500:
                    logger.warning(f"已收到执行回复，但等待输出超时（已迭代 {iteration} 次），退出等待")
                    # 最后尝试获取剩余消息
                    try:
                        for _ in range(20):
                            final_msg = client.get_iopub_msg(timeout=0.2)
                            if final_msg['header']['msg_type'] == 'stream':
                                stream_text = final_msg['content'].get('text', '')
                                if stream_text:
                                    output.append(stream_text)
                    except:
                        pass
                    execution_complete = True
                    break

                iteration += 1
                
                # 每100次迭代记录一次进度（仅在调试时有用）
                if iteration % 100 == 0:
                    logger.debug(f"等待执行完成，已迭代 {iteration} 次，输出长度: {len(''.join(output))} 字符")

            except KeyboardInterrupt:
                logger.warning("代码执行被中断")
                output.append("\n[执行被中断]")
                break
            except Exception as e:
                if "Timeout" not in str(e):
                    logger.error(f"获取输出时发生错误: {str(e)}")
                iteration += 1
                if iteration > MAX_ITERATIONS:
                    logger.warning(f"达到最大迭代次数 {MAX_ITERATIONS}，停止等待")
                    break
            
            if execution_complete:
                break

        result = '\n'.join(output) if output else ""
        
        # 如果没有输出但有错误，添加错误提示
        if not result and error_occurred:
            result = "执行过程中出现错误，但未捕获到详细错误信息。\n请检查代码是否正确。"
        elif not result:
            result = "代码执行完成，但没有输出内容。\n这可能是因为代码没有使用 print() 输出结果。"
        
        logger.info(f"执行完成，输出长度: {len(result)} 字符，是否有错误: {error_occurred}")
        
        return result

    except KeyboardInterrupt:
        logger.warning("代码执行被用户中断")
        return "执行被中断"
    except Exception as e:
        logger.error(f"代码执行发生错误: {str(e)}", exc_info=True)
        return f"执行失败: {str(e)}"


def model_execute_main(command):
    """主函数:创建内核、执行代码并清理资源"""
    kernel_manager = None
    client = None

    try:
        # 创建新内核
        kernel_manager, client = start_new_kernel()
        logger.info(f"正在执行代码（前200字符）: {command[:200]}...")

        # 执行代码并获取结果
        result = run_code(command, client)
        logger.info(f"代码执行完成，输出长度: {len(result)} 字符")
        return result

    except KeyboardInterrupt:
        logger.warning("代码执行被中断")
        return "执行被中断"
    except Exception as e:
        logger.error(f"执行过程发生错误: {str(e)}", exc_info=True)
        return f"执行失败: {str(e)}"

    finally:
        # 清理资源
        if client:
            try:
                client.stop_channels()
            except Exception as e:
                logging.error(f"停止通道时发生错误: {str(e)}")

        if kernel_manager:
            try:
                kernel_manager.shutdown_kernel()
            except Exception as e:
                logging.error(f"关闭内核时发生错误: {str(e)}")

        del client
        del kernel_manager


if __name__ == "__main__":
    # 测试代码
    test_code = '''
import math
print("pi =", round(math.pi, 2))
'''
    res = model_execute_main(test_code)
    print(res)