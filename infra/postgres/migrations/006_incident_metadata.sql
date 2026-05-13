ALTER TABLE incidents
  ADD COLUMN IF NOT EXISTS app_id TEXT,
  ADD COLUMN IF NOT EXISTS service_name TEXT,
  ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS trigger_source TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_incidents_app_open
  ON incidents (app_id, service_name, status, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_trigger_source
  ON incidents (trigger_source, detected_at DESC);
