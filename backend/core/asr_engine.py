"""离线语音识别引擎（本地 ASR，不依赖云端与系统 ffmpeg）。

选型：sherpa-onnx + SenseVoice int8 量化模型。
- 引擎 wheel 双平台覆盖（macOS arm64/x86_64、Windows amd64/arm64），不引入 torch；
- 模型预置在 ``bin/asr/sense-voice/``（model.int8.onnx + tokens.txt），运行时离线加载；
- 音频解码复用 core.ffmpeg_tool 内置 imageio-ffmpeg 二进制。

对外主入口：
    from core.asr_engine import transcribe_video
    entries = transcribe_video(video_path)  # [{"text": str, "start": float, "end": float}, ...]
"""
import logging
import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import List, Dict, Optional

from core.ffmpeg_tool import ffmpeg_exe

logger = logging.getLogger(__name__)

# 句末标点：遇到即闭合一句
_SENT_END = set("。！？!?；;")
# 句内停顿标点：长句在此处二次断句
_CLAUSE_PAUSE = set("，,、")

_recognizer = None
_recognizer_lock = threading.Lock()
_model_dir_cache: Optional[Path] = None


def _model_dir() -> Path:
    """定位 ASR 模型目录，兼容开发目录、PyInstaller 解包目录、环境变量覆盖。"""
    global _model_dir_cache
    if _model_dir_cache is not None:
        return _model_dir_cache

    env_dir = os.environ.get("ASR_MODEL_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))
    # 开发态：<project>/backend/bin/asr/sense-voice
    backend_dir = Path(__file__).resolve().parent.parent
    candidates.append(backend_dir / "bin" / "asr" / "sense-voice")
    # PyInstaller 冻结态：解包临时目录 _MEIPASS/bin/asr/sense-voice
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "bin" / "asr" / "sense-voice")

    for cand in candidates:
        if (cand / "model.int8.onnx").exists() and (cand / "tokens.txt").exists():
            _model_dir_cache = cand
            return _model_dir_cache
    # 都没命中，返回开发态默认路径（后续加载时给出可读错误）
    _model_dir_cache = candidates[0]
    return _model_dir_cache


def _load_recognizer():
    """懒加载识别器，全局单例复用，避免每条成片重复加载模型。"""
    global _recognizer
    if _recognizer is not None:
        return _recognizer
    with _recognizer_lock:
        if _recognizer is not None:
            return _recognizer
        try:
            import sherpa_onnx
        except ImportError as exc:  # pragma: no cover - 依赖未装时的可读报错
            raise RuntimeError(
                "未安装 sherpa-onnx 引擎，请先在 requirements 安装 sherpa-onnx"
            ) from exc

        model_dir = _model_dir()
        model_path = model_dir / "model.int8.onnx"
        tokens_path = model_dir / "tokens.txt"
        if not model_path.exists() or not tokens_path.exists():
            raise FileNotFoundError(f"ASR 模型缺失：{model_dir}（model.int8.onnx / tokens.txt）")

        _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            num_threads=2,
            provider="cpu",
            use_itn=True,
            language="zh",
        )
        logger.info("ASR 识别器加载完成：%s", model_dir)
        return _recognizer


def _extract_wav(video_path: Path, wav_path: Path) -> None:
    """成片抽 16kHz 单声道 wav，供识别使用。"""
    subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-y", "-i", str(video_path),
         "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path)],
        capture_output=True, timeout=30, check=True,
    )


def _read_wav(wav_path: Path):
    """读 wav 为 (sample_rate, float32 样本)。"""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        frames = w.getnframes()
        raw = w.readframes(frames)
    import numpy as np
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return rate, samples


def _aggregate(tokens: List[str], timestamps: List[float]) -> List[Dict]:
    """把 token 流（含标点 + 每 token 结束时间）聚合成句级条目。

    断句条件（任一命中即闭合一句）：句末标点、相邻 token 停顿间隙偏大、
    长句在句内停顿标点处二次断开。

    Returns:
        [{"text": str, "start": float, "end": float}, ...]
    """
    entries: List[Dict] = []
    if not tokens:
        return entries

    cur_chars: List[str] = []
    cur_start: Optional[float] = None
    last_ts: Optional[float] = None
    GAP_BREAK = 0.45  # 相邻 token 停顿超过该秒数视为断句

    def flush(end_ts: float) -> None:
        text = "".join(cur_chars).strip("，,、 ")
        if not text:
            return
        start = max(0.0, (cur_start or 0.0) - 0.15)
        entries.append({"text": text, "start": round(start, 3), "end": round(end_ts, 3)})

    for token, ts in zip(tokens, timestamps):
        # 停顿间隙偏大：先闭合上一句，再累积当前 token
        if cur_chars and last_ts is not None and ts - last_ts > GAP_BREAK:
            flush(last_ts)
            cur_chars, cur_start = [], None
        if token in _SENT_END:
            flush(ts)
            cur_chars, cur_start = [], None
        elif token in _CLAUSE_PAUSE:
            if len(cur_chars) >= 20:
                flush(ts)
                cur_chars, cur_start = [], None
            else:
                cur_chars.append("，")
        else:
            if cur_start is None:
                cur_start = ts
            cur_chars.append(token)
        last_ts = ts
    if cur_chars:
        flush(timestamps[-1])

    # 过滤过短碎片（<0.3s 且无实义），合并到前一条尾部由人工微调
    return [e for e in entries if e["end"] - e["start"] >= 0.3 or len(e["text"]) >= 2]


def transcribe_video(video_path) -> List[Dict]:
    """识别成片音频，返回句级字幕条目。

    Args:
        video_path: 成片视频路径（Path 或 str）。

    Returns:
        [{"text": str, "start": float, "end": float}, ...]，时间为段内秒。
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"成片不存在：{video_path}")

    recognizer = _load_recognizer()

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "clip.wav"
        _extract_wav(video_path, wav_path)
        rate, samples = _read_wav(wav_path)

        # 单例识别器并发 decode 已实测稳定，多线程并行识别无需推理锁串行化
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        recognizer.decode_stream(stream)
        result = stream.result

    entries = _aggregate(result.tokens, result.timestamps)
    logger.info("ASR 识别 %s：%d 句", video_path.name, len(entries))
    return entries
