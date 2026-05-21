# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Codex CLI schema definitions and transformations."""

from opentrace.schemas.codex_cli.v1 import (
    # Top-level rollout types
    CodexSessionMeta,
    CodexResponseItem,
    CodexCompactedItem,
    CodexTurnContext,
    CodexEventMsg,
    CodexRolloutItem,
    # Session meta
    CodexSessionMetaPayload,
    CodexGitInfo,
    CodexBaseInstructions,
    # Turn context
    CodexTurnContextPayload,
    CodexSandboxPolicyWorkspaceWrite,
    CodexCollaborationMode,
    CodexTruncationPolicy,
    # Response payloads
    CodexMessagePayload,
    CodexReasoningPayload,
    CodexFunctionCallPayload,
    CodexFunctionCallOutputPayload,
    CodexLocalShellCallPayload,
    CodexWebSearchCallPayload,
    CodexResponsePayload,
    # Event payloads
    CodexUserMessageEventPayload,
    CodexAgentMessageEventPayload,
    CodexTokenCountEventPayload,
    CodexTurnAbortedEventPayload,
    CodexErrorEventPayload,
    CodexEventPayload,
    # Token types
    CodexTokenUsage,
    CodexTokenUsageInfo,
    CodexRateLimitSnapshot,
    # Content types
    CodexContentItem,
    CodexInputText,
    CodexOutputText,
)
from opentrace.schemas.codex_cli.transform import (
    CodexTransformContext,
    transform_codex_v1,
)

__all__ = [
    # Top-level types
    "CodexSessionMeta",
    "CodexResponseItem",
    "CodexCompactedItem",
    "CodexTurnContext",
    "CodexEventMsg",
    "CodexRolloutItem",
    # Session meta
    "CodexSessionMetaPayload",
    "CodexGitInfo",
    "CodexBaseInstructions",
    # Turn context
    "CodexTurnContextPayload",
    "CodexSandboxPolicyWorkspaceWrite",
    "CodexCollaborationMode",
    "CodexTruncationPolicy",
    # Response payloads
    "CodexMessagePayload",
    "CodexReasoningPayload",
    "CodexFunctionCallPayload",
    "CodexFunctionCallOutputPayload",
    "CodexLocalShellCallPayload",
    "CodexWebSearchCallPayload",
    "CodexResponsePayload",
    # Event payloads
    "CodexUserMessageEventPayload",
    "CodexAgentMessageEventPayload",
    "CodexTokenCountEventPayload",
    "CodexTurnAbortedEventPayload",
    "CodexErrorEventPayload",
    "CodexEventPayload",
    # Token types
    "CodexTokenUsage",
    "CodexTokenUsageInfo",
    "CodexRateLimitSnapshot",
    # Content types
    "CodexContentItem",
    "CodexInputText",
    "CodexOutputText",
    # Transform
    "CodexTransformContext",
    "transform_codex_v1",
]
