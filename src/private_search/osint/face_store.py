"""Persistent SQLite face-index storage for local InsightFace matching."""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _normalize_path(path: Path, *, field: str) -> Path:
    if not isinstance(path, Path):
        raise ValueError(f"{field} must be a Path")  # noqa: TRY004
    try:
        resolved = path.expanduser().resolve()
    except OSError as error:  # pragma: no cover - Path.resolve is reliable in tests
        raise ValueError(f"{field} could not be resolved") from error
    if not resolved.name:
        raise ValueError(f"{field} must point to a file path")
    return resolved


def _normalize_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _normalize_embedding(values: Sequence[float], *, field: str) -> tuple[float, ...]:
    if isinstance(values, (bytes, bytearray, memoryview, str)):
        raise ValueError(f"{field} must be a numeric sequence")  # noqa: TRY004
    normalized: list[float] = []
    for raw in values:
        if isinstance(raw, bool):
            raise ValueError(f"{field} must contain only finite numbers")  # noqa: TRY004
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{field} must contain only finite numbers")
        normalized.append(value)
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    norm = math.sqrt(sum(value * value for value in normalized))
    if norm <= 0.0:
        raise ValueError(f"{field} must have a positive norm")
    return tuple(_float32(value / norm) for value in normalized)


def _pack_embedding(values: Sequence[float]) -> tuple[bytes, int]:
    normalized = _normalize_embedding(values, field="embedding")
    return struct.pack(f"<{len(normalized)}f", *normalized), len(normalized)


def _unpack_embedding(blob: bytes) -> tuple[float, ...]:
    if len(blob) % 4 != 0:
        raise ValueError("embedding blob length must be a multiple of 4")
    count = len(blob) // 4
    return struct.unpack(f"<{count}f", blob)


def _normalize_bbox(values: Sequence[float]) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise ValueError("bbox must contain exactly 4 values")
    bbox = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in bbox):
        raise ValueError("bbox must contain only finite numbers")
    return bbox  # type: ignore[return-value]


def _normalize_landmarks(values: Sequence[float]) -> tuple[float, ...]:
    if isinstance(values, (bytes, bytearray, memoryview, str)):
        raise ValueError("landmarks must be a numeric sequence")  # noqa: TRY004
    landmarks = tuple(float(value) for value in values)
    if len(landmarks) % 2 != 0 or not landmarks:
        raise ValueError("landmarks must contain an even number of coordinates")
    if not all(math.isfinite(value) for value in landmarks):
        raise ValueError("landmarks must contain only finite numbers")
    return landmarks


@dataclass(frozen=True)
class ImageRecord:
    path: Path
    content_hash: str
    file_size: int
    modified_at_ns: int
    width: int
    height: int


@dataclass(frozen=True)
class FaceRecord:
    face_id: str
    face_number: int
    bbox: tuple[float, float, float, float]
    landmarks: tuple[float, ...]
    embedding: Sequence[float]
    detection_score: float
    crop_path: Path | None = None


@dataclass(frozen=True)
class FaceMatch:
    image_path: Path
    face_id: str
    face_number: int
    score: float
    bbox: tuple[float, float, float, float]
    crop_path: Path | None = None


@dataclass(frozen=True)
class RefreshReport:
    pending_images: tuple[ImageRecord, ...]
    reused_images: tuple[ImageRecord, ...]
    deleted_paths: tuple[Path, ...]


