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

CREATE TABLE IF NOT EXISTS applications (
  app_id TEXT PRIMARY KEY,
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  environment TEXT NOT NULL,
  manifest JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE INDEX IF NOT EXISTS idx_applications_sandbox
  ON applications (sandbox_id, status);

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
  '{"app_id": "breakable-target", "public_url": "http://localhost:8001", "adapter_url": "http://target-adapter:8010"}'::jsonb
)
ON CONFLICT (sandbox_id, service_name) DO UPDATE
SET base_url = EXCLUDED.base_url,
    health_url = EXCLUDED.health_url,
    metadata = EXCLUDED.metadata;

INSERT INTO applications (app_id, sandbox_id, display_name, environment, manifest, status)
VALUES (
  'breakable-target',
  'local-docker',
  'Breakable Target API',
  'local',
  '{
    "app_id": "breakable-target",
    "display_name": "Breakable Target API",
    "environment": "local",
    "sandbox_id": "local-docker",
    "dependencies": ["postgres", "checkout-provider"],
    "services": [{
      "name": "target-api",
      "service_type": "fastapi",
      "base_url": "http://target-api:8001",
      "health_url": "http://target-api:8001/health",
      "public_url": "http://localhost:8001",
      "adapter_url": "http://target-adapter:8010",
      "metadata": {"role": "reference-app"}
    }],
    "health_checks": [{"name": "health", "service": "target-api", "path": "/health", "healthy_status": "healthy"}],
    "critical_probes": [
      {"name": "metadata", "service": "target-api", "method": "GET", "path": "/metadata"},
      {"name": "items", "service": "target-api", "method": "GET", "path": "/items"},
      {"name": "checkout", "service": "target-api", "method": "GET", "path": "/checkout"}
    ],
    "safe_actions": [
      {"action_type": "SET_ENV_VAR", "service": "target-api", "description": "Restore a known-good runtime configuration value.", "required_params": ["service", "key", "value_from"], "parameter_allowlists": {"key": ["DATABASE_URL", "TARGET_REQUIRED_SECRET"]}, "adapter_path": "/adapter/actions/SET_ENV_VAR", "max_autonomous_risk": 0.35, "blast_radius": "low", "rollback_available": true, "approval_required": false, "clears_scenarios": ["bad_database_url", "missing_required_env"]},
      {"action_type": "RESTART_SERVICE", "service": "target-api", "description": "Request a bounded service restart.", "required_params": ["service"], "parameter_allowlists": {}, "adapter_path": "/adapter/actions/RESTART_SERVICE", "max_autonomous_risk": 0.35, "blast_radius": "low", "rollback_available": true, "approval_required": false, "clears_scenarios": ["port_conflict"]},
      {"action_type": "DISABLE_FEATURE_FLAG", "service": "target-api", "description": "Disable an allowlisted feature flag.", "required_params": ["service", "flag"], "parameter_allowlists": {"flag": ["FEATURE_CHECKOUT_ENABLED"]}, "adapter_path": "/adapter/actions/DISABLE_FEATURE_FLAG", "max_autonomous_risk": 0.35, "blast_radius": "low", "rollback_available": true, "approval_required": false, "clears_scenarios": ["bad_feature_flag", "rate_limit"]},
      {"action_type": "SWITCH_DEPENDENCY_TO_MOCK", "service": "target-api", "description": "Route a dependency to an allowlisted fallback.", "required_params": ["service", "dependency"], "parameter_allowlists": {"dependency": ["checkout-provider"]}, "adapter_path": "/adapter/actions/SWITCH_DEPENDENCY_TO_MOCK", "max_autonomous_risk": 0.35, "blast_radius": "low", "rollback_available": true, "approval_required": false, "clears_scenarios": ["dependency_unavailable", "rate_limit"]},
      {"action_type": "ROLLBACK_CONFIG", "service": "target-api", "description": "Return runtime configuration to a previous known-good version.", "required_params": ["service", "target"], "parameter_allowlists": {"target": ["previous_known_good_app_version"]}, "adapter_path": "/adapter/actions/ROLLBACK_CONFIG", "max_autonomous_risk": 0.0, "blast_radius": "medium", "rollback_available": true, "approval_required": true, "clears_scenarios": ["schema_mismatch"]}
    ],
    "repair_policy": {
      "approved_paths": ["target-app/api/tests", "target-app/api/main.py", "target-app/api/requirements.txt"],
      "path_owners": {"target-app/api/main.py": "target-api", "target-app/api/tests/": "target-api-tests", "target-app/api/requirements.txt": "target-api"},
      "test_commands": [["python", "-m", "unittest", "discover", "target-app/api/tests"]],
      "build_commands": [],
      "rollback_strategy": "Apply generated rollback operations."
    },
    "repo": {"root": "/workspace", "kind": "local"},
    "verification": {"commands": [["python", "-m", "unittest", "discover", "target-app/api/tests"]], "sandbox_replay": {"scenario": "bad_database_url"}},
    "canary": {"environment": "local-docker-canary", "traffic_percentage": 10.0, "probes": [
      {"name": "health", "service": "target-api", "method": "GET", "path": "/health", "healthy_status": "healthy"},
      {"name": "metadata", "service": "target-api", "method": "GET", "path": "/metadata"},
      {"name": "items", "service": "target-api", "method": "GET", "path": "/items"},
      {"name": "checkout", "service": "target-api", "method": "GET", "path": "/checkout"}
    ]}
  }'::jsonb,
  'active'
)
ON CONFLICT (app_id) DO UPDATE
SET sandbox_id = EXCLUDED.sandbox_id,
    display_name = EXCLUDED.display_name,
    environment = EXCLUDED.environment,
    manifest = EXCLUDED.manifest,
    status = EXCLUDED.status,
    updated_at = now();
