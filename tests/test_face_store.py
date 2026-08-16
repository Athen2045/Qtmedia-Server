from __future__ import annotations

import math
import sqlite3
import struct
from pathlib import Path

import pytest

from private_search.osint.face_store import (
    FaceIndex,
    FaceRecord,
    ImageRecord,
)


def make_image(
    tmp_path: Path,
    name: str,
    *,
    content_hash: str,
    file_size: int = 1,
    modified_at_ns: int = 1,
    width: int = 640,
    height: int = 480,
) -> ImageRecord:
    path = (tmp_path / name).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")
    return ImageRecord(
        path=path,
        content_hash=content_hash,
        file_size=file_size,
        modified_at_ns=modified_at_ns,
        width=width,
        height=height,
    )


def make_face(
    face_id: str,
    face_number: int,
    embedding: tuple[float, ...],
    *,
    bbox: tuple[float, float, float, float] = (1.0, 2.0, 11.0, 12.0),
    landmarks: tuple[float, ...] = (1.0, 1.0, 3.0, 1.0, 2.0, 2.0, 1.0, 3.0, 3.0, 3.0),
    detection_score: float = 0.98,
    crop_path: Path | None = None,
) -> FaceRecord:
    return FaceRecord(
        face_id=face_id,
        face_number=face_number,
        bbox=bbox,
        landmarks=landmarks,
        embedding=embedding,
        detection_score=detection_score,
        crop_path=crop_path,
    )


def explain_details(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]):
    rows = connection.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return [str(row[3]).upper() for row in rows]


def unpack_embedding(blob: bytes) -> tuple[float, ...]:
    count = len(blob) // 4
    return struct.unpack(f"<{count}f", blob)


def sorted_images(*images: ImageRecord) -> tuple[ImageRecord, ...]:
    return tuple(
        sorted(
            images,
            key=lambda item: (item.path.as_posix().casefold(), item.path.as_posix()),
        )
    )


