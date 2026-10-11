"""Stable codes for yt-dlp failures shown by the desktop app."""

from __future__ import annotations


def is_source_changed(error: BaseException) -> bool:
    """Whether yt-dlp failed because the site changed (an *unexpected*
    extractor error), so updating yt-dlp is the likely fix.

    yt-dlp marks user-facing conditions (private, geo-blocked, sign-in) and
    network failures as ``expected``; anything else is extractor breakage.
    """
    from yt_dlp.utils import (  # pylint: disable=import-outside-toplevel
        DownloadError,
        ExtractorError,
    )

    cause: BaseException | None = error
    if isinstance(error, DownloadError) and error.exc_info and error.exc_info[1] is not None:
        cause = error.exc_info[1]
    return isinstance(cause, ExtractorError) and not cause.expected


def _error_chain(error: BaseException) -> list[BaseException]:
    """The error and everything yt-dlp chained behind it, without cycles."""
    chain: list[BaseException] = []
    pending: list[object] = [error]
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or any(current is seen for seen in chain):
            continue
        chain.append(current)
        exc_info = getattr(current, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) > 1:
            pending.append(exc_info[1])
        pending.extend((getattr(current, "cause", None), current.__cause__, current.__context__))
    return chain


def is_source_blocked(error: BaseException) -> bool:
    """Whether the site refused the connection (HTTP 403, usually a Cloudflare
    anti-bot challenge). Common on VPN and shared IPs; updating yt-dlp or
    retrying from the same address does not help.
    """
    from yt_dlp.networking.exceptions import (  # pylint: disable=import-outside-toplevel
        HTTPError,
    )

    for item in _error_chain(error):
        if isinstance(item, HTTPError) and item.status == 403:
            return True
        if "cloudflare anti-bot challenge" in str(item).casefold():
            return True
    return False


def failure_code(error: BaseException) -> str:
    if is_source_blocked(error):
        return "source_blocked"
    return "source_changed" if is_source_changed(error) else "provider_unavailable"
