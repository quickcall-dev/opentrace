# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Codex CLI Schema v1 - Frozen 2026-02-04.

Official Source: https://github.com/openai/codex
Schema Files:
  - codex-rs/protocol/src/protocol.rs (RolloutLine, RolloutItem, EventMsg, etc.)
  - codex-rs/protocol/src/models.rs (ResponseItem, ContentItem, etc.)

CLI Version: 0.95.0+
Location: ~/.codex/sessions/YYYY/MM/DD/rollout-{ISO-timestamp}-{uuid}.jsonl
Format: JSONL
Example: rollout-2026-02-04T16-44-26-019c285c-569c-7f12-b514-a9ceff5f3f8d.jsonl

DO NOT MODIFY this schema. If Codex CLI changes its format,
create a v2.py file instead.
"""

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================


# AskForApproval - Approval policy enum
CodexApprovalPolicy = Literal["untrusted", "on-failure", "on-request", "never"]

# SandboxPolicy types
CodexSandboxPolicyType = Literal[
    "danger-full-access", "read-only", "external-sandbox", "workspace-write"
]

# SessionSource - Where the session originated
CodexSessionSource = Literal["cli", "vscode", "exec", "mcp", "subagent", "unknown"]

# NetworkAccess
CodexNetworkAccess = Literal["restricted", "enabled"]

# AgentStatus
CodexAgentStatus = Literal[
    "pending_init", "running", "completed", "errored", "shutdown", "not_found"
]

# CodexErrorInfo types
CodexErrorInfoType = Literal[
    "context_window_exceeded",
    "usage_limit_exceeded",
    "model_cap",
    "http_connection_failed",
    "response_stream_connection_failed",
    "internal_server_error",
    "unauthorized",
    "bad_request",
    "sandbox_error",
    "response_stream_disconnected",
    "response_too_many_failed_attempts",
    "thread_rollback_failed",
    "other",
]

# LocalShellStatus
CodexLocalShellStatus = Literal[
    "in_progress", "completed", "incomplete", "approved", "rejected"
]

# ReviewDecision
CodexReviewDecision = Literal["approve", "deny", "approve_session", "deny_session"]


# =============================================================================
# TOKEN USAGE TYPES
# =============================================================================


class CodexTokenUsage(TypedDict, total=False):
    """Token usage information (protocol.rs:1145-1156)."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int


class CodexTokenUsageInfo(TypedDict, total=False):
    """Token usage info with context window (protocol.rs:1158-1165)."""

    total_token_usage: CodexTokenUsage
    last_token_usage: CodexTokenUsage
    model_context_window: int | None


class CodexRateLimitWindow(TypedDict, total=False):
    """Rate limit window info (protocol.rs:1236-1246)."""

    used_percent: float
    window_minutes: int | None
    resets_at: int | None  # Unix timestamp


class CodexCreditsSnapshot(TypedDict, total=False):
    """Credits snapshot (protocol.rs:1248-1253)."""

    has_credits: bool
    unlimited: bool
    balance: str | None


class CodexRateLimitSnapshot(TypedDict, total=False):
    """Rate limit snapshot (protocol.rs:1228-1234)."""

    primary: CodexRateLimitWindow | None
    secondary: CodexRateLimitWindow | None
    credits: CodexCreditsSnapshot | None
    plan_type: str | None


# =============================================================================
# CONTENT TYPES (models.rs)
# =============================================================================


class CodexInputText(TypedDict):
    """Input text content block (models.rs:70)."""

    type: Literal["input_text"]
    text: str


class CodexInputImage(TypedDict):
    """Input image content block (models.rs:71)."""

    type: Literal["input_image"]
    image_url: str


class CodexOutputText(TypedDict):
    """Output text content block (models.rs:72)."""

    type: Literal["output_text"]
    text: str


CodexContentItem = CodexInputText | CodexInputImage | CodexOutputText


# =============================================================================
# REASONING TYPES (models.rs)
# =============================================================================


class CodexReasoningSummary(TypedDict, total=False):
    """Reasoning summary item."""

    text: str
    headline: str | None


