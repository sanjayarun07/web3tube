"""Exercise the Claude code path against a fake HTTP transport (no network, no key)."""
import json

import anthropic
import httpx2 as httpx

from pipeline import classify

RESULT = {"video": {"topics": ["Data availability"], "technical_depth": 0.9, "audience": "researchers",
                    "shill_risk": 0.0, "still_current": "current", "summary": "Explains danksharding."},
          "mentions": [{"mention_index": 0, "label": "recommendation", "strength": 0.9,
                        "self_promotion": False, "evidence": "Great talk"}]}


def test_llm_path(monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(RESULT)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10}})

    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(classify, "_client", client)
    m = {"kind": "post", "forum": "ethresear.ch", "topic_title": "t", "category": "", "author": "a",
         "created_at": "2020-01-01", "text": "Great talk [VIDEO]"}
    out = classify.classify_llm("AAAAAAAAAAA", {"title": "x"}, None, [m])
    assert out["mentions"][0]["label"] == "recommendation"
    assert seen["output_config"]["effort"] == "low" and seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["model"] == classify.MODEL
