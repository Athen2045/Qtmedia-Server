from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image as PILImage

from private_search.search import preview


class _DummyTempFile:
    def __init__(self, path: Path):
        self.path = path
        self.name = str(path)

    def __enter__(self):
        self.path.write_bytes(b"temp")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeImage:
    def __init__(self):
        self.calls = []

    def thumbnail(self, size):
        self.calls.append(("thumbnail", size))

    def convert(self, mode):
        self.calls.append(("convert", mode))
        return self

    def save(self, path, format=None, optimize=None):
        self.calls.append(("save", Path(path), format, optimize))
        Path(path).write_bytes(b"png")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_render_local_image_returns_false_when_kitty_unavailable(monkeypatch, tmp_path):
    calls = []
    (tmp_path / "sample.png").write_bytes(b"image")
    monkeypatch.setattr(preview, "is_kitty_terminal", lambda: False)
    monkeypatch.setattr(preview, "_write_kitty_png", lambda path: calls.append(path))

    assert preview.render_local_image(tmp_path / "sample.png") is False
    assert calls == []


def test_render_local_image_renders_and_deletes_temporary_png(
    monkeypatch, tmp_path
):
    temp_path = tmp_path / "preview.png"
    (tmp_path / "sample.png").write_bytes(b"image")
    fake_image = _FakeImage()
    written = []

    monkeypatch.setattr(preview, "is_kitty_terminal", lambda: True)
    monkeypatch.setattr(
        preview,
        "tempfile",
        SimpleNamespace(NamedTemporaryFile=lambda **kwargs: _DummyTempFile(temp_path)),
    )
    monkeypatch.setattr(
        preview,
        "Image",
        SimpleNamespace(open=lambda path: fake_image),
    )
    monkeypatch.setattr(
        preview,
        "ImageOps",
        SimpleNamespace(exif_transpose=lambda image: image),
    )
    monkeypatch.setattr(
        preview,
        "_write_kitty_png",
        lambda path: written.append(path),
    )

    assert preview.render_local_image(tmp_path / "sample.png") is True
    assert written == [temp_path]
    assert fake_image.calls == [
        ("thumbnail", (preview.PREVIEW_WIDTH_PIXELS, preview.PREVIEW_HEIGHT_PIXELS)),
        ("convert", "RGBA"),
        ("save", temp_path, "PNG", True),
    ]
    assert not temp_path.exists()


def test_render_local_image_returns_false_and_deletes_temporary_png_on_failure(
    monkeypatch, tmp_path
):
    temp_path = tmp_path / "preview.png"
    (tmp_path / "sample.png").write_bytes(b"image")
    created = []

    monkeypatch.setattr(preview, "is_kitty_terminal", lambda: True)
    monkeypatch.setattr(
        preview,
        "tempfile",
        SimpleNamespace(
            NamedTemporaryFile=lambda **kwargs: _DummyTempFile(temp_path)
        ),
    )
    monkeypatch.setattr(
        preview,
        "Image",
        SimpleNamespace(open=lambda path: (_ for _ in ()).throw(OSError("boom"))),
    )
    monkeypatch.setattr(
        preview,
        "ImageOps",
        SimpleNamespace(exif_transpose=lambda image: image),
    )
    monkeypatch.setattr(
        preview,
        "_write_kitty_png",
        lambda path: created.append(path),
    )

    assert preview.render_local_image(tmp_path / "sample.png") is False
    assert created == []
    assert not temp_path.exists()


def test_render_local_image_returns_false_on_decompression_bomb(
    monkeypatch, tmp_path
):
    temp_path = tmp_path / "preview.png"
    (tmp_path / "sample.png").write_bytes(b"image")

    monkeypatch.setattr(preview, "is_kitty_terminal", lambda: True)
    monkeypatch.setattr(
        preview,
        "tempfile",
        SimpleNamespace(
            NamedTemporaryFile=lambda **kwargs: _DummyTempFile(temp_path)
        ),
    )

    def raise_decompression_bomb(path):
        raise PILImage.DecompressionBombError("image too large")

    monkeypatch.setattr(
        preview,
        "Image",
        SimpleNamespace(open=raise_decompression_bomb),
    )

    assert preview.render_local_image(tmp_path / "sample.png") is False
    assert not temp_path.exists()


def test_render_local_image_returns_false_when_preview_cleanup_fails(
    monkeypatch, tmp_path
):
    temp_path = tmp_path / "preview.png"
    (tmp_path / "sample.png").write_bytes(b"image")

    monkeypatch.setattr(preview, "is_kitty_terminal", lambda: True)
    monkeypatch.setattr(
        preview,
        "tempfile",
        SimpleNamespace(
            NamedTemporaryFile=lambda **kwargs: _DummyTempFile(temp_path)
        ),
    )
    monkeypatch.setattr(
        preview,
        "Image",
        SimpleNamespace(open=lambda path: _FakeImage()),
    )
    monkeypatch.setattr(
        preview,
        "ImageOps",
        SimpleNamespace(exif_transpose=lambda image: image),
    )
    monkeypatch.setattr(preview, "_write_kitty_png", lambda path: None)

    def fail_unlink(path, *, missing_ok=False):
        raise OSError("cleanup failed")

    monkeypatch.setattr(preview.Path, "unlink", fail_unlink)

    assert preview.render_local_image(tmp_path / "sample.png") is False
