from pipeline.extract import parse_post, timestamp_from_url, video_id_from_url

ID = "dQw4w9WgXcQ"


def test_url_forms():
    for u in [f"https://www.youtube.com/watch?v={ID}", f"https://youtu.be/{ID}?t=42",
              f"https://m.youtube.com/watch?feature=share&v={ID}", f"https://www.youtube.com/embed/{ID}",
              f"https://www.youtube-nocookie.com/embed/{ID}?start=3", f"https://youtube.com/shorts/{ID}",
              f"https://www.youtube.com/live/{ID}", f"youtube.com/watch?v={ID}"]:
        assert video_id_from_url(u) == ID, u
    assert video_id_from_url("https://www.youtube.com/playlist?list=PL123") is None
    assert video_id_from_url("https://www.youtube.com/@EthereumFoundation") is None
    assert video_id_from_url("https://example.com/watch?v=" + ID) is None


def test_timestamps():
    assert timestamp_from_url(f"https://youtu.be/{ID}?t=1h2m3s") == 3723
    assert timestamp_from_url(f"https://youtu.be/{ID}?t=90") == 90
    assert timestamp_from_url(f"https://youtu.be/{ID}") is None


def test_onebox_quote_and_bare_link():
    other = "abcdefghijk"
    cooked = f"""
    <aside class="quote"><blockquote><p>see <a href="https://youtu.be/{other}">this</a></p></blockquote></aside>
    <p>Great talk explaining the fork choice rule:</p>
    <div class="youtube-onebox lazy-video-container" data-video-id="{ID}" data-provider-name="youtube"></div>
    <p>also https://youtu.be/zzzzzzzzzzz?t=30 is relevant</p>"""
    text, vids = parse_post(cooked)
    assert ID in vids and "zzzzzzzzzzz" in vids
    assert other not in vids, "links inside quotes belong to the quoted author"
    assert vids["zzzzzzzzzzz"] == 30
    assert "Great talk" in text and "[VIDEO]" in text
