"""
语音处理模块：处理 WebSocket 实时语音输入
"""
import os
import asyncio
import base64
import json
import logging
import tempfile
from typing import Optional
from flask_socketio import SocketIO, emit

logger = logging.getLogger(f'excel_agent.{__name__}')

# 尝试导入语音相关模块，如果失败则禁用语音功能
try:
    import sys
    sys.path.append('realtime voice w6 demo')
    from realtime_stt import transcribe_microphone_async, transcribe_audio_async
    VOICE_ENABLED = True
except ImportError as e:
    logger.warning(f"语音功能未启用: {e}. 如需使用语音功能，请安装 pyaudio 和相关依赖。")
    VOICE_ENABLED = False
    transcribe_microphone_async = None
    transcribe_audio_async = None

class VoiceHandler:
    """语音处理器"""
    
    def __init__(self, socketio: SocketIO, api_key: Optional[str] = None):
        """
        初始化语音处理器
        
        Args:
            socketio: Flask-SocketIO 实例
            api_key: OpenAI API Key
        """
        self.socketio = socketio
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.is_recording = False
    
    async def handle_voice_stream(self, audio_data: bytes, session_id: str, audio_format: str = 'wav'):
        """
        处理语音流数据
        
        Args:
            audio_data: 音频数据（base64 编码或原始字节）
            session_id: 会话ID
        """
        # 顶层快速检查：如果语音功能在导入阶段就被禁用，直接给前端详细提示
        if not VOICE_ENABLED:
            msg = '语音功能未启用，请检查服务端是否成功安装 pyaudio / websockets 相关依赖。'
            logger.warning(f"VOICE_DEBUG: VOICE_ENABLED=False, session_id={session_id}")
            self.socketio.emit('transcription', {
                'text': msg,
                'language': 'zh-CN',
                'session_id': session_id
            })
            return
        
        import tempfile
        
        temp_audio_path = None
        try:
            logger.info(f"开始处理语音数据，session_id: {session_id}")
            logger.info(
                "VOICE_DEBUG: VOICE_ENABLED=%s, transcribe_audio_async=%s, api_key_configured=%s",
                VOICE_ENABLED,
                "yes" if transcribe_audio_async else "no",
                "yes" if bool(self.api_key) else "no",
            )
            
            # 检查语音功能是否启用
            if not VOICE_ENABLED:
                error_msg = '语音功能未启用。请安装 pyaudio 和相关依赖。'
                logger.warning(error_msg)
                self.socketio.emit('transcription', {
                    'text': error_msg,
                    'language': 'zh-CN',
                    'session_id': session_id
                })
                return
            
            if not transcribe_audio_async:
                error_msg = '语音转录功能未正确配置'
                logger.warning(error_msg)
                self.socketio.emit('transcription', {
                    'text': error_msg,
                    'language': 'zh-CN',
                    'session_id': session_id
                })
                return
            
            # 解码 base64 音频数据
            if isinstance(audio_data, str):
                audio_bytes = base64.b64decode(audio_data)
                logger.info(f"解码 base64 音频数据，长度: {len(audio_bytes)} 字节")
            else:
                audio_bytes = audio_data
                logger.info(f"接收原始音频数据，长度: {len(audio_bytes)} 字节")
            
            # 保存为临时 WAV 文件
            # 使用 soundfile 可以读取多种格式，包括 WAV
            temp_audio_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio_path = temp_audio_file.name
            temp_audio_file.close()
            
            logger.info(f"保存临时音频文件到: {temp_audio_path}")
            
            # 将音频数据写入文件
            with open(temp_audio_path, 'wb') as f:
                f.write(audio_bytes)
            
            # 检查文件是否存在且大小合理
            if not os.path.exists(temp_audio_path):
                raise FileNotFoundError(f"临时音频文件创建失败: {temp_audio_path}")
            
            file_size = os.path.getsize(temp_audio_path)
            logger.info(f"临时音频文件大小: {file_size} 字节")
            
            if file_size < 100:
                raise ValueError(f"音频文件太小，可能格式不正确: {file_size} 字节")
            
            # 检查 API Key
            if not self.api_key:
                raise ValueError("OpenAI API Key 未配置，请在环境变量中设置 OPENAI_API_KEY")
            
            # 使用 OpenAI Realtime API 进行转录
            logger.info("开始调用 transcribe_audio_async (Realtime API)")
            logger.info(f"API Key 前10位: {self.api_key[:10]}...")
            
            try:
                # 使用适中的整体超时时间，避免长时间卡住（例如 30 秒）
                transcript = await asyncio.wait_for(
                    transcribe_audio_async(
                        temp_audio_path,
                        self.api_key
                    ),
                    timeout=30.0  # 整体转录超时 30 秒
                )
                
                if not transcript or not transcript.strip():
                    logger.warning("转录结果为空")
                    transcript = "未识别到语音内容，请重试"
                
                logger.info(f"转录完成，结果长度: {len(transcript)} 字符")
                logger.debug(f"转录结果: {transcript[:100]}...")
            except asyncio.TimeoutError:
                # 不再抛出异常，直接给前端返回友好的提示
                error_msg = (
                    "语音转录超时（约30秒），可能原因：\n"
                    "1. 当前网络无法连接 OpenAI 实时语音服务（被防火墙或代理拦截）\n"
                    "2. 网络较慢或临时不稳定\n\n"
                    "建议：\n"
                    "- 先用浏览器访问 https://api.openai.com 检查是否可达；\n"
                    "- 或切换网络 / 关闭公司 VPN / 代理后再试；\n"
                    "- 尝试录制更短的语音。"
                )
                logger.error(error_msg)
                self.socketio.emit('transcription', {
                    'text': error_msg,
                    'language': 'zh-CN',
                    'session_id': session_id
                })
                return
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                logger.error(f"转录过程中出错 [{error_type}]: {error_msg}", exc_info=True)
                
                # 提供更友好的错误信息
                if "401" in error_msg or "Unauthorized" in error_msg:
                    raise ValueError("OpenAI API Key 无效或已过期，请检查 .env 文件中的配置")
                elif "429" in error_msg or "rate limit" in error_msg.lower():
                    raise ValueError("API 请求频率过高，请稍后重试")
                elif "timeout" in error_msg.lower() or "TimeoutError" in error_type:
                    raise TimeoutError("连接超时，请检查网络连接")
                else:
                    raise Exception(f"转录失败: {error_msg}")
            
            # 发送转录结果
            logger.info("VOICE_DEBUG: 即将向前端发送转录结果")
            self.socketio.emit('transcription', {
                'text': transcript,
                'language': 'zh-CN',
                'session_id': session_id
            })
            logger.info("VOICE_DEBUG: 已向前端发送转录结果")
            
        except Exception as e:
            error_msg = f'语音处理失败: {str(e)}'
            logger.error(f"VOICE_DEBUG: 处理语音流时出错: {error_msg}", exc_info=True)
            self.socketio.emit('error', {
                'message': error_msg,
                'session_id': session_id
            })
            # 也发送一个空的转录结果，让前端知道处理失败
            self.socketio.emit('transcription', {
                'text': f'转录失败: {str(e)}',
                'language': 'zh-CN',
                'session_id': session_id
            })
        finally:
            # 清理临时文件
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.unlink(temp_audio_path)
                    logger.info(f"已清理临时文件: {temp_audio_path}")
                except Exception as e:
                    logger.warning(f"删除临时音频文件失败 {temp_audio_path}: {e}")
    
    def start_recording(self, session_id: str):
        """开始录音"""
        self.is_recording = True
        self.socketio.emit('recording_started', {'session_id': session_id})
    
    def stop_recording(self, session_id: str):
        """停止录音"""
        self.is_recording = False
        self.socketio.emit('recording_stopped', {'session_id': session_id})
    
    async def transcribe_audio_file(self, audio_file_path: str) -> str:
        """
        转录音频文件
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            转录文本
        """
        if not VOICE_ENABLED:
            return "语音功能未启用。请安装 pyaudio 和相关依赖以启用语音功能。"
        
        try:
            transcript = await transcribe_audio_async(
                audio_file_path,
                self.api_key
            )
            return transcript
        except Exception as e:
            logger.error(f"转录音频文件时出错: {e}", exc_info=True)
            return f"转录失败: {str(e)}"
    
    async def transcribe_microphone(self, duration_seconds: int = 10) -> str:
        """
        从麦克风实时转录
        
        Args:
            duration_seconds: 录音时长（秒）
            
        Returns:
            转录文本
        """
        if not VOICE_ENABLED:
            return "语音功能未启用。请安装 pyaudio 和相关依赖以启用语音功能。"
        
        try:
            transcript = await transcribe_microphone_async(
                self.api_key,
                duration_seconds=duration_seconds
            )
            return transcript
        except Exception as e:
            logger.error(f"从麦克风转录时出错: {e}", exc_info=True)
            return f"转录失败: {str(e)}"

