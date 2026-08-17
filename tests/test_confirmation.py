from __future__ import annotations

from private_search.ai.confirmation import ConfirmationRequest, ConfirmationService


def test_confirmation_service_passes_the_exact_request_to_the_decider():
    captured = []

    def decide(request):
        captured.append(request)
        return True

    request = ConfirmationRequest(
        action="download_media",
        summary="Download the selected media",
        details=(
            ("URL", "https://example.com/video"),
            ("Destination", "var/downloads"),
        ),
    )

    result = ConfirmationService(decide=decide).confirm(request)

    assert result is True
    assert captured == [request]


def test_confirmation_service_defaults_to_decline_when_decider_rejects():
    request = ConfirmationRequest(
        action="username_osint",
        summary="Scan a username",
        details=(("Username", "example_user"),),
    )

    assert ConfirmationService(decide=lambda _: False).confirm(request) is False
