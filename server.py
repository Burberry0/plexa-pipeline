"""
Plexa Housing — API Server
Flask server for webhook ingestion + demo API.

Usage:
  OPENAI_API_KEY=sk-... WEBHOOK_SECRET=... python server.py
"""

import hmac
import logging
import os
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import PipelineConfig
from email_templates import render_email_for_tier
from ingestion import DirectInputAdapter, parse_webhook_payload
from pipeline import Pipeline
from validation import tier_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_HEADER = "X-Webhook-Secret"


def create_app(config: PipelineConfig, pipeline) -> Flask:
    app = Flask(__name__)
    if config.allowed_origin:
        CORS(app, origins=[config.allowed_origin], allow_headers=["Content-Type", SECRET_HEADER])

    def require_secret(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not config.has_webhook_secret:
                return jsonify({"error": "WEBHOOK_SECRET not configured"}), 503
            provided = request.headers.get(SECRET_HEADER, "")
            if not hmac.compare_digest(provided, config.webhook_secret):
                return jsonify({"error": "Unauthorized"}), 401
            return fn(*args, **kwargs)
        return wrapper

    @app.route("/", methods=["GET"])
    def index():
        return send_from_directory(ROOT_DIR, "ui.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "models": {
                "junk_filter": config.junk_filter_model,
                "extraction": config.extraction_model,
            },
            "airtable": config.has_airtable_config,
            "auto_reply_enabled": config.auto_reply_enabled,
        })

    @app.route("/auth/check", methods=["GET"])
    @require_secret
    def auth_check():
        return jsonify({"ok": True})

    @app.route("/ingest", methods=["POST"])
    @require_secret
    def ingest():
        """n8n webhook endpoint. Accepts JSON email payload."""
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "No JSON payload"}), 400
        email = parse_webhook_payload(payload)
        result = pipeline.process_email(email, persist=True)
        return jsonify(result.to_dict())

    @app.route("/demo/classify", methods=["POST"])
    @require_secret
    def demo_classify():
        """Demo endpoint — full pipeline, nothing persisted."""
        data = request.get_json(silent=True)
        if not data or "body" not in data:
            return jsonify({"error": "Missing 'body' field"}), 400

        email = DirectInputAdapter().add_email(
            sender_email=data.get("sender_email", "demo@test.com"),
            sender_name=data.get("sender_name", "Demo User"),
            subject=data.get("subject", "Rental Inquiry"),
            body=data["body"],
        )
        result = pipeline.process_email(email, persist=False)
        result_dict = result.to_dict()
        if result.extracted and result.tier:
            result_dict["tier_summary"] = tier_summary(result.tier, result.extracted)
            result_dict["auto_reply_html"] = render_email_for_tier(result.tier, email, result.extracted)
        return jsonify(result_dict)

    return app


config = PipelineConfig.from_env()
app = create_app(config, Pipeline(config))


if __name__ == "__main__":
    print(f"\n  Plexa Housing API Server on port {config.port}")
    print(f"  Junk filter: {config.junk_filter_model} | Extraction: {config.extraction_model}")
    print(f"  Airtable: {'configured' if config.has_airtable_config else 'off'} | Auto-reply: {config.auto_reply_enabled}\n")
    app.run(host="0.0.0.0", port=config.port, debug=os.getenv("FLASK_DEBUG") == "1")
