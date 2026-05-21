-- QuickCall OpenTrace database schema v1

CREATE TABLE IF NOT EXISTS schema_version (
    version INT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orgs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    user_email TEXT,
    user_name TEXT,
    device_name TEXT,
    device_id TEXT,
    cwd TEXT,
    repo_url TEXT,
    repo_name TEXT,
    git_branch TEXT,
    git_commit TEXT,
    project_hash TEXT,
    org TEXT,
    org_id UUID REFERENCES orgs(id),
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    raw_file_path TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_schema_version INT NOT NULL,
    msg_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ,
    content TEXT,
    thinking TEXT,
    model TEXT,
    raw_data JSONB,
    raw_file_path TEXT,
    raw_line_number INT,
    ingested_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS token_usage (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    cached_tokens INT DEFAULT 0,
    thinking_tokens INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tool_calls (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    tool_id TEXT,
    tool_name TEXT NOT NULL,
    tool_input JSONB
);

CREATE TABLE IF NOT EXISTS tool_results (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    call_id TEXT,
    output TEXT,
    status TEXT CHECK (status IN ('success', 'failure'))
);

CREATE TABLE IF NOT EXISTS file_progress (
    raw_file_path TEXT NOT NULL,
    source TEXT NOT NULL,
    last_line_read INT NOT NULL DEFAULT 0,
    content_hash TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (raw_file_path, source)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(msg_type);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_ingested_at ON messages(ingested_at);
CREATE INDEX IF NOT EXISTS idx_messages_raw_file_path ON messages(raw_file_path) WHERE raw_file_path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_last_updated ON sessions(last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_sessions_repo ON sessions(repo_name);
CREATE INDEX IF NOT EXISTS idx_sessions_org ON sessions(org);
CREATE INDEX IF NOT EXISTS idx_sessions_device_id ON sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_org_id ON sessions(org_id);

CREATE INDEX IF NOT EXISTS idx_messages_session_timestamp ON messages(session_id, timestamp);

INSERT INTO schema_version (version) VALUES (1) ON CONFLICT DO NOTHING;
