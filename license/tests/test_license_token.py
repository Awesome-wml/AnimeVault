import base64
import json

import pytest

from dongai_license import crypto
from dongai_license import license_token as lt

MC = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
NOW = 1_800_000_000


@pytest.fixture(scope="module")
def keys():
    priv, pub = crypto.generate_keypair()
    kid = crypto.key_id_for(pub)
    return priv, pub, kid, {kid: pub}


def mk(keys, **kw):
    priv, _, kid, _ = keys
    args = dict(lid="lic_1", mc=MC, plan="pro", features=["video"],
                exp=NOW + 1000, iat=NOW - 10)
    args.update(kw)
    return lt.issue_license(priv, kid, **args)


def mklease(keys, **kw):
    priv, _, kid, _ = keys
    args = dict(lid="lic_1", mc=MC, sid="s1", ttl_seconds=100, iat=NOW,
                lexp=NOW + 5000, plan="pro", features=["video"], cv=3)
    args.update(kw)
    return lt.issue_lease(priv, kid, **args)


def test_roundtrip(keys):
    p = lt.verify_license(mk(keys, uid="usr_1"), keys[3], MC, now=NOW)
    assert p["typ"] == "license" and p["lid"] == "lic_1" and p["uid"] == "usr_1"
    assert p["plan"] == "pro" and p["mc"] == MC and p["v"] == 1


def test_fields_preserved(keys):
    c = mk(keys, dev_max=3, features=["a", "b", "c"], plan="team")
    p = lt.verify_license(c, keys[3], MC, now=NOW)
    assert p["dev_max"] == 3 and p["features"] == ["a", "b", "c"] and p["plan"] == "team"
    assert "uid" not in p
    assert lt.verify_license(mk(keys), keys[3], MC, now=NOW)["dev_max"] == 1


def _tamper(code, mutate):
    data_b32, sig = code.split(".")
    data = base64.b32decode(data_b32 + "=" * (-len(data_b32) % 8))
    obj = json.loads(data)
    mutate(obj)
    new = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return base64.b32encode(new).decode().rstrip("=") + "." + sig


@pytest.mark.parametrize("m", [
    lambda o: o.update(plan="enterprise"),
    lambda o: o.update(exp=o["exp"] + 999999),
    lambda o: o.update(mc=["dddddddddddddddd"] + o["mc"][1:]),
])
def test_tamper_payload(keys, m):
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_license(_tamper(mk(keys), m), keys[3], MC, now=NOW)


def test_flip_every_byte_position_sample(keys):
    code = mk(keys)
    data_b32, sig = code.split(".")
    raw = bytearray(base64.b32decode(data_b32 + "=" * (-len(data_b32) % 8)))
    for i in range(0, len(raw), 7):
        r = bytearray(raw)
        r[i] ^= 1
        bad = base64.b32encode(bytes(r)).decode().rstrip("=") + "." + sig
        with pytest.raises(lt.LicenseError):
            lt.verify_license(bad, keys[3], MC, now=NOW)


def test_wrong_public_key(keys):
    _, other = crypto.generate_keypair()
    with pytest.raises(lt.LicenseInvalid) as e:
        lt.verify_license(mk(keys), {keys[2]: other}, MC, now=NOW)
    assert e.value.code == "LICENSE_INVALID" and not isinstance(e.value, lt.UnknownKey)


def test_unknown_kid(keys):
    with pytest.raises(lt.UnknownKey) as e:
        lt.verify_license(mk(keys), {"zzzz": keys[1]}, MC, now=NOW)
    assert e.value.code == "LICENSE_INVALID" and "kid" in str(e.value)


def test_machine_mismatch_and_tolerance(keys):
    c = mk(keys)
    lt.verify_license(c, keys[3], ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "x" * 16], now=NOW)
    with pytest.raises(lt.MachineMismatch) as e:
        lt.verify_license(c, keys[3], ["aaaaaaaaaaaaaaaa", "y" * 16, "z" * 16], now=NOW)
    assert e.value.code == "LICENSE_MACHINE_MISMATCH"
    with pytest.raises(lt.MachineMismatch):
        lt.verify_license(c, keys[3], [], now=NOW)