class CodexReasoningContent(TypedDict, total=False):
    """Reasoning content item."""

    type: Literal["reasoning_text"]
    text: str


# =============================================================================
# SESSION META (protocol.rs:1644-1686)
# =============================================================================


class CodexGitInfo(TypedDict, total=False):
    """Git repository info (protocol.rs:1756-1767)."""

    commit_hash: str | None
    branch: str | None
    repository_url: str | None


class CodexBaseInstructions(TypedDict, total=False):
    """Base instructions in session meta (models.rs:191-203)."""

    text: str


class CodexDynamicToolSpec(TypedDict, total=False):
    """Dynamic tool specification."""

    name: str
    description: str
    parameters: dict[str, Any]


class CodexSessionMetaPayload(TypedDict, total=False):
    """Payload of session_meta (protocol.rs:1644-1661)."""

    id: str  # ThreadId (UUID)
    forked_from_id: str | None  # ThreadId of forked session
    timestamp: str
    cwd: str
    originator: str  # e.g., "codex_cli_rs"
    cli_version: str  # e.g., "0.95.0"
    source: CodexSessionSource
    model_provider: str | None  # e.g., "openai"
    base_instructions: CodexBaseInstructions | None
    dynamic_tools: list[CodexDynamicToolSpec] | None


class CodexSessionMetaLine(TypedDict, total=False):
    """Session meta with git info (protocol.rs:1680-1686)."""

    meta: CodexSessionMetaPayload  # Flattened in JSON
    git: CodexGitInfo | None


# =============================================================================
# SANDBOX POLICY (protocol.rs:380-426)
# =============================================================================


class CodexSandboxPolicyDangerFullAccess(TypedDict):
    """Danger full access sandbox policy."""

    type: Literal["danger-full-access"]


class CodexSandboxPolicyReadOnly(TypedDict):
    """Read-only sandbox policy."""

    type: Literal["read-only"]


class CodexSandboxPolicyExternalSandbox(TypedDict, total=False):
    """External sandbox policy."""

    type: Literal["external-sandbox"]
    network_access: CodexNetworkAccess


class CodexSandboxPolicyWorkspaceWrite(TypedDict, total=False):
    """Workspace write sandbox policy (protocol.rs:401-425)."""

    type: Literal["workspace-write"]
    writable_roots: list[str]
    network_access: bool
    exclude_tmpdir_env_var: bool
    exclude_slash_tmp: bool


CodexSandboxPolicy = (
    CodexSandboxPolicyDangerFullAccess
    | CodexSandboxPolicyReadOnly
    | CodexSandboxPolicyExternalSandbox
    | CodexSandboxPolicyWorkspaceWrite
)


# =============================================================================
# COLLABORATION MODE
# =============================================================================


class CodexCollaborationModeSettings(TypedDict, total=False):
    """Collaboration mode settings."""

    model: str
    reasoning_effort: str | None  # "low", "medium", "high"
    developer_instructions: str | None


class CodexCollaborationMode(TypedDict, total=False):
    """Collaboration mode configuration."""

    mode: str  # "default", "custom", etc.
    settings: CodexCollaborationModeSettings


# =============================================================================
# TRUNCATION POLICY (protocol.rs:1742-1747)
# =============================================================================


class CodexTruncationPolicyBytes(TypedDict):
    """Truncation policy by bytes."""

    mode: Literal["bytes"]
    limit: int


class CodexTruncationPolicyTokens(TypedDict):
    """Truncation policy by tokens."""

    mode: Literal["tokens"]
    limit: int


CodexTruncationPolicy = CodexTruncationPolicyBytes | CodexTruncationPolicyTokens


# =============================================================================
# TURN CONTEXT (protocol.rs:1719-1740)
# =============================================================================


class CodexTurnContextPayload(TypedDict, total=False):
    """Turn context payload (protocol.rs:1719-1740)."""

    cwd: str
    approval_policy: CodexApprovalPolicy
    sandbox_policy: CodexSandboxPolicy
    model: str
    personality: str | None
    collaboration_mode: CodexCollaborationMode | None
    effort: str | None  # ReasoningEffortConfig: "low", "medium", "high"
    summary: str  # ReasoningSummaryConfig: "auto", "none", "detailed"
    user_instructions: str | None
    developer_instructions: str | None
    final_output_json_schema: dict[str, Any] | None
    truncation_policy: CodexTruncationPolicy | None


