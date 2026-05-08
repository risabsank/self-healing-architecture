const SANDBOX_ID = "local-docker";
const DEFAULT_API = "http://localhost:8000";

const state = {
  apiBase: localStorage.getItem("controlApiBaseUrl") || DEFAULT_API,
  selectedIncidentId: null,
  data: {}
};

const $ = (id) => document.getElementById(id);
const dom = Object.fromEntries([
  "api-base",
  "save-api",
  "refresh",
  "run-health",
  "reset-scenarios",
  "analyze-incident",
  "execute-selected",
  "run-evaluation",
  "plan-repair",
  "error-banner",
  "status-strip",
  "sandbox-health",
  "scenario-list",
  "incident-list",
  "evaluation-list",
  "incident-header",
  "timeline",
  "evidence-list",
  "hypothesis-list",
  "action-list",
  "repair-list",
  "ci-list",
  "canary-list",
  "autonomy-list",
  "verification-list",
  "memory-list"
].map((id) => [camel(id), $(id)]));

// The dashboard never performs runtime work directly; every operator action
// goes through a bounded Control API endpoint.
const BUTTON_ACTIONS = {
  "save-api": () => saveApiBase(),
  refresh: () => refresh(),
  "run-health": () => mutate(`/sandboxes/${SANDBOX_ID}/health-check`),
  "reset-scenarios": () => mutate(`/sandboxes/${SANDBOX_ID}/scenarios/reset`),
  "run-evaluation": () => mutate("/evaluations/run", { scenarios: ["bad_database_url"], repeats: 1 }),
  "analyze-incident": () => selected((id) => mutate(`/incidents/${id}/analyze`)),
  "execute-selected": () => selected((id) => mutate(`/incidents/${id}/actions/execute-selected`)),
  "plan-repair": () => selected((id) => mutate(`/incidents/${id}/repairs/plan`))
};

const DATASET_ACTIONS = {
  actionExecute: (id) => mutate(`/actions/${id}/execute`),
  actionApprove: (id) => mutate(`/actions/${id}/approve`),
  actionReject: (id) => mutate(`/actions/${id}/reject`),
  repairApprove: (id) => mutate(`/repairs/${id}/approve`),
  repairReject: (id) => mutate(`/repairs/${id}/reject`),
  repairApply: (id) => mutate(`/repairs/${id}/apply`),
  repairVerify: (id) => mutate(`/repairs/${id}/verify`),
  repairCanary: (id) => mutate(`/repairs/${id}/canary-rollouts/start`),
  rolloutPromote: (id) => mutate(`/canary-rollouts/${id}/promote`),
  rolloutRollback: (id) => mutate(`/canary-rollouts/${id}/rollback`),
  rolloutQuarantine: (id) => mutate(`/canary-rollouts/${id}/quarantine`)
};

dom.apiBase.value = state.apiBase;
document.addEventListener("click", handleClick);
refresh();
setInterval(refresh, 10000);

async function handleClick(event) {
  const button = event.target.closest("button");
  if (!button) return;

  const id = button.id;
  const data = button.dataset;
  if (BUTTON_ACTIONS[id]) return BUTTON_ACTIONS[id]();
  if (data.incident) return selectAndRefresh(data.incident);
  if (data.scenario) return mutate(`/sandboxes/${SANDBOX_ID}/scenarios/${data.scenario}/${data.next}`);

  for (const [key, action] of Object.entries(DATASET_ACTIONS)) {
    if (data[key]) return action(data[key]);
  }
}

function saveApiBase() {
  state.apiBase = dom.apiBase.value.replace(/\/$/, "") || DEFAULT_API;
  localStorage.setItem("controlApiBaseUrl", state.apiBase);
  refresh();
}

async function selectAndRefresh(incidentId) {
  state.selectedIncidentId = incidentId;
  await refresh();
}

function selected(callback) {
  return state.selectedIncidentId ? callback(state.selectedIncidentId) : undefined;
}

