from qtmedia_bot.bot.sources.adapters import adapter_for_url, inspection_candidates


def test_eporner_adapter_offers_embed_variant_for_same_video():
    adapter = adapter_for_url(
        "https://www.eporner.com/video-AbC123/example-title?tracking=ignored"
    )

    assert adapter is not None
    assert adapter.name == "eporner"
    assert adapter.inspection_urls(
        "https://www.eporner.com/video-AbC123/example-title?tracking=ignored"
    ) == (
        "https://www.eporner.com/video-AbC123/example-title?tracking=ignored",
        "https://www.eporner.com/embed/AbC123",
    )
    assert adapter.owns_transfer_url(
        "https://www.eporner.com/video-AbC123/example-title",
        "https://www.eporner.com/embed/AbC123",
    )
    assert not adapter.owns_transfer_url(
        "https://www.eporner.com/video-AbC123/example-title",
        "https://www.eporner.com/embed-Other/example-title",
    )


def test_noodle_adapter_offers_public_and_adult_hosts_for_same_video():
    adapter = adapter_for_url("https://noodlemagazine.com/watch/-123_456")

    assert adapter is not None
    assert adapter.name == "noodlemagazine"
    assert adapter.impersonate == "chrome131"
    assert adapter.inspection_urls("https://noodlemagazine.com/watch/-123_456") == (
        "https://noodlemagazine.com/watch/-123_456",
        "https://adult.noodlemagazine.com/watch/-123_456",
        "https://www.noodlemagazine.com/watch/-123_456",
    )
    assert adapter.owns_transfer_url(
        "https://noodlemagazine.com/watch/-123_456",
        "https://adult.noodlemagazine.com/watch/-123_456",
    )


def test_unknown_provider_has_no_alternate_candidates():
    assert adapter_for_url("https://example.com/video") is None
    assert tuple(
        inspection_candidates("https://example.com/video", "https://example.com/video")
    ) == (
        ("https://example.com/video", False),
        ("https://example.com/video", True),
    )

