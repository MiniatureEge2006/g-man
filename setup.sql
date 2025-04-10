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