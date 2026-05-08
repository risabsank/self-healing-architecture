CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidents_detected_at
  ON incidents (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_remediation_actions_incident_status
  ON remediation_actions (incident_id, status);

CREATE INDEX IF NOT EXISTS idx_verification_runs_repair_status
  ON verification_runs (repair_change_id, status);
