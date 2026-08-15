-- Retrieval corpus: data-dictionary chunks and exemplar SQL, embedded for vector search and
-- indexed for keyword search. Owned by askindia_app; readable by askindia_ro via default privileges.
CREATE TABLE IF NOT EXISTS rag.chunks (
    id           bigserial PRIMARY KEY,
    dataset      text        NOT NULL,
    kind         text        NOT NULL CHECK (kind IN ('table', 'column', 'exemplar', 'caveat')),
    title        text        NOT NULL,
    content      text        NOT NULL,
    metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    embedding    public.vector(384) NOT NULL,
    tsv          tsvector    GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED,
    content_sha  text        NOT NULL,
    indexed_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset, content_sha)
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON rag.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON rag.chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_dataset_idx ON rag.chunks (dataset);
