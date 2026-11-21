"""四格分镜图的出图质检与兜底拼图。

文生图模型不一定照着“2×2 四格”画：实际出过单张人像（一个戴草帽的女孩）、黑白速写这种完全跑题的图，
原来照单全收，直接当成这一段的视频参考图。这里做两件事：
- looks_like_grid：检查图中间有没有贯穿的横竖两条分格线（或左右、上下两半的明显接缝）；
- compose_grid：四格图没画成时，改为逐格单独出图，再由代码拼成 2×2——单幅画面只讲一件事，模型更容易画对。
"""
import io
from typing import List

import numpy as np
from PIL import Image

BAND = 0.06            # 在图中线左右各这么宽的范围里找分格线
EDGE_DIFF = 14         # 相邻两列（行）灰度差超过这个值算“这一点有边”
SEAM_COVERAGE = 0.6    # 一条线上有边的点占到这个比例，才算贯穿的分格线
GUTTER = 6             # 拼图时格与格之间的黑线宽度（像素）


def _seam(gray: np.ndarray) -> float:
    """竖直方向：中线附近最像“贯穿全高的竖线”的那一列，有边的行占比（0~1）。"""
    h, w = gray.shape
    lo, hi = int(w * (0.5 - BAND)), int(w * (0.5 + BAND))
    diff = np.abs(np.diff(gray[:, lo:hi].astype(np.int16), axis=1)) > EDGE_DIFF
    return float(diff.mean(axis=0).max()) if diff.size else 0.0


def grid_score(image_bytes: bytes) -> tuple:
    """(竖线得分, 横线得分)。读不出图返回 (0, 0)。"""
    try:
        gray = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("L").resize((512, 512)))
    except Exception:
        return 0.0, 0.0
    return _seam(gray), _seam(gray.T)


def looks_like_grid(image_bytes: bytes) -> bool:
    """这张图是不是 2×2 四格：中间要同时有贯穿的竖线和横线。"""
    v, h = grid_score(image_bytes)
    return v >= SEAM_COVERAGE and h >= SEAM_COVERAGE


def compose_grid(panels: List[bytes], size: int = 1024) -> bytes:
    """四张单幅图按 左上 → 右上 → 左下 → 右下 拼成一张方图，中间留黑色分格线。每格居中裁成方形。"""
    if len(panels) != 4:
        raise ValueError("拼四格图需要正好 4 张图")
    cell = (size - GUTTER) // 2
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    for i, data in enumerate(panels):
        im = Image.open(io.BytesIO(data)).convert("RGB")
        side = min(im.size)
        left, top = (im.width - side) // 2, (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side)).resize((cell, cell), Image.LANCZOS)
        canvas.paste(im, ((i % 2) * (cell + GUTTER), (i // 2) * (cell + GUTTER)))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
