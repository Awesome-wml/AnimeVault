"""豆包TTS服务提供者"""
import httpx
import logging
from .base import BaseTTSProvider
from . import fake

logger = logging.getLogger(__name__)


class DoubaoTTSProvider(BaseTTSProvider):
    """豆包TTS服务提供者"""

    # 豆包可用音色列表（扩充：标注性别与年龄段，供自动关联使用）
    VOICES = [
        # 女声
        {"name": "zh_female_qingxin", "display_name": "清新女声", "language": "zh",
         "gender": "female", "age_group": "青年", "tone": "清新灵动",
         "tags": ["青年", "少女", "清新", "灵动"]},
        {"name": "zh_female_wanxin", "display_name": "婉心女声", "language": "zh",
         "gender": "female", "age_group": "青年", "tone": "温柔婉转",
         "tags": ["青年", "温柔", "婉转", "知性"]},
        {"name": "zh_female_tianmei", "display_name": "甜美女声", "language": "zh",
         "gender": "female", "age_group": "少年", "tone": "甜美俏皮",
         "tags": ["少女", "甜美", "俏皮", "活泼"]},
        {"name": "zh_female_dunhou", "display_name": "醇厚女声", "language": "zh",
         "gender": "female", "age_group": "中年", "tone": "沉稳厚重",
         "tags": ["中年", "沉稳", "母性", "成熟"]},
        {"name": "zh_female_canglao", "display_name": "苍老女声", "language": "zh",
         "gender": "female", "age_group": "暮年", "tone": "苍老慈祥",
         "tags": ["暮年", "苍老", "慈祥", "长辈"]},
        # 男声
        {"name": "zh_male_qinglang", "display_name": "清朗男声", "language": "zh",
         "gender": "male", "age_group": "青年", "tone": "清朗阳光",
         "tags": ["青年", "阳光", "清朗", "少年感"]},
        {"name": "zh_male_chunhou", "display_name": "醇厚男声", "language": "zh",
         "gender": "male", "age_group": "中年", "tone": "醇厚磁性",
         "tags": ["中年", "醇厚", "磁性", "沉稳"]},
        {"name": "zh_male_chengwen", "display_name": "成稳男声", "language": "zh",
         "gender": "male", "age_group": "中年", "tone": "稳重低沉",
         "tags": ["中年", "稳重", "低沉", "成熟"]},
        {"name": "zh_male_shuangle", "display_name": "爽朗男声", "language": "zh",
         "gender": "male", "age_group": "青年", "tone": "爽朗豪迈",
         "tags": ["青年", "豪迈", "爽朗", "热血"]},
        {"name": "zh_male_shaonian", "display_name": "少年男声", "language": "zh",
         "gender": "male", "age_group": "少年", "tone": "青涩少年",
         "tags": ["少年", "青涩", "稚嫩", "少年感"]},
        {"name": "zh_male_cangmang", "display_name": "苍茫男声", "language": "zh",
         "gender": "male", "age_group": "暮年", "tone": "苍老厚重",
         "tags": ["暮年", "苍老", "厚重", "长者"]},
        {"name": "zh_male_yinleng", "display_name": "阴冷男声", "language": "zh",
         "gender": "male", "age_group": "中年", "tone": "阴冷邪气",
         "tags": ["反派", "阴冷", "邪气", "威慑"]},
    ]

    def __init__(self, api_key: str, base_url: str = "https://ark.cn-beijing.volces.com/api/v3"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def generate_speech(
        self,
        text: str,
        voice_name: str = "zh_female_qingxin",
        model: str = "doubao-tts",
        **kwargs
    ) -> bytes:
        """
        生成语音

        Args:
            text: 文本内容
            voice_name: 音色名称
            model: 模型名称

        Returns:
            音频二进制数据（MP3格式）
        """
        if fake.enabled():
            return fake.speech_bytes()
        url = f"{self.base_url}/audio/speech"

        payload = {
            "model": model,
            "input": text,
            "voice": voice_name,
            "response_format": "mp3"
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()

                # 直接返回音频二进制数据
                return response.content

        except httpx.HTTPStatusError as e:
            logger.error(f"TTS API调用失败: {e.response.text}")
            raise ValueError(f"TTS生成失败: {e.response.text}")
        except Exception as e:
            logger.error(f"TTS异常: {str(e)}")
            raise ValueError(f"TTS异常: {str(e)}")

    def get_available_voices(self) -> list[dict]:
        """获取可用音色列表"""
        return self.VOICES