def test_components_match_rules():
    m = lt.components_match
    assert m(["a", "b", "c"], ["a", "b", "x"])
    assert not m(["a", "b", "c"], ["a", "x", "y"])
    assert m(["a"], ["a", "b", "c"])          # 较短一边全部命中
    assert not m(["a"], ["b", "c"])
    assert m(["a", "b"], ["a", "b"])
    assert not m(["a", "b"], ["a", "x"])      # 较短一边 2 个，需 2 命中
    assert not m([], ["a"]) and not m(["a"], [])


def test_expired(keys):
    c = mk(keys, exp=NOW + 5)
    lt.verify_license(c, keys[3], MC, now=NOW)
    with pytest.raises(lt.LicenseExpired) as e:
        lt.verify_license(c, keys[3], MC, now=NOW + 5)
    assert e.value.code == "LICENSE_EXPIRED"


def test_lease_roundtrip_and_expiry_payload(keys):
    t = mklease(keys)
    p = lt.verify_lease(t, keys[3], MC, now=NOW + 50)
    assert p["typ"] == "lease" and p["sid"] == "s1" and p["st"] == "active"
    assert p["exp"] == NOW + 100
    with pytest.raises(lt.LeaseExpired) as e:
        lt.verify_lease(t, keys[3], MC, now=NOW + 101)
    assert e.value.code == "LEASE_EXPIRED"
    assert e.value.payload["lid"] == "lic_1" and e.value.payload["exp"] == NOW + 100


def test_lease_signed_entitlement_fields(keys):
    p = lt.verify_lease(mklease(keys, lexp=NOW + 777, plan="team", features=["a", "b"], cv=9),
                        keys[3], MC, now=NOW + 1)
    assert p["v"] == 2 and p["lexp"] == NOW + 777 and p["plan"] == "team"
    assert p["features"] == ["a", "b"] and p["cv"] == 9
    # 租约过期时 LeaseExpired.payload 同样带这些字段
    with pytest.raises(lt.LeaseExpired) as e:
        lt.verify_lease(mklease(keys), keys[3], MC, now=NOW + 101)
    assert e.value.payload["lexp"] == NOW + 5000 and e.value.payload["features"] == ["video"]


@pytest.mark.parametrize("m", [
    lambda o: o.update(lexp=o["lexp"] + 10**6),
    lambda o: o.update(plan="enterprise"),
    lambda o: o.update(features=o["features"] + ["admin"]),
    lambda o: o.update(features=[]),
    lambda o: o.update(cv=o["cv"] + 1),
])
def test_lease_tamper_entitlement_fields(keys, m):
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(_tamper(mklease(keys), m), keys[3], MC, now=NOW + 1)


def test_lease_tamper_every_byte_sample(keys):
    data_b32, sig = mklease(keys).split(".")
    raw = bytearray(base64.b32decode(data_b32 + "=" * (-len(data_b32) % 8)))
    for i in range(0, len(raw), 5):
        r = bytearray(raw)
        r[i] ^= 1
        bad = base64.b32encode(bytes(r)).decode().rstrip("=") + "." + sig
        with pytest.raises(lt.LicenseError):
            lt.verify_lease(bad, keys[3], MC, now=NOW + 1)


def _lease_obj(keys):
    t = mklease(keys).split(".")[0]
    return json.loads(base64.b32decode(t + "=" * (-len(t) % 8)))


def test_lease_field_type_checks_and_required(keys):
    base = _lease_obj(keys)
    for k, v in [("lexp", "123"), ("lexp", 1.5), ("lexp", True), ("plan", 1), ("features", "video"),
                 ("features", [1]), ("cv", "1"), ("cv", None), ("cv", True)]:
        obj = dict(base); obj[k] = v
        with pytest.raises(lt.LicenseInvalid):
            lt.verify_lease(_raw(keys, obj), keys[3], MC, now=NOW + 1)
    for k in ("lexp", "plan", "features", "cv"):  # 必需字段缺失
        obj = dict(base); del obj[k]
        with pytest.raises(lt.LicenseInvalid):
            lt.verify_lease(_raw(keys, obj), keys[3], MC, now=NOW + 1)


