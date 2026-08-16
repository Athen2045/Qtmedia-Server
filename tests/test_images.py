from __future__ import annotations

from private_search.images import SUPPORTED_IMAGE_SUFFIXES, discover_images


def test_discover_images_is_recursive_case_insensitive_and_sorted(tmp_path):
    (tmp_path / "z.JPG").write_bytes(b"z")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "a.webp").write_bytes(b"a")
    (tmp_path / "nested" / "b.PnG").write_bytes(b"b")
    (tmp_path / "ignore.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "nested" / "skip.jpegx").write_bytes(b"skip")

    candidates = discover_images(tmp_path)

    assert [candidate.relative_path for candidate in candidates] == [
        "nested/a.webp",
        "nested/b.PnG",
        "z.JPG",
    ]
    assert [candidate.path for candidate in candidates] == [
        (tmp_path / "nested" / "a.webp").resolve(),
        (tmp_path / "nested" / "b.PnG").resolve(),
        (tmp_path / "z.JPG").resolve(),
    ]


def test_supported_image_suffixes_are_lowercase_expected_values():
    assert SUPPORTED_IMAGE_SUFFIXES == frozenset(
        {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
    )
