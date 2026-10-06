from types import SimpleNamespace

from alerts import send_alert


class _Session:
    def __init__(self, status=200, raise_exc=None):
        self.status = status
        self.raise_exc = raise_exc
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        if self.raise_exc:
            raise self.raise_exc
        return SimpleNamespace(status_code=self.status)


def test_no_url_is_noop():
    assert send_alert("", "hi") is False


def test_posts_text():
    s = _Session()
    assert send_alert("https://hooks.example/x", "boom", session=s) is True
    assert s.calls == [("https://hooks.example/x", {"text": "boom"}, 5)]


def test_swallows_errors():
    assert send_alert("https://hooks.example/x", "boom", session=_Session(raise_exc=RuntimeError("down"))) is False
    assert send_alert("https://hooks.example/x", "boom", session=_Session(status=500)) is False
