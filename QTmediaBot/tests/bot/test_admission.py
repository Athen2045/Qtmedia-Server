from qtmedia_bot.bot.services.admission import AdmissionController


def test_request_window_allows_limit_then_reopens_after_expiry():
    now = [100.0]
    admission = AdmissionController(
        max_requests=2,
        window_seconds=10,
        max_queued_jobs=1,
        clock=lambda: now[0],
    )

    assert admission.allow_request(123) is True
    assert admission.allow_request(123) is True
    assert admission.allow_request(123) is False
    assert admission.allow_request(999) is True

    now[0] = 111.0
    assert admission.allow_request(123) is True


def test_queue_admission_is_bounded_idempotent_and_releasable():
    admission = AdmissionController(
        max_requests=1,
        window_seconds=10,
        max_queued_jobs=1,
    )

    assert admission.try_enter_queue("opaque-job-one") is True
    assert admission.try_enter_queue("opaque-job-one") is True
    assert admission.try_enter_queue("opaque-job-two") is False

    admission.leave_queue("opaque-job-one")
    assert admission.try_enter_queue("opaque-job-two") is True

