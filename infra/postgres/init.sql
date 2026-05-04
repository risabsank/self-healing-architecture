CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

CREATE TABLE IF NOT EXISTS health_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  service_name TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS incident_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
  summary TEXT NOT NULL,
  root_cause TEXT,
  successful_action JSONB,
  failed_actions JSONB,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_health_checks_sandbox_checked_at
  ON health_checks (sandbox_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_sandbox_status
  ON incidents (sandbox_id, status);

CREATE INDEX IF NOT EXISTS idx_incident_events_incident_ts
  ON incident_events (incident_id, ts);

INSERT INTO sandboxes (id, name, runtime, status, metadata)
VALUES (
  'local-docker',
  'Local Docker Sandbox',
  'docker-compose',
  'active',
  '{"description": "Phase 1 local sandbox running the intentionally breakable target API."}'::jsonb
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
