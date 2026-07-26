from private_search.downloader import is_direct_video_url


def test_direct_url_validation():
    assert is_direct_video_url("https://www.xvideos.com/video.abc/title")
    assert not is_direct_video_url("https://www.xvideos.com/")
    assert not is_direct_video_url("https://www.xvideos.com/video...")
