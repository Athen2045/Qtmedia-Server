from __future__ import annotations

import threading

import pytest

from qtmedia.desktop_service.models import InspectedMedia
from qtmedia_engine.session import SessionCatalog, SessionError


def _media(identifier: str) -> InspectedMedia:
    return InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id=identifier,
        title="Title",
        site="XVideos",
        thumbnail_url=None,
    )


def test_session_catalog_expires_media_and_bounds_entries():
    now = [10.0]
    catalog = SessionCatalog(max_media=2, ttl_seconds=5, clock=lambda: now[0])
    catalog.store_media(_media("media-1"))
    catalog.store_media(_media("media-2"))
    catalog.store_media(_media("media-3"))

    with pytest.raises(SessionError, match="unknown_media"):
        catalog.get_media("media-1")
    assert catalog.get_media("media-3").title == "Title"

    now[0] = 20.0
    with pytest.raises(SessionError, match="expired_media"):
        catalog.get_media("media-3")


def test_session_catalog_cancels_registered_job():
    catalog = SessionCatalog()
    event = threading.Event()
    catalog.register_job("job-1", event)

    catalog.cancel_job("job-1")

    assert event.is_set()


def test_session_catalog_bounds_concurrent_jobs():
    catalog = SessionCatalog(max_jobs=1)
    catalog.register_job("job-1", threading.Event())

    with pytest.raises(SessionError, match="too_many_jobs"):
        catalog.register_job("job-2", threading.Event())
