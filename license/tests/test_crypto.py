import os
import stat
import subprocess
import sys
from pathlib import Path

from dongai_license import crypto

ROOT = Path(__file__).resolve().parents[1]


def test_roundtrip():
    priv, pub = crypto.generate_keypair()
    sig = crypto.sign(priv, b"hello")
    assert crypto.verify(pub, b"hello", sig)
    assert not crypto.verify(pub, b"hellp", sig)


def test_wrong_key_and_garbage_never_raise():
    priv, pub = crypto.generate_keypair()
    _, pub2 = crypto.generate_keypair()
    sig = crypto.sign(priv, b"x")
    assert not crypto.verify(pub2, b"x", sig)
    assert not crypto.verify("!!!", b"x", sig)
    assert not crypto.verify(pub, b"x", b"short")
    assert not crypto.verify(None, b"x", sig)  # type: ignore[arg-type]


def test_key_format_and_kid():
    priv, pub = crypto.generate_keypair()
    assert len(crypto.b64u_decode(priv)) == 32
    assert len(crypto.b64u_decode(pub)) == 32
    assert "=" not in priv + pub
    kid = crypto.key_id_for(pub)
    assert len(kid) == 8 and int(kid, 16) >= 0
    assert crypto.key_id_for(pub) == kid


def test_gen_keys_script(tmp_path):
    out = tmp_path / "k.key"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen_keys.py"), "--out", str(out)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    priv = out.read_text().strip()
    assert priv not in r.stdout and priv not in r.stderr
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert "public_key:" in r.stdout and "kid:" in r.stdout


def test_gen_keys_refuses_inside_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    out = tmp_path / "k.key"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen_keys.py"), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert not out.exists()
