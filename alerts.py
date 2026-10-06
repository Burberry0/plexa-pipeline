"""
Plexa Housing — Alerts
POSTs to a Slack-compatible incoming webhook. Never raises.
"""

import logging

import requests

logger = logging.getLogger("plexa.alerts")


def send_alert(url: str, text: str, session=None) -> bool:
    if not url:
        return False
    try:
        resp = (session or requests).post(url, json={"text": text}, timeout=5)
        return 200 <= resp.status_code < 300
    except Exception as e:  # noqa: BLE001 — alerts must never break the pipeline
        logger.warning(f"Alert delivery failed: {e}")
        return False
