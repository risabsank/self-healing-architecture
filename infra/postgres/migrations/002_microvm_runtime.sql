CREATE TABLE IF NOT EXISTS sandbox_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE,
  snapshot_name TEXT NOT NULL,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sandbox_snapshots_sandbox_created
  ON sandbox_snapshots (sandbox_id, created_at DESC);
