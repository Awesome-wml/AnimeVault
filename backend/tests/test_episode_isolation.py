"""剧集隔离：镜号每集从 1 开始，承接尾帧、成片文件名不能跨集串号。"""
from core.prev_frame import prev_frame_name, prev_shot_filter
from core.doubao_automation import video_filename


def test_prev_shot_filter_stays_in_same_episode():
    shot = {"_id": "s2", "project_id": "p", "video_set_id": "ep2", "shot_no": 3}
    assert prev_shot_filter(shot) == {"project_id": "p", "video_set_id": "ep2", "shot_no": 2}


def test_prev_shot_filter_ungrouped_matches_null():
    shot = {"_id": "s1", "project_id": "p", "shot_no": 2}
    assert prev_shot_filter(shot)["video_set_id"] is None
    assert prev_shot_filter({**shot, "video_set_id": ""})["video_set_id"] is None


def test_prev_frame_name_unique_per_shot():
    a = {"_id": "aaa", "project_id": "p1", "shot_no": 2}
    b = {"_id": "bbb", "project_id": "p2", "shot_no": 2}
    assert prev_frame_name(a) != prev_frame_name(b)
    assert prev_frame_name(a).endswith(".png")


def test_video_filename_unique_within_same_second():
    names = {video_filename(1) for _ in range(50)}
    assert len(names) == 50
    assert all(n.startswith("shot_001_") and n.endswith(".mp4") for n in names)
    assert video_filename("x").startswith("shot_000_")


def test_failed_reasons_same_shape_and_group_error():
    from api.video import _failed_reasons
    got = _failed_reasons({3: {"code": "REJECTED", "msg": "内容被拒绝", "detail": "版权限制", "conversation_url": "u"}},
                          failed=[3, 4], error="浏览器起不来")
    assert got["3"] == {"code": "REJECTED", "msg": "内容被拒绝", "reason": "版权限制", "conversation_url": "u"}
    assert got["4"]["code"] == "ERROR" and got["4"]["reason"] == "浏览器起不来"
    assert _failed_reasons({}) == {}


def test_account_pool_reuses_mongo_client(monkeypatch):
    from core import doubao_account_pool as P
    made = []

    class FakeClient:
        def __init__(self, url):
            made.append(url)
    monkeypatch.setattr(P, "MongoClient", FakeClient)
    monkeypatch.setattr(P.DoubaoAccountPool, "_clients", {})
    a = P.DoubaoAccountPool._shared_client("mongodb://x")
    b = P.DoubaoAccountPool._shared_client("mongodb://x")
    assert a is b and made == ["mongodb://x"]
