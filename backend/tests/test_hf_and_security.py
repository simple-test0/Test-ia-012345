from pathlib import Path

from core import security
from core.config import settings
from services.image_gen import hf_connector


def test_repo_cache_path_format():
    p = hf_connector._repo_cache_path("org/Model-Name")
    assert p.name == "models--org--Model-Name"


def test_download_progress_zero_total():
    assert hf_connector.download_progress("org/x", 0) == 0


def test_download_progress_no_dir(tmp_path, monkeypatch):
    # Point cache at an empty temp dir -> 0% progress.
    monkeypatch.setattr(settings, "models_dir", tmp_path)
    assert hf_connector.download_progress("org/missing", 1000) == 0


def test_ws_token_disabled(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")
    assert security.ws_token_ok("anything") is True
    assert security.ws_token_ok("") is True


def test_ws_token_enabled(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret")
    assert security.ws_token_ok("secret") is True
    assert security.ws_token_ok("wrong") is False
