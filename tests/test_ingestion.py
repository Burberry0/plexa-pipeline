from ingestion import parse_webhook_payload, strip_html


def test_strip_html_drops_style_and_keeps_block_breaks():
    html = "<html><head><style>p{}</style></head><body><p>Hi</p><div>2BR in Henderson</div></body></html>"
    assert strip_html(html) == "Hi\n\n2BR in Henderson"


def test_strip_html_empty_returns_empty():
    assert strip_html("") == ""


def test_parse_webhook_prefers_plain_and_falls_back_to_html():
    email = parse_webhook_payload(
        {"sender_email": "a@b.com", "body_html": "<p>hello</p>", "message_id": "m1", "thread_id": "t1"}
    )
    assert email.body_plain == "hello"
    assert email.message_id == "m1"
    assert email.thread_id == "t1"
    assert email.sender_name == "Unknown"

    email2 = parse_webhook_payload({"body_plain": "plain wins", "body_html": "<p>html</p>"})
    assert email2.body_plain == "plain wins"
