import json
from datetime import date
from types import SimpleNamespace

import pytest

from ai_client import (
    EXTRACTION_JSON_SCHEMA,
    AIClient,
    ExtractionRefused,
    PROMPTS,
    coerce_extraction,
)
from config import PipelineConfig
from models import Classification


class _FakeCompletions:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content, refusal=self.refusal))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class FakeOpenAI:
    def __init__(self, content, refusal=None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content, refusal))


FULL = {
    "location": "Henderson", "bedrooms": 2, "budget_min": 1620.0, "budget_max": 1980.0,
    "move_in_date": "2026-11-01", "pets": ["1 dog"], "occupants": 2, "duration_months": None,
    "pet_friendly_required": None, "confidence": 0.9, "missing_fields": [], "notes": None,
}


def test_classify_only_junk_on_explicit_junk(base_config, make_email):
    assert AIClient(base_config, client=FakeOpenAI("JUNK")).classify_email(make_email())[0] == Classification.JUNK
    assert AIClient(base_config, client=FakeOpenAI("junk.")).classify_email(make_email())[0] == Classification.JUNK
    assert AIClient(base_config, client=FakeOpenAI("LEAD")).classify_email(make_email())[0] == Classification.LEAD
    assert AIClient(base_config, client=FakeOpenAI("NOT A LEAD")).classify_email(make_email())[0] == Classification.LEAD
    assert AIClient(base_config, client=FakeOpenAI("")).classify_email(make_email())[0] == Classification.LEAD


def test_classify_warns_on_empty_content(base_config, make_email, caplog):
    with caplog.at_level("WARNING", logger="plexa.ai_client"):
        cls, _ = AIClient(base_config, client=FakeOpenAI("")).classify_email(make_email())
    assert cls == Classification.LEAD
    assert any("empty" in rec.message.lower() and "max_tokens" in rec.message for rec in caplog.records)


def test_extract_uses_structured_outputs_and_today(base_config, make_email):
    fake = FakeOpenAI(json.dumps(FULL))
    client = AIClient(base_config, client=fake)
    lead, tokens = client.extract_lead(make_email(), today=date(2026, 10, 5))
    kwargs = fake.chat.completions.last_kwargs
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["response_format"]["json_schema"]["schema"] == EXTRACTION_JSON_SCHEMA
    assert "TODAY: 2026-10-05" in kwargs["messages"][1]["content"]
    assert lead.location == "Henderson"
    assert lead.bedrooms == 2
    assert tokens == 15


def test_extract_strips_fences_if_model_disobeys(base_config, make_email):
    fake = FakeOpenAI("```json\n" + json.dumps(FULL) + "\n```")
    lead, _ = AIClient(base_config, client=fake).extract_lead(make_email())
    assert lead.occupants == 2


def test_extract_refusal_raises(base_config, make_email):
    fake = FakeOpenAI(None, refusal="I can't help with that.")
    with pytest.raises(ExtractionRefused):
        AIClient(base_config, client=fake).extract_lead(make_email())


def test_extract_empty_content_raises(base_config, make_email):
    with pytest.raises(ExtractionRefused):
        AIClient(base_config, client=FakeOpenAI("")).extract_lead(make_email())


def test_coerce_numeric_strings_and_missing_fields():
    data = coerce_extraction({
        "location": "89102", "bedrooms": "2", "budget_min": "1200", "budget_max": 1500.5,
        "occupants": 2.0, "duration_months": "twelve", "confidence": "0.7", "pets": "no pets",
    })
    assert data["bedrooms"] == 2
    assert data["budget_min"] == 1200.0
    assert data["budget_max"] == 1500.5
    assert data["occupants"] == 2
    assert data["duration_months"] is None
    assert data["confidence"] == 0.7
    assert data["pets"] is None
    assert data["missing_fields"] == []
    assert data["move_in_date"] is None
    assert data["notes"] is None


def test_coerce_drops_extra_fields():
    assert "extra" not in coerce_extraction({**FULL, "extra": 1})


def test_prompt_versions_bumped():
    assert PROMPTS["extraction"]["version"] == "1.1.0"
    assert PROMPTS["junk_filter"]["version"] == "1.1.0"
    assert "2026-06-15" not in PROMPTS["extraction"]["system_prompt"]


# ── Provider wiring ─────────────────────────────────────────────────────────

from ai_client import build_openai_client  # noqa: E402
from config import OPENCODE_DEFAULT_BASE_URL  # noqa: E402


def test_build_client_points_at_opencode_with_user_agent():
    cfg = PipelineConfig(opencode_api_key="oc-key", ai_user_agent="plexa-pipeline/1.0")
    client = build_openai_client(cfg)
    assert str(client.base_url).rstrip("/") == OPENCODE_DEFAULT_BASE_URL
    assert client._custom_headers["User-Agent"] == "plexa-pipeline/1.0"
    assert client.api_key == "oc-key"


def test_build_client_defaults_to_openai_without_opencode_key():
    client = build_openai_client(PipelineConfig(openai_api_key="sk-x"))
    assert "api.openai.com" in str(client.base_url)
    assert client.api_key == "sk-x"


def test_calls_send_message_id_as_opencode_session(base_config, make_email):
    fake = FakeOpenAI("LEAD")
    AIClient(base_config, client=fake).classify_email(make_email(message_id="msg-42"))
    assert fake.chat.completions.last_kwargs["extra_headers"]["x-opencode-session"] == "msg-42"

    fake = FakeOpenAI(json.dumps(FULL))
    AIClient(base_config, client=fake).extract_lead(make_email(message_id="msg-43"))
    assert fake.chat.completions.last_kwargs["extra_headers"]["x-opencode-session"] == "msg-43"


def test_calls_without_message_id_still_send_a_session(base_config, make_email):
    fake = FakeOpenAI("LEAD")
    AIClient(base_config, client=fake).classify_email(make_email(message_id=None))
    assert fake.chat.completions.last_kwargs["extra_headers"]["x-opencode-session"]


def test_extract_json_object_mode(make_email):
    cfg = PipelineConfig(openai_api_key="k", extraction_response_format="json_object")
    fake = FakeOpenAI(json.dumps(FULL))
    lead, _ = AIClient(cfg, client=fake).extract_lead(make_email())
    assert fake.chat.completions.last_kwargs["response_format"] == {"type": "json_object"}
    assert lead.bedrooms == 2


def test_extract_none_mode_omits_response_format(make_email):
    cfg = PipelineConfig(openai_api_key="k", extraction_response_format="none")
    fake = FakeOpenAI("```json\n" + json.dumps(FULL) + "\n```")
    lead, _ = AIClient(cfg, client=fake).extract_lead(make_email())
    assert "response_format" not in fake.chat.completions.last_kwargs
    assert lead.location == "Henderson"
