"""文件工具类"""
import logging
import os
import uuid
from pathlib import Path
from config.settings import settings


logger = logging.getLogger(__name__)


class UnsafePathError(ValueError):
    """相对路径逃出了 static 目录（绝对路径、../ 之类）。"""


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
    def safe_path(relative_path: str) -> Path:
        """static 目录下的完整路径；绝对路径、../ 等逃出 static 目录的一律拒绝（抛 UnsafePathError）。

        ref_image / image_path 等字段可由客户端写入，原来直接 static_dir / relative_path，
        传 "/app/main.py" 或 "../../x" 就能读写、删除 static 目录外的文件。
        """
        base = FileUtil.get_static_dir().resolve()
        rel = str(relative_path or "").strip()
        if not rel or os.path.isabs(rel) or rel.startswith(("\\", "/")) or (len(rel) > 1 and rel[1] == ":"):
            raise UnsafePathError(f"不是 static 下的相对路径: {relative_path!r}")
        full = (base / rel).resolve()
        if full != base and base not in full.parents:
            raise UnsafePathError(f"路径越出 static 目录: {relative_path!r}")
        return full

    @staticmethod
    def delete_file(relative_path: str):
        """
        删除 static 目录下的文件；越界路径只记日志、不删除。

        Args:
            relative_path: 相对路径（如：images/xxx.png）
        """
        if not relative_path:
            return
        try:
            filepath = FileUtil.safe_path(relative_path)
        except UnsafePathError as e:
            logger.warning(f"拒绝删除：{e}")
            return
        if filepath.exists() and filepath.is_file():
            filepath.unlink()

    @staticmethod
    def get_full_path(relative_path: str) -> Path:
        """
        获取 static 下的完整路径（越界抛 UnsafePathError）

        Args:
            relative_path: 相对路径

        Returns:
            完整路径
        """
        return FileUtil.safe_path(relative_path)
