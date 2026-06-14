"""Tests for integrations/webhook.py — error handling and edge cases."""
from __future__ import annotations

import io
import urllib.error
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(__file__).replace("\\tests\\test_webhook.py", ""))
from integrations.webhook import _parse_header, _validate_url, main


# ---------------------------------------------------------------------------
# Unit: URL validation
# ---------------------------------------------------------------------------

def test_valid_https_url():
    assert _validate_url("https://example.com/hook") is None


def test_valid_http_url():
    assert _validate_url("http://localhost:9000/") is None


def test_bad_scheme_returns_error():
    err = _validate_url("ftp://example.com/hook")
    assert err is not None
    assert "ftp" in err


def test_no_scheme_returns_error():
    err = _validate_url("example.com/hook")
    assert err is not None


def test_empty_url_returns_error():
    err = _validate_url("")
    assert err is not None


# ---------------------------------------------------------------------------
# Unit: header parsing
# ---------------------------------------------------------------------------

def test_parse_header_ok():
    assert _parse_header("Authorization: Bearer tok") == ("Authorization", "Bearer tok")


def test_parse_header_no_colon_returns_none():
    assert _parse_header("BadHeader") is None


def test_parse_header_empty_key_returns_none():
    assert _parse_header(": value") is None


def test_parse_header_preserves_value_with_colon():
    key, val = _parse_header("X-Custom: foo:bar")
    assert key == "X-Custom"
    assert val == "foo:bar"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stdin(text: str | bytes) -> io.BytesIO:
    data = text if isinstance(text, bytes) else text.encode()
    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# Integration: main() exit codes via _stdin parameter
# ---------------------------------------------------------------------------

def test_empty_stdin_returns_nonzero():
    code = main(["--url", "https://example.com/hook"], _stdin=_stdin(""))
    assert code != 0


def test_whitespace_only_stdin_returns_nonzero():
    code = main(["--url", "https://example.com/hook"], _stdin=_stdin("   \n  "))
    assert code != 0


def test_invalid_json_stdin_returns_nonzero():
    code = main(["--url", "https://example.com/hook"], _stdin=_stdin("not json {{{"))
    assert code != 0


def test_bad_url_scheme_exits_2():
    code = main(["--url", "ftp://example.com/"], _stdin=_stdin('{"k": 1}'))
    assert code == 2


def test_malformed_header_exits_2():
    code = main(
        ["--url", "https://example.com/hook", "--header", "BadHeader"],
        _stdin=_stdin('{"k": 1}'),
    )
    assert code == 2


def test_allow_empty_flag_skips_empty_check():
    """--allow-empty should move past the empty-stdin guard (will fail at network)."""
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("no route to host")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        code = main(
            ["--url", "https://example.com/hook", "--allow-empty"],
            _stdin=_stdin(""),
        )
    # Network error -> 1, NOT the empty-stdin exit code 2
    assert code == 1


def test_http_error_returns_nonzero():
    """A 4xx response should produce a non-zero exit and not raise."""
    exc = urllib.error.HTTPError(
        url="https://example.com/hook",
        code=403,
        msg="Forbidden",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=exc):
        code = main(
            ["--url", "https://example.com/hook"],
            _stdin=_stdin('{"k": 1}'),
        )
    assert code != 0


def test_successful_post_returns_zero():
    """A successful POST should return 0."""
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.status = 200

    with patch("urllib.request.urlopen", return_value=mock_response):
        code = main(
            ["--url", "https://example.com/hook"],
            _stdin=_stdin('{"findings": []}'),
        )
    assert code == 0


def test_valid_json_array_is_accepted():
    """A JSON array (not object) should be accepted."""
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.status = 201

    with patch("urllib.request.urlopen", return_value=mock_response):
        code = main(
            ["--url", "https://example.com/hook"],
            _stdin=_stdin('[1, 2, 3]'),
        )
    assert code == 0


def test_url_error_returns_nonzero():
    """A network-level URLError should return 1, not raise."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        code = main(
            ["--url", "https://example.com/hook"],
            _stdin=_stdin('{"x": 1}'),
        )
    assert code == 1
