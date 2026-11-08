"""皮肤/脸部区域线框网格后处理（零第三方依赖，便于打包成可执行软件）。

用途：仿真人漫剧角色板在脸部等皮肤区域叠加规则三角/四边形线框网格，弱化真人皮相
的可识别度，降低肖像风险。仅依赖 Pillow 与 numpy，不引入 cv2 / mediapipe。

实现思路：
1. 用肤色阈值规则得到皮肤掩码；
2. 在透明图层上绘制规则网格（横竖线 + 可选三角对角线）；
3. 网格透明度只在皮肤掩码处保留，alpha 混合回原图。
"""
import io
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw


def _skin_mask(arr: np.ndarray) -> np.ndarray:
    """基于 RGB 规则的肤色掩码，返回 HxW 布尔数组。"""
    r = arr[..., 0].astype(np.int16)
    g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16)

    mask = (
        (r > 60) & (g > 25) & (b > 15)
        & (r >= g) & (r >= b)
        & (r - np.minimum(g, b) > 12)
        & (np.maximum(r, np.maximum(g, b)) - np.minimum(r, np.minimum(g, b)) > 8)
    )
    return mask


def apply_face_grid(
    data: bytes,
    cell: int = 22,
    line_width: int = 1,
    color: Tuple[int, int, int] = (70, 86, 110),
    alpha: int = 120,
    diagonal: bool = False,
) -> bytes:
    """在皮肤区域叠加规则线框网格。

    Args:
        data: 原始图片二进制（PNG/JPG 等）。
        cell: 网格单元边长（像素），越小越密。
        line_width: 网线宽（像素）。
        color: 网线 RGB 颜色。
        alpha: 网格不透明度 0-255。
        diagonal: 是否叠加三角对角线（False 为纯四边形网格）。

    Returns:
        处理后的 PNG 二进制。
    """
    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    mask = _skin_mask(arr)

    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid)
    line_fill = color + (255,)

    # 横竖网格线
    for x in range(0, w + 1, cell):
        draw.line([(x, 0), (x, h)], fill=line_fill, width=line_width)
    for y in range(0, h + 1, cell):
        draw.line([(0, y), (w, y)], fill=line_fill, width=line_width)

    # 三角对角线
    if diagonal:
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                draw.line([(x, y), (x + cell, y + cell)], fill=line_fill, width=line_width)
                draw.line([(x + cell, y), (x, y + cell)], fill=line_fill, width=line_width)

    grid_arr = np.asarray(grid)
    # 网格只在皮肤区域显示
    grid_alpha = (grid_arr[..., 3].astype(np.float32) / 255.0) * mask.astype(np.float32)
    a = grid_alpha[..., None] * (alpha / 255.0)

    out = arr.astype(np.float32) * (1 - a) + grid_arr[..., :3].astype(np.float32) * a
    out = np.clip(out, 0, 255).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="PNG")
    return buf.getvalue()
