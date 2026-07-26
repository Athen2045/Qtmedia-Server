from private_search.search import (
    ADAPTERS,
    SearchCandidate,
    VideoResult,
    deduplicate,
    filter_rejection_reason,
)


def test_configured_adapters_have_expected_url_shapes():
    adapters = {adapter.name: adapter for adapter in ADAPTERS}
    assert adapters["TNAFlix"].make_search_urls("test title")[0].endswith(
        "/search/test+title"
    )
    assert adapters["YouJizz"].make_search_urls("test title")[0].endswith(
        "/tags/test-title-1.html"
    )
    assert adapters["YouPorn"].make_search_urls("test title")[0].endswith(
        "/porntags/test-title/"
    )


def test_deduplicate_keeps_highest_quality_result():
    low = VideoResult("Same Title", "https://one.test/1", "One", None, 720, 1000)
    high = VideoResult("same-title", "https://two.test/2", "Two", None, 1080, 800)
    assert deduplicate([low, high]) == [high]


def test_filter_reason_is_specific():
    result = VideoResult("Bimbo title", "https://example.test/video/1", "Test", 5, 720, 0)
    assert filter_rejection_reason(result, ["missing"], [], 0) == "include filter"
    assert filter_rejection_reason(result, [], ["bimbo"], 0) == "exclusion"
    assert filter_rejection_reason(result, [], [], 10) == "minimum views"
