#!/usr/bin/env python3
"""Minimal, dependency-free webhook forwarder for Cognis findings.

Reads JSON findings on stdin and POSTs them to a URL (SIEM/Slack/Jira bridge).
Usage:  <tool> scan . --format json | python integrations/webhook.py --url URL
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _die(msg: str, code: int = 1) -> int:
    """Print *msg* to stderr and return *code* (never raises)."""
    print(f"webhook error: {msg}", file=sys.stderr)
    return code


def _validate_url(url: str) -> str | None:
    """Return None if *url* is acceptable, else an error string."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "could not parse URL"
    if parsed.scheme not in ("http", "https"):
        return f"URL scheme must be http or https, got {parsed.scheme!r}"
    if not parsed.netloc:
        return "URL has no host"
    return None


def _parse_header(raw: str) -> tuple[str, str] | None:
    """Split 'Key: Value' into (key, value).  Returns None if malformed."""
    k, sep, v = raw.partition(":")
    if not sep:
        return None
    key = k.strip()
    if not key:
        return None
    return key, v.strip()


def main(argv: list[str] | None = None, _stdin: io.RawIOBase | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="POST JSON findings to a webhook endpoint."
    )
    ap.add_argument("--url", required=True, help="Destination URL (http/https)")
    ap.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="Key: Value",
        help="Extra request header; may be repeated",
    )
    ap.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow posting an empty payload (default: error on empty stdin)",
    )
    args = ap.parse_args(argv)

    # Validate URL early so the user gets a clear message, not a urllib traceback.
    url_err = _validate_url(args.url)
    if url_err:
        return _die(f"invalid --url: {url_err}", code=2)

    # Validate headers before reading stdin.
    parsed_headers: list[tuple[str, str]] = []
    for raw in args.header:
        result = _parse_header(raw)
        if result is None:
            return _die(
                f"malformed --header {raw!r}; expected 'Key: Value' format", code=2
            )
        parsed_headers.append(result)

    # Read and validate payload.
    stdin_src = _stdin if _stdin is not None else sys.stdin.buffer
    try:
        raw_stdin = stdin_src.read()
    except Exception as exc:
        return _die(f"failed to read stdin: {exc}")

    is_empty = not raw_stdin.strip()
    if is_empty:
        if args.allow_empty:
            raw_stdin = b""
        else:
            return _die("stdin is empty; nothing to post (use --allow-empty to override)", code=2)

    # Validate that the payload is well-formed JSON (skip if intentionally empty).
    if not is_empty:
        try:
            json.loads(raw_stdin)
        except json.JSONDecodeError as exc:
            return _die(f"stdin is not valid JSON: {exc}", code=2)

    payload = raw_stdin

    req = urllib.request.Request(args.url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in parsed_headers:
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"posted {len(payload)} bytes -> {r.status}")
        return 0
    except urllib.error.HTTPError as exc:
        return _die(f"HTTP {exc.code} from server: {exc.reason}")
    except urllib.error.URLError as exc:
        return _die(f"network error: {exc.reason}")
    except TimeoutError:
        return _die("request timed out")
    except OSError as exc:
        return _die(f"connection error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
