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
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    uses INTEGER DEFAULT 0,
    CONSTRAINT valid_tag_scope CHECK (
        (guild_id IS NOT NULL AND user_id IS NULL) OR
        (user_id IS NOT NULL AND guild_id IS NULL)
    ),
    CONSTRAINT name_lowercase CHECK (name = lower(name)),
    CONSTRAINT unique_tag UNIQUE (name, guild_id, user_id)
);


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unique_tag' AND conrelid = 'tags'::regclass
    ) THEN
        BEGIN
            ALTER TABLE tags ADD CONSTRAINT unique_tag UNIQUE (name, guild_id, user_id);
        EXCEPTION WHEN duplicate_object THEN
        END;
    END IF;
END $$;


CREATE TABLE IF NOT EXISTS tag_aliases (
    id SERIAL PRIMARY KEY,
    alias TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    guild_id BIGINT,
    user_id BIGINT,
    CONSTRAINT alias_lowercase CHECK (alias = lower(alias)),
    CONSTRAINT valid_alias_scope CHECK (
        (guild_id IS NOT NULL AND user_id IS NULL) OR
        (user_id IS NOT NULL AND guild_id IS NULL)
    ),
    FOREIGN KEY (tag_name, guild_id, user_id)
        REFERENCES tags(name, guild_id, user_id)
        ON DELETE CASCADE
);


CREATE UNIQUE INDEX IF NOT EXISTS tag_aliases_guild_unique 
    ON tag_aliases (alias, guild_id) WHERE guild_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS tag_aliases_user_unique 
    ON tag_aliases (alias, user_id) WHERE user_id IS NOT NULL;



CREATE INDEX IF NOT EXISTS idx_tags_guild ON tags (guild_id) WHERE guild_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tags_user ON tags (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tags_author ON tags (author_id);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags (name);
CREATE INDEX IF NOT EXISTS idx_tag_aliases_guild ON tag_aliases (guild_id) WHERE guild_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tag_aliases_user ON tag_aliases (user_id) WHERE user_id IS NOT NULL;


CREATE TABLE IF NOT EXISTS ai_conversations (
    conversation_key TEXT PRIMARY KEY,
    history JSONB NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS command_usage (
    id SERIAL PRIMARY KEY,
    command_name TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    guild_id BIGINT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    content TEXT
);