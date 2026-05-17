-- Enable pgvector for issue-embedding similarity search (used by ingest dedup).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
