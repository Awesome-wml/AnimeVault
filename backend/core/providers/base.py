"""AI服务提供者基类（适配器模式）"""
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator


class BaseLLMProvider(ABC):
    """LLM服务提供者基类"""
    
    @abstractmethod
    async def chat(
        self, 
        messages: list, 
        model: str, 
        temperature: float = 0.7,
        stream: bool = False
    ) -> str | AsyncIterator[str]:
        """聊天接口"""
        pass
    
    @abstractmethod
    async def chat_json(
        self, 
        messages: list, 
        model: str,
        max_retries: int = 3
    ) -> dict:
        """聊天接口（强制JSON输出）"""
        pass


class BaseImageProvider(ABC):
    """文生图服务提供者基类"""
    
    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        neg_prompt: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
        **kwargs
    ) -> bytes:
        """生成图片，返回图片二进制数据"""
        pass


class BaseTTSProvider(ABC):
    """TTS服务提供者基类"""
    
    @abstractmethod
    async def generate_speech(
        self,
        text: str,
        voice_name: str = "zh_female_qingxin",
        **kwargs
    ) -> bytes:
        """生成语音，返回音频二进制数据"""
        pass
    
    @abstractmethod
    def get_available_voices(self) -> list[dict]:
        """获取可用音色列表"""
        pass
