"""Local AI runtime and action-protocol integration."""

from .actions import (
    ACTION_JSON_SCHEMA,
    ACTION_SYSTEM_PROMPT,
    ALLOWED_ACTIONS,
    NATURAL_SYSTEM_PROMPT,
    ActionValidationError,
    AgentAction,
    parse_action,
)
from .chat import ChatOrchestrator, ChatTurnResult
from .client import ChatCompletion, LlamaClient, LlamaClientError
from .confirmation import ConfirmationRequest, ConfirmationService
from .runtime import (
    LlamaServer,
    LlamaServerError,
    RuntimeConfigurationError,
    RuntimeSettings,
)
from .tools import (
    ToolExecutionError,
    ToolRegistry,
    ToolResult,
    ToolUnavailableError,
)

__all__ = [
    "ACTION_JSON_SCHEMA",
    "ACTION_SYSTEM_PROMPT",
    "ALLOWED_ACTIONS",
    "NATURAL_SYSTEM_PROMPT",
    "ActionValidationError",
    "AgentAction",
    "ChatCompletion",
    "ChatOrchestrator",
    "ChatTurnResult",
    "ConfirmationRequest",
    "ConfirmationService",
    "LlamaClient",
    "LlamaClientError",
    "LlamaServer",
    "LlamaServerError",
    "RuntimeConfigurationError",
    "RuntimeSettings",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolResult",
    "ToolUnavailableError",
    "parse_action",
]
