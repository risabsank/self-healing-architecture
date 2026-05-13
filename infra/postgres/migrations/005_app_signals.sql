CREATE TABLE IF NOT EXISTS app_metric_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  unit TEXT,
  source TEXT NOT NULL,
  labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_slo_evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
  slo_name TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  status TEXT NOT NULL,
  target DOUBLE PRECISION NOT NULL,
  observed_value DOUBLE PRECISION NOT NULL,
  comparator TEXT NOT NULL,
  slo_window TEXT NOT NULL,
  observation_id UUID REFERENCES app_metric_observations(id) ON DELETE SET NULL,
  incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_operator_notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
  sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
  service_name TEXT,
  severity TEXT NOT NULL,
  note TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  metric_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_metrics_app_observed
  ON app_metric_observations (app_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_slo_app_evaluated
  ON app_slo_evaluations (app_id, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_notes_app_created
  ON app_operator_notes (app_id, created_at DESC);