class FaceIndex:
    """Own the SQLite face index and deterministic cosine search."""

    def __init__(self, path: Path) -> None:
        self.path = _normalize_path(path, field="path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path), timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._create_schema()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def refresh_images(
        self,
        images: Sequence[ImageRecord],
        *,
        model_version: str,
    ) -> RefreshReport:
        normalized_version = _normalize_text(model_version, field="model_version")
        normalized_images = tuple(self._normalize_image(image) for image in images)
        seen_paths: set[str] = set()
        for image in normalized_images:
            path_text = image.path.as_posix()
            if path_text in seen_paths:
                raise ValueError(f"duplicate image path: {image.path}")
            seen_paths.add(path_text)
        ordered_images = tuple(
            sorted(
                normalized_images,
                key=lambda item: (item.path.as_posix().casefold(), item.path.as_posix()),
            )
        )

        with self._connection:
            existing_rows = {
                str(row["path"]): row
                for row in self._connection.execute(
                    """
                    SELECT id, path, content_hash, file_size, modified_at_ns, width, height,
                           model_version, indexed_at
                    FROM images
                    """
                ).fetchall()
            }
            incoming_paths = {image.path.as_posix() for image in ordered_images}
            deleted_paths = tuple(
                Path(path)
                for path in sorted(
                    set(existing_rows) - incoming_paths,
                    key=lambda item: (item.casefold(), item),
                )
            )
            if deleted_paths:
                self._connection.executemany(
                    "DELETE FROM images WHERE path = ?",
                    [(path.as_posix(),) for path in deleted_paths],
                )

            reused: list[ImageRecord] = []
            pending: list[ImageRecord] = []
            inserts: list[tuple[object, ...]] = []
            updates: list[tuple[object, ...]] = []
            clear_face_ids: list[tuple[int]] = []
            for image in ordered_images:
                path_text = image.path.as_posix()
                existing = existing_rows.get(path_text)
                if (
                    existing is not None
                    and str(existing["content_hash"]) == image.content_hash
                    and str(existing["model_version"]) == normalized_version
                    and existing["indexed_at"] is not None
                ):
                    reused.append(image)
                    if (
                        int(existing["file_size"]) != image.file_size
                        or int(existing["modified_at_ns"]) != image.modified_at_ns
                        or int(existing["width"]) != image.width
                        or int(existing["height"]) != image.height
                    ):
                        updates.append(
                            (
                                image.content_hash,
                                image.file_size,
                                image.modified_at_ns,
                                image.width,
                                image.height,
                                normalized_version,
                                existing["indexed_at"],
                                existing["id"],
                            )
                        )
                    continue

                pending.append(image)
                if existing is None:
                    inserts.append(
                        (
                            path_text,
                            image.content_hash,
                            image.file_size,
                            image.modified_at_ns,
                            image.width,
                            image.height,
                            normalized_version,
                        )
                    )
                else:
                    clear_face_ids.append((int(existing["id"]),))
                    updates.append(
                        (
                            image.content_hash,
                            image.file_size,
                            image.modified_at_ns,
                            image.width,
                            image.height,
                            normalized_version,
                            None,
                            existing["id"],
                        )
                    )

            if clear_face_ids:
                self._connection.executemany(
                    "DELETE FROM faces WHERE image_id = ?",
                    clear_face_ids,
                )
            if inserts:
                self._connection.executemany(
                    """
                    INSERT INTO images(
                        path, content_hash, file_size, modified_at_ns, width, height,
                        model_version, indexed_at, face_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)
                    """,
                    inserts,
                )
            if updates:
                self._connection.executemany(
                    """
                    UPDATE images
                    SET content_hash = ?, file_size = ?, modified_at_ns = ?,
                        width = ?, height = ?, model_version = ?, indexed_at = ?,
                        face_count = CASE WHEN ? IS NULL THEN 0 ELSE face_count END
                    WHERE id = ?
                    """,
                    [
                        (
                            content_hash,
                            file_size,
                            modified_at_ns,
                            width,
                            height,
                            version,
                            indexed_at,
                            indexed_at,
                            row_id,
                        )
                        for (
                            content_hash,
                            file_size,
                            modified_at_ns,
                            width,
                            height,
                            version,
                            indexed_at,
                            row_id,
                        ) in updates
                    ],
                )

        return RefreshReport(
            pending_images=tuple(pending),
            reused_images=tuple(reused),
            deleted_paths=deleted_paths,
        )

    def upsert_faces(self, image: ImageRecord, faces: Sequence[FaceRecord]) -> None:
        normalized_image = self._normalize_image(image)
        normalized_faces = tuple(self._normalize_face(face) for face in faces)
        seen_face_ids: set[str] = set()
        seen_face_numbers: set[int] = set()
        for face in normalized_faces:
            if face.face_id in seen_face_ids:
                raise ValueError(f"duplicate face_id: {face.face_id}")
            if face.face_number in seen_face_numbers:
                raise ValueError(f"duplicate face_number: {face.face_number}")
            seen_face_ids.add(face.face_id)
            seen_face_numbers.add(face.face_number)

        with self._connection:
            row = self._connection.execute(
                "SELECT id FROM images WHERE path = ?",
                (normalized_image.path.as_posix(),),
            ).fetchone()
            if row is None:
                raise ValueError("refresh_images must be called before upsert_faces")
            image_id = int(row["id"])

            self._connection.execute("DELETE FROM faces WHERE image_id = ?", (image_id,))
            if normalized_faces:
                self._connection.executemany(
                    """
                    INSERT INTO faces(
                        face_id, image_id, face_number, bbox_json, landmarks_json,
                        crop_path, embedding_blob, embedding_dimension, detection_score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            face.face_id,
                            image_id,
                            face.face_number,
                            json.dumps(face.bbox),
                            json.dumps(face.landmarks),
                            face.crop_path.as_posix() if face.crop_path is not None else None,
                            _pack_embedding(face.embedding)[0],
                            _pack_embedding(face.embedding)[1],
                            face.detection_score,
                        )
                        for face in normalized_faces
                    ],
                )
            self._connection.execute(
                """
                UPDATE images
                SET content_hash = ?, file_size = ?, modified_at_ns = ?, width = ?, height = ?,
                    indexed_at = ?, face_count = ?
                WHERE id = ?
                """,
                (
                    normalized_image.content_hash,
                    normalized_image.file_size,
                    normalized_image.modified_at_ns,
                    normalized_image.width,
                    normalized_image.height,
                    time.time_ns(),
                    len(normalized_faces),
                    image_id,
                ),
            )

    def search(self, embedding: Sequence[float], *, limit: int) -> list[FaceMatch]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        query = _normalize_embedding(embedding, field="embedding")
        rows = self._connection.execute(
            """
            SELECT images.path, faces.face_id, faces.face_number, faces.bbox_json,
                   faces.crop_path, faces.embedding_blob
            FROM faces
            INNER JOIN images ON images.id = faces.image_id
            """
        ).fetchall()
        if not rows:
            return []

        matches: list[FaceMatch] = []
        for row in rows:
            stored = _unpack_embedding(bytes(row["embedding_blob"]))
            if len(stored) != len(query):
                continue
            score = sum(query_value * stored_value for query_value, stored_value in zip(query, stored))
            bbox = tuple(json.loads(str(row["bbox_json"])))
            crop_path = row["crop_path"]
            matches.append(
                FaceMatch(
                    image_path=Path(str(row["path"])),
                    face_id=str(row["face_id"]),
                    face_number=int(row["face_number"]),
                    score=float(score),
                    bbox=_normalize_bbox(bbox),
                    crop_path=Path(str(crop_path)) if crop_path else None,
                )
            )

        matches.sort(
            key=lambda match: (
                -match.score,
                match.image_path.as_posix().casefold(),
                match.image_path.as_posix(),
                match.face_id,
            )
        )
        return matches[:limit]

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    modified_at_ns INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    model_version TEXT NOT NULL,
                    indexed_at INTEGER,
                    face_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS faces (
                    face_id TEXT PRIMARY KEY,
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    face_number INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    landmarks_json TEXT NOT NULL,
                    crop_path TEXT,
                    embedding_blob BLOB NOT NULL,
                    embedding_dimension INTEGER NOT NULL,
                    detection_score REAL NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_images_path ON images(path)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_images_content_hash ON images(content_hash)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_faces_image_id ON faces(image_id)"
            )

    @staticmethod
    def _normalize_image(image: ImageRecord) -> ImageRecord:
        path = _normalize_path(image.path, field="image.path")
        return ImageRecord(
            path=path,
            content_hash=_normalize_text(image.content_hash, field="content_hash"),
            file_size=_normalize_non_negative_int(image.file_size, field="file_size"),
            modified_at_ns=_normalize_non_negative_int(
                image.modified_at_ns,
                field="modified_at_ns",
            ),
            width=_normalize_non_negative_int(image.width, field="width"),
            height=_normalize_non_negative_int(image.height, field="height"),
        )

    @staticmethod
    def _normalize_face(face: FaceRecord) -> FaceRecord:
        face_id = _normalize_text(face.face_id, field="face_id")
        face_number = _normalize_non_negative_int(face.face_number, field="face_number")
        if isinstance(face.detection_score, bool):
            raise ValueError("detection_score must be a finite number")  # noqa: TRY004
        detection_score = float(face.detection_score)
        if not math.isfinite(detection_score):
            raise ValueError("detection_score must be a finite number")
        crop_path = (
            _normalize_path(face.crop_path, field="crop_path")
            if face.crop_path is not None
            else None
        )
        return FaceRecord(
            face_id=face_id,
            face_number=face_number,
            bbox=_normalize_bbox(face.bbox),
            landmarks=_normalize_landmarks(face.landmarks),
            embedding=_normalize_embedding(face.embedding, field="embedding"),
            detection_score=detection_score,
            crop_path=crop_path,
        )


__all__ = [
    "FaceIndex",
    "FaceMatch",
    "FaceRecord",
    "ImageRecord",
    "RefreshReport",
]