# =============================================================================
# RESPONSE ITEMS (models.rs:82-186)
# =============================================================================


class CodexMessagePayload(TypedDict, total=False):
    """Message response item (models.rs:85-100)."""

    type: Literal["message"]
    id: str | None
    role: Literal["developer", "user", "assistant"]
    content: list[CodexContentItem]
    end_turn: bool | None
    phase: Literal["commentary", "final_answer"] | None


class CodexReasoningPayload(TypedDict, total=False):
    """Reasoning response item (models.rs:101-110)."""

    type: Literal["reasoning"]
    id: str
    summary: list[CodexReasoningSummary]
    content: list[CodexReasoningContent] | None
    encrypted_content: str | None


class CodexLocalShellAction(TypedDict, total=False):
    """Local shell action."""

    type: str
    command: list[str]
    cwd: str | None
    timeout_ms: int | None
    env: dict[str, str] | None


class CodexLocalShellCallPayload(TypedDict, total=False):
    """Local shell call response item (models.rs:111-120)."""

    type: Literal["local_shell_call"]
    id: str | None
    call_id: str | None
    status: CodexLocalShellStatus
    action: CodexLocalShellAction


class CodexFunctionCallPayload(TypedDict, total=False):
    """Function call response item (models.rs:121-131)."""

    type: Literal["function_call"]
    id: str | None
    name: str  # e.g., "shell", "apply_patch"
    arguments: str  # JSON string
    call_id: str


class CodexFunctionCallOutputInner(TypedDict, total=False):
    """Parsed inner structure of function_call_output.output JSON string.

    The output field in the JSONL is a JSON-encoded string. When parsed,
    it contains these fields.
    """

    output: str
    success: bool
    metadata: dict[str, Any] | None


class CodexFunctionCallOutputPayload(TypedDict, total=False):
    """Function call output response item (models.rs:132-140).

    Note: The `output` field is a JSON-encoded string, not a nested dict.
    Parse it with json.loads() to get CodexFunctionCallOutputInner.
    """

    type: Literal["function_call_output"]
    call_id: str
    output: str  # JSON string; parse to get CodexFunctionCallOutputInner


class CodexCustomToolCallPayload(TypedDict, total=False):
    """Custom tool call response item (models.rs:141-152)."""

    type: Literal["custom_tool_call"]
    id: str | None
    status: str | None
    call_id: str
    name: str
    input: str


class CodexCustomToolCallOutputPayload(TypedDict, total=False):
    """Custom tool call output response item (models.rs:153-156)."""

    type: Literal["custom_tool_call_output"]
    call_id: str
    output: str


class CodexWebSearchAction(TypedDict, total=False):
    """Web search action."""

    type: str
    query: str


class CodexWebSearchCallPayload(TypedDict, total=False):
    """Web search call response item (models.rs:157-175)."""

    type: Literal["web_search_call"]
    id: str | None
    status: str | None
    action: CodexWebSearchAction | None


class CodexGhostCommit(TypedDict, total=False):
    """Ghost commit snapshot."""

    sha: str
    message: str
    author: str
    timestamp: str


class CodexGhostSnapshotPayload(TypedDict, total=False):
    """Ghost snapshot response item (models.rs:176-179)."""

    type: Literal["ghost_snapshot"]
    ghost_commit: CodexGhostCommit


class CodexCompactionPayload(TypedDict, total=False):
    """Compaction response item (models.rs:180-183)."""

    type: Literal["compaction"]
    encrypted_content: str


CodexResponsePayload = (
    CodexMessagePayload
    | CodexReasoningPayload
    | CodexLocalShellCallPayload
    | CodexFunctionCallPayload
    | CodexFunctionCallOutputPayload
    | CodexCustomToolCallPayload
    | CodexCustomToolCallOutputPayload
    | CodexWebSearchCallPayload
    | CodexGhostSnapshotPayload
    | CodexCompactionPayload
)


