"""光影不能与场景时辰、室内外冲突（深夜雨巷不配“窗外惨白天光”“清晨明亮日光”）。"""
from core.genre_rhythm import lighting_for_mood as L


def test_night_outdoor_never_gets_daylight_or_indoor_light():
    scene = "暴雨老城巷弄，深夜，冷蓝雨幕压抑"
    for mood in ("冷冽", "对峙", "坚定", "悲伤", "压抑", "轻蔑"):
        got = L(mood, "古风", scene)
        assert not any(w in got for w in ("日光", "天光", "窗外", "殿内")), (mood, got)


def test_no_conflict_keeps_original_mapping():
    assert L("对峙", "古风", "金銮殿，午后") == "惨白天光从高窗斜入，殿内大面积阴影"
    assert L("坚定", "", "城门外，清晨").startswith("清晨明亮日光")
    assert L("压抑", "", "") .startswith("冷白顶光")


def test_night_tension_gets_neutral_alternative():
    assert L("压抑", "", "云顶包厢，深夜") == "冷色侧光勾出轮廓，阴影压在眼窝，暗部偏冷"
