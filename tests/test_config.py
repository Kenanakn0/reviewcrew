from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsError

from reviewcrew.config import CoreSettings, Settings, get_settings


@pytest.fixture
def required_env(monkeypatch: pytest.MonkeyPatch, private_key_path: Path) -> None:
    for name in ("APP_ENV", "LOG_LEVEL", "HOST", "PORT", "GITHUB_API_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv23liExample")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY_PATH", str(private_key_path))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "shh")


@pytest.mark.usefixtures("required_env")
def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert str(settings.github_api_url) == "https://api.github.com/"


@pytest.mark.usefixtures("required_env")
def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.port == 9000


@pytest.mark.usefixtures("required_env")
def test_env_file_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.log_level == "WARNING"


@pytest.mark.usefixtures("required_env")
def test_webhook_secret_is_masked_in_repr() -> None:
    settings = Settings(_env_file=None)

    assert "shh" not in repr(settings)
    assert settings.github_webhook_secret.get_secret_value() == "shh"


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOG_LEVEL", "LOUD"),
        ("PORT", "70000"),
        ("GITHUB_WEBHOOK_SECRET", ""),
        ("GITHUB_PRIVATE_KEY_PATH", "does/not/exist.pem"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize("missing", ["GITHUB_APP_CLIENT_ID", "GITHUB_WEBHOOK_SECRET"])
def test_github_credentials_are_required(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


@pytest.mark.usefixtures("required_env")
def test_diff_options_follow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIFF_MAX_TOKENS_PER_CHUNK", "12000")
    monkeypatch.setenv("DIFF_MAX_CHANGED_LINES_PER_FILE", "500")
    monkeypatch.setenv("DIFF_CONTEXT_LINES", "0")

    options = Settings(_env_file=None).diff_options()

    assert options.max_tokens_per_chunk == 12000
    assert options.filters.max_changed_lines == 500
    assert options.context_lines == 0


@pytest.mark.usefixtures("required_env")
def test_chunk_budget_below_minimum_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIFF_MAX_TOKENS_PER_CHUNK", "999")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
def test_llm_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_EFFORT", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "anthropic"
    assert settings.llm_model == "claude-opus-5-5"
    assert settings.llm_effort == "high"
    assert settings.anthropic_api_key is None  # the SDK can still find it on its own


@pytest.mark.usefixtures("required_env")
def test_openai_compat_requires_a_base_url_and_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(ValidationError, match="OPENAI_COMPAT_BASE_URL"):
        Settings(_env_file=None)

    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(ValidationError, match="LLM_MODEL is required"):
        Settings(_env_file=None)  # a Claude model name must not leak into Ollama

    monkeypatch.setenv("LLM_MODEL", "qwen2.5-coder:7b")
    settings = Settings(_env_file=None)
    assert (settings.llm_provider, settings.llm_model) == ("openai_compat", "qwen2.5-coder:7b")


@pytest.mark.usefixtures("required_env")
def test_ollama_setup_needs_no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # left empty in .env

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key is None


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize("name", ["OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY"])
def test_empty_values_mean_unset(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "  ")

    assert getattr(Settings(_env_file=None), name.lower()) is None


@pytest.mark.usefixtures("required_env")
def test_api_key_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret")

    assert "sk-ant-very-secret" not in repr(Settings(_env_file=None))


@pytest.mark.usefixtures("required_env")
def test_review_defaults_run_all_agents() -> None:
    settings = Settings(_env_file=None)

    assert settings.review_agents == ["security", "performance", "tests"]
    options = settings.review_options()
    assert options.aggregation.min_confidence == 0.5
    assert options.max_inline_comments == 20
    assert options.max_concurrent_llm_calls == 4


@pytest.mark.usefixtures("required_env")
def test_review_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_AGENTS", '["security", "tests"]')
    monkeypatch.setenv("REVIEW_MIN_CONFIDENCE", "0.7")
    monkeypatch.setenv("REVIEW_MAX_INLINE_COMMENTS", "5")
    monkeypatch.setenv("REVIEW_AGENT_TIMEOUT_SECONDS", "120")

    settings = Settings(_env_file=None)
    options = settings.review_options()

    assert settings.review_agents == ["security", "tests"]
    assert options.aggregation.min_confidence == 0.7
    assert options.max_inline_comments == 5
    assert options.agent_timeout_seconds == 120


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize("value", ['["security", "style"]', "[]"])
def test_invalid_agent_lists_are_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("REVIEW_AGENTS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
def test_agent_list_must_be_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_AGENTS", "security")

    with pytest.raises(SettingsError, match="review_agents"):
        Settings(_env_file=None)


def test_env_example_is_a_valid_local_llm_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_MODEL", "OPENAI_COMPAT_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    example = Path(__file__).parent.parent / ".env.example"

    settings = CoreSettings(_env_file=example)

    assert settings.llm_provider == "openai_compat"
    assert settings.llm_model == "qwen2.5-coder:7b"
    assert str(settings.openai_compat_base_url) == "http://localhost:11434/v1"
    assert settings.anthropic_api_key is None
    options = settings.review_options()
    assert options.diff.max_tokens_per_chunk == 4000
    assert options.max_concurrent_llm_calls == 1
