from private_search.downloader import is_direct_video_url


def test_direct_url_validation():
    assert is_direct_video_url("https://www.xvideos.com/video.abc/title")
    assert not is_direct_video_url("https://www.xvideos.com/")
    assert not is_direct_video_url("https://www.xvideos.com/video...")


def test_direct_url_validation_shares_xhamster_creator_exclusion_with_search():
    """downloader.py must reuse search.py's SiteAdapter rules, not a stale copy."""
    assert is_direct_video_url("https://xhamster.com/videos/example-title")
    assert not is_direct_video_url("https://xhamster.com/creators/videos/example")


def test_direct_url_validation_spankbang():
    assert is_direct_video_url("https://spankbang.com/abcd/video/title")
    assert not is_direct_video_url("https://spankbang.com/")


def test_direct_url_validation_unknown_host_is_permissive():
    assert is_direct_video_url("https://example.test/some/video/path")
