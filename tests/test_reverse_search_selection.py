from __future__ import annotations

from private_search.ai.actions import is_reverse_image_request


def test_reverse_search_keyword_detection_is_casefolded():
    assert is_reverse_image_request("Can you REVERSE SEARCH this image?") is True


def test_reverse_search_keyword_detection_rejects_partial_match():
    assert is_reverse_image_request("Please reverse the image later.") is False
