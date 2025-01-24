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
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, entity_id)
);


CREATE TABLE IF NOT EXISTS blocklist (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('user', 'channel', 'role')),
    entity_id BIGINT UNIQUE NOT NULL,
    reason TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, entity_id)
);
