# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Cursor IDE Schema v1 - Frozen 2026-02-05.

Data locations:
- Global state: ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
- Workspace state: ~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/state.vscdb
- AI tracking: ~/.cursor/ai-tracking/ai-code-tracking.db
- Agent transcripts: ~/.cursor/projects/<slug>/agent-transcripts/<composerId>.txt
- MCP metadata: ~/.cursor/projects/<slug>/mcps/<server>/

DO NOT MODIFY this schema. If Cursor changes its format,
create a v2.py file instead.

Reference: Cross-validated against Cursor transcript and SQLite samples.
"""

from typing import Literal, TypedDict


# --- Global State Database (globalStorage/state.vscdb:ItemTable) ---


class CursorDailyStats(TypedDict):
    """Daily AI usage statistics.

    Key pattern: aiCodeTracking.dailyStats.v1.5.<YYYY-MM-DD>
    Location: globalStorage/state.vscdb:ItemTable
    """

    date: str  # ISO date YYYY-MM-DD
    tabSuggestedLines: int  # Lines suggested via tab completion
    tabAcceptedLines: int  # Lines accepted from tab completion
    composerSuggestedLines: int  # Lines suggested via composer/agent
    composerAcceptedLines: int  # Lines accepted from composer/agent


class CursorPendingMemory(TypedDict):
    """A pending memory item queued for user review.

    Key: cursor/pendingMemories (JSON array)
    Location: globalStorage/state.vscdb:ItemTable
    """

    id: str  # UUID for this memory
    memory: str  # The learned preference/instruction text
    title: str  # Short descriptive title
    requestId: str  # UUID of the request that generated this
    composerId: str  # UUID of the composer session
    timestamp: int  # Unix timestamp in milliseconds


class CursorServerConfigChat(TypedDict, total=False):
    """Chat configuration from server config."""

    fullContextTokenLimit: int
    maxRuleLength: int
    maxMcpTools: int


class CursorServerConfigBackground(TypedDict, total=False):
    """Background composer configuration from server config."""

    enableBackgroundAgent: bool
    maxWindowInWindows: int


class CursorServerConfigIndexing(TypedDict, total=False):
    """Indexing configuration from server config."""

    maxConcurrentUploads: int
    absoluteMaxNumberFiles: int


class CursorServerConfig(TypedDict, total=False):
    """Server-side feature configuration.

    Key: cursorai/serverConfig
    Location: globalStorage/state.vscdb:ItemTable

    Note: This is a partial schema covering key fields.
    The actual config contains many more feature flags.
    """

    chatConfig: CursorServerConfigChat
    backgroundComposerConfig: CursorServerConfigBackground
    indexingConfig: CursorServerConfigIndexing


# --- Workspace State Database (workspaceStorage/*/state.vscdb:ItemTable) ---


class CursorComposerEntry(TypedDict, total=False):
    """Individual composer/chat session metadata.

    Part of allComposers array in composer.composerData.
    Location: workspaceStorage/<hash>/state.vscdb:ItemTable
    """

    type: Literal["head"]  # Always "head" for main composer entries
    composerId: str  # UUID identifying this session
    createdAt: int  # Unix timestamp in milliseconds
    lastUpdatedAt: int  # Unix timestamp in milliseconds
    unifiedMode: Literal["agent", "chat", "edit"]  # Composer mode
    forceMode: str | None  # Override mode if set
    hasUnreadMessages: bool
    totalLinesAdded: int
    totalLinesRemoved: int
    hasBlockingPendingActions: bool
    isArchived: bool
    isDraft: bool
    isWorktree: bool
    isSpec: bool
    isProject: bool
    isBestOfNSubcomposer: bool
    numSubComposers: int
    referencedPlans: list[str]  # Plan IDs referenced
    name: str  # Conversation title/name
    subtitle: str  # Context info subtitle
    contextUsagePercent: float  # Percentage of context used
    filesChangedCount: int
    createdOnBranch: str  # Git branch when created


class CursorComposerData(TypedDict, total=False):
    """Composer state containing all chat/agent sessions for a workspace.

    Key: composer.composerData
    Location: workspaceStorage/<hash>/state.vscdb:ItemTable
    """

    allComposers: list[CursorComposerEntry]
    selectedComposerIds: list[str]  # Currently selected composer IDs
    lastFocusedComposerIds: list[str]  # Recently focused composer IDs
    hasMigratedComposerData: bool


class CursorAiServicePrompt(TypedDict):
    """Individual prompt from AI service history.

    Part of aiService.prompts array.
    Location: workspaceStorage/<hash>/state.vscdb:ItemTable
    """

    text: str  # The prompt text
    commandType: int  # Type of command (1 = user query, etc.)


# --- AI Code Tracking Database (ai-code-tracking.db) ---


class CursorAiCodeHash(TypedDict, total=False):
    """Row from ai_code_hashes table tracking AI-generated code.

    Location: ~/.cursor/ai-tracking/ai-code-tracking.db:ai_code_hashes
    Used for attribution of AI-generated code to specific sessions.
    """

    hash: str  # Primary key - hash of the code content
    source: Literal["tab", "composer"]  # Origin of the suggestion
    fileExtension: str | None  # File extension (e.g., ".py")
    fileName: str | None  # File name
    requestId: str | None  # UUID of the LLM request
    conversationId: str | None  # UUID linking to composer session
    timestamp: int | None  # Unix timestamp in milliseconds
    createdAt: int  # Unix timestamp in milliseconds (NOT NULL)
    model: str | None  # Model used for generation


class CursorConversationSummary(TypedDict, total=False):
    """Row from conversation_summaries table.

    Location: ~/.cursor/ai-tracking/ai-code-tracking.db:conversation_summaries
    Provides quick overview of chat/agent sessions.
    """

    conversationId: str  # Primary key - UUID of the conversation
    title: str | None  # Generated title
    tldr: str | None  # Short summary
    overview: str | None  # Longer overview
    summaryBullets: str | None  # Bullet point summary (may be JSON)
    model: str | None  # Model used
    mode: str | None  # Conversation mode
    updatedAt: int  # Unix timestamp in milliseconds (NOT NULL)


class CursorScoredCommit(TypedDict):
    """Row from scored_commits table tracking AI attribution in commits.

    Location: ~/.cursor/ai-tracking/ai-code-tracking.db:scored_commits
    Primary key: (commitHash, branchName)
    """

    commitHash: str  # Git commit SHA
    branchName: str  # Branch name
    scoredAt: int  # Unix timestamp in milliseconds when scored


class CursorTrackingState(TypedDict):
    """Row from tracking_state table for key-value storage.

    Location: ~/.cursor/ai-tracking/ai-code-tracking.db:tracking_state
    """

    key: str  # Primary key
    value: str  # Value (NOT NULL)


# --- Workspace JSON (for mapping hash to folder) ---


class CursorWorkspaceJson(TypedDict):
    """Contents of workspace.json in workspaceStorage/<hash>/.

    Used to map workspace hash to actual folder path.
    """

    folder: str  # file:// URI to workspace folder


# --- MCP Server Metadata ---


class CursorMcpServerMetadata(TypedDict):
    """Server metadata from SERVER_METADATA.json.

    Location: ~/.cursor/projects/<slug>/mcps/<server>/SERVER_METADATA.json
    """

    serverIdentifier: str  # Server ID
    serverName: str  # Display name


class CursorMcpToolArguments(TypedDict, total=False):
    """JSON Schema for MCP tool arguments."""

    type: Literal["object"]
    properties: dict  # Property definitions
    required: list[str]  # Required property names


class CursorMcpToolOutputSchema(TypedDict, total=False):
    """JSON Schema for MCP tool output."""

    type: str
    additionalProperties: bool


class CursorMcpTool(TypedDict, total=False):
    """MCP tool definition from tools/<name>.json.

    Location: ~/.cursor/projects/<slug>/mcps/<server>/tools/<name>.json
    """

    name: str  # Tool name
    description: str  # Tool description
    arguments: CursorMcpToolArguments  # Input schema
    outputSchema: CursorMcpToolOutputSchema  # Output schema


# --- IDE State ---


class CursorRecentFile(TypedDict):
    """Recently viewed file entry."""

    relativePath: str  # Path relative to project
    absolutePath: str  # Full filesystem path


class CursorIdeState(TypedDict, total=False):
    """IDE state from ~/.cursor/ide_state.json."""

    recentlyViewedFiles: list[CursorRecentFile]


# --- Global MCP Configuration ---


class CursorMcpServerConfig(TypedDict, total=False):
    """Individual MCP server configuration."""

    command: str  # Command to run (e.g., "uvx")
    args: list[str]  # Command arguments


class CursorMcpConfig(TypedDict):
    """Global MCP configuration from ~/.cursor/mcp.json."""

    mcpServers: dict[str, CursorMcpServerConfig]


# --- Agent Transcript Types (Parser-Agent additions) ---


class CursorToolInvocation(TypedDict, total=False):
    """Tool call or result extracted from agent transcript.

    Format in transcript:
    [Tool call] ToolName
      param1: value1
      param2: value2

    [Tool result] ToolName
    Result content here.
    """

    type: Literal["tool_call", "tool_result"]  # Whether this is a call or result
    tool_name: str  # Name of the tool
    parameters: dict[str, str]  # Parameters (only for tool_call)
    result: str | None  # Result content (only for tool_result)


class CursorTranscriptMessage(TypedDict, total=False):
    """Individual message in an agent transcript.

    User messages are wrapped in <user_query>...</user_query>
    Assistant messages may contain <think>...</think> blocks
    """

    role: Literal["user", "assistant"]  # Message author
    content: str  # Main message content
    thinking: str | None  # Extracted <think>...</think> content (assistant only)
    tool_calls: list[CursorToolInvocation]  # Tool invocations (assistant only)


class CursorAgentTranscript(TypedDict, total=False):
    """Full parsed agent transcript.

    Location: ~/.cursor/projects/<slug>/agent-transcripts/<composerId>.txt
    """

    composer_id: str  # UUID extracted from filename
    file_path: str  # Original file path
    messages: list[CursorTranscriptMessage]  # Parsed messages in order
    raw_content: str | None  # Original file content (optional)


class CursorTerminalSession(TypedDict, total=False):
    """Terminal session with YAML frontmatter.

    Location: ~/.cursor/projects/<slug>/terminals/<id>.txt

    Format:
    ---
    pid: 79706
    cwd: /path/to/workspace
    ---
    <terminal output content>
    """

    session_id: str  # ID extracted from filename
    file_path: str  # Original file path
    pid: int | None  # Process ID from frontmatter
    cwd: str | None  # Working directory from frontmatter
    content: str  # Terminal output content


class CursorProject(TypedDict, total=False):
    """Discovered Cursor project with associated data.

    Location: ~/.cursor/projects/<slug>/
    """

    slug: str  # Project slug (e.g., "Users-test-work-myproject")
    path: str  # Full path to project directory under ~/.cursor/projects/
    workspace_path: str | None  # Decoded workspace path (e.g., /Users/test/work/myproject)
    transcript_files: list[str]  # List of agent transcript file paths
    terminal_files: list[str]  # List of terminal session file paths
    mcp_servers: list[str]  # List of MCP server names
