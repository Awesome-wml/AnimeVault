"""模型预设接口只回掩码 Key；编辑时送回的掩码换回原 Key，不会把掩码当 Key 存。"""
from api.model import KEY_MASK, _restore_masked_keys, mask_key, router


def test_mask_key():
    assert mask_key("sk-abcdef123456") == "sk-a****3456"
    assert mask_key("short") == KEY_MASK
    assert "abcdef12" not in mask_key("sk-abcdef123456")


def test_restore_masked_keys():
    old = ["sk-abcdef123456", "zp-0000111122223333"]
    sent = [mask_key(old[0]), "new-key-999", "xx****yy"]
    assert _restore_masked_keys(sent, old) == ["sk-abcdef123456", "new-key-999"]


def test_router_requires_login():
    deps = [d.dependency.__name__ for d in router.dependencies]
    assert "get_current_user" in deps
