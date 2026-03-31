"""
Plexa Housing — API Server
Flask server for webhook ingestion + demo API.

Usage:
  OPENAI_API_KEY=sk-... python server.py
"""

import os
import json
import logging
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS

from config import PipelineConfig
from pipeline import Pipeline
from ingestion import DirectInputAdapter, parse_webhook_payload
from validation import tier_summary
from email_templates import render_email_for_tier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)
CORS(app)

config = PipelineConfig.from_env()
pipeline = Pipeline(config)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "models": {
            "junk_filter": config.junk_filter_model,
            "extraction": config.extraction_model,
        },
    })


@app.route("/ingest", methods=["POST"])
def ingest():
    """n8n webhook endpoint. Accepts JSON email payload."""
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "No JSON payload"}), 400

    email = parse_webhook_payload(payload)
    result = pipeline.process_email(email)
    return jsonify(result.to_dict())


@app.route("/demo/classify", methods=["POST"])
def demo_classify():
    """Demo endpoint — process an email through the full pipeline."""
    data = request.get_json()
    if not data or "body" not in data:
        return jsonify({"error": "Missing 'body' field"}), 400

    adapter = DirectInputAdapter()
    email = adapter.add_email(
        sender_email=data.get("sender_email", "demo@test.com"),
        sender_name=data.get("sender_name", "Demo User"),
        subject=data.get("subject", "Rental Inquiry"),
        body=data["body"],
    )

    result = pipeline.process_email(email)
    result_dict = result.to_dict()

    # Add tier summary and email template if it's a lead
    if result.extracted and result.tier:
        result_dict["tier_summary"] = tier_summary(result.tier, result.extracted)
        result_dict["auto_reply_html"] = render_email_for_tier(
            result.tier, email, result.extracted
        )

    return jsonify(result_dict)


if __name__ == "__main__":
    port = config.port
    print(f"\n  Plexa Housing API Server")
    print(f"  Port: {port}")
    print(f"  Junk filter: {config.junk_filter_model}")
    print(f"  Extraction:  {config.extraction_model}")
    print(f"\n  Endpoints:")
    print(f"    GET  /health          → Health check")
    print(f"    POST /ingest          → n8n webhook (production)")
    print(f"    POST /demo/classify   → Demo email classification")
    print()
    app.run(host="0.0.0.0", port=port, debug=True)
