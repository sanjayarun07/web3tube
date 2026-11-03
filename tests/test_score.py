from collections import Counter

from pipeline.score import collapse_bursts, score_video, _dt

VID = "dQw4w9WgXcQ"
META = {"title": "Deep dive into danksharding", "description": "Devcon talk", "captions": True}
JUDGE = {"topics": ["Data availability"], "technical_depth": 0.9, "audience": "researchers",
         "shill_risk": 0.0, "still_current": "current", "summary": "x"}


def mention(i, author, forum="ethresear.ch", date="2022-01-01", trust=3):
    return {"id": f"m{i}", "video_id": VID, "kind": "post", "source": "discourse", "forum": forum,
            "author": author, "author_trust": trust, "author_is_staff": False, "created_at": date + "T00:00:00Z",
            "likes": 5, "url": "u", "topic_title": "t", "text": "great talk"}


def lab(ms, label="recommendation", **kw):
    return {"video": JUDGE, "mentions": [{"id": m["id"], "label": label, "strength": 0.9,
                                          "self_promotion": False, "evidence": "great", **kw} for m in ms]}


def test_more_independent_voices_rank_higher():
    one = [mention(1, "a")]
    many = [mention(i, f"a{i}", date=f"20{18 + i}-01-01", forum=f) for i, f in
            enumerate(["ethresear.ch", "ethereum-magicians.org", "news.ycombinator.com", "github.com"])]
    s1 = score_video(VID, one, lab(one), META, None, Counter())
    s2 = score_video(VID, many, lab(many), META, None, Counter())
    assert s2["score"] > s1["score"]
    assert s2["n"]["communities"] == 4 and s2["sig"]["longevity"] == 1.0


def test_same_author_counts_once():
    ms = [mention(i, "a") for i in range(5)]
    s = score_video(VID, ms, lab(ms), META, None, Counter())
    assert s["n"]["voices"] == 1


def test_criticism_and_promotion_lower_score():
    ms = [mention(1, "a"), mention(2, "b")]
    good = score_video(VID, ms, lab(ms), META, None, Counter())
    l = lab(ms)
    l["mentions"][1]["label"] = "criticism"
    crit = score_video(VID, ms, l, META, None, Counter())
    l2 = lab(ms)
    l2["mentions"][1]["label"] = "promotion"
    promo = score_video(VID, ms, l2, META, None, Counter())
    assert crit["score"] < good["score"] and promo["score"] < good["score"]
    assert "promoted" in promo["flags"]


def test_shill_markers_penalised():
    ms = [mention(1, "a")]
    clean = score_video(VID, ms, lab(ms), META, None, Counter())
    shill = score_video(VID, ms, lab(ms), {**META, "description": "Use my code for 100x airdrop"}, None, Counter())
    assert shill["score"] < clean["score"] and "sponsor_markers" in shill["flags"]


def test_burst_of_new_accounts_collapses():
    rows = [{**mention(i, f"new{i}", trust=0, date="2023-05-0" + str(i + 1)), "_dt": _dt(f"2023-05-0{i + 1}T00:00:00Z")}
            for i in range(4)]
    kept, dropped = collapse_bursts(rows)
    assert len(kept) == 1 and dropped == 3


def test_relevance_filter():
    from pipeline.score import is_relevant
    lab = lambda summary: {"video": {"summary": summary}}
    keep = [
        {"title": "Danksharding deep dive", "description": "Devcon research talk"},
        {"title": "EIP-1559 explained"},
        {"title": "Intro to zkEVMs"},
        {"title": "Lecture 3", "channel": "Ethereum Foundation"},
    ]
    drop = [
        {"title": "I Made a 32-bit Computer Inside Terraria", "description": "define the ethernet layer"},
        {"title": "Carl Sagan's Cosmos, episode 1"},
        {"title": "Let's build GPT from scratch", "description": "tokens and attention"},
        {"title": "Oracle database tuning", "description": "consensus among DBAs, layer 2 switches"},
    ]
    assert all(is_relevant(m, lab("")) for m in keep)
    assert not any(is_relevant(m, lab("")) for m in drop)
    assert is_relevant({"title": "Episode 12"}, lab("A talk on Bitcoin's Lightning Network."))


def test_clean_topics():
    from pipeline.score import clean_topics
    # A chain tag the video never names is removed, and the named chain is added.
    assert clean_topics(["Smart contracts", "Solana"], "Cardano testnet: set up a stake pool", set()) == \
        ["Smart contracts", "Cardano"]
    # "Ethereum protocol" survives only with an Ethereum signal (text or forum).
    assert clean_topics(["Consensus", "Ethereum protocol"], "Ouroboros proof of stake", set()) == \
        ["Consensus", "Cardano"]
    assert "Ethereum protocol" in clean_topics(["Ethereum protocol"], "Fee market change", {"ethresear.ch"})
    # Invented or differently-cased topics map onto the list or are dropped.
    assert clean_topics(["Smart Contracts", "Wallets", "Made up topic"], "Solidity patterns", set()) == \
        ["Smart contracts", "Security & exploits"]


def test_names_do_not_pluralise():
    from pipeline.score import is_relevant
    lab = {"video": {"summary": "Documentary on Argentina's 2001 bank crisis"}}
    assert not is_relevant({"title": "Memoria del Saqueo - De Pino Solanas"}, lab)
    assert is_relevant({"title": "Solana validator internals"}, lab)
