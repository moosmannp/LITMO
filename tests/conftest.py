"""Shared setup for all tests (DECISIONS 123): the project on the import path, sessions in a temporary folder, and
every global a test replaces (a fake model, a fake OOPS! service ...) restored after the test."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
os.environ["ODT_SESSION_DIR"] = tempfile.mkdtemp()     # before the first `import app`: never the user's projects
os.chdir(ROOT)

import requests  # noqa: E402


def _patchable_modules():
    """The tool's own modules (the tests replace their functions) and requests (the tests fake its calls)."""
    mods = [requests]
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None) or ""
        if os.path.dirname(os.path.abspath(f)) == ROOT:
            mods.append(m)
    return mods


@pytest.fixture(autouse=True)
def restore_globals():
    """Tests assign fakes directly (`L.call_llm = FakeLLM(...)`); without this, a fake stays for every later test
    and the result depends on the order. Only the bindings are restored - the contents of a dict such as
    app.sessions are state the tests share on purpose."""
    saved = [(m, dict(vars(m))) for m in _patchable_modules()]
    yield
    for m, before in saved:
        now = vars(m)
        for name in [n for n in now if n not in before]:
            del now[name]
        for name, value in before.items():
            if now.get(name, object()) is not value:
                now[name] = value
