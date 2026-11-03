"""Shared helpers: polite cached HTTP, JSONL I/O, paths."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("W3T_DATA", ROOT / "data"))
RAW = DATA / "raw"
CACHE = DATA / "http_cache"
USER_AGENT = os.environ.get("W3T_USER_AGENT", "Web3TubeBot/0.1 (research crawler; low rate)")

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_call: dict[str, float] = {}


MIN_INTERVAL = float(os.environ.get("W3T_MIN_INTERVAL", "1.0"))  # seconds between requests to one host


def get_json(url: str, *, params: dict | None = None, min_interval: float = MIN_INTERVAL,
             cache: bool = True, retries: int = 5) -> Any:
    """GET a JSON URL with per-host rate limiting, on-disk cache and 429 backoff."""
    key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    path = CACHE / key[:2] / f"{key}.json"
    if cache and path.exists():
        return json.loads(path.read_text())

    host = requests.utils.urlparse(url).netloc
    for attempt in range(retries):
        wait = _last_call.get(host, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        try:
            r = _session.get(url, params=params, timeout=30)
        except requests.exceptions.ConnectionError as e:  # proxy resets, DNS blips: back off and retry
            print(f"  {type(e).__name__} from {host}, retrying")
            time.sleep(2 ** attempt * 5)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            delay = float(r.headers.get("Retry-After", 0) or 0) or (2 ** attempt * 5)
            print(f"  {r.status_code} from {host}, sleeping {delay:.0f}s")
            time.sleep(delay)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        body = r.json()
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body))
        return body
    raise RuntimeError(f"gave up on {url}")


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
