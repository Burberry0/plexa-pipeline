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
