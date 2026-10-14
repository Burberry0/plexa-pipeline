import pytest

from config import OPENCODE_DEFAULT_BASE_URL, PipelineConfig


def _clear(monkeypatch):
    for name in ("OPENCODE_API_KEY", "OPENCODE_BASE_URL", "OPENAI_API_KEY", "EXTRACTION_RESPONSE_FORMAT", "AI_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)


def test_opencode_key_selects_opencode_provider(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", "oc-key")
    cfg = PipelineConfig.from_env(load_env_file=False)
    assert cfg.ai_provider == "opencode"
    assert cfg.ai_api_key == "oc-key"
    assert cfg.ai_base_url == OPENCODE_DEFAULT_BASE_URL
    assert cfg.has_ai_key is True


def test_without_opencode_key_provider_is_openai(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = PipelineConfig.from_env(load_env_file=False)
    assert cfg.ai_provider == "openai"
    assert cfg.ai_api_key == "sk-test"
    assert cfg.ai_base_url is None
    assert cfg.has_ai_key is True


def test_no_key_at_all(monkeypatch):
    _clear(monkeypatch)
    assert PipelineConfig.from_env(load_env_file=False).has_ai_key is False


def test_opencode_base_url_override(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", "oc-key")
    monkeypatch.setenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
    assert PipelineConfig.from_env(load_env_file=False).ai_base_url == "https://opencode.ai/zen/go/v1"


def test_extraction_response_format_defaults_to_json_schema(monkeypatch):
    _clear(monkeypatch)
    assert PipelineConfig.from_env(load_env_file=False).extraction_response_format == "json_schema"
    assert PipelineConfig.from_env(load_env_file=False).ai_user_agent == "plexa-pipeline/1.0"
    # Reasoning models count their thinking against max_tokens; 1024 left glm-5.3-flash with empty output.
    assert PipelineConfig.from_env(load_env_file=False).extraction_max_tokens == 4096
    # Same for the one-word junk filter: at 50 tokens glm-5.3-flash returned nothing and everything became LEAD.
    assert PipelineConfig.from_env(load_env_file=False).junk_filter_max_tokens == 512


@pytest.mark.parametrize("value", ["json_object", "none", "JSON_SCHEMA"])
def test_extraction_response_format_accepts_known_values(monkeypatch, value):
    _clear(monkeypatch)
    monkeypatch.setenv("EXTRACTION_RESPONSE_FORMAT", value)
    assert PipelineConfig.from_env(load_env_file=False).extraction_response_format == value.lower()


def test_extraction_response_format_rejects_unknown(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EXTRACTION_RESPONSE_FORMAT", "yaml")
    with pytest.raises(ValueError):
        PipelineConfig.from_env(load_env_file=False)


def test_repr_and_str_hide_secrets():
    cfg = PipelineConfig(
        openai_api_key="sk-openai-secret",
        opencode_api_key="oc-secret",
        airtable_api_key="pat-secret",
        webhook_secret="hook-secret",
        alert_webhook_url="https://hooks.slack.com/services/T0/B0/slack-secret",
    )
    text = repr(cfg) + str(cfg)
    for secret in ("sk-openai-secret", "oc-secret", "pat-secret", "hook-secret", "slack-secret"):
        assert secret not in text
    assert "junk_filter_model" in text  # non-secret fields still shown