async function mutate(path, body = null) {
  setBusy(true);
  try {
    await api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    await refresh();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function refresh() {
  setBusy(true);
  hideError();
  try {
    await loadOverview();
    chooseIncident();
    if (state.selectedIncidentId) await loadIncident(state.selectedIncidentId);
    render();
  } catch (error) {
    showError(error);
    render();
  } finally {
    setBusy(false);
  }
}

async function loadOverview() {
  const [control, sandbox, scenarios, incidents, memories, evaluations] = await Promise.all([
    api("/health"),
    api(`/sandboxes/${SANDBOX_ID}`),
    api(`/sandboxes/${SANDBOX_ID}/scenarios`),
    api("/incidents"),
    api("/memory/incidents?limit=6"),
    api("/evaluations")
  ]);

  state.data = {
    control,
    sandbox,
    scenarios: normalizeScenarios(scenarios),
    incidents: incidents.incidents || [],
    memories: memories.memories || [],
    evaluations: evaluations.runs || []
  };
}

async function loadIncident(incidentId) {
  const [incident, timeline, evidence, hypotheses, actions, repairs] = await Promise.all([
    api(`/incidents/${incidentId}`),
    api(`/incidents/${incidentId}/timeline`),
    api(`/incidents/${incidentId}/evidence`),
    api(`/incidents/${incidentId}/hypotheses`),
    api(`/incidents/${incidentId}/actions`),
    api(`/incidents/${incidentId}/repairs`)
  ]);

  const repairsList = repairs.repairs || [];
  const query = encodeURIComponent([incident.root_cause, incident.title].filter(Boolean).join(" "));
  const [matches, repairLifecycle] = await Promise.all([
    query ? api(`/memory/search?query=${query}&limit=5`) : { memories: [] },
    loadRepairLifecycle(repairsList)
  ]);

  Object.assign(state.data, {
    incident,
    timeline: timeline.events || [],
    evidence: evidence.evidence || [],
    hypotheses: hypotheses.hypotheses || [],
    actions: actions.actions || [],
    repairs: repairsList,
    repairLifecycle,
    memoryMatches: matches.memories || []
  });
}

async function loadRepairLifecycle(repairs) {
  const entries = await Promise.all(repairs.slice(0, 6).map(async (repair) => {
    // Older or partially initialized backends may not have lifecycle records yet.
    const [verification, canary] = await Promise.all([
      api(`/repairs/${repair.id}/verification-runs`).catch(() => ({ verification_runs: [] })),
      api(`/repairs/${repair.id}/canary-rollouts`).catch(() => ({ canary_rollouts: [] }))
    ]);
    return [repair.id, {
      verificationRuns: verification.verification_runs || [],
      canaryRollouts: canary.canary_rollouts || []
    }];
  }));
  return Object.fromEntries(entries);
}

async function api(path, options = {}) {
  const response = await fetch(`${state.apiBase}${path}`, {
    headers: { "content-type": "application/json" },
    ...options
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

function chooseIncident() {
  const incidents = state.data.incidents || [];
  if (incidents.some((incident) => incident.id === state.selectedIncidentId)) return;
  state.selectedIncidentId = (incidents.find(isActiveIncident) || incidents[0] || {}).id || null;
}

function render() {
  renderStatus();
  renderSandbox();
  renderScenarios();
  renderIncidents();
  renderEvaluations();
  renderIncidentHeader();
  renderTimeline();
  renderCollection("evidenceList", state.data.evidence, renderEvidence, "No evidence captured");
  renderCollection("hypothesisList", state.data.hypotheses, renderHypothesis, "No hypotheses generated");
  renderCollection("actionList", state.data.actions, renderAction, "No remediation candidates");
  renderCollection("repairList", state.data.repairs, renderRepair, "No durable repair plans");
  renderCollection("ciList", ciChecks(), renderCiRun, "No CI verification runs");
  renderCollection("canaryList", canaryRollouts(), renderCanary, "No canary rollouts");
  renderCollection("autonomyList", autonomyDecisions(), renderAutonomy, "No autonomy decisions recorded");
  renderCollection("verificationList", verificationChecks(), renderCheck, "No verification results yet");
  renderCollection("memoryList", memoryMatches(), renderMemory, "No memories stored");
}

function renderStatus() {
  const health = first(state.data.sandbox?.latest_health);
  const incidents = state.data.incidents || [];
  const metrics = [
    ["Control API", state.data.control?.status || "unknown", state.apiBase],
    ["Target Health", health?.status || "unknown", health?.service_name || SANDBOX_ID],
    ["Active Incidents", incidents.filter(isActiveIncident).length, `${incidents.length} total`],
    ["Memory Records", state.data.memories?.length || 0, "retrievable incidents"],
    ["Last Refresh", new Date().toLocaleTimeString(), "local operator time"]
  ];
  dom.statusStrip.innerHTML = metrics.map(([label, value, help]) => `
    <div class="metric"><span>${safe(label)}</span><strong>${safe(value)}</strong><span>${safe(help)}</span></div>
  `).join("");
}

function renderSandbox() {
  const sandbox = state.data.sandbox;
  if (!sandbox) return setHtml("sandboxHealth", empty("No sandbox data"));

  const latest = new Map((sandbox.latest_health || []).map((check) => [check.service_name, check]));
  const services = (sandbox.services || []).map((service) => {
    const health = latest.get(service.service_name);
    return card(`
      <div class="row"><strong>${safe(service.service_name)}</strong>${pill(health?.status)}</div>
      <p class="muted">${safe(service.base_url || service.health_url || service.service_type)}</p>
    `);
  });

  setHtml("sandboxHealth", [
    card(`
      <div class="row"><strong>${safe(sandbox.sandbox?.name || SANDBOX_ID)}</strong>${pill(sandbox.sandbox?.status)}</div>
      <p class="muted">${safe(sandbox.runtime?.runtime || sandbox.sandbox?.runtime || "runtime unknown")}</p>
    `),
    ...services
  ].join(""));
}

function renderScenarios() {
  renderCollection("scenarioList", state.data.scenarios, (scenario) => {
    const next = scenario.active ? "deactivate" : "activate";
    return `
      <div class="scenario">
        <div>
          <strong>${safe(labelize(scenario.name))}</strong>
          <p class="muted">${safe(scenario.description || scenario.name)}</p>
        </div>
        <button type="button" data-scenario="${safe(scenario.name)}" data-next="${next}">
          ${scenario.active ? "Deactivate" : "Activate"}
        </button>
      </div>
    `;
  }, "No scenarios returned");
}

function renderIncidents() {
  renderCollection("incidentList", state.data.incidents, (incident) => `
    <button class="incident-button ${incident.id === state.selectedIncidentId ? "active" : ""}" type="button" data-incident="${incident.id}">
      <div class="row"><strong>${safe(incident.title || "Incident")}</strong>${pill(incident.status)}</div>
      <p class="muted">${date(incident.detected_at)} · ${safe(incident.root_cause || "root cause pending")}</p>
    </button>
  `, "No incidents recorded");
}

function renderEvaluations() {
  renderCollection("evaluationList", state.data.evaluations, (run) => {
    const metrics = run.aggregate_metrics || {};
    return card(`
      <div class="row"><strong>${date(run.started_at)}</strong>${pill(run.status)}</div>
      <p class="muted">${safe((run.scenario_filter || []).join(", ") || "all scenarios")}</p>
      <div class="mini-grid">
        <span>Accuracy <strong>${percent(metrics.diagnosis_accuracy)}</strong></span>
        <span>First action <strong>${percent(metrics.first_action_success_rate)}</strong></span>
        <span>Cases <strong>${safe(metrics.case_count ?? 0)}</strong></span>
      </div>
    `);
  }, "No evaluation runs");
}

function renderIncidentHeader() {
  const incident = state.data.incident;
  dom.executeSelected.disabled = !incident;
  dom.analyzeIncident.disabled = !incident;
  dom.planRepair.disabled = !incident;
  if (!incident) return setHtml("incidentHeader", `<h2>Incident State</h2>${empty("Select or create an incident")}`);

  setHtml("incidentHeader", `
    <div class="row">
      <div>
        <h2>Incident State</h2>
        <h3>${safe(incident.title || "Incident")}</h3>
      </div>
      ${pill(incident.status)}
    </div>
    <p class="muted">${date(incident.detected_at)} · ${safe(incident.root_cause || "root cause pending")}</p>
    ${incident.final_summary ? `<p>${safe(incident.final_summary)}</p>` : ""}
  `);
}

function renderTimeline() {
  renderCollection("timeline", state.data.timeline, (event) => `
    <article class="timeline-event">
      <div class="event-head">
        <span class="event-type">${safe(event.type)}</span>
        <span class="muted">${date(event.ts)}</span>
      </div>
      <span class="muted">${safe(event.actor || "system")}</span>
      ${json(event.payload)}
    </article>
  `, "No timeline events");
}

function renderEvidence(evidence) {
  return card(`
    <div class="row"><strong>${safe(evidence.kind)}</strong>${score(evidence.confidence)}</div>
    <p class="muted">${safe(evidence.source)}</p>
    ${summary(evidence.content)}
  `);
}

function renderHypothesis(hypothesis) {
  return card(`
    <div class="row"><strong>${safe(hypothesis.cause)}</strong>${score(hypothesis.confidence)}</div>
    <p>${safe(hypothesis.rationale_summary || "No rationale summary")}</p>
  `);
}

function renderAction(action) {
  const guardrail = action.requires_approval ? "approval required" : riskLabel(action.risk_score);
  const autonomy = action.result?.execution?.autonomy;
  const controls = [
    actionButton("Execute", "action-execute", action.id),
    action.requires_approval ? actionButton("Approve", "action-approve", action.id) : "",
    action.status === "rejected" ? "" : actionButton("Reject", "action-reject", action.id, "danger")
  ].join("");

  return card(`
    <div class="row"><strong>${safe(labelize(action.action_type))}</strong>${pill(action.status)}</div>
    <p class="muted">Risk ${Number(action.risk_score || 0).toFixed(2)} · ${safe(guardrail)}</p>
    ${autonomy ? `<p class="muted">Policy: ${safe(autonomy.decision)} · ${safe((autonomy.reasons || []).join("; "))}</p>` : ""}
    ${summary(action.params)}
    <div class="action-controls">${controls}</div>
  `);
}

function renderRepair(repair) {
  const plan = repair.result?.plan || {};
  const lifecycle = state.data.repairLifecycle?.[repair.id] || {};
  const controls = [
    repair.requires_approval ? actionButton("Approve", "repair-approve", repair.id) : "",
    actionButton("Apply", "repair-apply", repair.id),
    actionButton("Verify", "repair-verify", repair.id),
    actionButton("Canary", "repair-canary", repair.id),
    actionButton("Reject", "repair-reject", repair.id, "danger")
  ].join("");

  return card(`
    <div class="row"><strong>${safe(repair.patch_summary || plan.patch_summary || repair.change_type)}</strong>${pill(repair.status)}</div>
    <p class="muted">${safe(repair.change_type)} · Risk ${Number(repair.risk_score || 0).toFixed(2)} · ${safe((repair.affected_paths || []).join(", ") || "no paths")}</p>
    ${renderPolicyLine(repair.result?.autonomy)}
    ${summary({ verification_plan: repair.verification_plan, rollback_plan: repair.rollback_plan })}
    <div class="mini-grid">
      <span>CI runs <strong>${safe((lifecycle.verificationRuns || []).length)}</strong></span>
      <span>Canaries <strong>${safe((lifecycle.canaryRollouts || []).length)}</strong></span>
    </div>
    <div class="action-controls">${controls}</div>
  `);
}

function renderCiRun(run) {
  const checks = run.checks || [];
  return card(`
    <div class="row"><strong>${safe(run.runner || "bounded verifier")}</strong>${pill(run.status)}</div>
    <p class="muted">${date(run.started_at)} · ${checks.filter((check) => check.passed).length}/${checks.length} passed</p>
    ${checks.slice(0, 5).map((check) => `<p class="muted">${safe(check.name)}: ${safe(check.status || (check.passed ? "passed" : "failed"))}</p>`).join("")}
  `);
}

function renderCanary(rollout) {
  const signals = rollout.health_signals || {};
  const controls = [
    actionButton("Promote", "rollout-promote", rollout.id),
    actionButton("Quarantine", "rollout-quarantine", rollout.id),
    actionButton("Rollback", "rollout-rollback", rollout.id, "danger")
  ].join("");

  return card(`
    <div class="row"><strong>${safe(rollout.target_environment || "canary")}</strong>${pill(rollout.status)}</div>
    <p class="muted">${safe(rollout.traffic_percentage)}% traffic · decision ${safe(rollout.decision || "pending")}</p>
    ${renderPolicyLine(signals.autonomy)}
    <div class="mini-grid">
      <span>Passed <strong>${safe(signals.passed ?? 0)}</strong></span>
      <span>Failed <strong>${safe(signals.failed ?? 0)}</strong></span>
      <span>Error <strong>${percent(signals.error_rate)}</strong></span>
    </div>
    <div class="action-controls">${controls}</div>
  `);
}

function renderAutonomy(decision) {
  return card(`
    <div class="row"><strong>${safe(decision.source)}</strong>${pill(decision.decision)}</div>
    <p class="muted">Risk ${Number(decision.risk_score || 0).toFixed(2)} · ${safe(decision.blast_radius || "unknown")} blast radius</p>
    <p>${safe((decision.reasons || []).join("; ") || "No reasons recorded")}</p>
    ${(decision.requirements || []).length ? `<p class="muted">Requires ${safe(decision.requirements.join(", "))}</p>` : ""}
  `);
}

function renderCheck(check) {
  return card(`
    <div class="check">
      <strong>${safe(check.name || check.kind || "check")}</strong>
      ${pill(check.status || (check.passed ? "healthy" : "failed"))}
    </div>
    ${summary(check.detail || check)}
  `);
}

function renderMemory(memory) {
  const action = memory.successful_action || {};
  const symptoms = memory.symptoms || [];
  return card(`
    <div class="row">
      <strong>${safe(memory.root_cause || "Stored incident")}</strong>
      ${memory.similarity_score !== undefined ? score(memory.similarity_score) : ""}
    </div>
    <p>${safe(memory.summary || "No summary")}</p>
    ${action.action_type ? `<p class="muted">Useful because ${safe(action.action_type)} previously recovered a similar incident.</p>` : ""}
    ${symptoms.length ? `<p class="muted">${safe(symptoms.slice(0, 2).map((item) => item.summary || item.kind).join(" · "))}</p>` : ""}
    <p class="muted">${date(memory.created_at)}</p>
  `);
}

function normalizeScenarios(payload) {
  if (!payload) return [];
  if (payload.available && typeof payload.available === "object") {
    const active = new Set(payload.active || []);
    return Object.entries(payload.available).map(([name, scenario]) => ({ name, active: active.has(name), ...scenario }));
  }
  if (Array.isArray(payload.scenarios)) return payload.scenarios.map(toScenario);

  return Object.entries(payload)
    .flatMap(([key, value]) => Array.isArray(value) ? value.map((scenario) => ({ ...toScenario(scenario), active: key === "active" })) : [])
    .filter((scenario) => scenario.name);
}

function toScenario(scenario) {
  return typeof scenario === "string" ? { name: scenario, active: false } : { name: scenario.name || scenario.id, active: !!scenario.active, ...scenario };
}

function verificationChecks() {
  return (state.data.actions || []).flatMap((action) => action.result?.execution?.verification?.checks || []).slice(-12);
}

function ciChecks() {
  return repairLifecycleEntries().flatMap((entry) => entry.verificationRuns || []);
}

function canaryRollouts() {
  return repairLifecycleEntries().flatMap((entry) => entry.canaryRollouts || []);
}

function autonomyDecisions() {
  const actions = (state.data.actions || []).flatMap((action) => [
    withSource(action.result?.execution?.autonomy, `Action ${labelize(action.action_type)}`)
  ]);
  const repairs = (state.data.repairs || []).flatMap((repair) => [
    withSource(repair.result?.autonomy, `Repair ${repair.change_type}`),
    withSource(repair.result?.ci_cd?.autonomy, "CI/CD verification"),
    withSource(repair.result?.canary?.health_signals?.autonomy, "Canary rollout")
  ]);
  return [...actions, ...repairs].filter(Boolean);
}

function repairLifecycleEntries() {
  return Object.values(state.data.repairLifecycle || {});
}

function withSource(decision, source) {
  return decision ? { source, ...decision } : null;
}

function memoryMatches() {
  return state.data.memoryMatches?.length ? state.data.memoryMatches : state.data.memories || [];
}

function renderCollection(target, records = [], renderer, emptyText) {
  setHtml(target, records.length ? records.map(renderer).join("") : empty(emptyText));
}

function setHtml(target, html) {
  dom[target].innerHTML = html;
}

function card(content) {
  return `<article class="item">${content}</article>`;
}

function actionButton(label, dataName, value, className = "") {
  return `<button ${className ? `class="${className}" ` : ""}type="button" data-${dataName}="${safe(value)}">${label}</button>`;
}

function empty(text) {
  return `<p class="muted">${safe(text)}</p>`;
}

function pill(value = "unknown") {
  const clean = String(value || "unknown");
  return `<span class="pill ${safe(clean)}">${safe(clean.replaceAll("_", " "))}</span>`;
}

function score(value) {
  return `<span class="pill info">${Math.round(Number(value || 0) * 100)}%</span>`;
}

function percent(value) {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function riskLabel(value) {
  const risk = Number(value || 0);
  if (risk >= 0.75) return "blocked or approval gated";
  if (risk >= 0.45) return "review recommended";
  return "autonomous eligible";
}

function summary(value) {
  if (!value) return "";
  if (typeof value === "string") return `<p>${safe(value)}</p>`;
  return value.summary || value.message || value.error ? `<p>${safe(value.summary || value.message || value.error)}</p>` : json(value);
}

function renderPolicyLine(policy) {
  if (!policy) return "";
  return `<p class="muted">Policy: ${safe(policy.decision)} · ${safe((policy.reasons || []).join("; "))}</p>`;
}

function json(value) {
  return value && Object.keys(value).length ? `<pre class="json">${safe(JSON.stringify(value, null, 2))}</pre>` : "";
}

function labelize(text = "") {
  return String(text).replaceAll("_", " ");
}

function date(value) {
  if (!value) return "unknown time";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function isActiveIncident(incident) {
  return !["resolved", "failed"].includes(incident.status);
}

function first(list = []) {
  return list[0];
}

function camel(text) {
  return text.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function safe(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showError(error) {
  dom.errorBanner.hidden = false;
  dom.errorBanner.textContent = error.message || String(error);
}

function hideError() {
  dom.errorBanner.hidden = true;
  dom.errorBanner.textContent = "";
}

function setBusy(busy) {
  [dom.refresh, dom.runHealth, dom.resetScenarios, dom.analyzeIncident, dom.executeSelected, dom.runEvaluation, dom.planRepair].forEach((button) => {
    button.disabled = busy;
  });
}
