from qtmedia.sources.pmvhaven import extract_video_id, is_pmvhaven_url

VIDEO_URL = "https://pmvhaven.com/video/0123456789abcdef01234567/example"
SLUGGED_VIDEO_URL = "https://pmvhaven.com/video/stamina-training-unit_6a3be99413e186bd6f619c2e?from=popular"


def test_pmvhaven_url_and_id_detection():
    assert is_pmvhaven_url(VIDEO_URL)
    assert extract_video_id(VIDEO_URL) == "0123456789abcdef01234567"
    assert not is_pmvhaven_url("https://pmvhaven.com/")


def test_pmvhaven_slugged_url_detection():
    assert is_pmvhaven_url(SLUGGED_VIDEO_URL)
    assert extract_video_id(SLUGGED_VIDEO_URL) == "6a3be99413e186bd6f619c2e"