# =============================================================================
# COMPACTED ITEM (protocol.rs:1698-1717)
# =============================================================================


class CodexCompactedItemPayload(TypedDict, total=False):
    """Compacted item payload (protocol.rs:1698-1703)."""

    message: str
    replacement_history: list[CodexResponsePayload] | None


# =============================================================================
# EVENT MESSAGES (protocol.rs:700-882)
# All 50+ EventMsg variants
# =============================================================================


# --- Error/Warning Events ---


class CodexErrorInfo(TypedDict, total=False):
    """Error info (protocol.rs:956-984)."""

    type: CodexErrorInfoType
    model: str | None
    reset_after_seconds: int | None
    http_status_code: int | None


class CodexErrorEventPayload(TypedDict, total=False):
    """Error event payload (protocol.rs:1116-1121)."""

    type: Literal["error"]
    message: str
    codex_error_info: CodexErrorInfo | None


class CodexWarningEventPayload(TypedDict, total=False):
    """Warning event payload (protocol.rs:1123-1126)."""

    type: Literal["warning"]
    message: str


# --- Context/Thread Events ---


class CodexContextCompactedEventPayload(TypedDict):
    """Context compacted event (protocol.rs:1128-1129)."""

    type: Literal["context_compacted"]


class CodexThreadRolledBackEventPayload(TypedDict, total=False):
    """Thread rolled back event."""

    type: Literal["thread_rolled_back"]
    num_turns: int


class CodexThreadNameUpdatedEventPayload(TypedDict, total=False):
    """Thread name updated event."""

    type: Literal["thread_name_updated"]
    name: str


# --- Turn Events ---


class CodexTurnStartedEventPayload(TypedDict, total=False):
    """Turn started event (protocol.rs:1136-1142)."""

    type: Literal["task_started"]  # Aliased from turn_started
    model_context_window: int | None
    collaboration_mode_kind: str


class CodexTurnCompleteEventPayload(TypedDict, total=False):
    """Turn complete event (protocol.rs:1132-1134)."""

    type: Literal["task_complete"]  # Aliased from turn_complete
    last_agent_message: str | None


class CodexTurnAbortedEventPayload(TypedDict, total=False):
    """Turn aborted event."""

    type: Literal["turn_aborted"]
    reason: str  # e.g., "interrupted"


# --- Token Events ---


class CodexTokenCountEventPayload(TypedDict, total=False):
    """Token count event (protocol.rs:1222-1226)."""

    type: Literal["token_count"]
    info: CodexTokenUsageInfo | None
    rate_limits: CodexRateLimitSnapshot | None


# --- Message Events ---


class CodexUserMessageEventPayload(TypedDict, total=False):
    """User message event (protocol.rs:1360-1375)."""

    type: Literal["user_message"]
    message: str
    images: list[str] | None
    local_images: list[str]
    text_elements: list[dict[str, Any]]


class CodexAgentMessageEventPayload(TypedDict, total=False):
    """Agent message event (protocol.rs:1354-1357)."""

    type: Literal["agent_message"]
    message: str


class CodexAgentMessageDeltaEventPayload(TypedDict, total=False):
    """Agent message delta event (protocol.rs:1377-1380)."""

    type: Literal["agent_message_delta"]
    delta: str


# --- Reasoning Events ---


class CodexAgentReasoningEventPayload(TypedDict, total=False):
    """Agent reasoning event (protocol.rs:1382-1385)."""

    type: Literal["agent_reasoning"]
    text: str


class CodexAgentReasoningDeltaEventPayload(TypedDict, total=False):
    """Agent reasoning delta event (protocol.rs:1406-1409)."""

    type: Literal["agent_reasoning_delta"]
    delta: str


class CodexAgentReasoningRawContentEventPayload(TypedDict, total=False):
    """Agent reasoning raw content event (protocol.rs:1387-1390)."""

    type: Literal["agent_reasoning_raw_content"]
    text: str


class CodexAgentReasoningRawContentDeltaEventPayload(TypedDict, total=False):
    """Agent reasoning raw content delta event (protocol.rs:1392-1395)."""

    type: Literal["agent_reasoning_raw_content_delta"]
    delta: str


