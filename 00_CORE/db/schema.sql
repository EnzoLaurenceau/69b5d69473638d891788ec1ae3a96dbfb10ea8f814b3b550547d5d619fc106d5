-- Super Agent Forge — Schéma PostgreSQL unifié (optiforge)
-- Appliqué automatiquement par docker-compose à l'init, et idempotent
-- (forge_db._ensure_schema() le rejoue aussi au démarrage).

CREATE EXTENSION IF NOT EXISTS vector;

-- Findings : unité atomique de connaissance (miroir de Finding/ForgeState)
CREATE TABLE IF NOT EXISTS findings (
    id        TEXT PRIMARY KEY,
    agent     TEXT,
    cycle     INT,
    content   TEXT,
    score     REAL,
    status    TEXT,            -- pending | confirmed | killed
    ts        DOUBLE PRECISION,
    embedding vector(64)       -- SimHash léger (forge_db.light_embedding)
);
CREATE INDEX IF NOT EXISTS findings_status_idx ON findings(status);

-- Episodes : timeline (logs Cervelet, événements). salience pour la consolidation.
-- dedup = clé déterministe (md5 signal|res|ts) → migration idempotente, runtime append-only.
CREATE TABLE IF NOT EXISTS episodes (
    id       BIGSERIAL PRIMARY KEY,
    signal   TEXT,
    res      TEXT,
    meta     JSONB,
    salience REAL DEFAULT 0,
    ts       DOUBLE PRECISION,
    dedup    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS episodes_dedup_idx ON episodes(dedup);

-- Checkpoints LangGraph (blob d'état par thread/session)
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id TEXT PRIMARY KEY,
    blob      JSONB,
    ts        DOUBLE PRECISION
);

-- Graphify : nœuds de connaissance (remplace graph.json)
CREATE TABLE IF NOT EXISTS graphify_nodes (
    id        TEXT PRIMARY KEY,
    agent     TEXT,
    cycle     INT,
    content   TEXT,
    ts        DOUBLE PRECISION,
    embedding vector(64)
);

-- RAG : documents ingérés par rag_anything (métadonnées + vecteur de recherche).
-- id = doc_id (rempli automatiquement par forge_db._pg_upsert si absent).
CREATE TABLE IF NOT EXISTS rag_docs (
    id         TEXT PRIMARY KEY,
    doc_id     TEXT,
    file_path  TEXT,
    file_name  TEXT,
    doc_hash   TEXT,
    content    TEXT,
    size_bytes BIGINT,
    agent      TEXT,
    ts         DOUBLE PRECISION,
    embedding  vector(64)
);
CREATE INDEX IF NOT EXISTS rag_docs_doc_id_idx ON rag_docs(doc_id);

-- GitNexus : miroir des symboles de code (index consolidé)
CREATE TABLE IF NOT EXISTS gitnexus_symbols (
    id      TEXT PRIMARY KEY,
    name    TEXT,
    kind    TEXT,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS gitnexus_name_idx ON gitnexus_symbols(name);
