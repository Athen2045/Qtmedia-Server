"""Song tags for saved music: title, artist and album only.

yt-dlp reports a track's name, artists and album for music sources (YouTube
Music, auto-generated "Artist - Topic" channels). The desktop app writes them
into saved MP3/FLAC files so the lyrics lookup can match on artist and title.
Nothing else is written: no source link, description or uploader details.
FLACs made from a lossy stream also get `SOURCE_CODEC` / `SOURCE_BITRATE`
(e.g. "opus" / "160") so the player can say they are not truly lossless.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TOPIC_SUFFIX = " - Topic"


@dataclass(frozen=True)
class SongTags:
    title: str | None = None
    artist: str | None = None
    album: str | None = None

    def is_empty(self) -> bool:
        return not (self.title or self.artist or self.album)


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def song_tags(info: dict[str, object]) -> SongTags:
    """Title/artist/album from a yt-dlp info dict (music metadata only)."""
    artists = info.get("artists")
    artist = _text(info.get("artist"))
    if artist is None and isinstance(artists, list):
        named = [name.strip() for name in artists if isinstance(name, str) and name.strip()]
        artist = ", ".join(named) or None
    if artist is None:
        artist = _text(info.get("creator"))
    if artist is None:
        # YouTube's auto-generated music channels are named "<Artist> - Topic".
        channel = _text(info.get("channel")) or _text(info.get("uploader"))
        if channel and channel.endswith(TOPIC_SUFFIX):
            artist = channel.removesuffix(TOPIC_SUFFIX).strip() or None
    return SongTags(title=_text(info.get("track")), artist=artist, album=_text(info.get("album")))


# Codecs that lose information; a FLAC made from one is not truly lossless.
LOSSY_CODECS = {"opus": "opus", "mp4a": "aac", "aac": "aac", "vorbis": "vorbis", "mp3": "mp3", "ac-3": "ac3", "ec-3": "eac3"}


def lossy_codec(acodec: object) -> str | None:
    """yt-dlp's `acodec` ("opus", "mp4a.40.2") as a lossy codec name, else None."""
    if not isinstance(acodec, str):
        return None
    family = acodec.strip().casefold().split(".", 1)[0]
    return LOSSY_CODECS.get(family)


def write_source_tags(path: Path, acodec: object, abr: object) -> bool:
    """Marks a FLAC made from a lossy stream; returns whether it did."""
    codec = lossy_codec(acodec)
    if codec is None or path.suffix.casefold() != ".flac":
        return False
    from mutagen.flac import FLAC  # pylint: disable=import-outside-toplevel

    audio = FLAC(path)
    audio["SOURCE_CODEC"] = [codec]
    if isinstance(abr, (int, float)) and abr > 0:
        audio["SOURCE_BITRATE"] = [str(round(abr))]
    audio.save(str(path))
    return True


def write_song_tags(path: Path, tags: SongTags, fallback_title: str) -> bool:
    """Writes the tags into a saved FLAC or MP3; returns whether it did."""
    title = tags.title or fallback_title
    fields = {"title": title, "artist": tags.artist, "album": tags.album}
    fields = {key: value for key, value in fields.items() if value}
    if not fields:
        return False
    suffix = path.suffix.casefold()
    if suffix == ".flac":
        from mutagen.flac import FLAC  # pylint: disable=import-outside-toplevel

        audio = FLAC(path)
    elif suffix == ".mp3":
        from mutagen.easyid3 import EasyID3  # pylint: disable=import-outside-toplevel
        from mutagen.id3 import (
            ID3NoHeaderError,  # pylint: disable=import-outside-toplevel
        )

        try:
            audio = EasyID3(path)
        except ID3NoHeaderError:
            audio = EasyID3()
            audio.filename = str(path)
    else:
        return False
    for key, value in fields.items():
        audio[key] = [value]
    audio.save(str(path))
    return True
