import base64
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JWT_PATTERN = re.compile(
    r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"
)


def _jwt_role(token: str) -> str | None:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))["role"]
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def test_handover_does_not_embed_service_role_key():
    for relative in ("handover/01_HANDOVER.md", "handover/generate_handover.py"):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert all(_jwt_role(token) != "service_role" for token in JWT_PATTERN.findall(content))
        assert "Service_role key actual:" not in content, relative


def test_frontend_has_xss_and_clickjacking_guards():
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    ranking = (ROOT / "web/ranking.html").read_text(encoding="utf-8")
    htaccess = (ROOT / "web/.htaccess").read_text(encoding="utf-8")

    assert "function htmlEsc(value)" in index
    assert "function htmlEsc(value)" in ranking
    assert "Content-Security-Policy" in htaccess
    assert "frame-ancestors 'self'" in htaccess


def test_node_server_blocks_internal_files_and_path_escape():
    server = (ROOT / "web/server.js").read_text(encoding="utf-8")
    htaccess = (ROOT / "web/.htaccess").read_text(encoding="utf-8")

    for filename in ("server.js", "package.json", "claude_debug.json"):
        assert filename in server
        assert filename.replace(".", r"\.") in htaccess
    assert "path.resolve(root, `.${pathname}`)" in server
    assert "root + path.sep" in server
