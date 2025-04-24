CREATE TABLE IF NOT EXISTS global_blocked_servers (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT UNIQUE NOT NULL,
    reason TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS global_blocked_users (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT UNIQUE NOT NULL,
    reason TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS allowlist (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('user', 'channel', 'role')),
    entity_id BIGINT UNIQUE NOT NULL,
    reason TEXT,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, entity_id)
);


CREATE TABLE IF NOT EXISTS blocklist (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('user', 'channel', 'role')),
    entity_id BIGINT UNIQUE NOT NULL,
    reason TEXT,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, entity_id)
);


CREATE TABLE IF NOT EXISTS command_permissions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    command_name TEXT NOT NULL,
    target_type TEXT CHECK (target_type IN ('user', 'channel', 'role')) NOT NULL,
    target_id BIGINT NOT NULL,
    status BOOLEAN NOT NULL,
    reason TEXT DEFAULT 'No reason provided',
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, command_name, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS server_command_permissions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    command_name TEXT NOT NULL,
    status BOOLEAN NOT NULL,
    reason TEXT DEFAULT 'No reason provided',
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, command_name)
);


CREATE TABLE IF NOT EXISTS guild_prefixes (
    guild_id BIGINT PRIMARY KEY,
    prefixes TEXT[] NOT NULL
);

CREATE TABLE IF NOT EXISTS user_prefixes (
    user_id BIGINT PRIMARY KEY,
    prefixes TEXT[] NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    guild_id BIGINT,
    channel_id BIGINT,
    reminder_id INTEGER,
    reminder TEXT NOT NULL,
    reminder_time TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS system_prompts (
    user_id BIGINT PRIMARY KEY,
    prompt TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    guild_id BIGINT,
    user_id BIGINT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    uses INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX idx_tags_primary ON tags (
    COALESCE(guild_id, -1),
    COALESCE(user_id, -1),
    name
);

ALTER TABLE tags ADD CONSTRAINT valid_tag_scope CHECK (
    (guild_id IS NOT NULL AND user_id IS NULL)
    OR
    (user_id IS NOT NULL AND guild_id IS NULL)
);

ALTER TABLE tags ADD CONSTRAINT name_lowercase CHECK (name = lower(name));

CREATE INDEX idx_tags_guild ON tags (guild_id) WHERE guild_id IS NOT NULL;
CREATE INDEX idx_tags_user ON tags (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_tags_author ON tags (author_id);
CREATE INDEX idx_tags_name ON tags (name);