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
    "pet_friendly_required": None,
    "zip_code": "89052", "phone": "(702) 555-1234", "bathrooms": 2, "square_feet": None,
    "adults": 2, "children": None, "pet_count": 1,
    "pet_details": [{"type": "Dog", "description": "40 lbs lab"}],
    "garage_required": None, "garage_spaces": None, "amenities": ["Pool"],
    "special_requests": None, "requester_type": "Individual", "company_name": None,
    "confidence": 0.9, "missing_fields": [], "notes": None,
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
    assert lead.zip_code == "89052"
    assert lead.amenities == ["Pool"]
    assert lead.pet_details == [{"type": "Dog", "description": "40 lbs lab"}]
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
    assert PROMPTS["extraction"]["version"] == "2.0.0"
    assert PROMPTS["extraction"]["last_updated"] == "2026-10-13"
    assert PROMPTS["junk_filter"]["version"] == "1.1.0"
    assert "2026-06-15" not in PROMPTS["extraction"]["system_prompt"]
    assert "zip_code" in PROMPTS["extraction"]["system_prompt"]


def test_coerce_zip_code():
    assert coerce_extraction({"zip_code": "89102"})["zip_code"] == "89102"
    assert coerce_extraction({"zip_code": "89102-1234"})["zip_code"] == "89102"
    assert coerce_extraction({"zip_code": 89102})["zip_code"] == "89102"
    assert coerce_extraction({"zip_code": "8910"})["zip_code"] is None
    assert coerce_extraction({"zip_code": "Henderson"})["zip_code"] is None


def test_coerce_backfills_zip_from_five_digit_location():
    assert coerce_extraction({"location": "89102", "zip_code": None})["zip_code"] == "89102"
    assert coerce_extraction({"location": "Henderson", "zip_code": None})["zip_code"] is None
    # an explicit zip is not overwritten by location
    assert coerce_extraction({"location": "89102", "zip_code": "89052"})["zip_code"] == "89052"


def test_coerce_amenities_filters_to_enum_and_keeps_empty_list():
    assert coerce_extraction({"amenities": ["Pool", "Jacuzzi"]})["amenities"] == ["Pool"]
    assert coerce_extraction({"amenities": ["pool", "hot tub"]})["amenities"] == ["Pool", "Hot tub"]
    assert coerce_extraction({"amenities": []})["amenities"] == []
    assert coerce_extraction({"amenities": "Pool"})["amenities"] is None
    assert coerce_extraction({})["amenities"] is None


def test_coerce_pet_details_shape():
    out = coerce_extraction({"pet_details": [
        {"type": "dog", "description": "40lb lab"},
        {"type": "parrot", "description": None},
        "not a dict",
        {"type": None, "description": "mystery"},
    ]})["pet_details"]
    assert out == [
        {"type": "Dog", "description": "40lb lab"},
        {"type": "Other", "description": None},
        {"type": "Other", "description": "mystery"},
    ]
    assert coerce_extraction({"pet_details": "a dog"})["pet_details"] is None
    assert coerce_extraction({"pet_details": []})["pet_details"] == []


def test_coerce_requester_type_bools_and_numbers():
    assert coerce_extraction({"requester_type": "company"})["requester_type"] == "Company"
    assert coerce_extraction({"requester_type": "Individual"})["requester_type"] == "Individual"
    assert coerce_extraction({"requester_type": "LLC"})["requester_type"] is None
    assert coerce_extraction({"garage_required": "yes"})["garage_required"] is None
    assert coerce_extraction({"garage_required": True})["garage_required"] is True
    assert coerce_extraction({"bathrooms": "1.5"})["bathrooms"] == 1.5
    assert coerce_extraction({"square_feet": "1,200"})["square_feet"] == 1200
    assert coerce_extraction({"adults": 2.0, "children": "1", "pet_count": "two"})["adults"] == 2
    assert coerce_extraction({"adults": 2.0, "children": "1", "pet_count": "two"})["children"] == 1
    assert coerce_extraction({"adults": 2.0, "children": "1", "pet_count": "two"})["pet_count"] is None
    assert coerce_extraction({"phone": 7025551234})["phone"] == "7025551234"
    assert coerce_extraction({"company_name": "  Acme  "})["company_name"] == "Acme"


def test_schema_is_strict_mode_compatible():
    props = EXTRACTION_JSON_SCHEMA["properties"]
    assert set(EXTRACTION_JSON_SCHEMA["required"]) == set(props)
    assert set(FULL) == set(props)
    items = props["pet_details"]["items"]
    assert items["additionalProperties"] is False
    assert set(items["required"]) == {"type", "description"}
    assert "Pool" in props["amenities"]["items"]["enum"]
    assert set(props["requester_type"]["enum"]) == {"Individual", "Company", None}


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