class CodexAgentReasoningSectionBreakEventPayload(TypedDict, total=False):
    """Agent reasoning section break event (protocol.rs:1397-1404)."""

    type: Literal["agent_reasoning_section_break"]
    item_id: str
    summary_index: int


# --- Session Events ---


class CodexSessionConfiguredEventPayload(TypedDict, total=False):
    """Session configured event."""

    type: Literal["session_configured"]
    thread_id: str
    rollout_path: str | None
    initial_messages: list[Any] | None


# --- MCP Events ---


class CodexMcpInvocation(TypedDict, total=False):
    """MCP invocation (protocol.rs:1411-1419)."""

    server: str
    tool: str
    arguments: dict[str, Any] | None


class CodexMcpStartupUpdateEventPayload(TypedDict, total=False):
    """MCP startup update event."""

    type: Literal["mcp_startup_update"]
    server: str
    status: str


class CodexMcpStartupCompleteEventPayload(TypedDict, total=False):
    """MCP startup complete event."""

    type: Literal["mcp_startup_complete"]
    servers: list[dict[str, Any]]


class CodexMcpToolCallBeginEventPayload(TypedDict, total=False):
    """MCP tool call begin event (protocol.rs:1421-1426)."""

    type: Literal["mcp_tool_call_begin"]
    call_id: str
    invocation: CodexMcpInvocation


class CodexMcpToolCallEndEventPayload(TypedDict, total=False):
    """MCP tool call end event (protocol.rs:1428-1437)."""

    type: Literal["mcp_tool_call_end"]
    call_id: str
    invocation: CodexMcpInvocation
    duration: str  # Duration as string
    result: dict[str, Any]  # Result<CallToolResult, String>


# --- Web Search Events ---


class CodexWebSearchBeginEventPayload(TypedDict, total=False):
    """Web search begin event (protocol.rs:1448-1451)."""

    type: Literal["web_search_begin"]
    call_id: str


class CodexWebSearchEndEventPayload(TypedDict, total=False):
    """Web search end event (protocol.rs:1453-1458)."""

    type: Literal["web_search_end"]
    call_id: str
    query: str
    action: CodexWebSearchAction


# --- Exec Command Events ---


class CodexExecCommandBeginEventPayload(TypedDict, total=False):
    """Exec command begin event."""

    type: Literal["exec_command_begin"]
    call_id: str
    command: list[str]
    cwd: str | None


class CodexExecCommandOutputDeltaEventPayload(TypedDict, total=False):
    """Exec command output delta event."""

    type: Literal["exec_command_output_delta"]
    call_id: str
    delta: str
    stream: Literal["stdout", "stderr"]


class CodexTerminalInteractionEventPayload(TypedDict, total=False):
    """Terminal interaction event."""

    type: Literal["terminal_interaction"]
    call_id: str
    stdin: str | None
    stdout: str | None


class CodexExecCommandEndEventPayload(TypedDict, total=False):
    """Exec command end event."""

    type: Literal["exec_command_end"]
    call_id: str
    exit_code: int | None
    duration_seconds: float


# --- Approval Events ---


class CodexExecApprovalRequestEventPayload(TypedDict, total=False):
    """Exec approval request event."""

    type: Literal["exec_approval_request"]
    id: str
    command: list[str]
    cwd: str | None
    reason: str | None


class CodexApplyPatchApprovalRequestEventPayload(TypedDict, total=False):
    """Apply patch approval request event."""

    type: Literal["apply_patch_approval_request"]
    id: str
    patch: str
    file_path: str


class CodexRequestUserInputEventPayload(TypedDict, total=False):
    """Request user input event."""

    type: Literal["request_user_input"]
    id: str
    prompt: str
    options: list[str] | None


class CodexElicitationRequestEventPayload(TypedDict, total=False):
    """Elicitation request event."""

    type: Literal["elicitation_request"]
    server_name: str
    request_id: str
    schema: dict[str, Any]


class CodexDynamicToolCallRequestPayload(TypedDict, total=False):
    """Dynamic tool call request."""

    type: Literal["dynamic_tool_call_request"]
    id: str
    name: str
    arguments: dict[str, Any]


