from private_search.lustpress import _records


def test_lustpress_records_accepts_normalized_payload_shapes():
    assert _records({"data": [{"title": "A"}, {"title": "B"}]}) == [
        {"title": "A"},
        {"title": "B"},
    ]
    assert _records({"data": {"videos": [{"title": "A"}]}}) == [{"title": "A"}]
