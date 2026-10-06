"""
Plexa Housing — Prompt eval runner
Runs the golden set through the real pipeline (OpenAI calls, no Airtable)
and reports classification / tier / gate-field accuracy.

Usage:
  OPENAI_API_KEY=sk-... python -m evals.run_eval
  python -m evals.run_eval --file evals/golden_emails.jsonl --min-tier-accuracy 0.9
"""

import argparse
import json
import os
import sys

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

    return {
        "id": case["id"],
        "classification_ok": result.classification.value == case.get("expected_classification"),
        "tier_ok": (result.tier.value if result.tier else None) == case.get("expected_tier"),
        "location_ok": location_ok,
        "bedrooms_ok": got_bedrooms == case.get("expected_bedrooms"),
    }


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
        "failures": [s["id"] for s in scores if not all((s["classification_ok"], s["tier_ok"], s["location_ok"], s["bedrooms_ok"]))],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=os.path.join(os.path.dirname(__file__), "golden_emails.jsonl"))
    parser.add_argument("--min-tier-accuracy", type=float, default=0.0)
    args = parser.parse_args()

    config = PipelineConfig.from_env()
    if not config.has_openai_key:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return 2

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
        flag = "OK " if all(v for k, v in s.items() if k != "id") else "BAD"
        print(f"{flag} {s['id']:<24} cls={result.classification.value:<4} tier={result.tier.value if result.tier else '-':<7} "
              f"loc={result.extracted.location if result.extracted else '-'} br={result.extracted.bedrooms if result.extracted else '-'}")

    summary = summarize(scores)
    print(json.dumps(summary, indent=2))
    return 0 if summary["tier_accuracy"] >= args.min_tier_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