# --- Patch Events ---


class CodexPatchApplyBeginEventPayload(TypedDict, total=False):
    """Patch apply begin event."""

    type: Literal["patch_apply_begin"]
    call_id: str
    file_path: str


class CodexPatchApplyEndEventPayload(TypedDict, total=False):
    """Patch apply end event."""

    type: Literal["patch_apply_end"]
    call_id: str
    success: bool
    error: str | None


# --- Diff Events ---


class CodexTurnDiffEventPayload(TypedDict, total=False):
    """Turn diff event."""

    type: Literal["turn_diff"]
    files: list[dict[str, Any]]


# --- History Events ---


class CodexGetHistoryEntryResponseEventPayload(TypedDict, total=False):
    """Get history entry response event."""

    type: Literal["get_history_entry_response"]
    offset: int
    log_id: int
    entry: dict[str, Any] | None


# --- Tool/Prompt List Events ---


class CodexMcpListToolsResponseEventPayload(TypedDict, total=False):
    """MCP list tools response event."""

    type: Literal["mcp_list_tools_response"]
    tools: list[dict[str, Any]]


class CodexListCustomPromptsResponseEventPayload(TypedDict, total=False):
    """List custom prompts response event."""

    type: Literal["list_custom_prompts_response"]
    prompts: list[dict[str, Any]]


class CodexListSkillsResponseEventPayload(TypedDict, total=False):
    """List skills response event."""

    type: Literal["list_skills_response"]
    skills: list[dict[str, Any]]


class CodexListRemoteSkillsResponseEventPayload(TypedDict, total=False):
    """List remote skills response event."""

    type: Literal["list_remote_skills_response"]
    skills: list[dict[str, Any]]


class CodexRemoteSkillDownloadedEventPayload(TypedDict, total=False):
    """Remote skill downloaded event."""

    type: Literal["remote_skill_downloaded"]
    hazelnut_id: str
    skill: dict[str, Any]


# --- Plan Events ---


class CodexPlanUpdateEventPayload(TypedDict, total=False):
    """Plan update event."""

    type: Literal["plan_update"]
    plan: dict[str, Any]


class CodexPlanDeltaEventPayload(TypedDict, total=False):
    """Plan delta event."""

    type: Literal["plan_delta"]
    thread_id: str
    turn_id: str
    item_id: str
    delta: str


# --- Undo Events ---


class CodexUndoStartedEventPayload(TypedDict, total=False):
    """Undo started event."""

    type: Literal["undo_started"]


class CodexUndoCompletedEventPayload(TypedDict, total=False):
    """Undo completed event."""

    type: Literal["undo_completed"]
    success: bool


# --- Stream Events ---


class CodexStreamErrorEventPayload(TypedDict, total=False):
    """Stream error event."""

    type: Literal["stream_error"]
    message: str
    retry_attempt: int | None


# --- Background Events ---


class CodexBackgroundEventEventPayload(TypedDict, total=False):
    """Background event."""

    type: Literal["background_event"]
    event: dict[str, Any]


# --- Review Events ---


class CodexReviewTarget(TypedDict, total=False):
    """Review target."""

    type: str  # "uncommittedChanges", "baseBranch", "commit", "custom"
    branch: str | None
    sha: str | None
    title: str | None
    instructions: str | None


class CodexReviewRequest(TypedDict, total=False):
    """Review request."""

    target: CodexReviewTarget
    user_facing_hint: str | None


class CodexEnteredReviewModeEventPayload(TypedDict, total=False):
    """Entered review mode event."""

    type: Literal["entered_review_mode"]
    request: CodexReviewRequest


class CodexExitedReviewModeEventPayload(TypedDict, total=False):
    """Exited review mode event."""

    type: Literal["exited_review_mode"]
    review_output: dict[str, Any] | None


# --- Deprecation Events ---


class CodexDeprecationNoticeEventPayload(TypedDict, total=False):
    """Deprecation notice event."""

    type: Literal["deprecation_notice"]
    message: str
    feature: str


# --- View Image Events ---


