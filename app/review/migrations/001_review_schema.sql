CREATE TABLE IF NOT EXISTS suppliers (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    ice TEXT,
    address TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS countries (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS document_reviews (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    raw_extracted_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    user_corrected_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'in_review',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_assets (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    stored_file_name TEXT NOT NULL,
    mime_type VARCHAR(128),
    source VARCHAR(32) NOT NULL DEFAULT 'heuristic',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suppliers_aliases_gin ON suppliers USING GIN (aliases);
CREATE INDEX IF NOT EXISTS idx_cities_aliases_gin ON cities USING GIN (aliases);
CREATE INDEX IF NOT EXISTS idx_countries_aliases_gin ON countries USING GIN (aliases);
