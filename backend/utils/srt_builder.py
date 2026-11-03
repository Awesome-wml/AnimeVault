"""SRT字幕构建工具"""
import srt
from datetime import timedelta
from typing import List


class SRTBuilder:
    """SRT字幕生成器"""
    
    @staticmethod
    def build_srt(shots: List[dict]) -> str:
        """
        根据分镜列表生成SRT字幕
        
        Args:
            shots: 分镜列表，需包含 shot_no, text, duration 字段
        
        Returns:
            SRT格式字幕文本
        """
        subtitles = []
        current_time = 0.0
        
        # 按shot_no排序
        sorted_shots = sorted(shots, key=lambda x: x.get("shot_no", 0))
        
        for shot in sorted_shots:
            text = shot.get("text", "").strip()
            duration = shot.get("duration", 3.0)
            
            if not text:
                current_time += duration
                continue
            
            # 创建字幕条目
            subtitle = srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=current_time),
                end=timedelta(seconds=current_time + duration),
                content=text
            )
            subtitles.append(subtitle)
            
            current_time += duration
        
        # 生成SRT文本
        return srt.compose(subtitles)
    
    @staticmethod
    def parse_srt(srt_content: str) -> List[dict]:
        """
        解析SRT字幕（预留功能）
        
        Args:
            srt_content: SRT字幕文本
        
        Returns:
            字幕列表
        """
        subtitles = list(srt.parse(srt_content))
        
        result = []
        for sub in subtitles:
            result.append({
                "index": sub.index,
                "start": sub.start.total_seconds(),
                "end": sub.end.total_seconds(),
                "text": sub.content
            })
        
        return result
