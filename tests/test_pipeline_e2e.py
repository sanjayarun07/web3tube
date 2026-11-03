"""End-to-end run on a tiny synthetic forum (no network): extract -> heuristic classify -> score."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def post(pid, topic, num, author, cooked, date, reply_to=None, trust=2, forum="ethresear.ch"):
    return {"source": "discourse", "forum": forum, "post_id": pid, "topic_id": topic, "topic_title": f"Topic {topic}",
            "category": "Sharding", "post_number": num, "reply_to": reply_to, "author": author, "author_trust": trust,
            "author_is_staff": False, "created_at": date, "likes": 3, "reads": 10, "cooked": cooked,
            "url": f"https://{forum}/t/x/{topic}/{num}"}

A, B, S = "AAAAAAAAAAA", "BBBBBBBBBBB", "SSSSSSSSSSS"
POSTS = [
    post(1, 10, 1, "alice", f'<p>Great talk that explains this well: <a href="https://youtu.be/{A}">talk</a></p>', "2019-03-01T00:00:00Z"),
    post(2, 10, 2, "bob", "<p>Agreed, really helpful, thanks for sharing</p>", "2019-03-02T00:00:00Z", reply_to=1),
    post(3, 11, 1, "carol", f'<div class="youtube-onebox" data-video-id="{A}"></div><p>Still the best intro, highly recommend</p>', "2022-06-01T00:00:00Z", forum="ethereum-magicians.org"),
    post(4, 12, 1, "dave", f'<p>Recording of the call: https://www.youtube.com/watch?v={B}</p>', "2023-01-01T00:00:00Z"),
    post(5, 13, 1, "eve", f'<p>use my code for a 100x airdrop https://youtu.be/{S}</p>', "2023-02-01T00:00:00Z", trust=0),
]
META = [
    {"video_id": A, "title": "Danksharding deep dive", "channel": "Ethereum Foundation", "published_at": "2019-01-01T00:00:00Z",
     "description": "Devcon research talk", "duration_s": 3000, "captions": True, "embeddable": True, "privacy": "public"},
    {"video_id": B, "title": "All Core Devs call #150", "channel": "Ethereum Foundation", "published_at": "2023-01-01T00:00:00Z",
     "description": "", "duration_s": 5400, "captions": False, "embeddable": True, "privacy": "public"},
    {"video_id": S, "title": "This token will 100x", "channel": "Moon", "published_at": "2023-01-01T00:00:00Z",
     "description": "use my code, airdrop", "duration_s": 600, "captions": False, "embeddable": True, "privacy": "public"},
]


def run(tmp: Path) -> dict:
    raw = tmp / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for f in ("ethresear.ch", "ethereum-magicians.org"):
        (raw / f"discourse_{f}.jsonl").write_text("".join(json.dumps(p) + "\n" for p in POSTS if p["forum"] == f))
    (raw / "seeds.jsonl").write_text(json.dumps({"video_id": A, "seed": "Devcon / Ethereum Foundation"}) + "\n")
    (tmp / "videos_meta.jsonl").write_text("".join(json.dumps(m) + "\n" for m in META))
    env = {**os.environ, "W3T_DATA": str(tmp), "W3T_CATALOG": str(tmp / "catalog.json")}
    for step in (["pipeline.extract"], ["pipeline.classify", "--heuristic"], ["pipeline.score"]):
        subprocess.run([sys.executable, "-m", *step], cwd=ROOT, env=env, check=True, capture_output=True)
    return json.loads((tmp / "catalog.json").read_text())


def test_e2e(tmp_path):
    cat = run(tmp_path)
    ids = [v["id"] for v in cat["videos"]]
    assert ids and ids[0] == A, "the repeatedly recommended talk ranks first"
    assert S not in ids, "the shill video is filtered out"
    top = cat["videos"][0]
    assert top["n"]["voices"] == 3 and top["n"]["communities"] == 2  # alice, bob (reply), carol
    assert top["seed"] and top["ev"][0]["url"].startswith("https://")


if __name__ == "__main__":  # write a demo catalog for eyeballing the frontend
    out = Path(sys.argv[1])
    print(json.dumps(run(out)["stats"]))
