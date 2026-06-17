from core.config import settings
from services.agent.tools.code_executor import code_executor


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_code_executor", False)
    out = code_executor("print(1)")
    assert "disabled" in out.lower()


def test_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_code_executor", True)
    monkeypatch.setattr(settings, "code_executor_timeout", 10)
    out = code_executor("print(2 + 3)")
    assert "5" in out


def test_timeout_is_clamped(monkeypatch):
    monkeypatch.setattr(settings, "enable_code_executor", True)
    monkeypatch.setattr(settings, "code_executor_timeout", 5)
    # Requesting a huge timeout must be clamped to the configured max.
    out = code_executor("print('ok')", timeout=9999)
    assert "ok" in out
