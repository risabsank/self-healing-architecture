CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sandboxes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  runtime TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sandbox_services (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  service_name TEXT NOT NULL,
  service_type TEXT NOT NULL,
  base_url TEXT,
  health_url TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (sandbox_id, service_name)
);

CREATE TABLE IF NOT EXISTS sandbox_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE,
  snapshot_name TEXT NOT NULL,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  service_name TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE,
  service_name TEXT,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  title TEXT,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  root_cause TEXT,
  final_summary TEXT
);

CREATE TABLE IF NOT EXISTS incident_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
  sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS evidence_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  content JSONB NOT NULL,
  confidence FLOAT
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
  cause TEXT NOT NULL,
  evidence_ids UUID[],
  confidence FLOAT NOT NULL,
  rationale_summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remediation_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
  action_type TEXT NOT NULL,
  params JSONB NOT NULL,
  risk_score FLOAT NOT NULL,
  requires_approval BOOLEAN NOT NULL,
  status TEXT NOT NULL,
  result JSONB
);

CREATE TABLE IF NOT EXISTS repair_changes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  change_type TEXT NOT NULL,
  branch_name TEXT,
  commit_sha TEXT,
  affected_paths TEXT[] NOT NULL DEFAULT '{}',
  patch_summary TEXT NOT NULL,
  risk_score FLOAT NOT NULL,
  requires_approval BOOLEAN NOT NULL,
  verification_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
  rollback_plan TEXT NOT NULL,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verification_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repair_change_id UUID REFERENCES repair_changes(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  runner TEXT NOT NULL,
  checks JSONB NOT NULL DEFAULT '[]'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  logs_ref TEXT
);

CREATE TABLE IF NOT EXISTS canary_rollouts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repair_change_id UUID REFERENCES repair_changes(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  target_environment TEXT NOT NULL,
  traffic_percentage FLOAT NOT NULL,
  health_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  decision TEXT
);

CREATE TABLE IF NOT EXISTS incident_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
  summary TEXT NOT NULL,
  symptoms JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  root_cause TEXT,
  successful_action JSONB,
  failed_actions JSONB,
  verification_result JSONB,
  repair_change JSONB,
  rollout_result JSONB,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL,
  scenario_filter JSONB NOT NULL DEFAULT '[]'::jsonb,
  repeats INTEGER NOT NULL,
  aggregate_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID REFERENCES evaluation_runs(id) ON DELETE CASCADE,
  scenario_name TEXT NOT NULL,
  iteration INTEGER NOT NULL,
  status TEXT NOT NULL,
  incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
  expected_root_cause TEXT NOT NULL,
  diagnosed_root_cause TEXT,
  selected_action TEXT,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

ALTER TABLE incident_memories
  ADD COLUMN IF NOT EXISTS symptoms JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS verification_result JSONB,
  ADD COLUMN IF NOT EXISTS repair_change JSONB,
  ADD COLUMN IF NOT EXISTS rollout_result JSONB,
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_memories_incident_id
  ON incident_memories (incident_id)
  WHERE incident_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_health_checks_sandbox_checked_at
  ON health_checks (sandbox_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_sandbox_snapshots_sandbox_created
  ON sandbox_snapshots (sandbox_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_events_sandbox_ts
  ON runtime_events (sandbox_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_sandbox_status
  ON incidents (sandbox_id, status);

CREATE INDEX IF NOT EXISTS idx_incidents_detected_at
  ON incidents (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_events_incident_ts
  ON incident_events (incident_id, ts);

CREATE INDEX IF NOT EXISTS idx_remediation_actions_incident_status
  ON remediation_actions (incident_id, status);

CREATE INDEX IF NOT EXISTS idx_repair_changes_incident_status
  ON repair_changes (incident_id, status);

CREATE INDEX IF NOT EXISTS idx_verification_runs_repair_status
  ON verification_runs (repair_change_id, status);

CREATE INDEX IF NOT EXISTS idx_canary_rollouts_repair_status
  ON canary_rollouts (repair_change_id, status);

CREATE INDEX IF NOT EXISTS idx_evaluation_cases_run_iteration
  ON evaluation_cases (run_id, iteration, scenario_name);

INSERT INTO sandboxes (id, name, runtime, status, metadata)
VALUES (
  'local-docker',
  'Local Docker Sandbox',
  'docker-compose',
  'active',
  '{"description": "Local sandbox running the intentionally breakable target API."}'::jsonb
)
ON CONFLICT (id) DO UPDATE
SET updated_at = now(),
    status = EXCLUDED.status,
    metadata = EXCLUDED.metadata;

INSERT INTO sandbox_services (sandbox_id, service_name, service_type, base_url, health_url, metadata)
VALUES (
  'local-docker',
  'target-api',
  'fastapi',
  'http://target-api:8001',
  'http://target-api:8001/health',
  '{"public_url": "http://localhost:8001"}'::jsonb
)
ON CONFLICT (sandbox_id, service_name) DO UPDATE
SET base_url = EXCLUDED.base_url,
    health_url = EXCLUDED.health_url,
    metadata = EXCLUDED.metadata;
