import pytest

from qtmedia_bot.bot.services.metrics import JobPhaseRecorder, PhaseMetric


def test_phase_recorder_emits_numeric_download_measurement():
    timestamps = iter((10.0, 11.25))
    emitted = []
    recorder = JobPhaseRecorder(
        "opaque-job-id",
        clock=lambda: next(timestamps),
        sink=emitted.append,
    )

    recorder.start("download")
    recorder.finish(outcome="completed", byte_count=4_000_000)

    assert emitted == [
        PhaseMetric(
            job_id="opaque-job-id",
            phase="download",
            duration_ms=1_250,
            outcome="completed",
            byte_count=4_000_000,
        )
    ]


def test_phase_recorder_rejects_arbitrary_or_overlapping_phases():
    recorder = JobPhaseRecorder(
        "opaque-job-id",
        clock=lambda: 1.0,
        sink=lambda metric: None,
    )

    with pytest.raises(ValueError, match="phase"):
        recorder.start("https://private.example/media")

    recorder.start("queue")
    with pytest.raises(ValueError, match="active"):
        recorder.start("upload")


def test_phase_recorder_failure_closes_active_phase_once():
    timestamps = iter((20.0, 20.5))
    emitted = []
    recorder = JobPhaseRecorder(
        "opaque-job-id",
        clock=lambda: next(timestamps),
        sink=emitted.append,
    )

    recorder.start("upload")
    recorder.fail_active("upload_unconfirmed")
    recorder.fail_active("upload_unconfirmed")

    assert emitted == [
        PhaseMetric(
            job_id="opaque-job-id",
            phase="upload",
            duration_ms=500,
            outcome="upload_unconfirmed",
            byte_count=None,
        )
    ]