class CodexViewImageToolCallEventPayload(TypedDict, total=False):
    """View image tool call event."""

    type: Literal["view_image_tool_call"]
    path: str
    label: str


# --- Item Events ---


class CodexRawResponseItemEventPayload(TypedDict, total=False):
    """Raw response item event (protocol.rs:986-989)."""

    type: Literal["raw_response_item"]
    item: CodexResponsePayload


class CodexItemStartedEventPayload(TypedDict, total=False):
    """Item started event (protocol.rs:991-996)."""

    type: Literal["item_started"]
    thread_id: str
    turn_id: str
    item: dict[str, Any]  # TurnItem


class CodexItemCompletedEventPayload(TypedDict, total=False):
    """Item completed event (protocol.rs:1009-1014)."""

    type: Literal["item_completed"]
    thread_id: str
    turn_id: str
    item: dict[str, Any]  # TurnItem


# --- Content Delta Events ---


class CodexAgentMessageContentDeltaEventPayload(TypedDict, total=False):
    """Agent message content delta event (protocol.rs:1026-1032)."""

    type: Literal["agent_message_content_delta"]
    thread_id: str
    turn_id: str
    item_id: str
    delta: str


class CodexReasoningContentDeltaEventPayload(TypedDict, total=False):
    """Reasoning content delta event (protocol.rs:1050-1059)."""

    type: Literal["reasoning_content_delta"]
    thread_id: str
    turn_id: str
    item_id: str
    delta: str
    summary_index: int


class CodexReasoningRawContentDeltaEventPayload(TypedDict, total=False):
    """Reasoning raw content delta event (protocol.rs:1069-1078)."""

    type: Literal["reasoning_raw_content_delta"]
    thread_id: str
    turn_id: str
    item_id: str
    delta: str
    content_index: int


# --- Collab Events ---


class CodexCollabAgentSpawnBeginEventPayload(TypedDict, total=False):
    """Collab agent spawn begin event."""

    type: Literal["collab_agent_spawn_begin"]
    agent_id: str
    agent_type: str


class CodexCollabAgentSpawnEndEventPayload(TypedDict, total=False):
    """Collab agent spawn end event."""

    type: Literal["collab_agent_spawn_end"]
    agent_id: str
    success: bool


class CodexCollabAgentInteractionBeginEventPayload(TypedDict, total=False):
    """Collab agent interaction begin event."""

    type: Literal["collab_agent_interaction_begin"]
    agent_id: str


class CodexCollabAgentInteractionEndEventPayload(TypedDict, total=False):
    """Collab agent interaction end event."""

    type: Literal["collab_agent_interaction_end"]
    agent_id: str


class CodexCollabWaitingBeginEventPayload(TypedDict, total=False):
    """Collab waiting begin event."""

    type: Literal["collab_waiting_begin"]


class CodexCollabWaitingEndEventPayload(TypedDict, total=False):
    """Collab waiting end event."""

    type: Literal["collab_waiting_end"]


class CodexCollabCloseBeginEventPayload(TypedDict, total=False):
    """Collab close begin event."""

    type: Literal["collab_close_begin"]
    agent_id: str


class CodexCollabCloseEndEventPayload(TypedDict, total=False):
    """Collab close end event."""

    type: Literal["collab_close_end"]
    agent_id: str


# --- Shutdown Event ---


class CodexShutdownCompleteEventPayload(TypedDict):
    """Shutdown complete event."""

    type: Literal["shutdown_complete"]


# --- Skills Update Event ---


class CodexSkillsUpdateAvailableEventPayload(TypedDict):
    """Skills update available event."""

    type: Literal["skills_update_available"]


