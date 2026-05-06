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
  "error-banner",
  "status-strip",
  "sandbox-health",
  "scenario-list",
  "incident-list",
  "incident-header",
  "timeline",
  "evidence-list",
  "hypothesis-list",
  "action-list",
  "verification-list",
  "memory-list"
].map((id) => [camel(id), $(id)]));

dom.apiBase.value = state.apiBase;
document.addEventListener("click", handleClick);
refresh();
setInterval(refresh, 10000);

async function handleClick(event) {
  const button = event.target.closest("button");
  if (!button) return;

  const id = button.id;
  const data = button.dataset;
  if (id === "save-api") return saveApiBase();
  if (id === "refresh") return refresh();
  if (id === "run-health") return mutate(`/sandboxes/${SANDBOX_ID}/health-check`);
  if (id === "reset-scenarios") return mutate(`/sandboxes/${SANDBOX_ID}/scenarios/reset`);
  if (id === "analyze-incident" && state.selectedIncidentId) return mutate(`/incidents/${state.selectedIncidentId}/analyze`);
  if (id === "execute-selected" && state.selectedIncidentId) return mutate(`/incidents/${state.selectedIncidentId}/actions/execute-selected`);
  if (data.incident) return selectAndRefresh(data.incident);
  if (data.scenario) return mutate(`/sandboxes/${SANDBOX_ID}/scenarios/${data.scenario}/${data.next}`);
  if (data.actionExecute) return mutate(`/actions/${data.actionExecute}/execute`);
  if (data.actionApprove) return mutate(`/actions/${data.actionApprove}/approve`);
  if (data.actionReject) return mutate(`/actions/${data.actionReject}/reject`);
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

async function mutate(path) {
  setBusy(true);
  try {
    await api(path, { method: "POST" });
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
  const [control, sandbox, scenarios, incidents, memories] = await Promise.all([
    api("/health"),
    api(`/sandboxes/${SANDBOX_ID}`),
    api(`/sandboxes/${SANDBOX_ID}/scenarios`),
    api("/incidents"),
    api("/memory/incidents?limit=6")
  ]);

  state.data = {
    control,
    sandbox,
    scenarios: normalizeScenarios(scenarios),
    incidents: incidents.incidents || [],
    memories: memories.memories || []
  };
}

async function loadIncident(incidentId) {
  const [incident, timeline, evidence, hypotheses, actions] = await Promise.all([
    api(`/incidents/${incidentId}`),
    api(`/incidents/${incidentId}/timeline`),
    api(`/incidents/${incidentId}/evidence`),
    api(`/incidents/${incidentId}/hypotheses`),
    api(`/incidents/${incidentId}/actions`)
  ]);

  const query = encodeURIComponent([incident.root_cause, incident.title].filter(Boolean).join(" "));
  const matches = query ? await api(`/memory/search?query=${query}&limit=5`) : { memories: [] };

  Object.assign(state.data, {
    incident,
    timeline: timeline.events || [],
    evidence: evidence.evidence || [],
    hypotheses: hypotheses.hypotheses || [],
    actions: actions.actions || [],
    memoryMatches: matches.memories || []
  });
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
  renderIncidentHeader();
  renderTimeline();
  renderCollection("evidenceList", state.data.evidence, renderEvidence, "No evidence captured");
  renderCollection("hypothesisList", state.data.hypotheses, renderHypothesis, "No hypotheses generated");
  renderCollection("actionList", state.data.actions, renderAction, "No remediation candidates");
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

function renderIncidentHeader() {
  const incident = state.data.incident;
  dom.executeSelected.disabled = !incident;
  dom.analyzeIncident.disabled = !incident;
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
  const approval = action.requires_approval ? `<button type="button" data-action-approve="${action.id}">Approve</button>` : "";
  const rejection = action.status === "rejected" ? "" : `<button class="danger" type="button" data-action-reject="${action.id}">Reject</button>`;
  const guardrail = action.requires_approval ? "approval required" : riskLabel(action.risk_score);

  return card(`
    <div class="row"><strong>${safe(labelize(action.action_type))}</strong>${pill(action.status)}</div>
    <p class="muted">Risk ${Number(action.risk_score || 0).toFixed(2)} · ${safe(guardrail)}</p>
    ${summary(action.params)}
    <div class="action-controls">
      <button type="button" data-action-execute="${action.id}">Execute</button>
      ${approval}
      ${rejection}
    </div>
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
  return card(`
    <div class="row">
      <strong>${safe(memory.root_cause || "Stored incident")}</strong>
      ${memory.similarity_score !== undefined ? score(memory.similarity_score) : ""}
    </div>
    <p>${safe(memory.summary || "No summary")}</p>
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
  [dom.refresh, dom.runHealth, dom.resetScenarios, dom.analyzeIncident, dom.executeSelected].forEach((button) => {
    button.disabled = busy;
  });
}
