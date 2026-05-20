const SANDBOX_ID = "local-docker";
const DEFAULT_API = "http://localhost:8000";

const state = {
  apiBase: localStorage.getItem("controlApiBaseUrl") || DEFAULT_API,
  selectedIncidentId: null,
  selectedAppId: localStorage.getItem("selectedAppId") || null,
  tutorialIndex: -1,
  data: {}
};

const $ = (id) => document.getElementById(id);
const dom = Object.fromEntries([
  "api-base",
  "save-api",
  "refresh",
  "start-tutorial",
  "run-health",
  "run-app-health",
  "reset-scenarios",
  "analyze-incident",
  "execute-selected",
  "run-evaluation",
  "plan-repair",
  "reload-preview",
  "open-user-app",
  "send-sample-metric",
  "note-form",
  "note-severity",
  "note-text",
  "error-banner",
  "help-popover",
  "tutorial-scrim",
  "tutorial-card",
  "status-strip",
  "app-console-title",
  "app-console-meta",
  "user-app-frame",
  "app-list",
  "app-probe-list",
  "system-narrative",
  "onboarding-list",
  "slo-list",
  "slo-history-list",
  "metric-list",
  "note-list",
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
  "start-tutorial": () => startTutorial(),
  "run-health": () => mutate(`/sandboxes/${SANDBOX_ID}/health-check`),
  "run-app-health": () => selectedApp((app) => mutate(`/apps/${app.app_id}/health-check`)),
  "reload-preview": () => reloadPreview(),
  "open-user-app": () => openUserApp(),
  "send-sample-metric": () => selectedApp((app) => mutate(`/apps/${app.app_id}/metrics`, sampleMetricPayload())),
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
  repairRollback: (id) => mutate(`/repairs/${id}/rollback`),
  rolloutPromote: (id) => mutate(`/canary-rollouts/${id}/promote`),
  rolloutRollback: (id) => mutate(`/canary-rollouts/${id}/rollback`),
  rolloutQuarantine: (id) => mutate(`/canary-rollouts/${id}/quarantine`)
};

const TUTORIAL_STEPS = [
  {
    selector: "#status-strip",
    title: "Start With The Status Strip",
    body: "Confirm the Control API is healthy, the selected app is active, target health is healthy, and active incidents are visible."
  },
  {
    selector: "[data-tour='user-console']",
    title: "Watch The User Experience",
    body: "This preview shows what the app user sees. During a recovery run, this is where you verify the app becomes reachable again."
  },
  {
    selector: "[data-tour='system-console']",
    title: "Read The System Summary",
    body: "The developer console summarizes the runtime's current app, health, incident, mitigation, repair, and onboarding state."
  },
  {
    selector: "[data-tour='slo-panel']",
    title: "Track Reliability Signals",
    body: "Metrics and SLO evaluations can create incidents even when basic health checks are still passing."
  },
  {
    selector: "[data-tour='notes-panel']",
    title: "Add Human Context",
    body: "Operator notes let support reports and developer observations become typed incident evidence."
  },
  {
    selector: "[data-tour='incidents']",
    title: "Select An Incident",
    body: "Incidents collect all signals for a failure. Select one here to inspect the timeline, evidence, actions, and repair lifecycle."
  },
  {
    selector: "[data-tour='timeline']",
    title: "Replay The Incident",
    body: "The timeline is the audit trail for detection, diagnosis, mitigation, verification, repair, canary, and memory."
  },
  {
    selector: "[data-tour='evidence']",
    title: "Inspect Evidence",
    body: "Evidence shows exactly what the agent used: health checks, runtime events, manifest data, SLO breaches, notes, and memory."
  },
  {
    selector: "[data-tour='hypotheses']",
    title: "Review Root-Cause Ranking",
    body: "Hypotheses explain likely causes with confidence and concise rationale summaries."
  },
  {
    selector: "[data-tour='actions']",
    title: "Check Guardrails",
    body: "Actions are bounded mitigations. Look for risk score, approval policy, autonomy decision, and execution result."
  },
  {
    selector: "[data-tour='verification']",
    title: "Confirm Recovery",
    body: "Verification proves the action worked through health checks, probes, dependencies, and scenario-specific checks."
  },
  {
    selector: "[data-tour='repairs']",
    title: "Review Durable Repairs",
    body: "After runtime recovery, repair plans can propose code or config changes with owners, diff preview, rollback, and approval controls."
  },
  {
    selector: "[data-tour='ci']",
    title: "Check CI Gates",
    body: "CI checks must pass before a generated repair can be released through canary."
  },
  {
    selector: "[data-tour='canary']",
    title: "Watch Canary Release",
    body: "Canary rollout validates a generated change with limited probes before promotion, rollback, or quarantine."
  },
  {
    selector: "[data-tour='memory']",
    title: "Use Incident Memory",
    body: "Memory matches show similar past incidents and what worked before. This gets more useful after repeated runs."
  }
];

dom.apiBase.value = state.apiBase;
installInfoButtons();
document.addEventListener("click", handleClick);
window.addEventListener("resize", hideHelp);
dom.noteForm.addEventListener("submit", submitNote);
refresh();
setInterval(refresh, 10000);

async function handleClick(event) {
  const button = event.target.closest("button");
  if (!button) {
    if (!event.target.closest("#help-popover")) hideHelp();
    return;
  }

  const id = button.id;
  const data = button.dataset;
  if (data.helpFor) return showHelp(button, document.querySelector(`[data-help-id="${data.helpFor}"]`));
  if (data.tutorialAction === "next") return nextTutorialStep();
  if (data.tutorialAction === "prev") return previousTutorialStep();
  if (data.tutorialAction === "close") return closeTutorial();
  if (BUTTON_ACTIONS[id]) return BUTTON_ACTIONS[id]();
  if (data.app) return selectApp(data.app);
  if (data.incident) return selectAndRefresh(data.incident);
  if (data.scenario) return mutate(`/sandboxes/${SANDBOX_ID}/scenarios/${data.scenario}/${data.next}`);

  for (const [key, action] of Object.entries(DATASET_ACTIONS)) {
    if (data[key]) return action(data[key]);
  }

  if (!event.target.closest("#help-popover")) hideHelp();
}

function installInfoButtons() {
  document.querySelectorAll("[data-help]").forEach((section, index) => {
    const helpId = `help-${index}`;
    section.dataset.helpId = helpId;
    section.classList.add("help-scope");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button info-button";
    button.dataset.helpFor = helpId;
    button.setAttribute("aria-label", `About ${section.dataset.helpTitle || "this section"}`);
    button.textContent = "i";

    const title = section.querySelector(":scope > .section-title");
    const summary = section.querySelector(":scope > summary");
    if (title) {
      title.append(button);
    } else if (summary) {
      summary.append(button);
    } else {
      button.classList.add("floating-info-button");
      section.prepend(button);
    }
  });
}

function showHelp(button, section) {
  if (!section) return;
  const title = section.dataset.helpTitle || "About this section";
  const body = section.dataset.help || "";
  dom.helpPopover.innerHTML = `
    <h3>${safe(title)}</h3>
    <p>${safe(body)}</p>
  `;
  placeFloatingBox(dom.helpPopover, button.getBoundingClientRect());
  dom.helpPopover.hidden = false;
}

function hideHelp() {
  dom.helpPopover.hidden = true;
}

function startTutorial() {
  hideHelp();
  state.tutorialIndex = 0;
  showTutorialStep();
}

function nextTutorialStep() {
  if (state.tutorialIndex >= TUTORIAL_STEPS.length - 1) return closeTutorial();
  state.tutorialIndex += 1;
  showTutorialStep();
}

function previousTutorialStep() {
  state.tutorialIndex = Math.max(0, state.tutorialIndex - 1);
  showTutorialStep();
}

function closeTutorial() {
  state.tutorialIndex = -1;
  document.querySelectorAll(".tutorial-highlight").forEach((element) => element.classList.remove("tutorial-highlight"));
  dom.tutorialScrim.hidden = true;
  dom.tutorialCard.hidden = true;
}

function showTutorialStep() {
  document.querySelectorAll(".tutorial-highlight").forEach((element) => element.classList.remove("tutorial-highlight"));
  const step = TUTORIAL_STEPS[state.tutorialIndex];
  const target = document.querySelector(step.selector);
  if (!target) return nextTutorialStep();

  target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  target.classList.add("tutorial-highlight");
  dom.tutorialScrim.hidden = false;
  dom.tutorialCard.innerHTML = `
    <div class="tutorial-progress">Step ${state.tutorialIndex + 1} of ${TUTORIAL_STEPS.length}</div>
    <h3>${safe(step.title)}</h3>
    <p>${safe(step.body)}</p>
    <div class="tutorial-actions">
      <button type="button" data-tutorial-action="close">Close</button>
      <button type="button" data-tutorial-action="prev" ${state.tutorialIndex === 0 ? "disabled" : ""}>Back</button>
      <button class="primary" type="button" data-tutorial-action="next">${state.tutorialIndex === TUTORIAL_STEPS.length - 1 ? "Done" : "Next"}</button>
    </div>
  `;
  const rect = target.getBoundingClientRect();
  placeFloatingBox(dom.tutorialCard, rect);
  dom.tutorialCard.hidden = false;
}

function placeFloatingBox(box, anchorRect) {
  box.hidden = false;
  const margin = 14;
  const width = Math.min(360, window.innerWidth - margin * 2);
  box.style.width = `${width}px`;

  let left = Math.min(Math.max(anchorRect.left, margin), window.innerWidth - width - margin);
  let top = anchorRect.bottom + margin;
  if (top + 220 > window.innerHeight) top = Math.max(margin, anchorRect.top - 230);

  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
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

function selectedApp(callback) {
  const app = currentApp();
  return app ? callback(app) : undefined;
}

async function selectApp(appId) {
  state.selectedAppId = appId;
  localStorage.setItem("selectedAppId", appId);
  await refresh();
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

async function submitNote(event) {
  event.preventDefault();
  const app = currentApp();
  const note = dom.noteText.value.trim();
  if (!app || !note) return;

  await mutate(`/apps/${app.app_id}/notes`, {
    note,
    severity: dom.noteSeverity.value,
    service_name: primaryService(app)?.name || null,
    tags: ["dashboard"],
    metric_refs: []
  });
  dom.noteText.value = "";
}

async function refresh() {
  setBusy(true);
  hideError();
  try {
    await loadOverview();
    chooseApp();
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
  const [control, apps, sandbox, scenarios, incidents, memories, evaluations] = await Promise.all([
    api("/health"),
    api("/apps").catch(() => ({ apps: [] })),
    api(`/sandboxes/${SANDBOX_ID}`),
    api(`/sandboxes/${SANDBOX_ID}/scenarios`),
    api("/incidents"),
    api("/memory/incidents?limit=6"),
    api("/evaluations")
  ]);

  state.data = {
    control,
    apps: apps.apps || [],
    sandbox,
    scenarios: normalizeScenarios(scenarios),
    incidents: incidents.incidents || [],
    memories: memories.memories || [],
    evaluations: evaluations.runs || []
  };

  chooseApp();
  if (state.selectedAppId) {
    const [metrics, slo, notes, validation] = await Promise.all([
      api(`/apps/${state.selectedAppId}/metrics`).catch(() => ({ observations: [], slo_evaluations: [] })),
      api(`/apps/${state.selectedAppId}/slo-status`).catch(() => ({ slo_targets: [] })),
      api(`/apps/${state.selectedAppId}/notes`).catch(() => ({ notes: [] })),
      api(`/apps/${state.selectedAppId}/validation`).catch(() => ({ checks: [], status: "unknown" }))
    ]);
    Object.assign(state.data, {
      metrics: metrics.observations || [],
      sloEvaluations: metrics.slo_evaluations || [],
      sloTargets: slo.slo_targets || [],
      notes: notes.notes || [],
      appValidation: validation
    });
  }
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

function chooseApp() {
  const apps = state.data.apps || [];
  const selected = apps.find((app) => app.app_id === state.selectedAppId);
  if (selected?.status === "active") return;
  state.selectedAppId = (apps.find((app) => app.status === "active") || selected || apps[0] || {}).app_id || null;
  if (state.selectedAppId) localStorage.setItem("selectedAppId", state.selectedAppId);
}

function render() {
  renderStatus();
  renderUserConsole();
  renderSystemNarrative();
  renderOnboardingHealth();
  renderReliabilitySignals();
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
  const app = currentApp();
  const metrics = [
    ["Control API", state.data.control?.status || "unknown", state.apiBase],
    ["Application", app?.display_name || "No app", app?.environment || "not registered"],
    ["Target Health", health?.status || "unknown", health?.service_name || SANDBOX_ID],
    ["Active Incidents", incidents.filter(isActiveIncident).length, `${incidents.length} total`],
    ["Last Refresh", new Date().toLocaleTimeString(), "local operator time"]
  ];
  dom.statusStrip.innerHTML = metrics.map(([label, value, help]) => `
    <div class="metric"><span>${safe(label)}</span><strong>${safe(value)}</strong><span>${safe(help)}</span></div>
  `).join("");
}

function renderUserConsole() {
  const app = currentApp();
  const service = primaryService(app);
  const previewUrl = app?.status === "active" ? service?.public_url || service?.base_url || "" : "";

  dom.appConsoleTitle.textContent = app?.display_name || "Application Preview";
  dom.appConsoleMeta.textContent = app
    ? `${app.app_id} · ${app.environment} · ${app.status}${previewUrl ? ` · ${previewUrl}` : " · no active preview configured"}`
    : "Register an application manifest to show the user-facing site here.";

  if (previewUrl && dom.userAppFrame.dataset.src !== previewUrl) {
    dom.userAppFrame.src = previewUrl;
    dom.userAppFrame.dataset.src = previewUrl;
  }
  if (!previewUrl) {
    dom.userAppFrame.removeAttribute("src");
    delete dom.userAppFrame.dataset.src;
  }

  renderCollection("appList", state.data.apps || [], renderAppButton, "No applications registered");
  renderCollection("appProbeList", appProbes(app), renderProbe, "No critical probes declared");
  dom.runAppHealth.disabled = !app || app.status !== "active";
  dom.reloadPreview.disabled = !previewUrl;
  dom.openUserApp.disabled = !previewUrl;
}

function renderReliabilitySignals() {
  renderCollection("sloList", state.data.sloTargets || [], renderSloTarget, "No SLO targets declared");
  renderCollection("sloHistoryList", (state.data.sloEvaluations || []).slice(0, 5), renderSloEvaluation, "No SLO evaluations yet");
  renderCollection("metricList", (state.data.metrics || []).slice(0, 5), renderMetric, "No metric observations yet");
  renderCollection("noteList", state.data.notes || [], renderNote, "No operator notes yet");
  dom.sendSampleMetric.disabled = !currentApp();
}

function renderOnboardingHealth() {
  const validation = state.data.appValidation;
  if (!validation) return setHtml("onboardingList", empty("No manifest validation data"));
  renderCollection("onboardingList", validation.checks || [], (check) => card(`
    <div class="row"><strong>${safe(labelize(check.name))}</strong>${pill(check.ok ? "ok" : "missing")}</div>
    <p class="muted">${safe(check.message)}</p>
  `), "No manifest validation checks");
}

function renderSloTarget(slo) {
  const latest = slo.latest;
  const value = latest ? `${latest.observed_value} ${slo.comparator} ${slo.target}` : `${slo.comparator} ${slo.target}`;
  return card(`
    <div class="row"><strong>${safe(slo.name)}</strong>${pill(slo.status)}</div>
    <p class="muted">${safe(slo.metric)} · ${safe(value)} · ${safe(slo.window)}</p>
    ${slo.description ? `<p>${safe(slo.description)}</p>` : ""}
  `);
}

function renderMetric(metric) {
  return card(`
    <div class="row"><strong>${safe(metric.metric_name)}</strong><span class="muted">${date(metric.observed_at)}</span></div>
    <p>${safe(metric.value)} ${safe(metric.unit || "")}</p>
    <p class="muted">${safe(metric.source)}</p>
  `);
}

function renderSloEvaluation(evaluation) {
  const incidentLink = evaluation.incident_id ? ` · incident ${String(evaluation.incident_id).slice(0, 8)}` : "";
  return card(`
    <div class="row"><strong>${safe(evaluation.slo_name)}</strong>${pill(evaluation.status)}</div>
    <p class="muted">${safe(evaluation.observed_value)} ${safe(evaluation.comparator)} ${safe(evaluation.target)} · ${date(evaluation.evaluated_at)}${safe(incidentLink)}</p>
  `);
}

function renderNote(note) {
  return card(`
    <div class="row"><strong>${safe(note.severity)}</strong>${note.incident_id ? pill("incident created") : pill("recorded")}</div>
    <p>${safe(note.note)}</p>
    <p class="muted">${date(note.created_at)}${note.service_name ? ` · ${safe(note.service_name)}` : ""}</p>
  `);
}

function sampleMetricPayload() {
  return {
    metric_name: "latency_p95_ms",
    value: 850,
    unit: "ms",
    source: "dashboard-sample",
    labels: { route: "/checkout" }
  };
}

function renderAppButton(app) {
  const selected = app.app_id === state.selectedAppId ? " active" : "";
  return `
    <button class="app-button${selected}" type="button" data-app="${safe(app.app_id)}">
      <div class="row"><strong>${safe(app.display_name)}</strong>${pill(app.status)}</div>
      <p class="muted">${safe(app.app_id)} · ${safe(app.environment)}</p>
    </button>
  `;
}

function renderProbe(probe) {
  return card(`
    <div class="row"><strong>${safe(probe.name)}</strong><span class="muted">${safe(probe.method || "GET")}</span></div>
    <p class="muted">${safe(probe.service)}${safe(probe.path)}</p>
  `);
}

function renderSystemNarrative() {
  const incident = state.data.incident;
  const actions = state.data.actions || [];
  const repairs = state.data.repairs || [];
  const latestAction = actions[0];
  const latestRepair = repairs[0];
  const health = first(state.data.sandbox?.latest_health);

  const lines = [
    narrativeStep("Application", currentApp()?.display_name || "No app registered", currentApp() ? "Manifest loaded with probes, safe actions, and repair policy." : "Use /apps/register to onboard a website."),
    narrativeStep("Health", health?.status || "unknown", health?.detail?.active_scenarios?.length ? `Active scenario: ${health.detail.active_scenarios.join(", ")}` : "No active scenario reported."),
    narrativeStep("Incident", incident?.status || "none selected", incident?.root_cause || incident?.title || "No active diagnosis selected."),
    narrativeStep("Mitigation", latestAction?.status || "not selected", latestAction ? `${labelize(latestAction.action_type)} · risk ${Number(latestAction.risk_score || 0).toFixed(2)}` : "The agent has not selected an action."),
    narrativeStep("Durable Repair", latestRepair?.status || "not planned", latestRepair?.patch_summary || "No code/config repair has been proposed yet.")
  ];

  setHtml("systemNarrative", lines.join(""));
}

function narrativeStep(label, value, detail) {
  return `
    <div class="narrative-step">
      <span>${safe(label)}</span>
      <strong>${safe(value)}</strong>
      <p>${safe(detail)}</p>
    </div>
  `;
}

function reloadPreview() {
  const frame = dom.userAppFrame;
  if (frame.src) frame.src = frame.src;
}

function openUserApp() {
  const service = primaryService(currentApp());
  const url = service?.public_url || service?.base_url;
  if (url) window.open(url, "_blank", "noopener,noreferrer");
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
      <p class="muted">${safe(incident.trigger_source || "unknown")} · ${safe(incident.severity || "medium")} · ${date(incident.detected_at)}</p>
      <p class="muted">${safe(incident.root_cause || "root cause pending")}</p>
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
    <p class="muted">${safe(incident.trigger_source || "unknown")} · ${safe(incident.severity || "medium")} · ${safe(incident.app_id || "unscoped app")} · ${safe(incident.service_name || "unscoped service")}</p>
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

  return card(`
    <div class="row"><strong>${safe(repair.patch_summary || plan.patch_summary || repair.change_type)}</strong>${pill(repair.status)}</div>
    <p class="muted">${safe(repair.change_type)} · Risk ${Number(repair.risk_score || 0).toFixed(2)} · ${safe((repair.affected_paths || []).join(", ") || "no paths")}</p>
    ${renderPolicyLine(repair.result?.autonomy)}
    ${renderOwnership(repair.result?.path_ownership || [])}
    ${summary({ verification_plan: repair.verification_plan, rollback_plan: repair.rollback_plan })}
    ${renderDiffPreview(repair.result?.patch_preview || [])}
    ${renderRepairLifecycle(repair)}
    <div class="action-controls">${repairControls(repair)}</div>
  `);
}

function repairControls(repair) {
  return [
    repair.requires_approval ? actionButton("Approve", "repair-approve", repair.id) : "",
    actionButton("Apply", "repair-apply", repair.id),
    actionButton("Verify", "repair-verify", repair.id),
    actionButton("Canary", "repair-canary", repair.id),
    canRollbackRepair(repair) ? actionButton("Rollback", "repair-rollback", repair.id, "danger") : "",
    actionButton("Reject", "repair-reject", repair.id, "danger")
  ].join("");
}

function renderRepairLifecycle(repair) {
  const lifecycle = state.data.repairLifecycle?.[repair.id] || {};
  return `
    <div class="mini-grid">
      <span>CI runs <strong>${safe((lifecycle.verificationRuns || []).length)}</strong></span>
      <span>Canaries <strong>${safe((lifecycle.canaryRollouts || []).length)}</strong></span>
    </div>
  `;
}

function canRollbackRepair(repair) {
  return ["patch_applied", "verification_failed"].includes(repair.status);
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

function renderOwnership(records) {
  if (!records.length) return "";
  return `<p class="muted">Owners: ${safe(records.map((record) => `${record.path} -> ${record.owner}`).join("; "))}</p>`;
}

function renderDiffPreview(previews) {
  if (!previews.length) return "";
  return previews.map((preview) => `
    <details class="diff-preview">
      <summary>${safe(preview.path)} · ${safe(preview.owner || "unowned")}</summary>
      <pre class="json">${safe(preview.diff || "No textual diff")}</pre>
    </details>
  `).join("");
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

function currentApp() {
  return (state.data.apps || []).find((app) => app.app_id === state.selectedAppId) || null;
}

function primaryService(app) {
  return first(app?.manifest?.services || []);
}

function appProbes(app) {
  return app?.manifest?.critical_probes || app?.manifest?.health_checks || [];
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
  [
    dom.refresh,
    dom.runHealth,
    dom.runAppHealth,
    dom.sendSampleMetric,
    dom.resetScenarios,
    dom.analyzeIncident,
    dom.executeSelected,
    dom.runEvaluation,
    dom.planRepair
  ].forEach((button) => {
    button.disabled = busy;
  });
}
