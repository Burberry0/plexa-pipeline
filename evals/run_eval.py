"""
Plexa Housing — Prompt eval runner
Runs the golden set through the real pipeline (live model calls, no Airtable)
and reports classification / tier / gate-field / match-readiness accuracy.

Usage:
  python -m evals.run_eval                      # provider/models from env (.env is loaded)
  python -m evals.run_eval --file evals/golden_emails.jsonl --min-tier-accuracy 0.9
  python -m evals.run_eval --junk-model glm-5.3-flash --extraction-model deepseek-v4-pro
"""

import argparse
import dataclasses
import json
import os
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import PipelineConfig  # noqa: E402
from ingestion import DirectInputAdapter  # noqa: E402
from models import PipelineResult  # noqa: E402
from pipeline import Pipeline  # noqa: E402


def load_cases(path: str) -> list:
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _norm(value):
    return str(value).strip().lower() if value is not None else None


def score_case(case: dict, result: PipelineResult) -> dict:
    extracted = result.extracted
    got_location = _norm(extracted.location) if extracted else None
    got_bedrooms = extracted.bedrooms if extracted else None
    exp_location = _norm(case.get("expected_location"))

    if exp_location is None:
        location_ok = got_location is None
    else:
        location_ok = got_location is not None and exp_location in got_location

    got_zip = extracted.zip_code if extracted else None
    return {
        "id": case["id"],
        "classification_ok": result.classification.value == case.get("expected_classification"),
        "tier_ok": (result.tier.value if result.tier else None) == case.get("expected_tier"),
        "location_ok": location_ok,
        "bedrooms_ok": got_bedrooms == case.get("expected_bedrooms"),
        "zip_ok": got_zip == case.get("expected_zip_code"),
        "match_ready_ok": result.match_ready == bool(case.get("expected_match_ready", False)),
    }


SCORE_KEYS = ("classification_ok", "tier_ok", "location_ok", "bedrooms_ok", "zip_ok", "match_ready_ok")


def format_line(score: dict, result: PipelineResult) -> str:
    """One console line per case. A pipeline error is shown so it cannot hide behind a default JUNK."""
    flag = "OK " if all(v for k, v in score.items() if k != "id") else "BAD"
    tier = result.tier.value if result.tier else "-"
    loc = result.extracted.location if result.extracted else "-"
    br = result.extracted.bedrooms if result.extracted else "-"
    zip_code = result.extracted.zip_code if result.extracted else "-"
    line = (f"{flag} {score['id']:<36} cls={result.classification.value:<4} tier={tier:<7} "
            f"loc={loc} zip={zip_code} br={br} mr={result.match_ready} ms={result.processing_time_ms:.0f}")
    if result.error:
        line += f" err={result.error}"
    return line


def summarize(scores: list) -> dict:
    total = len(scores)

    def acc(key):
        return round(sum(1 for s in scores if s[key]) / total, 3) if total else 0.0

    return {
        "total": total,
        "classification_accuracy": acc("classification_ok"),
        "tier_accuracy": acc("tier_ok"),
        "location_accuracy": acc("location_ok"),
        "bedrooms_accuracy": acc("bedrooms_ok"),
        "zip_accuracy": acc("zip_ok"),
        "match_ready_accuracy": acc("match_ready_ok"),
        "failures": [s["id"] for s in scores if not all(s[k] for k in SCORE_KEYS)],
    }


def apply_model_overrides(config: PipelineConfig, junk_model: Optional[str], extraction_model: Optional[str]) -> PipelineConfig:
    """Return a config with the given models swapped in; None keeps the configured one."""
    changes = {}
    if junk_model:
        changes["junk_filter_model"] = junk_model
    if extraction_model:
        changes["extraction_model"] = extraction_model
    return dataclasses.replace(config, **changes) if changes else config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=os.path.join(os.path.dirname(__file__), "golden_emails.jsonl"))
    parser.add_argument("--min-tier-accuracy", type=float, default=0.0)
    parser.add_argument("--junk-model", help="override JUNK_FILTER_MODEL for this run")
    parser.add_argument("--extraction-model", help="override EXTRACTION_MODEL for this run")
    args = parser.parse_args()

    config = apply_model_overrides(PipelineConfig.from_env(), args.junk_model, args.extraction_model)
    if not config.has_ai_key:
        print("Set OPENCODE_API_KEY or OPENAI_API_KEY", file=sys.stderr)
        return 2
    print(f"provider={config.ai_provider} junk_filter={config.junk_filter_model} "
          f"extraction={config.extraction_model} response_format={config.extraction_response_format}")

    pipeline = Pipeline(config, airtable=None)
    adapter = DirectInputAdapter()
    scores = []
    for case in load_cases(args.file):
        email = adapter.add_email(
            sender_email=case.get("sender_email", "eval@test.com"),
            sender_name=case.get("sender_name", "Eval"),
            subject=case.get("subject", ""),
            body=case["body"],
        )
        result = pipeline.process_email(email, persist=False)
        s = score_case(case, result)
        scores.append(s)
        print(format_line(s, result))

    summary = summarize(scores)
    print(json.dumps(summary, indent=2))
    return 0 if summary["tier_accuracy"] >= args.min_tier_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
