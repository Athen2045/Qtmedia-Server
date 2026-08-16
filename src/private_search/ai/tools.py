"""Confirmation-gated adapters for existing and optional external tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from ..download import engine as downloader
from ..search import engine as search
from .actions import AgentAction
from .confirmation import ConfirmationRequest, ConfirmationService


class ToolUnavailableError(RuntimeError):
    """Raised when an optional tool has not passed its runtime preflight."""


class ToolExecutionError(RuntimeError):
    """Raised when a configured tool adapter fails during execution."""


@dataclass(frozen=True)
class ToolResult:
    """Normalized result passed from a tool adapter to the chat renderer."""

    action: str
    ok: bool
    message: str
    data: object | None = None
    cancelled: bool = False


ToolAdapter = Callable[[AgentAction], object]


class ToolRegistry:
    """Dispatch validated actions to fixed adapters after confirmation."""

    def __init__(
        self,
        confirmation: ConfirmationService,
        *,
        search_tool: ToolAdapter | None = None,
        download_tool: ToolAdapter | None = None,
        reverse_image_tool: ToolAdapter | None = None,
        username_osint_tool: ToolAdapter | None = None,
        email_osint_tool: ToolAdapter | None = None,
        describe_image_tool: ToolAdapter | None = None,
        reverse_image_resolver: Callable[[], str | None] | None = None,
    ) -> None:
        self._confirmation = confirmation
        self._reverse_image_resolver = reverse_image_resolver
        self._adapters: dict[str, ToolAdapter | None] = {
            "refine_search": search_tool or self._default_search,
            "download_media": download_tool or self._default_download,
            "reverse_image_search": reverse_image_tool,
            "username_osint": username_osint_tool,
            "email_osint": email_osint_tool,
            "describe_image": describe_image_tool,
        }

    @staticmethod
    def _default_search(action: AgentAction) -> object:
        if action.query is None:
            raise ToolExecutionError("search action has no query")
        return search.search(action.query, source_scope=action.search_scope)

    @staticmethod
    def _default_download(action: AgentAction) -> object:
        if action.url is None:
            raise ToolExecutionError("download action has no URL")
        return downloader.download_video(action.url)

    def dispatch(self, action: AgentAction) -> ToolResult:
        if action.action == "respond":
            return ToolResult(
                action=action.action,
                ok=True,
                message=action.message or "",
            )

        if action.action == "reverse_image_search":
            resolved = self._resolve_reverse_image_action(action)
            if isinstance(resolved, ToolResult):
                return resolved
            action = resolved

        adapter = self._adapters.get(action.action)
        if adapter is None:
            raise ToolUnavailableError(f"tool is unavailable: {action.action}")

        request = self._request_for(action)
        if not self._confirmation.confirm(request):
            return ToolResult(
                action=action.action,
                ok=False,
                message="Cancelled by user.",
                cancelled=True,
            )

        try:
            data = adapter(action)
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError(f"{action.action} failed: {error}") from error

        if action.action == "download_media" and data is False:
            return ToolResult(
                action=action.action,
                ok=False,
                message="The downloader did not complete the requested media download.",
                data=data,
            )
        if action.action == "refine_search":
            count = len(data) if isinstance(data, list) else 0
            message = f"Found {count} search result(s)."
        elif action.action == "reverse_image_search":
            count = len(data) if isinstance(data, list) else 0
            message = f"Found {count} reverse-image result(s)."
        elif action.action == "username_osint":
            count = len(data) if isinstance(data, list) else 0
            message = f"Found {count} username result(s)."
        elif action.action == "email_osint":
            count = len(data) if isinstance(data, list) else 0
            message = f"Found {count} email result(s)."
        else:
            message = f"{action.action} completed."
        return ToolResult(action=action.action, ok=True, message=message, data=data)

    def _resolve_reverse_image_action(
        self, action: AgentAction
    ) -> AgentAction | ToolResult:
        if action.image_path is not None:
            return action
        if self._reverse_image_resolver is None:
            raise ToolUnavailableError(f"tool is unavailable: {action.action}")

        selected_path = self._reverse_image_resolver()
        if selected_path is None:
            return ToolResult(
                action=action.action,
                ok=False,
                message="Cancelled by user.",
                cancelled=True,
            )

        path = Path(selected_path)
        if not path.is_file():
            raise ToolExecutionError("reverse_image_search requires a regular image file")
        return replace(action, image_path=str(path))

    @staticmethod
    def _request_for(action: AgentAction) -> ConfirmationRequest:
        if action.action == "refine_search":
            sources = ", ".join(
                adapter.name for adapter in search.adapters_for_scope(action.search_scope)
            )
            details = (
                ("Query", action.query or ""),
                ("Sources", sources),
            )
            return ConfirmationRequest(action.action, "Search selected external sources", details)
        if action.action == "download_media":
            return ConfirmationRequest(
                action.action,
                "Download media with the configured downloader",
                (("URL", action.url or ""),),
            )
        if action.action == "reverse_image_search":
            return ConfirmationRequest(
                action.action,
                "Submit an image to configured reverse-search engines",
                (("Image", action.image_path or ""),),
            )
        if action.action == "username_osint":
            return ConfirmationRequest(
                action.action,
                "Probe configured sites for a username",
                (("Username", action.username or ""),),
            )
        if action.action == "email_osint":
            return ConfirmationRequest(
                action.action,
                "Probe configured sites for an email address",
                (("Email", action.email or ""),),
            )
        if action.action == "describe_image":
            return ConfirmationRequest(
                action.action,
                "Send a local image to the local multimodal model",
                (("Image", action.image_path or ""),),
            )
        raise ToolUnavailableError(f"tool is unavailable: {action.action}")
