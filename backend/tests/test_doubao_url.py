"""豆包视频直链：下载前一律改成无水印（lr=unwatermarked）"""


def test_unwatermarked_url():
    from core.doubao_automation import to_unwatermarked_url
    base = "https://v11-vdl.doubao.com/abc/video/tos/cn/x/?a=482431&ch=0&cr=4"
    u = to_unwatermarked_url(base + "&lr=video_gen_watermark_dyn&net=5&cd=0%7C1&mime_type=video_mp4")
    assert "lr=unwatermarked" in u and "watermark_dyn" not in u and u.count("lr=") == 1
    assert u.endswith("&net=5&cd=0%7C1&mime_type=video_mp4")  # 其他参数原样
    assert to_unwatermarked_url(base + "&lr=other_value") == base + "&lr=unwatermarked"
    assert to_unwatermarked_url(base) == base + "&lr=unwatermarked"  # 没有 lr 就补上
    clean = base + "&lr=unwatermarked&net=5"
    assert to_unwatermarked_url(clean) == clean
    assert to_unwatermarked_url("https://example.com/v.mp4?lr=x") == "https://example.com/v.mp4?lr=x"
    assert "flr=keep" in to_unwatermarked_url(base + "&flr=keep&lr=w")  # 只改名为 lr 的参数