def test_lease_v1_rejected_and_license_still_v1(keys):
    old = {k: v for k, v in _lease_obj(keys).items() if k not in ("lexp", "plan", "features", "cv")}
    old["v"] = 1
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(_raw(keys, old), keys[3], MC, now=NOW + 1)
    # 即使字段齐全，v=1 的租约也拒绝；授权码 v=2 同样拒绝
    full = _lease_obj(keys); full["v"] = 1
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(_raw(keys, full), keys[3], MC, now=NOW + 1)
    lic = json.loads(base64.b32decode((lambda s: s + "=" * (-len(s) % 8))(mk(keys).split(".")[0])))
    assert lic["v"] == 1
    lic["v"] = 2
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_license(_raw(keys, lic), keys[3], MC, now=NOW)


def test_lease_machine_mismatch_before_expiry(keys):
    with pytest.raises(lt.MachineMismatch):
        lt.verify_lease(mklease(keys), keys[3], ["q" * 16, "w" * 16], now=NOW + 1000)


def test_lease_tamper_does_not_leak_payload(keys):
    t = _tamper(mklease(keys), lambda o: o.update(exp=o["exp"] + 10**6))
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(t, keys[3], MC, now=NOW + 1000)


def test_typ_confusion(keys):
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_license(mklease(keys), keys[3], MC, now=NOW)
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(mk(keys), keys[3], MC, now=NOW)


def _raw(keys, obj):
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    sig = crypto.sign(keys[0], data)
    return lt._b32e(data) + "." + lt._b32e(sig)


def test_field_type_checks(keys):
    base = json.loads(base64.b32decode(
        (lambda s: s + "=" * (-len(s) % 8))(mk(keys).split(".")[0])))
    for k, v in [("exp", "123"), ("exp", 1.5), ("iat", True), ("features", "video"),
                 ("mc", [1, 2]), ("dev_max", None)]:
        obj = dict(base); obj[k] = v
        with pytest.raises(lt.LicenseInvalid):
            lt.verify_license(_raw(keys, obj), keys[3], MC, now=NOW)
    obj = dict(base); del obj["lid"]
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_license(_raw(keys, obj), keys[3], MC, now=NOW)


@pytest.mark.parametrize("bad", [
    "", "nodot", "A.B.C", "abc!.def", "A" * 5000 + "." + "A", ".", "AAAA.",
    ".AAAA", "11111.22222", "MFRGG.MFRGG",
    lt._b32e(b"not json") + "." + lt._b32e(b"sig"),
    lt._b32e(b"[1,2]") + "." + lt._b32e(b"sig"),
    lt._b32e(b"\xff\xfe") + "." + lt._b32e(b"sig"),
    None, 123,
])
def test_malformed(keys, bad):
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_license(bad, keys[3], MC, now=NOW)
    with pytest.raises(lt.LicenseInvalid):
        lt.verify_lease(bad, keys[3], MC, now=NOW)


def test_display_roundtrip(keys):
    code = mk(keys)
    shown = lt.format_for_display(code)
    assert "\n" in shown and "-" in shown
    assert lt.normalize_input(shown) == code
    messy = "  " + shown.lower().replace("\n", "\r\n  ").replace("-", " - ") + " \t"
    assert lt.normalize_input(messy) == code
    assert lt.normalize_input(lt.format_for_display(code, group=4, per_line=3)) == code
    p = lt.verify_license(lt.normalize_input(messy), keys[3], MC, now=NOW)
    assert p["lid"] == "lic_1"


def test_error_messages_generic(keys):
    with pytest.raises(lt.LicenseInvalid) as e:
        lt.verify_license(_tamper(mk(keys), lambda o: o.update(plan="x")), keys[3], MC, now=NOW)
    assert "plan" not in str(e.value) and "signature" not in str(e.value).lower()
