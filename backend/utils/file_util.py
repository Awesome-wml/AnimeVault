"""文件工具类"""
import os
import uuid
from pathlib import Path
from config.settings import settings


class FileUtil:
    """文件处理工具"""
    
    @staticmethod
    def get_static_dir() -> Path:
        """获取静态文件目录"""
        static_dir = Path(settings.STATIC_DIR)
        static_dir.mkdir(parents=True, exist_ok=True)
        return static_dir
    
    @staticmethod
    def get_images_dir() -> Path:
        """获取图片目录"""
        img_dir = FileUtil.get_static_dir() / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        return img_dir
    
    @staticmethod
    def get_audio_dir() -> Path:
        """获取音频目录"""
        audio_dir = FileUtil.get_static_dir() / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir
    
    @staticmethod
    def save_image(data: bytes, ext: str = "png") -> str:
        """
        保存图片文件
        
        Args:
            data: 图片二进制数据
            ext: 文件扩展名
        
        Returns:
            相对路径（如：images/xxx.png）
        """
        filename = f"{uuid.uuid4()}.{ext}"
        filepath = FileUtil.get_images_dir() / filename
        
        with open(filepath, "wb") as f:
            f.write(data)
        
        return f"images/{filename}"
    
    @staticmethod
    def save_audio(data: bytes, ext: str = "mp3") -> str:
        """
        保存音频文件
        
        Args:
            data: 音频二进制数据
            ext: 文件扩展名
        
        Returns:
            相对路径（如：audio/xxx.mp3）
        """
        filename = f"{uuid.uuid4()}.{ext}"
        filepath = FileUtil.get_audio_dir() / filename
        
        with open(filepath, "wb") as f:
            f.write(data)
        
        return f"audio/{filename}"
    
    @staticmethod
    def delete_file(relative_path: str):
        """
        删除文件
        
        Args:
            relative_path: 相对路径（如：images/xxx.png）
        """
        if not relative_path:
            return
        
        filepath = FileUtil.get_static_dir() / relative_path
        if filepath.exists() and filepath.is_file():
            filepath.unlink()
    
    @staticmethod
    def get_full_path(relative_path: str) -> Path:
        """
        获取完整路径
        
        Args:
            relative_path: 相对路径
        
        Returns:
            完整路径
        """
        return FileUtil.get_static_dir() / relative_path
