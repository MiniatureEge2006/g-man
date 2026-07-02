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

CREATE TABLE IF NOT EXISTS channel_prompts (
    channel_id BIGINT PRIMARY KEY,
    prompt TEXT
);

CREATE TABLE IF NOT EXISTS guild_prompts (
    guild_id BIGINT PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS chat_filters (
    id SERIAL PRIMARY KEY,
    filter_id INTEGER,
    guild_id BIGINT NOT NULL,
    filter_type TEXT NOT NULL CHECK (filter_type IN ('regex', 'word', 'link')),
    pattern TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('warn', 'delete', 'mute', 'kick', 'softban', 'ban')),
    target_type TEXT NOT NULL CHECK (target_type IN ('server', 'channel', 'user', 'role')),
    target_id BIGINT,
    custom_message TEXT,
    timeout_minutes INTEGER DEFAULT 60,
    delete_seconds INTEGER,
    delete_after INTEGER DEFAULT 10,
    added_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, filter_id),
    UNIQUE (guild_id, filter_type, pattern, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS chat_reactions (
    id SERIAL PRIMARY KEY,
    reaction_id INTEGER,
    guild_id BIGINT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('regex', 'word', 'link')),
    pattern TEXT NOT NULL,
    emoji TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('server', 'channel', 'user', 'role')),
    target_id BIGINT,
    added_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, reaction_id),
    UNIQUE (guild_id, trigger_type, pattern, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS chat_replies (
    id SERIAL PRIMARY KEY,
    reply_id INTEGER,
    guild_id BIGINT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('regex', 'word', 'link')),
    pattern TEXT NOT NULL,
    response_message TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('server', 'channel', 'user', 'role')),
    target_id BIGINT,
    delete_after INTEGER DEFAULT 10,
    added_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, reply_id),
    UNIQUE (guild_id, trigger_type, pattern, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS manual_slowmodes (
    id SERIAL PRIMARY KEY,
    slowmode_id INTEGER,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT,
    user_id BIGINT,
    role_id BIGINT,
    delay_seconds INTEGER NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    custom_message TEXT,
    UNIQUE (guild_id, slowmode_id),
    CONSTRAINT uq_manual_slowmode_target
        UNIQUE (guild_id, channel_id, user_id, role_id),
    CONSTRAINT valid_target CHECK (
        (channel_id IS NOT NULL AND user_id IS NULL AND role_id IS NULL) OR
        (user_id IS NOT NULL AND channel_id IS NULL AND role_id IS NULL) OR
        (role_id IS NOT NULL AND channel_id IS NULL AND user_id IS NULL) OR
        (channel_id IS NULL AND user_id IS NULL AND role_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_manual_slowmodes_guild_enabled
ON manual_slowmodes (guild_id) WHERE enabled;
CREATE INDEX IF NOT EXISTS idx_manual_slowmodes_channel_enabled
ON manual_slowmodes (guild_id, channel_id) WHERE enabled AND channel_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_manual_slowmodes_user_enabled
ON manual_slowmodes (guild_id, user_id) WHERE enabled AND user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_manual_slowmodes_role_enabled
ON manual_slowmodes (guild_id, role_id) WHERE enabled AND role_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS logging_rules (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    log_channel_id BIGINT NOT NULL,
    event_category TEXT NOT NULL CHECK (event_category IN ('message', 'user', 'member', 'role', 'channel', 'guild', 'voice', 'moderation')),
    include_channel_ids BIGINT[],
    exclude_channel_ids BIGINT[],
    added_by BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    template TEXT,
    UNIQUE(guild_id, log_channel_id, event_category)
);

CREATE TABLE IF NOT EXISTS guild_music_settings (
    guild_id BIGINT PRIMARY KEY,
    volume REAL DEFAULT 0.25,
    loop_mode TEXT DEFAULT 'off' CHECK (loop_mode IN ('off', 'track', 'queue')),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS music_playlists (
    id SERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(owner_id, name)
);

CREATE TABLE IF NOT EXISTS music_playlist_entries (
    playlist_id INT REFERENCES music_playlists(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    position INT NOT NULL,
    duration INT DEFAULT 0,
    PRIMARY KEY (playlist_id, position)
);

CREATE TABLE IF NOT EXISTS music_play_logs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    user_id BIGINT,
    track_url TEXT,
    track_title TEXT,
    duration_sec INT,
    played_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_music_logs_user ON music_play_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_music_logs_guild ON music_play_logs(guild_id);
CREATE INDEX IF NOT EXISTS idx_music_playlists_owner ON music_playlists(owner_id);
CREATE INDEX IF NOT EXISTS idx_music_playlist_entries ON music_playlist_entries(playlist_id);

CREATE TABLE IF NOT EXISTS tts_bindings (
    guild_id BIGINT NOT NULL,
    text_channel_id BIGINT PRIMARY KEY,
    filters TEXT,
    language TEXT
);

CREATE TABLE IF NOT EXISTS tts_configs (
    entity_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'channel', 'guild')),
    language TEXT,
    filters TEXT,
    PRIMARY KEY (entity_id, guild_id)
);
