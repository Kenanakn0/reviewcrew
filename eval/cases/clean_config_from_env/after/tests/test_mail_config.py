import pytest

from app.mail_config import load_mail_config


def test_reads_key_and_default_sender(monkeypatch):
    monkeypatch.setenv("MAIL_API_KEY", "test-key")
    monkeypatch.delenv("MAIL_SENDER", raising=False)
    config = load_mail_config()
    assert config.api_key == "test-key"
    assert config.sender == "noreply@example.com"


def test_missing_key_is_an_error(monkeypatch):
    monkeypatch.delenv("MAIL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MAIL_API_KEY"):
        load_mail_config()