def test_face_index_initializes_pragmas_schema_and_indexes(tmp_path: Path):
    image = make_image(tmp_path, "Álice one.jpg", content_hash="hash-a")
    database_path = tmp_path / "face-index.sqlite"

    with FaceIndex(database_path) as index:
        report = index.refresh_images([image], model_version="insightface-1")
        index.upsert_faces(image, [make_face("alice-1", 1, (1.0, 0.0, 0.0))])

        assert report.pending_images == (image,)
        assert report.reused_images == ()
        assert report.deleted_paths == ()

        assert index._connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert index._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert index._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000

        indexes = {
            row[0]
            for row in index._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert {"idx_images_path", "idx_images_content_hash", "idx_faces_image_id"} <= indexes

        image_id = index._connection.execute(
            "SELECT id FROM images WHERE path = ?",
            (image.path.as_posix(),),
        ).fetchone()[0]
        image_plan = explain_details(
            index._connection,
            "SELECT id FROM images WHERE path = ?",
            (image.path.as_posix(),),
        )
        face_plan = explain_details(
            index._connection,
            "SELECT face_id FROM faces WHERE image_id = ?",
            (image_id,),
        )
        hash_plan = explain_details(
            index._connection,
            "SELECT id FROM images WHERE content_hash = ?",
            (image.content_hash,),
        )

    assert any("IDX_IMAGES_PATH" in detail for detail in image_plan)
    assert any("IDX_IMAGES_CONTENT_HASH" in detail for detail in hash_plan)
    assert any("IDX_FACES_IMAGE_ID" in detail for detail in face_plan)


def test_refresh_images_tracks_reused_changed_new_and_deleted_images(tmp_path: Path):
    alpha = make_image(
        tmp_path,
        "Álice one.jpg",
        content_hash="hash-alpha-v1",
        file_size=10,
        modified_at_ns=10,
    )
    bravo = make_image(
        tmp_path,
        "bravo.jpg",
        content_hash="hash-bravo-v1",
        file_size=20,
        modified_at_ns=20,
    )
    alpha_changed = make_image(
        tmp_path,
        "Álice one.jpg",
        content_hash="hash-alpha-v2",
        file_size=11,
        modified_at_ns=11,
    )
    charlie = make_image(
        tmp_path,
        "charlie.jpg",
        content_hash="hash-charlie-v1",
        file_size=30,
        modified_at_ns=30,
    )

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        first = index.refresh_images([alpha, bravo], model_version="insightface-1")
        assert first.pending_images == sorted_images(alpha, bravo)
        assert first.reused_images == ()
        assert first.deleted_paths == ()

        index.upsert_faces(alpha, [make_face("alpha-face", 1, (1.0, 0.0))])
        index.upsert_faces(bravo, [make_face("bravo-face", 1, (0.0, 1.0))])

        second = index.refresh_images([alpha, bravo], model_version="insightface-1")
        assert second.pending_images == ()
        assert second.reused_images == sorted_images(alpha, bravo)
        assert second.deleted_paths == ()

        third = index.refresh_images(
            [alpha_changed, charlie],
            model_version="insightface-1",
        )
        assert third.pending_images == sorted_images(alpha_changed, charlie)
        assert third.reused_images == ()
        assert third.deleted_paths == (bravo.path,)

        assert index.search((0.0, 1.0), limit=5) == []


def test_refresh_images_rebuilds_rows_when_model_version_changes(tmp_path: Path):
    image = make_image(tmp_path, "model.jpg", content_hash="hash-model")

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        first = index.refresh_images([image], model_version="insightface-1")
        index.upsert_faces(image, [make_face("model-face", 1, (1.0, 0.0, 0.0))])
        second = index.refresh_images([image], model_version="insightface-1")
        third = index.refresh_images([image], model_version="insightface-2")

        assert first.pending_images == (image,)
        assert second.pending_images == ()
        assert second.reused_images == (image,)
        assert third.pending_images == (image,)
        assert third.reused_images == ()
        assert index.search((1.0, 0.0, 0.0), limit=5) == []


def test_upsert_faces_replaces_rows_and_stores_normalized_float32_embeddings(tmp_path: Path):
    image = make_image(tmp_path, "replace.jpg", content_hash="hash-replace")
    database_path = tmp_path / "face-index.sqlite"

    with FaceIndex(database_path) as index:
        index.refresh_images([image], model_version="insightface-1")
        index.upsert_faces(
            image,
            [
                make_face("replace-1", 1, (3.0, 4.0)),
                make_face("replace-2", 2, (5.0, 12.0)),
            ],
        )
        index.upsert_faces(
            image,
            [
                make_face("replace-3", 3, (8.0, 6.0)),
            ],
        )

        rows = index._connection.execute(
            """
            SELECT face_id, embedding_blob
            FROM faces
            ORDER BY face_id
            """
        ).fetchall()

    assert [row[0] for row in rows] == ["replace-3"]
    embedding = unpack_embedding(rows[0][1])
    assert len(embedding) == 2
    assert embedding == pytest.approx((0.8, 0.6), abs=1e-6)
    assert math.isclose(sum(value * value for value in embedding), 1.0, rel_tol=1e-6)


def test_face_index_rejects_directory_database_path(tmp_path: Path):
    database_path = tmp_path / "face-index.sqlite"
    database_path.mkdir()

    with pytest.raises(ValueError, match="path"):
        FaceIndex(database_path)


def test_refresh_images_rejects_directory_image_paths(tmp_path: Path):
    image_dir = tmp_path / "nested-image-dir"
    image_dir.mkdir()
    image = ImageRecord(
        path=image_dir,
        content_hash="hash-dir",
        file_size=1,
        modified_at_ns=1,
        width=640,
        height=480,
    )

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        with pytest.raises(ValueError, match="image.path"):
            index.refresh_images([image], model_version="insightface-1")

        assert index._connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0


def test_upsert_faces_preserves_refresh_owned_image_metadata(tmp_path: Path):
    image = make_image(
        tmp_path,
        "metadata-owner.jpg",
        content_hash="hash-refresh",
        file_size=10,
        modified_at_ns=100,
        width=320,
        height=240,
    )
    stale_image = ImageRecord(
        path=image.path,
        content_hash="hash-stale",
        file_size=999,
        modified_at_ns=999,
        width=999,
        height=999,
    )

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        index.refresh_images([image], model_version="insightface-1")
        index.upsert_faces(stale_image, [make_face("metadata-face", 1, (1.0, 0.0))])

        stored = index._connection.execute(
            """
            SELECT content_hash, file_size, modified_at_ns, width, height, face_count, indexed_at
            FROM images
            WHERE path = ?
            """,
            (image.path.as_posix(),),
        ).fetchone()

    assert stored is not None
    assert stored["content_hash"] == image.content_hash
    assert stored["file_size"] == image.file_size
    assert stored["modified_at_ns"] == image.modified_at_ns
    assert stored["width"] == image.width
    assert stored["height"] == image.height
    assert stored["face_count"] == 1
    assert stored["indexed_at"] is not None


def test_search_returns_deterministic_cosine_matches_and_empty_index(tmp_path: Path):
    alpha = make_image(tmp_path, "alpha.jpg", content_hash="hash-a")
    bravo = make_image(tmp_path, "bravo.jpg", content_hash="hash-b")
    charlie = make_image(tmp_path, "charlie.jpg", content_hash="hash-c")

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        assert index.search((1.0, 0.0), limit=5) == []

        index.refresh_images([alpha, bravo, charlie], model_version="insightface-1")
        index.upsert_faces(alpha, [make_face("face-b", 1, (1.0, 0.0))])
        index.upsert_faces(bravo, [make_face("face-a", 1, (1.0, 0.0))])
        index.upsert_faces(charlie, [make_face("face-c", 1, (0.6, 0.8))])

        matches = index.search((10.0, 0.0), limit=5)

    assert [match.face_id for match in matches] == ["face-b", "face-a", "face-c"]
    assert [match.image_path for match in matches[:2]] == [alpha.path, bravo.path]
    assert matches[0].score == pytest.approx(1.0, abs=1e-6)
    assert matches[1].score == pytest.approx(1.0, abs=1e-6)
    assert matches[2].score == pytest.approx(0.6, abs=1e-6)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda tmp_path: FaceIndex(tmp_path / "face-index.sqlite").refresh_images(
                [make_image(tmp_path, "dup.jpg", content_hash="a"), make_image(tmp_path, "dup.jpg", content_hash="b")],
                model_version="insightface-1",
            ),
            "duplicate image path",
        ),
        (
            lambda tmp_path: FaceIndex(tmp_path / "face-index.sqlite").refresh_images(
                [make_image(tmp_path, "blank-model.jpg", content_hash="hash")],
                model_version="",
            ),
            "model_version",
        ),
        (
            lambda tmp_path: FaceIndex(tmp_path / "face-index.sqlite").refresh_images(
                [
                    ImageRecord(
                        path="not-a-path",  # type: ignore[arg-type]
                        content_hash="hash",
                        file_size=1,
                        modified_at_ns=1,
                        width=1,
                        height=1,
                    )
                ],
                model_version="insightface-1",
            ),
            "image.path",
        ),
        (
            lambda tmp_path: FaceIndex(tmp_path / "face-index.sqlite").search((1.0, 0.0), limit=0),
            "limit",
        ),
        (
            lambda tmp_path: FaceIndex(tmp_path / "face-index.sqlite").search((0.0, 0.0), limit=1),
            "embedding",
        ),
    ],
)
def test_face_index_validates_inputs(tmp_path: Path, factory, message: str):
    with pytest.raises(ValueError, match=message):
        factory(tmp_path)


def test_upsert_faces_validates_embeddings_and_requires_refreshed_image(tmp_path: Path):
    image = make_image(tmp_path, "validate.jpg", content_hash="hash-validate")

    with FaceIndex(tmp_path / "face-index.sqlite") as index:
        with pytest.raises(ValueError, match="refresh_images"):
            index.upsert_faces(image, [make_face("missing-image", 1, (1.0, 0.0))])

        index.refresh_images([image], model_version="insightface-1")
        with pytest.raises(ValueError, match="embedding"):
            index.upsert_faces(image, [make_face("zero-face", 1, (0.0, 0.0))])


def test_face_index_context_manager_closes_connection(tmp_path: Path):
    index = FaceIndex(tmp_path / "face-index.sqlite")
    connection = index._connection

    with index as managed:
        assert managed is index
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
