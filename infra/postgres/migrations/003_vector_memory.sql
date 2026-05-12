CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE incident_memories
  ADD COLUMN IF NOT EXISTS embedding vector(1536);
