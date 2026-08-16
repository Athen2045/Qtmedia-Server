from __future__ import annotations

from pathlib import Path

from private_search.osint.insightface import InsightFaceAdapter, InsightFaceSettings


class FakeSmartImage:
    def __init__(self, responses: dict[Path, list[dict[str, object]]]) -> None:
        self.responses = responses
        self.calls: list[Path] = []

    def search_image(self, path: Path) -> list[dict[str, object]]:
        resolved = path.resolve()
        self.calls.append(resolved)
        return [dict(item) for item in self.responses[resolved]]


def test_face_assisted_search_merges_filters_deduplicates_and_cleans_crops(
    monkeypatch, tmp_path: Path
):
    image = tmp_path / "query.jpg"
    crop_one = tmp_path / "face-1.jpg"
    crop_two = tmp_path / "face-2.jpg"
    for path in (image, crop_one, crop_two):
        path.write_bytes(b"image")

    adapter = InsightFaceAdapter(
        InsightFaceSettings(
            root=tmp_path / "insightface",
            python=tmp_path / "python.exe",
            image_root=tmp_path,
            index_path=tmp_path / "face-index.sqlite",
            crop_root=tmp_path,
            keep_crops=False,
        )
    )
    monkeypatch.setattr(
        adapter,
        "_analyze_image",
        lambda image_path, *, operation="reverse": {
            "provider": "CPUExecutionProvider",
            "model_version": "9.9.9:buffalo_l",
            "faces": [
                {"face_number": 1, "crop_path": str(crop_one), "detection_score": 0.91},
                {"face_number": 2, "crop_path": str(crop_two), "detection_score": 0.88},
            ],
            "local_matches": [
                {
                    "face_number": 1,
                    "image_path": str((tmp_path / "library-a.jpg").resolve()),
                    "face_id": "match-a",
                    "match_face_number": 1,
                    "score": 0.92,
                },
                {
                    "face_number": 2,
                    "image_path": str((tmp_path / "library-b.jpg").resolve()),
                    "face_id": "match-b",
                    "match_face_number": 3,
                    "score": 0.72,
                },
            ],
            "crops": [str(crop_one), str(crop_two)],
        },
    )
    smartimage = FakeSmartImage(
        {
            image.resolve(): [
                {
                    "name": "Original hit",
                    "url": "https://example.test/original",
                    "similarity": "0.83",
                    "site": "Google",
                },
                {
                    "name": "Too low",
                    "url": "https://example.test/low",
                    "similarity": "0.20",
                    "site": "Google",
                },
            ],
            crop_one.resolve(): [
                {
                    "name": "Duplicate URL",
                    "url": "https://example.test/original",
                    "similarity": "99",
                    "site": "Yandex",
                },
                {
                    "name": "Face hit",
                    "url": "https://example.test/face-1",
                    "similarity": "88",
                    "site": "Yandex",
                },
            ],
            crop_two.resolve(): [
                {
                    "name": "Face hit 2",
                    "url": "https://example.test/face-2",
                    "similarity": "74",
                    "site": "Bing",
                }
            ],
        }
    )

    results = adapter.analyze_and_search(image, smartimage=smartimage)

    assert smartimage.calls == [image.resolve(), crop_one.resolve(), crop_two.resolve()]
    assert [result["kind"] for result in results] == ["local_face", "web_reverse", "web_reverse"]
    assert results[0] == {
        "kind": "local_face",
        "provider": "CPUExecutionProvider",
        "model_version": "9.9.9:buffalo_l",
        "face_number": 1,
        "image_path": str((tmp_path / "library-a.jpg").resolve()),
        "face_id": "match-a",
        "match_face_number": 1,
        "confidence": 92.0,
    }
    assert "crop_path" not in results[0]
    assert results[1]["url"] == "https://example.test/original"
    assert results[1]["provenance"] == "original"
    assert results[1]["confidence"] == 83.0
    assert results[2]["url"] == "https://example.test/face-1"
    assert results[2]["provenance"] == "face_crop"
    assert results[2]["face_number"] == 1
    assert not crop_one.exists()
    assert not crop_two.exists()