# Union of ALL event payloads
CodexEventPayload = (
    CodexErrorEventPayload
    | CodexWarningEventPayload
    | CodexContextCompactedEventPayload
    | CodexThreadRolledBackEventPayload
    | CodexThreadNameUpdatedEventPayload
    | CodexTurnStartedEventPayload
    | CodexTurnCompleteEventPayload
    | CodexTurnAbortedEventPayload
    | CodexTokenCountEventPayload
    | CodexUserMessageEventPayload
    | CodexAgentMessageEventPayload
    | CodexAgentMessageDeltaEventPayload
    | CodexAgentReasoningEventPayload
    | CodexAgentReasoningDeltaEventPayload
    | CodexAgentReasoningRawContentEventPayload
    | CodexAgentReasoningRawContentDeltaEventPayload
    | CodexAgentReasoningSectionBreakEventPayload
    | CodexSessionConfiguredEventPayload
    | CodexMcpStartupUpdateEventPayload
    | CodexMcpStartupCompleteEventPayload
    | CodexMcpToolCallBeginEventPayload
    | CodexMcpToolCallEndEventPayload
    | CodexWebSearchBeginEventPayload
    | CodexWebSearchEndEventPayload
    | CodexExecCommandBeginEventPayload
    | CodexExecCommandOutputDeltaEventPayload
    | CodexTerminalInteractionEventPayload
    | CodexExecCommandEndEventPayload
    | CodexExecApprovalRequestEventPayload
    | CodexApplyPatchApprovalRequestEventPayload
    | CodexRequestUserInputEventPayload
    | CodexElicitationRequestEventPayload
    | CodexDynamicToolCallRequestPayload
    | CodexPatchApplyBeginEventPayload
    | CodexPatchApplyEndEventPayload
    | CodexTurnDiffEventPayload
    | CodexGetHistoryEntryResponseEventPayload
    | CodexMcpListToolsResponseEventPayload
    | CodexListCustomPromptsResponseEventPayload
    | CodexListSkillsResponseEventPayload
    | CodexListRemoteSkillsResponseEventPayload
    | CodexRemoteSkillDownloadedEventPayload
    | CodexPlanUpdateEventPayload
    | CodexPlanDeltaEventPayload
    | CodexUndoStartedEventPayload
    | CodexUndoCompletedEventPayload
    | CodexStreamErrorEventPayload
    | CodexBackgroundEventEventPayload
    | CodexEnteredReviewModeEventPayload
    | CodexExitedReviewModeEventPayload
    | CodexDeprecationNoticeEventPayload
    | CodexViewImageToolCallEventPayload
    | CodexRawResponseItemEventPayload
    | CodexItemStartedEventPayload
    | CodexItemCompletedEventPayload
    | CodexAgentMessageContentDeltaEventPayload
    | CodexReasoningContentDeltaEventPayload
    | CodexReasoningRawContentDeltaEventPayload
    | CodexCollabAgentSpawnBeginEventPayload
    | CodexCollabAgentSpawnEndEventPayload
    | CodexCollabAgentInteractionBeginEventPayload
    | CodexCollabAgentInteractionEndEventPayload
    | CodexCollabWaitingBeginEventPayload
    | CodexCollabWaitingEndEventPayload
    | CodexCollabCloseBeginEventPayload
    | CodexCollabCloseEndEventPayload
    | CodexShutdownCompleteEventPayload
    | CodexSkillsUpdateAvailableEventPayload
)


# =============================================================================
# TOP-LEVEL ROLLOUT TYPES (protocol.rs:1688-1754)
# =============================================================================


@dataclass
class CodexSessionMeta:
    """Session metadata - first line of Codex session file."""

    timestamp: str
    type: Literal["session_meta"]
    payload: CodexSessionMetaPayload


@dataclass
class CodexResponseItem:
    """Response item from Codex."""

    timestamp: str
    type: Literal["response_item"]
    payload: CodexResponsePayload


@dataclass
class CodexCompactedItem:
    """Compacted item."""

    timestamp: str
    type: Literal["compacted"]
    payload: CodexCompactedItemPayload


@dataclass
class CodexTurnContext:
    """Turn context information."""

    timestamp: str
    type: Literal["turn_context"]
    payload: CodexTurnContextPayload


@dataclass
class CodexEventMsg:
    """Event message from Codex."""

    timestamp: str
    type: Literal["event_msg"]
    payload: CodexEventPayload


# RolloutLine wrapper (protocol.rs:1749-1754)
# The actual JSON has timestamp at top level and item flattened
CodexRolloutItem = (
    CodexSessionMeta
    | CodexResponseItem
    | CodexCompactedItem
    | CodexTurnContext
    | CodexEventMsg
)


