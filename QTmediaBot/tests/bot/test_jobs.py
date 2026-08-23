from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.quality import QualityOption


def inspection():
    return MediaInspection(
        url="https://example.com/private-source",
        title="Private title",
        duration_seconds=30,
        formats=(),
    )


def option():
    return QualityOption(
        key="v720",
        label="720p",
        height=720,
        size_bytes=1_000_000,
        size_approximate=False,
        format_selector="720",
        media_type="video",
    )


def test_job_catalog_uses_opaque_ids_and_enforces_owner():
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: 100.0)
    job_id = catalog.create(123, 456, inspection(), (option(),))

    assert "example.com" not in job_id
    assert catalog.get_for_user(job_id, 123, 456) is not None
    assert catalog.get_for_user(job_id, 999, 456) is None
    assert catalog.get_for_user(job_id, 123, 999) is None


def test_job_catalog_expires_records():
    now = [100.0]
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: now[0])
    job_id = catalog.create(123, 456, inspection(), (option(),))

    now[0] = 161.0

    assert catalog.get_for_user(job_id, 123, 456) is None
    assert catalog.remove_expired() == 0


def test_job_catalog_claims_a_quality_once_and_tracks_active_state():
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: 100.0)
    job_id = catalog.create(123, 456, inspection(), (option(),))

    claimed = catalog.claim_for_user(job_id, 123, 456, "v720")

    assert claimed is not None
    assert claimed.status == "queued"
    assert claimed.options == (option(),)
    assert catalog.claim_for_user(job_id, 123, 456, "v720") is None
    assert catalog.active_for_user(123, 456).job_id == job_id


def test_job_catalog_cancellation_is_owner_scoped():
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: 100.0)
    job_id = catalog.create(123, 456, inspection(), (option(),))
    assert catalog.claim_for_user(job_id, 123, 456, "v720") is not None

    assert catalog.cancel_for_user(job_id, 999, 456) is False
    assert catalog.cancel_for_user(job_id, 123, 456) is True
    assert catalog.active_for_user(123, 456) is None
    assert catalog.get_for_user(job_id, 123, 456).status == "cancelled"


def test_job_catalog_exposes_and_cancels_an_unselected_interaction():
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: 100.0)
    job_id = catalog.create(123, 456, inspection(), (option(),))

    assert catalog.current_for_user(123, 456).job_id == job_id
    assert catalog.cancel_for_user(job_id, 123, 456) is True
    assert catalog.current_for_user(123, 456) is None


def test_job_catalog_atomically_creates_only_when_owner_is_idle():
    catalog = JobCatalog(ttl_seconds=60, time_fn=lambda: 100.0)

    first = catalog.try_create(123, 456, inspection(), (option(),))
    second = catalog.try_create(123, 456, inspection(), (option(),))
    other_user = catalog.try_create(999, 456, inspection(), (option(),))

    assert first is not None
    assert second is None
    assert other_user is not None

