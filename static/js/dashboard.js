function drawStatusChart(canvasId, summary) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !summary || !window.Chart) return;

  const chart = summary.chart || [];
  const labels = chart.map((c) => c.status);
  const values = chart.map((c) => c.count);
  const colors = chart.map((c) => c.color);

  if (canvas._chartInstance) {
    canvas._chartInstance.destroy();
  }

  canvas._chartInstance = new Chart(canvas, {
    type: "pie",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
          borderWidth: 2,
          borderColor: "#fff",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              const item = chart[ctx.dataIndex];
              return `${item.status}: ${item.count} (${item.pct}%)`;
            },
          },
        },
      },
    },
  });
}

async function parseJsonResponse(resp, fallbackError) {
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_e) {
    const looksHtml = /^\s*</.test(text || "");
    if (!resp.ok && looksHtml) {
      throw new Error(
        fallbackError ||
          `Server returned HTML instead of JSON (HTTP ${resp.status}). ` +
            "Upload may be too large — try Import ZIP, fewer HTML files, or a server folder path."
      );
    }
    throw new Error(
      fallbackError ||
        `Unexpected response (HTTP ${resp.status}). Expected JSON.`
    );
  }
  if (!resp.ok) {
    throw new Error(
      (data && (data.error || data.detail)) ||
        fallbackError ||
        `Request failed (HTTP ${resp.status})`
    );
  }
  return data || {};
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

const LAST_PLAN_CTX_KEY = "testdeck_last_plan_ctx_v1";

function showToast(message, type = "info", ms = 4200) {
  const host = document.getElementById("toastHost");
  if (!host) {
    console[type === "error" ? "error" : "log"](message);
    return;
  }
  const el = document.createElement("div");
  el.className = `toast toast-${type === "error" ? "error" : type === "ok" || type === "success" ? "ok" : type === "warn" ? "warn" : "info"}`;
  el.textContent = String(message || "");
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

function currentExecutionKey() {
  const panel = document.getElementById("casesPanel");
  if (panel?.dataset?.execution) return panel.dataset.execution;
  const bulk = document.getElementById("bulkBar");
  return (bulk?.dataset?.execution || "").trim();
}

function rememberPlanContext(extra = {}) {
  const panel = document.getElementById("casesPanel");
  const plan =
    extra.plan ||
    panel?.dataset?.plan ||
    new URLSearchParams(window.location.search).get("plan") ||
    "";
  const execution =
    extra.execution || panel?.dataset?.execution || currentExecutionKey();
  if (!plan && !execution) return;
  const params = new URLSearchParams(window.location.search);
  const ctx = {
    plan: plan || "",
    execution: execution || "",
    technology: params.get("technology") || "",
    stack: params.get("stack") || "",
    release: params.get("release") || "",
    savedAt: Date.now(),
  };
  try {
    localStorage.setItem(LAST_PLAN_CTX_KEY, JSON.stringify(ctx));
  } catch (_e) {
    /* ignore */
  }
}

function readLastPlanContext() {
  try {
    const raw = localStorage.getItem(LAST_PLAN_CTX_KEY);
    if (!raw) return null;
    const ctx = JSON.parse(raw);
    if (!ctx || (!ctx.plan && !ctx.execution)) return null;
    return ctx;
  } catch (_e) {
    return null;
  }
}

function applyOverallSummary(summary) {
  if (!summary) return;
  const dataEl = document.getElementById("status-summary-data");
  if (dataEl) dataEl.textContent = JSON.stringify(summary);
  drawStatusChart("statusChart", summary);
  const pct = document.getElementById("statusPassPct");
  if (pct) pct.textContent = `${summary.pass_pct ?? 0}% passed`;
  const sub = document.getElementById("statusTodoSub");
  if (sub) {
    sub.textContent = `${summary.todo ?? 0} / ${summary.total ?? 0} untested (${summary.todo_pct ?? 0}%)`;
  }
  const chips = document.getElementById("statusChips");
  if (chips) {
    const pass = chips.querySelector(".pass-chip");
    const fail = chips.querySelector(".fail-chip");
    const todo = chips.querySelector(".todo-chip");
    const total = chips.querySelector(".chip:not(.pass-chip):not(.fail-chip):not(.todo-chip)");
    if (pass) pass.textContent = ` ${summary.passed ?? 0} PASS`;
    if (fail) fail.textContent = ` ${summary.failed ?? 0} FAIL`;
    if (todo) todo.textContent = ` ${summary.todo ?? 0} TODO`;
    if (total) total.textContent = ` ${summary.total ?? 0} total`;
  }
  const list = document.getElementById("statusList");
  if (list && Array.isArray(summary.chart)) {
    list.querySelectorAll(".status-row").forEach((row) => {
      const status = row.dataset.status;
      if (!status) return;
      const item = summary.chart.find((c) => c.status === status);
      if (!item) return;
      const count = row.querySelector(".status-count");
      const pctEl = row.querySelector(".status-pct");
      if (count) count.textContent = item.count;
      if (pctEl) pctEl.textContent = `(${item.pct}%)`;
    });
  }
}

async function refreshExecutionSummary(executionKey) {
  const key = executionKey || currentExecutionKey();
  if (!key) return;
  const params = new URLSearchParams(window.location.search);
  const tech = params.get("technology") || "";
  try {
    const url = `/api/executions/${encodeURIComponent(key)}/summary/${
      tech ? `?technology=${encodeURIComponent(tech)}` : ""
    }`;
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) return;
    applyOverallSummary(data.overall_summary || data);
  } catch (_e) {
    /* non-fatal */
  }
}

async function updateCaseStatus(selectEl) {
  const runId = selectEl.dataset.runId;
  const execution = selectEl.dataset.execution || "";
  const status = selectEl.value;
  if (!runId || !status) return;

  const prev = selectEl.dataset.prevStatus || status;
  let defects = [];
  let customFields = {};

  if (status === "PASS" || status === "FAIL") {
    const choice = await promptStatusUpdate({
      status,
      execution,
      title: `Set status → ${status}`,
      hint:
        status === "FAIL"
          ? "Fill execution details. Optionally link a Jira defect for FAIL."
          : "Fill execution details for this PASS result.",
    });
    if (choice === null) {
      selectEl.value = prev;
      return;
    }
    defects = choice.defects || [];
    customFields = choice.customFields || {};
  }

  selectEl.disabled = true;
  selectEl.classList.add("saving");

  try {
    const body = { status, execution };
    if (defects.length) body.defects = defects;
    if (Object.keys(customFields).length) body.custom_fields = customFields;
    const resp = await fetch(`/api/testruns/${runId}/status/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok && resp.status !== 207) {
      throw new Error(data.error || "Failed to update status");
    }
    selectEl.dataset.prevStatus = status;
    selectEl.className = `status-select status-${status}`;
    selectEl.classList.add("saved");
    setTimeout(() => selectEl.classList.remove("saved"), 800);
    if (Array.isArray(data.defects) && data.defects.length) {
      renderDefectLinksForRun(runId, data.defects, { merge: true });
    } else if (defects.length) {
      renderDefectLinksForRun(runId, defects, { merge: true });
    }
    if (data.defect_error) {
      showToast(
        `Status set to ${status}, but defect link failed: ${data.defect_error}`,
        "warn"
      );
    } else {
      showToast(`Status → ${status}`, "ok", 2200);
    }
    refreshExecutionSummary(execution);
  } catch (err) {
    showToast(err.message || "Unable to update status", "error");
    selectEl.value = prev;
  } finally {
    selectEl.disabled = false;
    selectEl.classList.remove("saving");
  }
}

function getJiraBaseUrl() {
  const meta = document.querySelector('meta[name="jira-base-url"]');
  return (meta && meta.content ? meta.content : "").replace(/\/$/, "");
}

function parseDefectKeysInput(raw) {
  const text = String(raw || "");
  const found = [];
  const re = /(?:https?:\/\/[^\s]+\/(?:browse|issues)\/)?([A-Za-z][A-Za-z0-9_]+-\d+)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const key = String(m[1] || "").toUpperCase();
    if (key && !found.includes(key)) found.push(key);
  }
  // Also split plain tokens if regex missed nothing from commas.
  if (!found.length) {
    return String(raw || "")
      .toUpperCase()
      .split(/[\s,;]+/)
      .map((s) => s.trim())
      .filter((s) => /^[A-Z][A-Z0-9_]+-\d+$/.test(s));
  }
  return found;
}

function renderDefectChips(keys) {
  const list = document.getElementById("failDefectSelected");
  if (!list) return;
  const uniq = [...new Set((keys || []).map((k) => String(k).toUpperCase()))];
  if (!uniq.length) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  list.hidden = false;
  list.innerHTML = uniq
    .map(
      (key) =>
        `<span class="defect-chip" data-key="${escapeHtml(key)}">${escapeHtml(
          key
        )} <button type="button" data-remove-key="${escapeHtml(
          key
        )}" aria-label="Remove">&times;</button></span>`
    )
    .join("");
  list.querySelectorAll("[data-remove-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const drop = btn.getAttribute("data-remove-key");
      const next = uniq.filter((k) => k !== drop);
      list.dataset.keys = JSON.stringify(next);
      renderDefectChips(next);
    });
  });
  list.dataset.keys = JSON.stringify(uniq);
}

function getDefectChips() {
  const list = document.getElementById("failDefectSelected");
  if (!list || !list.dataset.keys) return [];
  try {
    const parsed = JSON.parse(list.dataset.keys);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_e) {
    return [];
  }
}

function addDefectChips(keys) {
  const merged = [...new Set([...getDefectChips(), ...(keys || [])])];
  renderDefectChips(merged);
}

let _defectSearchTimer = null;
async function searchDefectIssues(query, suggestEl) {
  const q = String(query || "").trim();
  if (!suggestEl) return;
  if (q.length < 2) {
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
    return;
  }
  try {
    const resp = await fetch(
      `/api/issues/search/?q=${encodeURIComponent(q)}&limit=20`
    );
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Search failed");
    const issues = data.issues || [];
    if (!issues.length) {
      suggestEl.hidden = false;
      suggestEl.innerHTML =
        `<div class="defect-suggest-item muted">No matching issues</div>`;
      return;
    }
    suggestEl.hidden = false;
    suggestEl.innerHTML = issues
      .map((issue) => {
        const key = escapeHtml(issue.key || "");
        const summary = escapeHtml(issue.summary || "");
        return `<button type="button" class="defect-suggest-item" data-key="${key}">
          <span class="defect-suggest-key">${key}</span>${summary}
        </button>`;
      })
      .join("");
    suggestEl.querySelectorAll("[data-key]").forEach((btn) => {
      btn.addEventListener("click", () => {
        addDefectChips([btn.getAttribute("data-key")]);
        const input = document.getElementById("failDefectKeys");
        if (input) input.value = "";
        suggestEl.hidden = true;
        suggestEl.innerHTML = "";
        input?.focus();
      });
    });
  } catch (_err) {
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
  }
}

const EXEC_DETAILS_MEMORY_KEY = "testdeck_exec_details_v1";
let _execFieldsCache = null;

function readExecDetailsMemory() {
  try {
    return JSON.parse(localStorage.getItem(EXEC_DETAILS_MEMORY_KEY) || "{}") || {};
  } catch (_e) {
    return {};
  }
}

function writeExecDetailsMemory(values) {
  try {
    localStorage.setItem(EXEC_DETAILS_MEMORY_KEY, JSON.stringify(values || {}));
  } catch (_e) {
    /* ignore */
  }
}

async function loadExecDetailFields(execution) {
  if (_execFieldsCache && _execFieldsCache.execution === execution) {
    return _execFieldsCache.fields || [];
  }
  const qs = execution
    ? `?execution=${encodeURIComponent(execution)}`
    : "";
  const resp = await fetch(`/api/results-update/fields/${qs}`);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "Unable to load execution fields");
  const fields = data.fields || [];
  _execFieldsCache = { execution, fields };
  return fields;
}

function collectModalExecDetails() {
  const values = {};
  document.querySelectorAll("#statusExecFields .status-exec-select").forEach((sel) => {
    const key = sel.dataset.fieldKey;
    if (key && sel.value) values[key] = sel.value;
  });
  return values;
}

function renderModalExecDetails(fields) {
  const host = document.getElementById("statusExecFields");
  if (!host) return;
  const remembered = readExecDetailsMemory();
  if (!fields.length) {
    host.innerHTML = `<div class="small muted">No execution detail fields mapped.</div>`;
    return;
  }
  host.innerHTML = fields
    .map((field) => {
      const key = field.key || `trcf_${field.id}`;
      const selected = remembered[key] || field.current || "";
      const opts = ['<option value="">None</option>']
        .concat(
          (field.options || []).map((opt) => {
            const safe = escapeHtml(opt);
            const isSel = String(opt) === String(selected) ? " selected" : "";
            return `<option value="${safe}"${isSel}>${safe}</option>`;
          })
        )
        .join("");
      return `<label class="status-exec-field">
        <span class="small muted">${escapeHtml(field.label || key)}</span>
        <select class="status-exec-select" data-field-key="${escapeHtml(key)}" data-field-id="${escapeHtml(field.id || "")}">
          ${opts}
        </select>
      </label>`;
    })
    .join("");
}

/** Prompt for execution details (+ optional FAIL defects). Returns {defects, customFields} or null. */
async function promptStatusUpdate({
  title,
  hint,
  status = "FAIL",
  execution = "",
} = {}) {
  const modal = document.getElementById("failDefectModal");
  const input = document.getElementById("failDefectKeys");
  const titleEl = document.getElementById("failDefectTitle");
  const hintEl = document.getElementById("failDefectHint");
  const confirmBtn = document.getElementById("failDefectConfirmBtn");
  const skipBtn = document.getElementById("failDefectSkipBtn");
  const cancelBtn = document.getElementById("failDefectCancelBtn");
  const cancelX = document.getElementById("failDefectCancelX");
  const suggestEl = document.getElementById("failDefectSuggest");
  const defectSection = document.getElementById("failDefectSection");
  const showDefects = status === "FAIL";

  if (!modal) return null;

  if (titleEl) titleEl.textContent = title || `Set status → ${status}`;
  if (hintEl) {
    hintEl.textContent =
      hint ||
      (showDefects
        ? "Fill execution details. Link a Jira only if needed for FAIL."
        : "Fill execution details for this result.");
  }
  if (confirmBtn) confirmBtn.textContent = "Save";
  if (skipBtn) {
    skipBtn.hidden = !showDefects;
    skipBtn.textContent = "Save without defect";
  }
  if (defectSection) defectSection.hidden = !showDefects;
  if (input) input.value = "";
  renderDefectChips([]);
  if (suggestEl) {
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
  }

  const fieldsHost = document.getElementById("statusExecFields");
  if (fieldsHost) fieldsHost.innerHTML = `<div class="small muted">Loading fields…</div>`;
  modal.hidden = false;

  try {
    const fields = await loadExecDetailFields(execution);
    renderModalExecDetails(fields);
  } catch (err) {
    if (fieldsHost) {
      fieldsHost.innerHTML = `<div class="small muted">${escapeHtml(err.message || "Fields unavailable")}</div>`;
    }
  }

  return new Promise((resolve) => {
    const cleanup = (result) => {
      modal.hidden = true;
      clearTimeout(_defectSearchTimer);
      document.removeEventListener("keydown", onKey);
      input?.removeEventListener("input", onInput);
      input?.removeEventListener("keydown", onInputKey);
      confirmBtn?.removeEventListener("click", onConfirm);
      skipBtn?.removeEventListener("click", onSkip);
      cancelBtn?.removeEventListener("click", onCancel);
      cancelX?.removeEventListener("click", onCancel);
      resolve(result);
    };
    const pack = (defects) => {
      const customFields = collectModalExecDetails();
      writeExecDetailsMemory(customFields);
      return { defects: defects || [], customFields };
    };
    const collectKeys = () => {
      if (!showDefects || !input) return [];
      const typed = parseDefectKeysInput(input.value);
      return [...new Set([...getDefectChips(), ...typed])];
    };
    const onConfirm = () => cleanup(pack(collectKeys()));
    const onSkip = () => cleanup(pack([]));
    const onCancel = () => cleanup(null);
    const onInput = () => {
      clearTimeout(_defectSearchTimer);
      _defectSearchTimer = setTimeout(
        () => searchDefectIssues(input.value, suggestEl),
        280
      );
    };
    const onInputKey = (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        const typed = parseDefectKeysInput(input.value);
        if (typed.length) {
          addDefectChips(typed);
          input.value = "";
          if (suggestEl) {
            suggestEl.hidden = true;
            suggestEl.innerHTML = "";
          }
          return;
        }
        onConfirm();
      }
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") onCancel();
    };
    input?.addEventListener("input", onInput);
    input?.addEventListener("keydown", onInputKey);
    confirmBtn?.addEventListener("click", onConfirm);
    skipBtn?.addEventListener("click", onSkip);
    cancelBtn?.addEventListener("click", onCancel);
    cancelX?.addEventListener("click", onCancel);
    document.addEventListener("keydown", onKey);
    setTimeout(() => {
      const first = document.querySelector("#statusExecFields .status-exec-select");
      (first || input)?.focus?.();
    }, 40);
  });
}

/** @deprecated use promptStatusUpdate */
function promptFailDefects(opts = {}) {
  return promptStatusUpdate({ ...opts, status: opts.mode === "fail" ? "FAIL" : "FAIL" });
}

function renderDefectLinksForRun(runId, keys, { merge = false } = {}) {
  const rid = String(runId || "").replace(/"/g, "");
  const wrap = document.querySelector(
    `.exec-defects[data-run-id="${rid}"] .exec-defects-links`
  );
  const cell = document.querySelector(
    `tr[data-run-id="${rid}"] td[data-col="defects"]`
  );
  const base = getJiraBaseUrl();
  let merged = [...(keys || [])]
    .map((k) => String(k).trim().toUpperCase())
    .filter(Boolean);
  if (merge && wrap) {
    const existing = Array.from(wrap.querySelectorAll("a"))
      .map((a) => (a.textContent || "").trim().toUpperCase())
      .filter(Boolean);
    merged = [...new Set([...existing, ...merged])];
  } else {
    merged = [...new Set(merged)];
  }
  const html = merged.length
    ? merged
        .map((key) => {
          const href = base ? `${base}/browse/${encodeURIComponent(key)}` : `#`;
          return `<a href="${href}" target="_blank" rel="noopener">${escapeHtml(key)}</a>`;
        })
        .join(" ")
    : "";
  if (wrap) {
    wrap.innerHTML = html;
  } else if (cell) {
    cell.innerHTML = html
      ? `<div class="exec-defects" data-run-id="${rid}"><div class="exec-defects-links">${html}</div></div>`
      : "";
  }
  if (merged.length) {
    document
      .querySelectorAll('[data-col-toggle="defects"], input[value="defects"]')
      .forEach((el) => {
        if (el.type === "checkbox" && !el.checked) {
          el.checked = true;
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    document
      .querySelectorAll('th[data-col="defects"], td[data-col="defects"]')
      .forEach((el) => el.classList.remove("col-hidden"));
  }
}

function updateRowDefectsCell(selectEl, newKeys) {
  const runId = selectEl?.dataset?.runId;
  if (runId) renderDefectLinksForRun(runId, newKeys, { merge: true });
}

function initDefectEditors(_root = document) {
  // Linked Jira is display-only; defects are collected only when marking FAIL.
}

function bindCaseTableHandlers(root = document) {
  root.querySelectorAll("select.status-select").forEach((selectEl) => {
    if (selectEl.dataset.bound) return;
    selectEl.dataset.bound = "1";
    selectEl.dataset.prevStatus = selectEl.value;
    selectEl.addEventListener("change", () => updateCaseStatus(selectEl));
  });
  initAssigneeEditors(root);
  initDefectEditors(root);
  initBulkSelection();
  initColumnPickers();
}

function withPartialParam(url) {
  const u = new URL(url, window.location.origin);
  u.searchParams.set("partial", "cases");
  return u.pathname + u.search;
}

async function loadCasesPartial(url, { push = true } = {}) {
  const panel = document.getElementById("casesPanel");
  if (!panel) {
    window.location.href = url;
    return;
  }
  panel.classList.add("partial-loading");
  try {
    const resp = await fetch(withPartialParam(url), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!resp.ok) throw new Error(`Failed to load cases (HTTP ${resp.status})`);
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const payload = doc.getElementById("partial-payload");
    if (!payload) throw new Error("Unexpected partial response");

    const sideSrc = payload.querySelector("#partial-sidebar-tree");
    const sideDst = document.getElementById("sectionTreePanel");
    if (sideSrc && sideDst) sideDst.innerHTML = sideSrc.innerHTML;

    const casesSrc = payload.querySelector("#partial-cases-panel");
    if (casesSrc) {
      const header = casesSrc.querySelector("#casesPanelHeader");
      const body = casesSrc.querySelector("#casesPanelBody");
      const headerDst = document.getElementById("casesPanelHeader");
      const bodyDst = document.getElementById("casesPanelBody");
      if (header && headerDst) headerDst.innerHTML = header.innerHTML;
      if (body && bodyDst) bodyDst.innerHTML = body.innerHTML;
    }

    const summaryEl = payload.querySelector("#partial-overall-summary");
    if (summaryEl) {
      try {
        applyOverallSummary(JSON.parse(summaryEl.textContent || "{}"));
      } catch (_e) {
        /* ignore */
      }
    }

    const clean = new URL(url, window.location.origin);
    clean.searchParams.delete("partial");
    if (push) {
      history.pushState({ testdeckPartial: true }, "", clean.pathname + clean.search);
    } else {
      history.replaceState({ testdeckPartial: true }, "", clean.pathname + clean.search);
    }
    bindCaseTableHandlers(panel);
    initPartialNavigation();
    rememberPlanContext();
  } catch (err) {
    showToast(err.message || "Unable to update cases", "error");
    window.location.href = url;
  } finally {
    panel.classList.remove("partial-loading");
  }
}

function initPartialNavigation() {
  const panel = document.getElementById("casesPanel");
  if (!panel || panel.dataset.partialNavBound === "1") {
    // Re-bind form/auto-submit after swap even if document-level once-bound.
  }

  document.querySelectorAll("[data-partial-nav] a, a[data-partial-nav]").forEach((a) => {
    if (a.dataset.partialClickBound) return;
    a.dataset.partialClickBound = "1";
    a.addEventListener("click", (evt) => {
      if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey || a.target === "_blank") {
        return;
      }
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("http")) return;
      // Only intercept same-page query navigation for cases panel pages.
      if (!document.getElementById("casesPanel")) return;
      if (href.includes("refresh=1")) return;
      evt.preventDefault();
      loadCasesPartial(href);
    });
  });

  // Section tree links live under #sectionTreePanel
  const tree = document.getElementById("sectionTreePanel");
  if (tree && !tree.dataset.partialClickBound) {
    tree.dataset.partialClickBound = "1";
    tree.addEventListener("click", (evt) => {
      const a = evt.target.closest("a");
      if (!a || !tree.contains(a)) return;
      if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey) return;
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("http")) return;
      evt.preventDefault();
      loadCasesPartial(href);
    });
  }

  const form = document.getElementById("casesFilterForm");
  if (form && !form.dataset.partialBound) {
    form.dataset.partialBound = "1";
    form.addEventListener("submit", (evt) => {
      evt.preventDefault();
      const url = `${window.location.pathname}?${new URLSearchParams(new FormData(form)).toString()}`;
      loadCasesPartial(url);
    });
  }

  const statusSel = document.getElementById("casesStatusFilter");
  if (statusSel && !statusSel.dataset.autoBound) {
    statusSel.dataset.autoBound = "1";
    statusSel.addEventListener("change", () => {
      const f = document.getElementById("casesFilterForm");
      if (!f) return;
      if (typeof f.requestSubmit === "function") f.requestSubmit();
      else f.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    });
  }

  const searchEl = document.getElementById("casesSearchFilter");
  if (searchEl && !searchEl.dataset.debounceBound) {
    searchEl.dataset.debounceBound = "1";
    let timer = null;
    const submitSearch = () => {
      const f = document.getElementById("casesFilterForm");
      if (!f) return;
      if (typeof f.requestSubmit === "function") f.requestSubmit();
      else f.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    };
    searchEl.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(submitSearch, 400);
    });
    searchEl.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter") {
        evt.preventDefault();
        clearTimeout(timer);
        submitSearch();
      }
    });
  }

  // Pager links inside meta (not always under [data-partial-nav] alone)
  document.querySelectorAll(".cases-pager-meta a").forEach((a) => {
    if (a.dataset.partialClickBound) return;
    a.dataset.partialClickBound = "1";
    a.addEventListener("click", (evt) => {
      if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey) return;
      const href = a.getAttribute("href");
      if (!href) return;
      evt.preventDefault();
      loadCasesPartial(href);
    });
  });

  if (!window.__testdeckPopstateBound) {
    window.__testdeckPopstateBound = true;
    window.addEventListener("popstate", () => {
      if (document.getElementById("casesPanel")) {
        loadCasesPartial(window.location.href, { push: false });
      }
    });
  }
}

function initResumeLastPlan() {
  const btn = document.getElementById("continueLastRunBtn");
  const hint = document.getElementById("continueLastRunHint");
  const ctx = readLastPlanContext();
  if (!btn || !ctx || !ctx.plan || !ctx.execution) return;
  const params = new URLSearchParams();
  if (ctx.technology) params.set("technology", ctx.technology);
  if (ctx.stack) params.set("stack", ctx.stack);
  if (ctx.release) params.set("release", ctx.release);
  params.set("execution", ctx.execution);
  const href = `/plans/${encodeURIComponent(ctx.plan)}/?${params.toString()}`;
  btn.hidden = false;
  btn.href = href;
  btn.removeAttribute("hidden");
  if (hint) {
    hint.hidden = false;
    hint.innerHTML = `Last session: <strong>${escapeHtml(ctx.plan)}</strong> · <strong>${escapeHtml(ctx.execution)}</strong>`;
  }
  btn.addEventListener("click", (evt) => {
    evt.preventDefault();
    window.location.href = href;
  });
}

function initAssigneeEditors(root = document) {
  root.querySelectorAll(".assignee-input").forEach((inputEl) => {
    if (inputEl.dataset.bound) return;
    inputEl.dataset.bound = "1";
    inputEl.addEventListener("input", () => {
      clearTimeout(assigneeSearchTimer);
      const q = inputEl.value.trim();
      assigneeSearchTimer = setTimeout(() => fillAssigneeSuggestions(q), 250);
    });
    inputEl.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter") {
        evt.preventDefault();
        saveAssigneeInput(inputEl);
      }
      if (evt.key === "Escape") {
        inputEl.value = inputEl.dataset.prev || "";
        inputEl.blur();
      }
    });
    inputEl.addEventListener("change", () => saveAssigneeInput(inputEl));
  });

  const bulkAssignee = document.getElementById("bulkAssignee");
  if (bulkAssignee && !bulkAssignee.dataset.bound) {
    bulkAssignee.dataset.bound = "1";
    bulkAssignee.addEventListener("input", () => {
      syncBulkUi();
      clearTimeout(assigneeSearchTimer);
      const q = bulkAssignee.value.trim();
      assigneeSearchTimer = setTimeout(() => fillAssigneeSuggestions(q), 250);
    });
  }
}

function getCaseChecks() {
  return Array.from(document.querySelectorAll(".case-check:not(:disabled)"));
}

function getSelectedRunIds() {
  return getCaseChecks()
    .filter((el) => el.checked && el.dataset.runId)
    .map((el) => el.dataset.runId);
}

function syncBulkUi() {
  const selected = getSelectedRunIds();
  const bulkBar = document.getElementById("bulkBar");
  const countEl = document.getElementById("selectedCount");
  const applyBtn = document.getElementById("bulkApplyStatus");
  const assignBtn = document.getElementById("bulkApplyAssignee");
  const statusEl = document.getElementById("bulkStatus");
  const assigneeEl = document.getElementById("bulkAssignee");
  if (bulkBar) bulkBar.hidden = selected.length === 0;
  if (countEl) countEl.textContent = `${selected.length} selected`;
  if (applyBtn) {
    applyBtn.disabled = !(selected.length && statusEl && statusEl.value);
  }
  if (assignBtn) {
    assignBtn.disabled = !(
      selected.length &&
      assigneeEl &&
      assigneeEl.value.trim()
    );
  }

  const checks = getCaseChecks();
  const allChecked = checks.length > 0 && checks.every((c) => c.checked);
  const someChecked = checks.some((c) => c.checked);
  const header = document.getElementById("selectAllHeader");
  if (header) {
    header.checked = allChecked;
    header.indeterminate = someChecked && !allChecked;
  }

  document.querySelectorAll(".case-row").forEach((row) => {
    const check = row.querySelector(".case-check");
    row.classList.toggle("selected", !!(check && check.checked));
  });
}

function setAllChecks(checked) {
  getCaseChecks().forEach((el) => {
    el.checked = checked;
  });
  syncBulkUi();
}

async function applyBulkStatus() {
  const runIds = getSelectedRunIds();
  const statusEl = document.getElementById("bulkStatus");
  const bulkBar = document.getElementById("bulkBar");
  const applyBtn = document.getElementById("bulkApplyStatus");
  const status = statusEl ? statusEl.value : "";
  const execution = bulkBar ? bulkBar.dataset.execution || "" : "";

  if (!runIds.length || !status) return;
  if (!confirm(`Set status to ${status} for ${runIds.length} selected case(s)?`)) {
    return;
  }

  let defects = [];
  let customFields = {};
  if (status === "PASS" || status === "FAIL") {
    const choice = await promptStatusUpdate({
      status,
      execution,
      title: `Set ${runIds.length} case(s) → ${status}`,
      hint:
        status === "FAIL"
          ? "Same execution details (and optional Jira) apply to all selected FAIL cases."
          : "Same execution details apply to all selected PASS cases.",
    });
    if (choice === null) return;
    defects = choice.defects || [];
    customFields = choice.customFields || {};
  }

  if (applyBtn) {
    applyBtn.disabled = true;
    applyBtn.textContent = "…";
  }

  try {
    const body = { run_ids: runIds, status, execution };
    if (defects.length) body.defects = defects;
    if (Object.keys(customFields).length) body.custom_fields = customFields;
    const resp = await fetch("/api/testruns/bulk-status/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok && resp.status !== 207) {
      throw new Error(data.error || "Bulk update failed");
    }

    // Update row dropdowns for successful IDs
    const updated = new Set(data.updated || []);
    const linked = Array.isArray(data.defects) ? data.defects : defects;
    document.querySelectorAll("select.status-select").forEach((selectEl) => {
      if (updated.has(String(selectEl.dataset.runId))) {
        selectEl.value = status;
        selectEl.dataset.prevStatus = status;
        selectEl.className = `status-select status-${status}`;
        if (linked.length) updateRowDefectsCell(selectEl, linked);
      }
    });

    const failedCount = data.failed_count || 0;
    if (failedCount) {
      showToast(
        `Updated ${data.updated_count || 0}; failed ${failedCount}.`,
        "warn"
      );
    } else {
      showToast(`Updated ${data.updated_count || 0} case(s) → ${status}`, "ok");
    }
    await refreshExecutionSummary(execution);
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = "Apply";
    }
    setAllChecks(false);
    syncBulkUi();
  } catch (err) {
    showToast(err.message || "Unable to update selected cases", "error");
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = "Apply";
    }
    syncBulkUi();
  }
}

async function applyBulkAssignee() {
  const runIds = getSelectedRunIds();
  const assigneeEl = document.getElementById("bulkAssignee");
  const bulkBar = document.getElementById("bulkBar");
  const applyBtn = document.getElementById("bulkApplyAssignee");
  const user = assigneeEl ? assigneeEl.value.trim() : "";
  const execution = bulkBar ? bulkBar.dataset.execution || "" : "";

  if (!runIds.length || !user) return;
  if (!confirm(`Assign ${runIds.length} selected case(s) to "${user}"?`)) {
    return;
  }

  if (applyBtn) {
    applyBtn.disabled = true;
    applyBtn.textContent = "…";
  }

  try {
    const resp = await fetch("/api/testruns/bulk-assignee/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ run_ids: runIds, user, execution }),
    });
    const data = await resp.json();
    if (!resp.ok && resp.status !== 207) {
      throw new Error(data.error || "Bulk assign failed");
    }
    const failedCount = data.failed_count || 0;
    const updated = new Set(data.updated || []);
    const display = data.assignee || user;
    document.querySelectorAll(".assignee-input").forEach((inputEl) => {
      if (updated.has(String(inputEl.dataset.runId))) {
        inputEl.value = display;
        inputEl.dataset.prev = display;
      }
    });
    if (failedCount) {
      showToast(`Assigned ${data.updated_count || 0}; failed ${failedCount}.`, "warn");
    } else {
      showToast(`Assigned ${data.updated_count || 0} case(s)`, "ok");
    }
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = "Assign";
    }
    setAllChecks(false);
    syncBulkUi();
  } catch (err) {
    showToast(err.message || "Unable to assign selected cases", "error");
    if (applyBtn) {
      applyBtn.disabled = false;
      applyBtn.textContent = "Assign";
    }
    syncBulkUi();
  }
}

let assigneeSearchTimer = null;
async function fillAssigneeSuggestions(query) {
  const list = document.getElementById("assigneeSuggestions");
  if (!list || !query || query.length < 2) return;
  try {
    const resp = await fetch(
      `/api/users/search/?q=${encodeURIComponent(query)}`,
      { headers: { "X-CSRFToken": getCsrfToken() } }
    );
    const data = await resp.json();
    if (!resp.ok) return;
    list.innerHTML = "";
    (data.users || []).forEach((user) => {
      const opt = document.createElement("option");
      opt.value = user.displayName || user.name;
      opt.label = user.name ? `${user.displayName} (${user.name})` : user.displayName;
      list.appendChild(opt);
    });
  } catch (_err) {
    /* ignore search failures */
  }
}

async function saveAssigneeInput(inputEl) {
  const runId = inputEl.dataset.runId;
  const execution = inputEl.dataset.execution || "";
  const user = (inputEl.value || "").trim();
  const prev = inputEl.dataset.prev || "";
  if (!runId) return;
  if (user === prev) return;
  if (!user) {
    inputEl.value = prev;
    return;
  }

  inputEl.classList.add("saving");
  inputEl.disabled = true;
  try {
    const resp = await fetch(`/api/testruns/${encodeURIComponent(runId)}/assignee/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ user, execution }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Assign failed");
    const display = data.assignee || user;
    inputEl.value = display;
    inputEl.dataset.prev = display;
    inputEl.dataset.userKey = data.assignee_key || "";
    inputEl.classList.remove("saving");
    inputEl.classList.add("saved");
    setTimeout(() => inputEl.classList.remove("saved"), 1200);
  } catch (err) {
    showToast(err.message || "Unable to update assignee", "error");
    inputEl.value = prev;
    inputEl.classList.remove("saving");
  } finally {
    inputEl.disabled = false;
  }
}

function initBulkSelection() {
  const bulkBar = document.getElementById("bulkBar");
  const selectAllHeader = document.getElementById("selectAllHeader");
  const clearBtn = document.getElementById("bulkClearSelection");
  const applyBtn = document.getElementById("bulkApplyStatus");
  const assignBtn = document.getElementById("bulkApplyAssignee");
  const statusEl = document.getElementById("bulkStatus");

  if (bulkBar && !bulkBar.dataset.bound) {
    bulkBar.dataset.bound = "1";
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        setAllChecks(false);
        if (statusEl) statusEl.value = "";
        const assigneeEl = document.getElementById("bulkAssignee");
        if (assigneeEl) assigneeEl.value = "";
        syncBulkUi();
      });
    }
    if (statusEl) statusEl.addEventListener("change", syncBulkUi);
    if (applyBtn) applyBtn.addEventListener("click", applyBulkStatus);
    if (assignBtn) assignBtn.addEventListener("click", applyBulkAssignee);
  }

  // Header checkbox is inside the swapped table — rebind each time.
  if (selectAllHeader && !selectAllHeader.dataset.bound) {
    selectAllHeader.dataset.bound = "1";
    selectAllHeader.addEventListener("change", () =>
      setAllChecks(selectAllHeader.checked)
    );
  }

  // Shift-click range select on current page checks
  let lastChecked = window.__testdeckLastChecked || null;
  getCaseChecks().forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener("change", syncBulkUi);
    el.addEventListener("click", (evt) => {
      if (evt.shiftKey && lastChecked) {
        const checks = getCaseChecks();
        const start = checks.indexOf(lastChecked);
        const end = checks.indexOf(el);
        if (start >= 0 && end >= 0) {
          const [a, b] = start < end ? [start, end] : [end, start];
          for (let i = a; i <= b; i += 1) checks[i].checked = el.checked;
        }
      }
      lastChecked = el;
      window.__testdeckLastChecked = el;
      syncBulkUi();
    });
  });

  syncBulkUi();
}

function resolveImportExecution() {
  const shared = document.getElementById("resultsExecutionSelect");
  if (shared && shared.value) return shared.value.trim();
  for (const id of [
    "htmlExecutionSelect",
    "folderExecutionSelect",
    "zipExecutionSelect",
    "excelExecutionSelect",
  ]) {
    const sel = document.getElementById(id);
    if (sel && sel.value) return sel.value.trim();
  }
  for (const id of ["htmlImportPanel", "folderImportPanel"]) {
    const panel = document.getElementById(id);
    const key = ((panel && panel.dataset.execution) || "").trim();
    if (key) return key;
  }
  return "";
}

let _failureTriageState = {
  execution: "",
  failures: [],
  unmatched: [],
  todoCases: [],
  todoCount: 0,
  page: 1,
};

const FAILURE_TRIAGE_PICKS_KEY = "testdeck.failureTriage.picks.v2";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function allFailureTriageRows() {
  return [
    ...(_failureTriageState.failures || []),
    ...(_failureTriageState.unmatched || []),
    ...(_failureTriageState.todoCases || []),
  ];
}

function triageRowKind(row) {
  const kind = String(row.triage_kind || "").toLowerCase();
  if (kind === "todo") return "TODO";
  if (kind === "fail") return "FAIL";
  if (
    String(row.current_status || "").toUpperCase() === "TODO" &&
    !String(row.html_status || "").trim()
  ) {
    return "TODO";
  }
  return "FAIL";
}

function formatMultilineCell(text) {
  const raw = String(text || "").trim();
  if (!raw) return "—";
  return escapeHtml(raw).replace(/\n/g, "<br>");
}

function failureTriageRowKey(_row, absIndex) {
  return `triage_pick_${absIndex}`;
}

function normalizeSelectedJira(value) {
  return String(value || "")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "");
}

function failureTriageCaseStorageKey(row) {
  const mapId = normalizeSelectedJira(row.test_src_map_id || "").replace(
    /^C?/,
    "C"
  );
  if (mapId && /^C\d+$/i.test(mapId)) return mapId.toUpperCase();
  const caseKey = normalizeSelectedJira(row.key || "");
  return caseKey || "";
}

/** Group triage picks by the failure text shown (not case ID). */
function failureTriageDescriptionKey(row) {
  const reason = cleanReasonDisplay(
    row.reason_short || row.reason || row.key_error || row.explanation || ""
  )
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
  // Generic TODO placeholders would over-match — fall back to title.
  const generic =
    !reason ||
    reason === "—" ||
    /^untested\b/i.test(reason) ||
    reason.length < 8;
  if (!generic) return `reason:${reason.slice(0, 500)}`;
  const title = String(row.summary || row.test_name || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
  return title ? `title:${title.slice(0, 500)}` : "";
}

function loadFailureTriagePicks() {
  try {
    const raw = localStorage.getItem(FAILURE_TRIAGE_PICKS_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === "object" ? data : {};
  } catch (_e) {
    return {};
  }
}

function writeFailureTriagePickEntry(picks, storageKey, row) {
  if (!storageKey) return;
  const jira = getFailureTriageSelection(row);
  const mode = row.selected_jira_mode || "none";
  if (!jira || mode === "none") {
    delete picks[storageKey];
    return;
  }
  picks[storageKey] = {
    mode: mode === "linked" || mode === "similar" ? mode : "custom",
    jira,
    custom: mode === "custom" ? row.selected_jira_custom || jira : "",
    execution: _failureTriageState.execution || "",
    updated: Date.now(),
  };
}

function applyPickEntryToRow(row, saved) {
  if (!saved || !saved.jira) return false;
  const jira = normalizeSelectedJira(saved.jira);
  const similarKeys = (row.similar_jiras || [])
    .map((h) => normalizeSelectedJira(h.key || ""))
    .filter(Boolean);
  const linkedKeys = (row.existing_defects || [])
    .map((k) => normalizeSelectedJira(k))
    .filter(Boolean);

  if (linkedKeys.includes(jira)) {
    row.selected_jira_mode = "linked";
    row.selected_jira = jira;
    row.selected_jira_custom = "";
  } else if (similarKeys.includes(jira)) {
    row.selected_jira_mode = "similar";
    row.selected_jira = jira;
    row.selected_jira_custom = "";
  } else {
    row.selected_jira_mode = "custom";
    row.selected_jira = jira;
    row.selected_jira_custom = jira;
  }
  return true;
}

function copyFailureTriagePick(fromRow, toRow) {
  const mode = fromRow.selected_jira_mode || "none";
  toRow.selected_jira_mode = mode;
  if (mode === "none") {
    toRow.selected_jira = "";
    toRow.selected_jira_custom = "";
    return;
  }
  if (mode === "custom") {
    const jira = normalizeSelectedJira(
      fromRow.selected_jira_custom || fromRow.selected_jira || ""
    );
    toRow.selected_jira = jira;
    toRow.selected_jira_custom = jira;
    return;
  }
  // Prefer linked/similar on the target when that key exists there.
  applyPickEntryToRow(toRow, {
    jira: getFailureTriageSelection(fromRow),
    mode,
  });
}

function saveFailureTriagePick(row, { propagate = true } = {}) {
  const picks = loadFailureTriagePicks();
  writeFailureTriagePickEntry(picks, failureTriageCaseStorageKey(row), row);
  const descKey = failureTriageDescriptionKey(row);
  if (descKey) writeFailureTriagePickEntry(picks, descKey, row);
  try {
    localStorage.setItem(FAILURE_TRIAGE_PICKS_KEY, JSON.stringify(picks));
  } catch (_e) {
    /* ignore quota / private mode */
  }
  if (propagate) propagateFailureTriagePickByDescription(row);
}

function applySavedFailureTriagePick(row) {
  const picks = loadFailureTriagePicks();
  const caseKey = failureTriageCaseStorageKey(row);
  const descKey = failureTriageDescriptionKey(row);
  // Prefer a pick remembered for this failure description, then per-case.
  const saved =
    (descKey && picks[descKey]) || (caseKey && picks[caseKey]) || null;
  applyPickEntryToRow(row, saved);
}

function propagateFailureTriagePickByDescription(source) {
  const descKey = failureTriageDescriptionKey(source);
  if (!descKey) return;
  let applied = 0;
  allFailureTriageRows().forEach((row) => {
    if (row === source) return;
    if (failureTriageDescriptionKey(row) !== descKey) return;
    copyFailureTriagePick(source, row);
    syncFailureTriageSelection(row);
    saveFailureTriagePick(row, { propagate: false });
    applied += 1;
  });
  if (!applied) return;
  paintFailureTriagePage(_failureTriageState.page || 1);
  const jira = getFailureTriageSelection(source);
  showToast(
    jira
      ? `Applied ${jira} to ${applied} other case(s) with the same description`
      : `Cleared Jira on ${applied} other case(s) with the same description`,
    "ok",
    4500
  );
}

function getFailureTriageSelection(row) {
  const mode = row.selected_jira_mode || "none";
  if (mode === "custom") {
    return normalizeSelectedJira(row.selected_jira_custom || row.selected_jira || "");
  }
  if (mode === "similar" || mode === "linked") {
    return normalizeSelectedJira(row.selected_jira || "");
  }
  return "";
}

function syncFailureTriageSelection(row) {
  row.selected_jira = getFailureTriageSelection(row);
}

function linkedJirasText(row) {
  // Only defects already linked on the Xray case (not the triage pick).
  if (Array.isArray(row.existing_defects)) {
    return row.existing_defects
      .filter(Boolean)
      .map((k) => normalizeSelectedJira(k))
      .filter(Boolean)
      .join("\n");
  }
  return String(row.existing_defects_text || "").trim();
}

function selectedJiraDisplay(row) {
  const key = getFailureTriageSelection(row);
  if (!key) return "";
  let status = "";
  let summary = "";
  const hits = Array.isArray(row.similar_jiras) ? row.similar_jiras : [];
  for (const h of hits) {
    if (normalizeSelectedJira(h.key || "") === key) {
      status = h.status || "";
      summary = h.summary || "";
      break;
    }
  }
  const bits = [key];
  if (status) bits.push(`(${status})`);
  if (summary) bits.push(String(summary).slice(0, 80));
  return bits.join("\n");
}

function cleanReasonDisplay(text) {
  let raw = String(text || "");
  raw = raw.split(/Traceback\s*\(most recent call last\)/i)[0] || "";
  raw = raw.split(/\nDuring handling of the above exception/i)[0] || "";
  raw = raw
    .split("\n")
    .filter((ln) => {
      const s = ln.trim();
      if (!s) return false;
      if (/^File\s+"/i.test(s) || /^Traceback/i.test(s)) return false;
      return true;
    })
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return raw;
}

function failureDetailsDisplay(row) {
  if (row.details_text) {
    // Prefer server details, but drop obsolete "Command:" / method-as-API lines.
    return String(row.details_text)
      .split("\n")
      .filter((ln) => !/^Command:/i.test(ln.trim()))
      .join("\n");
  }
  const api = row.failed_api || row.failed_command || "";
  return [
    api ? `API: ${api}` : "",
    row.status_code ? `Status: ${row.status_code}` : "",
    row.failure_context && String(row.failure_context).includes("Call:")
      ? `Call: ${String(row.failure_context).split("Call:")[1].trim()}`
      : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildJiraPickCell(row, groupName, absIndex) {
  const similar = Array.isArray(row.similar_jiras) ? row.similar_jiras : [];
  const linked = Array.isArray(row.existing_defects)
    ? row.existing_defects.filter(Boolean)
    : [];
  const mode = row.selected_jira_mode || "none";
  const selectedKey = normalizeSelectedJira(row.selected_jira || "");
  const customVal = escapeHtml(row.selected_jira_custom || "");

  const options = [];
  options.push(`
    <label class="triage-pick">
      <input type="radio" name="${escapeHtml(groupName)}" value="none" data-mode="none"
        ${mode === "none" ? "checked" : ""}>
      <span>None</span>
    </label>
  `);

  linked.forEach((key) => {
    const k = normalizeSelectedJira(key);
    const checked =
      mode === "linked" && selectedKey === k ? "checked" : "";
    options.push(`
      <label class="triage-pick">
        <input type="radio" name="${escapeHtml(groupName)}" value="${escapeHtml(k)}"
          data-mode="linked" ${checked}>
        <span>
          <strong>${escapeHtml(k)}</strong>
          <span class="muted">(linked)</span>
        </span>
      </label>
    `);
  });

  similar.forEach((h) => {
    const k = normalizeSelectedJira(h.key || "");
    if (!k) return;
    const checked =
      mode === "similar" && selectedKey === k ? "checked" : "";
    const status = escapeHtml(h.status || "");
    const summary = escapeHtml((h.summary || "").slice(0, 90));
    const url = escapeHtml(h.url || "#");
    options.push(`
      <label class="triage-pick">
        <input type="radio" name="${escapeHtml(groupName)}" value="${escapeHtml(k)}"
          data-mode="similar" ${checked}>
        <span>
          <a href="${url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${escapeHtml(k)}</a>
          ${status ? `<span class="muted">(${status})</span>` : ""}
          ${summary ? `<br><span class="muted">${summary}</span>` : ""}
        </span>
      </label>
    `);
  });

  options.push(`
    <label class="triage-pick triage-pick-other">
      <input type="radio" name="${escapeHtml(groupName)}" value="__custom__" data-mode="custom"
        ${mode === "custom" ? "checked" : ""}>
      <span>Other</span>
    </label>
    <input type="text" class="triage-custom-jira"
      placeholder="SI91X-12345" value="${customVal}"
      title="Applied to all cases with the same failure description; remembered on later uploads"
      ${mode === "custom" ? "" : "disabled"}>
  `);

  if (!similar.length && !linked.length) {
    options.splice(
      1,
      0,
      `<div class="muted small" style="margin:4px 0;">No similar Jiras found — type a key below.</div>`
    );
  }

  return `<div class="triage-pick-list" data-abs-index="${absIndex}">${options.join("")}</div>`;
}

function refreshTriageSelectionCells(listEl, row) {
  const tr = listEl.closest("tr");
  if (!tr) return;
  // Columns: kind, map id, case, section, reason, api, linked, selected, pick, title
  const linkedTd = tr.children[6];
  const selectedTd = tr.children[7];
  if (linkedTd) linkedTd.innerHTML = formatMultilineCell(linkedJirasText(row));
  if (selectedTd) {
    selectedTd.innerHTML = formatMultilineCell(selectedJiraDisplay(row));
    selectedTd.classList.toggle("triage-selected-cell", !!getFailureTriageSelection(row));
  }
  listEl.querySelectorAll(".triage-pick").forEach((label) => {
    const radio = label.querySelector('input[type="radio"]');
    label.classList.toggle("is-checked", !!(radio && radio.checked));
  });
}

function bindFailureTriagePickers(bodyEl) {
  if (!bodyEl) return;
  const allRows = allFailureTriageRows();
  bodyEl.querySelectorAll(".triage-pick-list").forEach((listEl) => {
    const absIndex = Number(listEl.dataset.absIndex);
    const target = Number.isFinite(absIndex) ? allRows[absIndex] : null;
    if (!target) return;

    listEl.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        const mode = radio.dataset.mode || "none";
        const customInput = listEl.querySelector(".triage-custom-jira");
        target.selected_jira_mode = mode;
        if (mode === "custom") {
          if (customInput) {
            customInput.disabled = false;
            customInput.focus();
          }
          target.selected_jira_custom = (customInput && customInput.value) || "";
          syncFailureTriageSelection(target);
          // Don't propagate/repaint while the user is about to type a key.
          saveFailureTriagePick(target, { propagate: false });
          refreshTriageSelectionCells(listEl, target);
          return;
        }
        if (customInput) customInput.disabled = true;
        target.selected_jira =
          mode === "none" ? "" : normalizeSelectedJira(radio.value);
        syncFailureTriageSelection(target);
        saveFailureTriagePick(target);
        refreshTriageSelectionCells(listEl, target);
      });
    });

    const customInput = listEl.querySelector(".triage-custom-jira");
    if (customInput) {
      // While typing: update this row only. Propagate on blur/Enter so the
      // table is not re-rendered on every keystroke (which steals focus).
      customInput.addEventListener("input", () => {
        target.selected_jira_mode = "custom";
        target.selected_jira_custom = customInput.value || "";
        const otherRadio = listEl.querySelector('input[data-mode="custom"]');
        if (otherRadio) otherRadio.checked = true;
        customInput.disabled = false;
        syncFailureTriageSelection(target);
        saveFailureTriagePick(target, { propagate: false });
        refreshTriageSelectionCells(listEl, target);
      });
      const commitCustomJira = () => {
        target.selected_jira_mode = "custom";
        target.selected_jira_custom = customInput.value || "";
        syncFailureTriageSelection(target);
        saveFailureTriagePick(target, { propagate: true });
      };
      customInput.addEventListener("blur", commitCustomJira);
      customInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          customInput.blur();
        }
      });
      customInput.addEventListener("focus", () => {
        const otherRadio = listEl.querySelector('input[data-mode="custom"]');
        if (otherRadio && !otherRadio.checked) {
          otherRadio.checked = true;
          target.selected_jira_mode = "custom";
          target.selected_jira_custom = customInput.value || "";
          customInput.disabled = false;
          syncFailureTriageSelection(target);
          saveFailureTriagePick(target, { propagate: false });
          refreshTriageSelectionCells(listEl, target);
        }
      });
    }
  });
}

function paintFailureTriagePage(page) {
  const bodyEl = document.getElementById("failureTriageBody");
  const pagerEl = document.getElementById("failureTriagePager");
  const tableWrap = document.getElementById("failureTriageTableWrap");
  const rows = allFailureTriageRows();
  const state = paginatePreviewRows(rows, page, PREVIEW_PAGE_SIZE);
  _failureTriageState.page = state.page;
  if (bodyEl) {
    bodyEl.innerHTML = "";
    state.slice.forEach((row, i) => {
      const absIndex = state.start + i;
      const groupName = failureTriageRowKey(row, absIndex);
      if (!row.selected_jira_mode) {
        row.selected_jira_mode = "none";
        row.selected_jira = "";
        row.selected_jira_custom = "";
      }
      syncFailureTriageSelection(row);
      const tr = document.createElement("tr");
      const kind = triageRowKind(row);
      const kindClass = kind === "TODO" ? "chip todo-chip" : "chip fail-chip";
      const kindTitle = row.untested_fail
        ? "Untested in Xray — treated as FAIL for triage"
        : "";
      const kindLabel = row.untested_fail ? "FAIL (untested)" : kind;
      const reason = cleanReasonDisplay(
        row.reason_short ||
          row.reason ||
          row.key_error ||
          row.explanation ||
          ""
      );
      const details = failureDetailsDisplay(row);
      const linkedText = linkedJirasText(row);
      const selectedText = selectedJiraDisplay(row);
      const sectionPath = String(row.section_path || "").trim();
      const sectionName =
        String(row.section || "").trim() ||
        (sectionPath ? sectionPath.split("/").pop() : "");
      const sectionCell = sectionName
        ? `<span title="${escapeHtml(sectionPath || sectionName)}">${escapeHtml(
            sectionName
          )}</span>`
        : "—";
      const caseCell = row.key
        ? `<a href="${escapeHtml(row.url || "#")}" target="_blank" rel="noopener">${escapeHtml(row.key)}</a>`
        : `<span class="muted">unmatched</span>`;
      tr.innerHTML = `
        <td class="nowrap"><span class="${kindClass}"${
          kindTitle ? ` title="${escapeHtml(kindTitle)}"` : ""
        }>${escapeHtml(kindLabel)}</span></td>
        <td class="nowrap">${escapeHtml(row.test_src_map_id || "")}</td>
        <td class="nowrap">${caseCell}</td>
        <td class="small">${sectionCell}</td>
        <td class="small">${formatMultilineCell(reason)}</td>
        <td class="small">${formatMultilineCell(details)}</td>
        <td class="small">${formatMultilineCell(linkedText)}</td>
        <td class="small triage-selected-cell">${formatMultilineCell(selectedText)}</td>
        <td class="small">${buildJiraPickCell(row, groupName, absIndex)}</td>
        <td>${escapeHtml(row.summary || row.test_name || "")}</td>
      `;
      bodyEl.appendChild(tr);
    });
    bindFailureTriagePickers(bodyEl);
    bodyEl.querySelectorAll(".triage-pick-list").forEach((listEl) => {
      const absIndex = Number(listEl.dataset.absIndex);
      const allRows = allFailureTriageRows();
      const target = Number.isFinite(absIndex) ? allRows[absIndex] : null;
      if (target) refreshTriageSelectionCells(listEl, target);
    });
  }
  renderPreviewPager(pagerEl, state, paintFailureTriagePage);
  if (tableWrap) tableWrap.hidden = rows.length === 0;
}

function renderFailureTriage(data) {
  const panel = document.getElementById("failureTriagePanel");
  if (!panel) return;
  const statusEl = document.getElementById("failureTriageStatus");
  const summaryEl = document.getElementById("failureTriageSummary");
  const unmatchedEl = document.getElementById("failureTriageUnmatched");
  const downloadBtn = document.getElementById("failureTriageDownloadBtn");

  const failures = data.failures || [];
  const unmatched = data.unmatched_failures || [];
  const todoCases = data.todo_cases || [];
  const todoCount =
    data.todo_count != null ? data.todo_count : todoCases.length;
  // Restore remembered picks (Other / selected Jira) for the same C###### cases.
  [...failures, ...unmatched, ...todoCases].forEach((row) => {
    if (!row.selected_jira_mode || row.selected_jira_mode === "none") {
      applySavedFailureTriagePick(row);
    }
    syncFailureTriageSelection(row);
  });
  _failureTriageState = {
    execution: data.execution || resolveImportExecution() || "",
    failures,
    unmatched,
    todoCases,
    todoCount,
    page: 1,
  };

  const totalFail =
    (data.failure_count != null ? data.failure_count : failures.length) +
    (data.unmatched_failure_count != null
      ? data.unmatched_failure_count
      : unmatched.length);
  const totalRows = totalFail + todoCases.length;

  if (!totalRows) {
    panel.hidden = true;
    if (downloadBtn) downloadBtn.disabled = true;
    return;
  }

  panel.hidden = false;
  if (downloadBtn) downloadBtn.disabled = false;
  const skippedPass = data.skipped_xray_pass_count || 0;
  const withReportFail = failures.filter(
    (f) => String(f.html_status || "").toUpperCase() === "FAIL"
  ).length;
  if (statusEl) {
    const bits = [];
    if (todoCount || failures.length) {
      bits.push(
        `${failures.length || todoCount} TODO / untested to triage` +
          (withReportFail
            ? ` (${withReportFail} with report FAIL/ERROR)`
            : "")
      );
    }
    if (skippedPass) {
      bits.push(`${skippedPass} report FAIL skipped (already PASS in Xray)`);
    }
    statusEl.textContent = bits.join("; ");
    statusEl.className = "small muted";
  }
  if (summaryEl) {
    const withJira = failures.filter(
      (f) => (f.existing_defects || []).length > 0
    ).length;
    const withSimilar = failures.filter(
      (f) => (f.similar_jiras || []).length > 0 || f.similar_jiras_text
    ).length;
    summaryEl.hidden = false;
    summaryEl.innerHTML = `
      <span class="chip">TODO / untested: ${todoCount || failures.length}</span>
      <span class="chip">With report FAIL: ${withReportFail}</span>
      <span class="chip">Skipped already PASS in Xray: ${skippedPass}</span>
      <span class="chip">With linked Jiras: ${withJira}</span>
      <span class="chip">With similar Jiras: ${withSimilar}</span>
      <span class="chip">Preview only — no Jira/Xray writes</span>
    `;
  }
  paintFailureTriagePage(1);
  if (unmatchedEl) {
    if (!unmatched.length) {
      unmatchedEl.textContent = "";
    } else {
      unmatchedEl.textContent =
        `Not in execution (${unmatched.length}): ` +
        unmatched
          .slice(0, 16)
          .map((u) => u.test_src_map_id)
          .join(", ") +
        (unmatched.length > 16 ? "…" : "");
    }
  }
  if (typeof panel.scrollIntoView === "function") {
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function initFailureTriage() {
  const downloadBtn = document.getElementById("failureTriageDownloadBtn");
  if (!downloadBtn || downloadBtn.dataset.bound) return;
  downloadBtn.dataset.bound = "1";
  downloadBtn.addEventListener("click", async () => {
    const execution =
      _failureTriageState.execution || resolveImportExecution();
    const failures = _failureTriageState.failures || [];
    const unmatched = _failureTriageState.unmatched || [];
    const todoCases = _failureTriageState.todoCases || [];
    if (!execution) {
      showToast("Select a Test Execution first.", "warn");
      return;
    }
    if (!failures.length && !unmatched.length && !todoCases.length) {
      showToast("No triage rows to download.", "warn");
      return;
    }
    downloadBtn.disabled = true;
    downloadBtn.textContent = "Preparing…";
    try {
      [...failures, ...unmatched, ...todoCases].forEach((row) =>
        syncFailureTriageSelection(row)
      );
      const resp = await fetch("/api/failure-triage/download/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          execution,
          failures,
          unmatched_failures: unmatched,
          todo_cases: todoCases,
        }),
      });
      if (!resp.ok) {
        let msg = "Download failed";
        try {
          const err = await resp.json();
          msg = err.error || msg;
        } catch (_e) {
          /* ignore */
        }
        throw new Error(msg);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${execution}_failure_triage.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err.message || "Download failed", "error");
    } finally {
      downloadBtn.disabled = false;
      downloadBtn.textContent = "Download triage Excel";
    }
  });
}

let _applyPollTimer = null;

function paintApplyProgress(job) {
  const box = document.getElementById("applyProgress");
  if (!box) return;
  box.hidden = false;
  const titleEl = document.getElementById("applyProgressTitle");
  const metaEl = document.getElementById("applyProgressMeta");
  const detailEl = document.getElementById("applyProgressDetail");
  const barEl = document.getElementById("applyProgressBar");
  const statsEl = document.getElementById("applyProgressStats");
  const dismissBtn = document.getElementById("applyProgressDismissBtn");
  const pct = Math.max(0, Math.min(100, Number(job.percent) || 0));
  const total = Number(job.total) || 0;
  const done = Number(job.done) || 0;
  const left =
    job.left != null ? Number(job.left) : Math.max(0, total - done);
  const updated = Number(job.updated_count) || 0;
  const failed = Number(job.failed_count) || 0;

  if (barEl) {
    barEl.style.width = `${pct}%`;
    barEl.setAttribute("aria-valuenow", String(pct));
  }
  if (titleEl) {
    titleEl.textContent =
      job.status === "done"
        ? "Results update complete"
        : job.status === "error"
          ? "Results update failed"
          : job.message || "Updating results…";
  }
  const bits = [];
  if (total) bits.push(`${done}/${total}`);
  bits.push(`${pct}%`);
  if (job.status === "running" || job.status === "queued") {
    const eta = formatEta(job.eta_seconds);
    if (eta) bits.push(eta);
  }
  if (metaEl) metaEl.textContent = bits.join(" · ");
  if (statsEl) {
    statsEl.hidden = false;
    statsEl.innerHTML = `
      <span class="chip">Done: ${done}</span>
      <span class="chip">Left: ${left}</span>
      <span class="chip">Total: ${total}</span>
      <span class="chip">${pct}%</span>
      <span class="chip">OK: ${updated}</span>
      <span class="chip">Failed: ${failed}</span>
    `;
  }
  if (detailEl) {
    if (job.status === "error") {
      detailEl.textContent = job.error || "Unknown error";
      detailEl.className = "small alert-error-inline";
    } else if (job.current) {
      detailEl.textContent = `Current: ${job.current}`;
      detailEl.className = "small muted";
    } else {
      detailEl.textContent = job.message || "";
      detailEl.className = "small muted";
    }
  }
  if (dismissBtn) {
    dismissBtn.hidden = !(job.status === "done" || job.status === "error");
  }
}

function stopApplyPoll() {
  if (_applyPollTimer) {
    clearInterval(_applyPollTimer);
    _applyPollTimer = null;
  }
}

async function runPassApplyWithProgress({
  applyUrl,
  execution,
  updates,
  customFields,
  applyBtn,
  setStatus,
  syncApply,
}) {
  const dismissBtn = document.getElementById("applyProgressDismissBtn");
  if (dismissBtn && !dismissBtn.dataset.bound) {
    dismissBtn.dataset.bound = "1";
    dismissBtn.addEventListener("click", () => {
      const box = document.getElementById("applyProgress");
      if (box) box.hidden = true;
    });
  }

  stopApplyPoll();
  if (applyBtn) {
    applyBtn.disabled = true;
    applyBtn.textContent = "Updating…";
  }
  paintApplyProgress({
    status: "queued",
    percent: 1,
    message: "Starting update…",
    done: 0,
    total: updates.length,
    left: updates.length,
    updated_count: 0,
    failed_count: 0,
  });
  const box = document.getElementById("applyProgress");
  if (box && typeof box.scrollIntoView === "function") {
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const resp = await fetch(applyUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify({
      execution,
      updates,
      custom_fields: customFields || {},
    }),
  });
  const started = await resp.json();
  if (!resp.ok) throw new Error(started.error || "Failed to start update");
  const jobId = started.id;
  if (!jobId) throw new Error("No job id returned");

  paintApplyProgress(started);

  return new Promise((resolve, reject) => {
    const finish = (job, err) => {
      stopApplyPoll();
      if (err) {
        paintApplyProgress({
          status: "error",
          percent: 0,
          message: "Update failed",
          error: err.message || "Update failed",
          total: updates.length,
          done: 0,
          left: updates.length,
        });
        if (applyBtn) {
          applyBtn.disabled = false;
          applyBtn.textContent = "Submit PASS";
        }
        if (syncApply) syncApply();
        if (setStatus) setStatus(err.message || "Apply failed", true);
        reject(err);
        return;
      }
      paintApplyProgress(job);
      const result = job.result || {};
      const failed = job.failed_count || result.failed_count || 0;
      const updated = job.updated_count || result.updated_count || 0;
      const cfErr = job.custom_fields_error || result.custom_fields_error || "";
      const cfPosted =
        job.custom_fields_posted || result.custom_fields_posted || 0;
      const skipped = (
        job.custom_fields_skipped ||
        result.custom_fields_skipped ||
        []
      ).join(", ");
      const cfCount = Object.keys(customFields || {}).length;
      const msg =
        `Updated ${updated} run(s)` +
        (cfPosted ? ` · custom fields: ${cfPosted}` : "") +
        (skipped ? ` · skipped: ${skipped}` : "") +
        (failed ? ` · failed: ${failed}` : "") +
        (cfErr ? ` · ${cfErr}` : "");
      showToast(msg, failed || cfErr ? "warn" : "ok", 6500);
      const execKey = resolveImportExecution() || currentExecutionKey();
      refreshExecutionSummary(execKey).then(() => {
        showToast("Summary refreshed. Use Refresh on Plan/Execution for full case list.", "info", 5000);
      });
      if (applyBtn) {
        applyBtn.disabled = false;
        applyBtn.textContent = "Submit PASS";
      }
      if (syncApply) syncApply();
      resolve(job);
    };

    const pollOnce = async () => {
      try {
        const r = await fetch(`/api/apply-jobs/${encodeURIComponent(jobId)}/`);
        const job = await r.json();
        if (!r.ok) throw new Error(job.error || "Progress check failed");
        paintApplyProgress(job);
        if (job.status === "done" || job.status === "error") {
          if (job.status === "error") {
            finish(job, new Error(job.error || "Update failed"));
          } else {
            finish(job);
          }
        }
      } catch (err) {
        finish(null, err);
      }
    };

    pollOnce();
    _applyPollTimer = setInterval(pollOnce, 800);
  });
}

function collectCustomFieldValues() {
  const values = {};
  document.querySelectorAll(".custom-field-select").forEach((sel) => {
    const key = sel.dataset.fieldKey;
    if (!key) return;
    const other = document.querySelector(
      `.custom-field-other[data-field-key="${key}"]`
    );
    if (other && !other.hidden && other.value.trim()) {
      values[key] = other.value.trim();
      return;
    }
    if (sel.value) values[key] = sel.value;
  });
  return values;
}

function bindCustomFieldToggles(panel) {
  panel.querySelectorAll(".custom-field-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.fieldKey;
      const other = panel.querySelector(
        `.custom-field-other[data-field-key="${key}"]`
      );
      const sel = panel.querySelector(
        `.custom-field-select[data-field-key="${key}"]`
      );
      if (!other || !sel) return;
      const show = other.hidden;
      other.hidden = !show;
      sel.disabled = show;
      btn.textContent = show ? "Use list" : "Custom";
      if (show) other.focus();
    });
  });
}

function renderCustomFields(fields) {
  const grid = document.getElementById("customFieldsGrid");
  if (!grid) return;
  const previous = collectCustomFieldValues();
  grid.innerHTML = "";
  (fields || []).forEach((field) => {
    const key = field.key || `trcf_${field.id}`;
    const label = document.createElement("label");
    label.className = "custom-field";
    label.dataset.fieldKey = key;

    const options = field.options || [];
    const selected = previous[key] || field.current || "";
    const optionHtml = ['<option value="">None</option>']
      .concat(
        options.map((opt) => {
          const safe = String(opt)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/"/g, "&quot;");
          const isSel = String(opt) === String(selected) ? " selected" : "";
          return `<option value="${safe}"${isSel}>${safe}</option>`;
        })
      )
      .join("");

    label.innerHTML = `
      <span class="label">${field.label || key}</span>
      <select class="custom-field-select" data-field-key="${key}" data-field-id="${field.id || ""}">
        ${optionHtml}
      </select>
      <input type="text" class="custom-field-other" data-field-key="${key}"
             placeholder="Or type a value" hidden>
      <button type="button" class="btn btn-tiny custom-field-toggle" data-field-key="${key}">
        Custom
      </button>
    `;
    grid.appendChild(label);

    // Preserve a typed/custom value that wasn't in the option list.
    if (selected && !options.map(String).includes(String(selected))) {
      const other = label.querySelector(".custom-field-other");
      const sel = label.querySelector(".custom-field-select");
      const btn = label.querySelector(".custom-field-toggle");
      if (other && sel && btn) {
        other.hidden = false;
        other.value = selected;
        sel.disabled = true;
        btn.textContent = "Use list";
      }
    }
  });
  bindCustomFieldToggles(document.getElementById("customFieldsPanel"));
}

async function loadCustomFields(forceRefresh) {
  const statusEl = document.getElementById("customFieldsStatus");
  const execution = resolveImportExecution();
  if (!execution) {
    if (statusEl) statusEl.textContent = "Select a Test Execution to load fields.";
    return;
  }
  if (statusEl) statusEl.textContent = "Loading field mapping…";
  try {
    const qs = new URLSearchParams({
      execution,
      refresh: forceRefresh ? "1" : "0",
    });
    const resp = await fetch(`/api/results-update/fields/?${qs.toString()}`, {
      headers: { "X-CSRFToken": getCsrfToken() },
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Unable to load fields");
    renderCustomFields(data.fields || []);
    if (statusEl) {
      if (data.ready || data.mapped_ids) {
        const src = (data.discovered_from || []).join(", ") || "xray";
        statusEl.textContent = `Discovered ${data.mapped_ids} field ID(s) from ${src}`;
        statusEl.className = "small muted";
      } else {
        statusEl.textContent =
          "Field mapping unavailable — PASS can still post; custom values need Refresh after Jira access.";
        statusEl.className = "small muted";
      }
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = err.message || "Unable to load fields";
      statusEl.className = "small alert-error-inline";
    }
  }
}

function initCustomFields() {
  const panel = document.getElementById("customFieldsPanel");
  if (!panel) return;
  bindCustomFieldToggles(panel);
  const reloadBtn = document.getElementById("customFieldsReloadBtn");
  if (reloadBtn) {
    reloadBtn.addEventListener("click", () => loadCustomFields(true));
  }
  const execEl = document.getElementById("resultsExecutionSelect");
  if (execEl) {
    execEl.addEventListener("change", () => loadCustomFields(false));
  }
  // Use cached mapping first; Refresh button forces a full probe.
  loadCustomFields(false);
}

const PREVIEW_PAGE_SIZE = 50;

function paginatePreviewRows(rows, page, pageSize) {
  const size = pageSize || PREVIEW_PAGE_SIZE;
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / size) || 1);
  const safePage = Math.min(Math.max(1, page || 1), totalPages);
  const start = (safePage - 1) * size;
  return {
    page: safePage,
    totalPages,
    total,
    start,
    slice: rows.slice(start, start + size),
    showingFrom: total ? start + 1 : 0,
    showingTo: Math.min(start + size, total),
  };
}

function renderPreviewPager(hostEl, state, onPage) {
  if (!hostEl) return;
  if (state.total <= PREVIEW_PAGE_SIZE) {
    hostEl.innerHTML = "";
    hostEl.hidden = true;
    return;
  }
  hostEl.hidden = false;
  hostEl.classList.add("cases-pager-meta");
  hostEl.innerHTML = `
    <span class="small muted">${state.showingFrom}–${state.showingTo} of ${state.total}</span>
    <button type="button" class="btn btn-compact" data-preview-page="prev" ${
      state.page <= 1 ? "disabled" : ""
    }>Previous</button>
    <span class="small muted">Page ${state.page} / ${state.totalPages}</span>
    <button type="button" class="btn btn-compact" data-preview-page="next" ${
      state.page >= state.totalPages ? "disabled" : ""
    }>Next</button>
  `;
  hostEl.querySelectorAll("[data-preview-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = btn.getAttribute("data-preview-page");
      onPage(dir === "next" ? state.page + 1 : state.page - 1);
    });
  });
}

function isHtmlUploadFile(file) {
  if (!file || !file.name) return false;
  const name = String(file.name).toLowerCase();
  const path = String(file.webkitRelativePath || file.name).toLowerCase();
  if (name.endsWith(".htm") || name.endsWith(".html")) return true;
  if (path.endsWith(".htm") || path.endsWith(".html")) return true;
  const type = String(file.type || "").toLowerCase();
  return type === "text/html" || type === "application/xhtml+xml";
}

function isZipUploadFile(file) {
  if (!file || !file.name) return false;
  const name = String(file.name).toLowerCase();
  const path = String(file.webkitRelativePath || file.name).toLowerCase();
  if (name.endsWith(".zip") || path.endsWith(".zip")) return true;
  const type = String(file.type || "").toLowerCase();
  return (
    type === "application/zip" ||
    type === "application/x-zip-compressed" ||
    type === "multipart/x-zip"
  );
}

function collectNamedUploadFiles(filesEl, folderEl, isMatch) {
  const out = [];
  const seen = new Set();
  const rawFolder = [];

  const pushFile = (f, force) => {
    if (!f) return;
    if (!force && !isMatch(f)) return;
    // Exact-selection dedupe only; basename/hash dedupe is server-side.
    const key = `${f.webkitRelativePath || f.name}:${f.size}:${f.lastModified}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(f);
  };

  if (filesEl && filesEl.files) {
    Array.from(filesEl.files).forEach((f) => pushFile(f, false));
  }
  if (folderEl && folderEl.files) {
    Array.from(folderEl.files).forEach((f) => {
      rawFolder.push(f);
      pushFile(f, false);
    });
    if (!out.length && rawFolder.length) {
      rawFolder.forEach((f) => pushFile(f, true));
    }
  }
  return out;
}

function collectHtmlUploadFiles(filesEl, folderEl) {
  return collectNamedUploadFiles(filesEl, folderEl, isHtmlUploadFile);
}

function collectZipUploadFiles(filesEl, folderEl) {
  return collectNamedUploadFiles(filesEl, folderEl, isZipUploadFile);
}

function duplicateSkipChip(data) {
  const n = data.duplicate_files_skipped_count || 0;
  if (!n) return "";
  return `<span class="chip">Duplicates removed: ${n}</span>`;
}

function htmlUploadFileName(file) {
  const rel = (file.webkitRelativePath || "").replace(/\\/g, "/").trim();
  if (rel) return rel.split("/").pop() || file.name || "upload.htm";
  return file.name || "upload.htm";
}

function bindHtmlPassImportPanel(cfg) {
  const panel = document.getElementById(cfg.panelId);
  if (!panel) return;

  const technology = panel.dataset.technology || "";
  const previewBtn = document.getElementById(cfg.previewBtnId);
  const applyBtn = document.getElementById(cfg.applyBtnId);
  const pathEl = cfg.pathElId ? document.getElementById(cfg.pathElId) : null;
  const filesEl = cfg.filesElId ? document.getElementById(cfg.filesElId) : null;
  const folderEl = cfg.folderElId
    ? document.getElementById(cfg.folderElId)
    : null;
  const hintEl = document.getElementById(cfg.hintElId);
  const statusEl = document.getElementById(cfg.statusElId);
  const summaryEl = document.getElementById(cfg.summaryElId);
  const tableWrap = document.getElementById(cfg.tableWrapId);
  const bodyEl = document.getElementById(cfg.bodyElId);
  const unmatchedEl = document.getElementById(cfg.unmatchedElId);
  const selectAllEl = document.getElementById(cfg.selectAllElId);
  const pagerEl = document.getElementById(cfg.pagerElId);
  const checkClass = cfg.checkClass || "html-import-check";
  const emptyMsg =
    cfg.emptyMsg ||
    "Select HTML file(s), or use Import Folder / Import ZIP.";

  if (!previewBtn) return;

  const hintBase = hintEl ? hintEl.innerHTML : "";

  function refreshUploadHint() {
    if (!hintEl) return;
    const folderCount = folderEl && folderEl.files ? folderEl.files.length : 0;
    const files = collectHtmlUploadFiles(filesEl, folderEl);
    const pathVal = pathEl ? pathEl.value.trim() : "";
    const bits = [hintBase];
    if (folderCount) {
      bits.push(`Folder picker: <strong>${folderCount}</strong> item(s)`);
    }
    if (files.length) {
      const sample = files
        .slice(0, 3)
        .map((f) => f.webkitRelativePath || f.name)
        .join(", ");
      bits.push(
        `<strong>${files.length} HTML file(s) will be uploaded</strong>` +
          (sample ? `: ${sample}${files.length > 3 ? "…" : ""}` : "")
      );
    } else if (folderCount) {
      bits.push(
        `<span class="alert-error-inline">No .htm/.html files detected in folder</span>`
      );
    }
    if (pathVal) bits.push(`Server path set`);
    hintEl.innerHTML = bits.join(" · ");
  }

  if (filesEl) filesEl.addEventListener("change", refreshUploadHint);
  if (folderEl) folderEl.addEventListener("change", refreshUploadHint);
  if (pathEl) pathEl.addEventListener("input", refreshUploadHint);
  refreshUploadHint();

  let lastMatches = [];
  let selectedIdx = new Set();
  let previewPage = 1;

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = isError ? "small alert-error-inline" : "small muted";
  }

  function syncApply() {
    if (applyBtn) applyBtn.disabled = selectedIdx.size === 0;
    if (selectAllEl) {
      selectAllEl.checked =
        lastMatches.length > 0 && selectedIdx.size === lastMatches.length;
      selectAllEl.indeterminate =
        selectedIdx.size > 0 && selectedIdx.size < lastMatches.length;
    }
  }

  function paintPreviewPage(page) {
    const state = paginatePreviewRows(lastMatches, page, PREVIEW_PAGE_SIZE);
    previewPage = state.page;
    if (bodyEl) {
      bodyEl.innerHTML = "";
      const start = (state.page - 1) * PREVIEW_PAGE_SIZE;
      state.slice.forEach((row, offset) => {
        const idx = start + offset;
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="check-col">
            <input type="checkbox" class="${checkClass}" data-idx="${idx}" ${
              selectedIdx.has(idx) ? "checked" : ""
            }>
          </td>
          <td class="nowrap">${row.test_src_map_id || ""}</td>
          <td class="nowrap"><a href="${row.url || "#"}" target="_blank" rel="noopener">${row.key || ""}</a></td>
          <td><span class="status-pill status-${row.current_status}">${row.current_status}</span></td>
          <td><span class="status-pill status-${row.html_status}">${row.html_status}</span></td>
          <td>${row.summary || ""}</td>
        `;
        bodyEl.appendChild(tr);
      });
      bodyEl.querySelectorAll(`.${checkClass}`).forEach((el) => {
        el.addEventListener("change", () => {
          const idx = Number(el.dataset.idx);
          if (el.checked) selectedIdx.add(idx);
          else selectedIdx.delete(idx);
          syncApply();
        });
      });
    }
    renderPreviewPager(pagerEl, state, paintPreviewPage);
    if (tableWrap) tableWrap.hidden = lastMatches.length === 0;
    syncApply();
  }

  function renderPreview(data) {
    lastMatches = data.matches || [];
    selectedIdx = new Set(lastMatches.map((_, idx) => idx));
    previewPage = 1;
    if (summaryEl) {
      const counts = data.status_counts || {};
      const parts = Object.keys(counts).map((k) => `${k}: ${counts[k]}`);
      const triageFail = (data.failures || []).filter(
        (f) => String(f.html_status || "").toUpperCase() === "FAIL"
      ).length;
      summaryEl.hidden = false;
      summaryEl.innerHTML = `
        <span class="chip">Files: ${(data.files || []).length}</span>
        <span class="chip">Parsed IDs: ${data.parsed_map_ids || 0}</span>
        <span class="chip">PASS to update: ${data.match_count || 0}</span>
        <span class="chip">TODO triage: ${data.todo_count || 0}</span>
        <span class="chip">TODO with report FAIL: ${triageFail}</span>
        <span class="chip">Skipped: ${data.skipped_count || 0}</span>
        <span class="chip">Unmatched: ${data.unmatched_count || 0}</span>
        ${duplicateSkipChip(data)}
        ${parts.map((p) => `<span class="chip">${p}</span>`).join("")}
      `;
    }

    paintPreviewPage(1);
    renderFailureTriage(data);

    if (unmatchedEl) {
      const unmatched = data.unmatched_html || [];
      const skipped = data.skipped || [];
      const noRun = data.no_run_id || [];
      const errors = data.parse_errors || [];
      const dupes = data.duplicate_files_skipped || [];
      const bits = [];
      if (errors.length) {
        bits.push(`Parse issues: ${errors.map((e) => e.error || e).join("; ")}`);
      }
      if (dupes.length) {
        bits.push(
          `Duplicates removed (${dupes.length}): ${dupes
            .slice(0, 8)
            .map((d) => d.name || d.kept || "?")
            .join(", ")}${dupes.length > 8 ? "…" : ""}`
        );
      }
      const already = skipped.filter((s) => s.skip_reason === "already_present");
      if (already.length) {
        bits.push(
          `Already PASS — left untouched (${already.length}): ${already
            .slice(0, 10)
            .map((s) => s.test_src_map_id)
            .join(", ")}${already.length > 10 ? "…" : ""}`
        );
      }
      const failSkip = skipped.filter((s) => s.html_status !== "PASS");
      if (failSkip.length) {
        bits.push(
          `Not updating non-PASS (${failSkip.length}): ${failSkip
            .slice(0, 10)
            .map((s) => `${s.test_src_map_id}=${s.html_status}`)
            .join(", ")}${failSkip.length > 10 ? "…" : ""}`
        );
      }
      if (unmatched.length) {
        bits.push(
          `Not in execution (${unmatched.length}): ${unmatched
            .slice(0, 12)
            .map((u) => u.test_src_map_id)
            .join(", ")}${unmatched.length > 12 ? "…" : ""}`
        );
      }
      if (noRun.length) {
        bits.push(`${noRun.length} matched case(s) have no Xray run id`);
      }
      unmatchedEl.textContent = bits.join(" · ");
    }
  }

  previewBtn.addEventListener("click", async () => {
    const execution = resolveImportExecution();
    if (!execution) {
      setStatus("Select a Test Execution.", true);
      return;
    }
    const form = new FormData();
    form.append("execution", execution);
    form.append("technology", technology);
    form.append("only_changed", "1");
    const pathVal = pathEl ? pathEl.value.trim() : "";
    if (pathVal) form.append("folder_path", pathVal);
    const folderCount = folderEl && folderEl.files ? folderEl.files.length : 0;
    const uploadFiles = collectHtmlUploadFiles(filesEl, folderEl);
    uploadFiles.forEach((f) => form.append("files", f, htmlUploadFileName(f)));
    if (!pathVal && !uploadFiles.length) {
      setStatus(
        folderCount
          ? `Folder has ${folderCount} item(s) but no .htm/.html files were found.`
          : emptyMsg,
        true
      );
      return;
    }

    if (uploadFiles.length > 40) {
      setStatus(
        `Uploading ${uploadFiles.length} HTML files can exceed server limits. Prefer Import ZIP or a server folder path.`,
        true
      );
    }
    previewBtn.disabled = true;
    previewBtn.textContent = "Parsing…";
    setStatus(
      uploadFiles.length
        ? `Uploading/parsing ${uploadFiles.length} file(s)…`
        : "Parsing HTML from server path…"
    );
    try {
      const resp = await fetch("/api/html-import/preview/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: form,
      });
      const data = await parseJsonResponse(resp, "Preview failed");
      renderPreview(data);
      setStatus(
        data.match_count
          ? `Ready: ${data.match_count} PASS update(s). FAIL and already-PASS are not written.`
          : "No PASS updates to apply. Triage lists TODO / untested below."
      );
    } catch (err) {
      setStatus(err.message || "Preview failed", true);
    } finally {
      previewBtn.disabled = false;
      previewBtn.textContent = "Preview";
    }
  });

  if (selectAllEl) {
    selectAllEl.addEventListener("change", () => {
      if (selectAllEl.checked) {
        selectedIdx = new Set(lastMatches.map((_, idx) => idx));
      } else {
        selectedIdx = new Set();
      }
      paintPreviewPage(previewPage);
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      const execution = resolveImportExecution();
      const updates = Array.from(selectedIdx)
        .sort((a, b) => a - b)
        .map((idx) => lastMatches[idx])
        .filter((row) => row && row.html_status === "PASS")
        .map((row) => ({
          run_id: row.run_id,
          status: "PASS",
          key: row.key,
          test_src_map_id: row.test_src_map_id,
        }));
      if (!updates.length) return;
      const customFields = collectCustomFieldValues();
      const cfCount = Object.keys(customFields).length;
      if (
        !confirm(
          `Post ${updates.length} PASS result(s) to ${execution}` +
            (cfCount ? ` with ${cfCount} custom field(s)` : "") +
            `? Failed cases will not be updated.`
        )
      ) {
        return;
      }

      applyBtn.disabled = true;
      applyBtn.textContent = "Updating…";
      try {
        await runPassApplyWithProgress({
          applyUrl: "/api/html-import/apply/",
          execution,
          updates,
          customFields,
          applyBtn,
          setStatus,
          syncApply,
        });
      } catch (err) {
        // Status / button reset handled by runPassApplyWithProgress
      }
    });
  }
}

function initHtmlImport() {
  bindHtmlPassImportPanel({
    panelId: "htmlImportPanel",
    previewBtnId: "htmlPreviewBtn",
    applyBtnId: "htmlApplyBtn",
    filesElId: "htmlUploadFiles",
    hintElId: "htmlUploadHint",
    statusElId: "htmlImportStatus",
    summaryElId: "htmlImportSummary",
    tableWrapId: "htmlImportTableWrap",
    bodyElId: "htmlImportBody",
    unmatchedElId: "htmlImportUnmatched",
    selectAllElId: "htmlSelectAll",
    pagerElId: "htmlImportPager",
    checkClass: "html-import-check",
    emptyMsg: "Select one or more HTML files.",
  });
}

function initFolderImport() {
  bindHtmlPassImportPanel({
    panelId: "folderImportPanel",
    previewBtnId: "folderPreviewBtn",
    applyBtnId: "folderApplyBtn",
    pathElId: "folderServerPath",
    folderElId: "folderUploadFolder",
    hintElId: "folderUploadHint",
    statusElId: "folderImportStatus",
    summaryElId: "folderImportSummary",
    tableWrapId: "folderImportTableWrap",
    bodyElId: "folderImportBody",
    unmatchedElId: "folderImportUnmatched",
    selectAllElId: "folderSelectAll",
    pagerElId: "folderImportPager",
    checkClass: "folder-import-check",
    emptyMsg: "Select a folder of HTML reports, or enter a server path.",
  });
}

function initImportTabs() {
  const root = document.getElementById("importTabs");
  if (!root) return;
  const tabs = root.querySelectorAll(".import-tab");
  const panels = root.querySelectorAll("[data-tab-panel]");

  function activate(name) {
    const target = name || "export";
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === target;
      tab.classList.toggle("active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== target;
    });
    try {
      const url = new URL(window.location.href);
      if (target === "export") url.searchParams.set("tab", "export");
      else url.searchParams.delete("tab");
      window.history.replaceState({}, "", url.toString());
    } catch (err) {
      /* ignore */
    }
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activate(tab.dataset.tab || "export"));
  });

  const params = new URLSearchParams(window.location.search);
  const hash = (window.location.hash || "").replace(/^#/, "");
  const requested = params.get("tab") || hash;
  // Default to Export Excel so download is obvious; import tabs are one click away.
  let initial = "export";
  if (
    requested === "export" ||
    requested === "html" ||
    requested === "folder" ||
    requested === "zip" ||
    requested === "excel"
  ) {
    initial = requested;
  }
  activate(initial);
}

function zipUploadFileName(file) {
  const rel = (file.webkitRelativePath || "").replace(/\\/g, "/").trim();
  if (rel) return rel.split("/").pop() || file.name || "upload.zip";
  return file.name || "upload.zip";
}

function initZipImport() {
  const panel = document.getElementById("zipImportPanel");
  if (!panel) return;

  const previewBtn = document.getElementById("zipPreviewBtn");
  const applyBtn = document.getElementById("zipApplyBtn");
  const filesEl =
    document.getElementById("zipUploadFiles") ||
    document.getElementById("zipUploadFile");
  const folderEl = null;
  const hintEl = document.getElementById("zipUploadHint");
  const statusEl = document.getElementById("zipImportStatus");
  const summaryEl = document.getElementById("zipImportSummary");
  const tableWrap = document.getElementById("zipImportTableWrap");
  const bodyEl = document.getElementById("zipImportBody");
  const skippedEl = document.getElementById("zipImportSkipped");
  const selectAllEl = document.getElementById("zipSelectAll");

  if (!previewBtn) return;

  const hintBase = hintEl ? hintEl.innerHTML : "";

  function refreshUploadHint() {
    if (!hintEl) return;
    const folderCount = folderEl && folderEl.files ? folderEl.files.length : 0;
    const files = collectZipUploadFiles(filesEl, folderEl);
    const bits = [hintBase];
    if (folderCount) {
      bits.push(`Folder picker: <strong>${folderCount}</strong> item(s)`);
    }
    if (files.length) {
      const sample = files
        .slice(0, 3)
        .map((f) => f.webkitRelativePath || f.name)
        .join(", ");
      bits.push(
        `<strong>${files.length} ZIP(s) will be uploaded</strong>` +
          (sample ? `: ${sample}${files.length > 3 ? "…" : ""}` : "")
      );
    } else if (folderCount) {
      bits.push(
        `<span class="alert-error-inline">No .zip files detected from folder</span>`
      );
    }
    hintEl.innerHTML = bits.join(" · ");
  }

  if (filesEl) {
    filesEl.addEventListener("change", () => {
      if (folderEl && filesEl.files && filesEl.files.length) folderEl.value = "";
      refreshUploadHint();
    });
  }
  if (folderEl) {
    folderEl.addEventListener("change", () => {
      if (filesEl && folderEl.files && folderEl.files.length) filesEl.value = "";
      refreshUploadHint();
    });
  }
  refreshUploadHint();

  let lastMatches = [];
  let selectedIdx = new Set();
  let previewPage = 1;
  const pagerEl = document.getElementById("zipImportPager");

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = isError ? "small alert-error-inline" : "small muted";
  }

  function syncApply() {
    if (applyBtn) applyBtn.disabled = selectedIdx.size === 0;
    if (selectAllEl) {
      selectAllEl.checked =
        lastMatches.length > 0 && selectedIdx.size === lastMatches.length;
      selectAllEl.indeterminate =
        selectedIdx.size > 0 && selectedIdx.size < lastMatches.length;
    }
  }

  function paintPreviewPage(page) {
    const state = paginatePreviewRows(lastMatches, page, PREVIEW_PAGE_SIZE);
    previewPage = state.page;
    if (bodyEl) {
      bodyEl.innerHTML = "";
      const start = (state.page - 1) * PREVIEW_PAGE_SIZE;
      state.slice.forEach((row, offset) => {
        const idx = start + offset;
        const fileName = (row.source || "").split("/").pop();
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="check-col">
            <input type="checkbox" class="zip-import-check" data-idx="${idx}" ${
              selectedIdx.has(idx) ? "checked" : ""
            }>
          </td>
          <td class="nowrap">${row.test_src_map_id || ""}</td>
          <td class="nowrap"><a href="${row.url || "#"}" target="_blank" rel="noopener">${row.key || ""}</a></td>
          <td><span class="status-pill status-${row.current_status}">${row.current_status}</span></td>
          <td><span class="status-pill status-${row.html_status}">${row.html_status}</span></td>
          <td class="small muted nowrap" title="${row.source || ""}">${fileName || ""}</td>
          <td>${row.summary || ""}</td>
        `;
        bodyEl.appendChild(tr);
      });
      bodyEl.querySelectorAll(".zip-import-check").forEach((el) => {
        el.addEventListener("change", () => {
          const idx = Number(el.dataset.idx);
          if (el.checked) selectedIdx.add(idx);
          else selectedIdx.delete(idx);
          syncApply();
        });
      });
    }
    renderPreviewPager(pagerEl, state, paintPreviewPage);
    if (tableWrap) tableWrap.hidden = lastMatches.length === 0;
    syncApply();
  }

  function renderPreview(data) {
    lastMatches = data.matches || [];
    selectedIdx = new Set(lastMatches.map((_, idx) => idx));
    previewPage = 1;
    if (summaryEl) {
      const counts = data.status_counts || {};
      const parts = Object.keys(counts).map((k) => `${k}: ${counts[k]}`);
      const triageFail = (data.failures || []).filter(
        (f) => String(f.html_status || "").toUpperCase() === "FAIL"
      ).length;
      summaryEl.hidden = false;
      summaryEl.innerHTML = `
        <span class="chip">ZIPs: ${data.zip_count || 0}</span>
        <span class="chip">Reports: ${(data.files || []).length}</span>
        <span class="chip">Parsed IDs: ${data.parsed_map_ids || 0}</span>
        <span class="chip">PASS to update: ${data.match_count || 0}</span>
        <span class="chip">TODO triage: ${data.todo_count || 0}</span>
        <span class="chip">TODO with report FAIL: ${triageFail}</span>
        <span class="chip">Skipped: ${data.skipped_count || 0}</span>
        <span class="chip">Unmatched: ${data.unmatched_count || 0}</span>
        ${duplicateSkipChip(data)}
        ${parts.map((p) => `<span class="chip">${p}</span>`).join("")}
      `;
    }

    paintPreviewPage(1);
    renderFailureTriage(data);

    if (skippedEl) {
      const skipped = data.skipped || [];
      const unmatched = data.unmatched_html || [];
      const errors = data.parse_errors || [];
      const dupes = data.duplicate_files_skipped || [];
      const bits = [];
      if (errors.length) {
        bits.push(`Parse issues: ${errors.map((e) => e.error || e).join("; ")}`);
      }
      if (dupes.length) {
        bits.push(
          `Duplicates removed (${dupes.length}): ${dupes
            .slice(0, 8)
            .map((d) => d.name || d.kept || "?")
            .join(", ")}${dupes.length > 8 ? "…" : ""}`
        );
      }
      const already = skipped.filter((s) => s.skip_reason === "already_present");
      if (already.length) {
        bits.push(
          `Already PASS — left untouched (${already.length}): ${already
            .slice(0, 10)
            .map((s) => s.test_src_map_id)
            .join(", ")}${already.length > 10 ? "…" : ""}`
        );
      }
      const failSkip = skipped.filter((s) => s.html_status !== "PASS");
      if (failSkip.length) {
        bits.push(
          `Not updating non-PASS (${failSkip.length}): ${failSkip
            .slice(0, 10)
            .map((s) => `${s.test_src_map_id}=${s.html_status}`)
            .join(", ")}${failSkip.length > 10 ? "…" : ""}`
        );
      }
      if (unmatched.length) {
        bits.push(
          `Not in execution (${unmatched.length}): ${unmatched
            .slice(0, 12)
            .map((u) => u.test_src_map_id)
            .join(", ")}${unmatched.length > 12 ? "…" : ""}`
        );
      }
      skippedEl.textContent = bits.join(" · ");
    }
  }

  previewBtn.addEventListener("click", async () => {
    const execution = resolveImportExecution();
    if (!execution) {
      setStatus("Select a Test Execution.", true);
      return;
    }
    const folderCount = folderEl && folderEl.files ? folderEl.files.length : 0;
    const uploadFiles = collectZipUploadFiles(filesEl, folderEl);
    if (!uploadFiles.length) {
      setStatus(
        folderCount
          ? `Folder has ${folderCount} item(s) but no .zip files were found.`
          : "Select one or more ZIP files.",
        true
      );
      return;
    }

    const form = new FormData();
    form.append("execution", execution);
    uploadFiles.forEach((f) => form.append("zips", f, zipUploadFileName(f)));

    previewBtn.disabled = true;
    previewBtn.textContent = "Parsing…";
    setStatus(
      `Parsing ${uploadFiles.length} ZIP(s) in one preview…`
    );
    try {
      const resp = await fetch("/api/zip-import/preview/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: form,
      });
      const data = await parseJsonResponse(resp, "Preview failed");
      renderPreview(data);
      setStatus(
        data.match_count
          ? `Ready: ${data.match_count} PASS update(s). Non-PASS cases will not be written.`
          : "No PASS updates to apply. Triage lists TODO / untested below."
      );
    } catch (err) {
      setStatus(err.message || "Preview failed", true);
    } finally {
      previewBtn.disabled = false;
      previewBtn.textContent = "Preview";
    }
  });

  if (selectAllEl) {
    selectAllEl.addEventListener("change", () => {
      if (selectAllEl.checked) {
        selectedIdx = new Set(lastMatches.map((_, idx) => idx));
      } else {
        selectedIdx = new Set();
      }
      paintPreviewPage(previewPage);
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      const execution = resolveImportExecution();
      const updates = Array.from(selectedIdx)
        .sort((a, b) => a - b)
        .map((idx) => lastMatches[idx])
        .filter((row) => row && row.html_status === "PASS")
        .map((row) => ({
          run_id: row.run_id,
          status: "PASS",
          key: row.key,
          test_src_map_id: row.test_src_map_id,
        }));
      if (!updates.length) return;
      const customFields = collectCustomFieldValues();
      const cfCount = Object.keys(customFields).length;
      if (
        !confirm(
          `Post ${updates.length} PASS result(s) to ${execution}` +
            (cfCount ? ` with ${cfCount} custom field(s)` : "") +
            `? Failed cases will not be updated.`
        )
      ) {
        return;
      }

      applyBtn.disabled = true;
      applyBtn.textContent = "Updating…";
      try {
        await runPassApplyWithProgress({
          applyUrl: "/api/zip-import/apply/",
          execution,
          updates,
          customFields,
          applyBtn,
          setStatus,
          syncApply,
        });
      } catch (err) {
        // Status / button reset handled by runPassApplyWithProgress
      }
    });
  }
}

function initExcelImport() {
  const panel = document.getElementById("excelImportPanel");
  if (!panel) return;

  const previewBtn = document.getElementById("excelPreviewBtn");
  const applyBtn = document.getElementById("excelApplyBtn");
  const filesEl = document.getElementById("excelUploadFile");
  const statusEl = document.getElementById("excelImportStatus");
  const summaryEl = document.getElementById("excelImportSummary");
  const tableWrap = document.getElementById("excelImportTableWrap");
  const bodyEl = document.getElementById("excelImportBody");
  const skippedEl = document.getElementById("excelImportSkipped");
  const selectAllEl = document.getElementById("excelSelectAll");
  const pagerEl = document.getElementById("excelImportPager");

  if (!previewBtn) return;

  let lastMatches = [];
  let selectedIdx = new Set();
  let previewPage = 1;

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = isError ? "small alert-error-inline" : "small muted";
  }

  function syncApply() {
    if (applyBtn) applyBtn.disabled = selectedIdx.size === 0;
    if (selectAllEl) {
      selectAllEl.checked =
        lastMatches.length > 0 && selectedIdx.size === lastMatches.length;
      selectAllEl.indeterminate =
        selectedIdx.size > 0 && selectedIdx.size < lastMatches.length;
    }
  }

  function paintPreviewPage(page) {
    const state = paginatePreviewRows(lastMatches, page, PREVIEW_PAGE_SIZE);
    previewPage = state.page;
    if (bodyEl) {
      bodyEl.innerHTML = "";
      const start = (state.page - 1) * PREVIEW_PAGE_SIZE;
      state.slice.forEach((row, offset) => {
        const idx = start + offset;
        const timeLabel = (row.source || "").includes(":")
          ? (row.source || "").split(":").slice(1).join(":")
          : row.source || "";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="check-col">
            <input type="checkbox" class="excel-import-check" data-idx="${idx}" ${
              selectedIdx.has(idx) ? "checked" : ""
            }>
          </td>
          <td class="nowrap">${row.test_src_map_id || ""}</td>
          <td class="nowrap"><a href="${row.url || "#"}" target="_blank" rel="noopener">${row.key || ""}</a></td>
          <td><span class="status-pill status-${row.current_status}">${row.current_status}</span></td>
          <td><span class="status-pill status-${row.html_status}">${row.html_status}</span></td>
          <td class="small muted nowrap" title="${row.source || ""}">${timeLabel || ""}</td>
          <td>${row.summary || ""}</td>
        `;
        bodyEl.appendChild(tr);
      });
      bodyEl.querySelectorAll(".excel-import-check").forEach((el) => {
        el.addEventListener("change", () => {
          const idx = Number(el.dataset.idx);
          if (el.checked) selectedIdx.add(idx);
          else selectedIdx.delete(idx);
          syncApply();
        });
      });
    }
    renderPreviewPager(pagerEl, state, paintPreviewPage);
    if (tableWrap) tableWrap.hidden = lastMatches.length === 0;
    syncApply();
  }

  function renderPreview(data) {
    lastMatches = data.matches || [];
    selectedIdx = new Set(lastMatches.map((_, idx) => idx));
    previewPage = 1;
    if (summaryEl) {
      const counts = data.status_counts || {};
      const parts = Object.keys(counts).map((k) => `${k}: ${counts[k]}`);
      const fileMeta = (data.files && data.files[0]) || {};
      summaryEl.hidden = false;
      summaryEl.innerHTML = `
        <span class="chip">Sheet: ${fileMeta.sheet || "—"}</span>
        <span class="chip">Rows: ${fileMeta.row_count || 0}</span>
        <span class="chip">Parsed IDs: ${data.parsed_map_ids || 0}</span>
        <span class="chip">PASS to update: ${data.match_count || 0}</span>
        <span class="chip">Skipped: ${data.skipped_count || 0}</span>
        <span class="chip">Unmatched: ${data.unmatched_count || 0}</span>
        ${parts.map((p) => `<span class="chip">${p}</span>`).join("")}
      `;
    }

    paintPreviewPage(1);
    renderFailureTriage(data);

    if (skippedEl) {
      const skipped = data.skipped || [];
      const unmatched = data.unmatched_html || [];
      const errors = data.parse_errors || [];
      const bits = [];
      if (errors.length) {
        bits.push(`Parse issues: ${errors.map((e) => e.error || e).join("; ")}`);
      }
      const already = skipped.filter((s) => s.skip_reason === "already_present");
      if (already.length) {
        bits.push(
          `Already PASS — left untouched (${already.length}): ${already
            .slice(0, 10)
            .map((s) => s.test_src_map_id)
            .join(", ")}${already.length > 10 ? "…" : ""}`
        );
      }
      const failSkip = skipped.filter((s) => s.html_status !== "PASS");
      if (failSkip.length) {
        bits.push(
          `Not updating non-PASS (${failSkip.length}): ${failSkip
            .slice(0, 10)
            .map((s) => `${s.test_src_map_id}=${s.html_status}`)
            .join(", ")}${failSkip.length > 10 ? "…" : ""}`
        );
      }
      if (unmatched.length) {
        bits.push(
          `Not in execution (${unmatched.length}): ${unmatched
            .slice(0, 12)
            .map((u) => u.test_src_map_id)
            .join(", ")}${unmatched.length > 12 ? "…" : ""}`
        );
      }
      skippedEl.textContent = bits.join(" · ");
    }
  }

  previewBtn.addEventListener("click", async () => {
    const execution = resolveImportExecution();
    if (!execution) {
      setStatus("Select a Test Execution.", true);
      return;
    }
    if (!(filesEl && filesEl.files && filesEl.files.length)) {
      setStatus("Upload an Excel (.xlsx) report.", true);
      return;
    }

    const form = new FormData();
    form.append("execution", execution);
    form.append("excel", filesEl.files[0]);

    previewBtn.disabled = true;
    previewBtn.textContent = "Parsing…";
    setStatus("Parsing Excel; skipping already-PASS and non-PASS…");
    try {
      const resp = await fetch("/api/excel-import/preview/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: form,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Preview failed");
      renderPreview(data);
      setStatus(
        data.match_count
          ? `Ready: ${data.match_count} PASS update(s). Non-PASS cases will not be written.`
          : "No PASS updates to apply."
      );
    } catch (err) {
      setStatus(err.message || "Preview failed", true);
    } finally {
      previewBtn.disabled = false;
      previewBtn.textContent = "Preview";
    }
  });

  if (selectAllEl) {
    selectAllEl.addEventListener("change", () => {
      if (selectAllEl.checked) {
        selectedIdx = new Set(lastMatches.map((_, idx) => idx));
      } else {
        selectedIdx = new Set();
      }
      paintPreviewPage(previewPage);
    });
  }

  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      const execution = resolveImportExecution();
      const updates = Array.from(selectedIdx)
        .sort((a, b) => a - b)
        .map((idx) => lastMatches[idx])
        .filter((row) => row && row.html_status === "PASS")
        .map((row) => ({
          run_id: row.run_id,
          status: "PASS",
          key: row.key,
          test_src_map_id: row.test_src_map_id,
        }));
      if (!updates.length) return;
      const customFields = collectCustomFieldValues();
      const cfCount = Object.keys(customFields).length;
      if (
        !confirm(
          `Post ${updates.length} PASS result(s) to ${execution}` +
            (cfCount ? ` with ${cfCount} custom field(s)` : "") +
            `? Failed cases will not be updated.`
        )
      ) {
        return;
      }

      applyBtn.disabled = true;
      applyBtn.textContent = "Updating…";
      try {
        await runPassApplyWithProgress({
          applyUrl: "/api/excel-import/apply/",
          execution,
          updates,
          customFields,
          applyBtn,
          setStatus,
          syncApply,
        });
      } catch (err) {
        // Status / button reset handled by runPassApplyWithProgress
      }
    });
  }
}

function initSearchableSelects() {
  if (typeof TomSelect === "undefined") return;
  document.querySelectorAll("select[data-searchable]").forEach((el) => {
    if (el.tomselect) return;
    const placeholder = el.dataset.placeholder || "Type to search…";
    const isTop = el.closest(".topmeta");
    try {
      // eslint-disable-next-line no-new
      new TomSelect(el, {
        allowEmptyOption: true,
        create: false,
        maxOptions: null,
        placeholder,
        plugins: ["clear_button"],
        dropdownParent: "body",
        score(search) {
          const scoring = this.getScoreFunction(search);
          return (item) => {
            // Prefer matches in key/value; still allow summary text search.
            return scoring(item);
          };
        },
        render: {
          no_results: () =>
            '<div class="no-results">No matches — try another search</div>',
        },
        onInitialize() {
          if (isTop && this.control) {
            this.control.classList.add("ts-top");
          }
        },
      });
    } catch (err) {
      console.warn("Tom Select init failed", el.id || el.name, err);
    }
  });
}

function initContextForms() {
  // Ensure Tom Select values are written back before GET submit.
  ["planHomeForm", "resultsPlanForm"].forEach((formId) => {
    const form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener("submit", () => {
      form.querySelectorAll("select").forEach((el) => {
        if (el.tomselect) {
          try {
            el.tomselect.sync();
          } catch (err) {
            /* ignore */
          }
        }
      });
    });
  });

  // After a plan is chosen alone, auto-submit once so executions load.
  ["planHomeForm", "resultsPlanForm"].forEach((formId) => {
    const form = document.getElementById(formId);
    if (!form) return;
    const planSelect = form.querySelector("[data-plan-select]");
    const execSelect = form.querySelector('select[name="execution"]');
    if (!planSelect || !execSelect) return;
    const onPlanChange = () => {
      const plan = planSelect.tomselect
        ? planSelect.tomselect.getValue()
        : planSelect.value;
      const exec = execSelect.tomselect
        ? execSelect.tomselect.getValue()
        : execSelect.value;
      // Only auto-load executions when plan changes and no run chosen yet.
      if (plan && !exec) {
        if (execSelect.tomselect) execSelect.tomselect.clear(true);
        else execSelect.value = "";
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }
    };
    if (planSelect.tomselect) {
      planSelect.tomselect.on("change", onPlanChange);
    } else {
      planSelect.addEventListener("change", onPlanChange);
    }
  });
}

async function resolvePlanRef(ref) {
  const techSelect = document.getElementById("technology");
  const techHidden = document.querySelector(
    '#planContextForm input[name="technology"], #resultsPlanForm input[name="technology"]'
  );
  const stackSelect = document.getElementById("stack");
  const stackHidden = document.querySelector(
    '#planContextForm input[name="stack"], #resultsPlanForm input[name="stack"]'
  );
  const releaseSelect = document.getElementById("release");
  const releaseHidden = document.querySelector(
    '#planContextForm input[name="release"], #resultsPlanForm input[name="release"]'
  );
  const tech =
    (techHidden && techHidden.value) ||
    (techSelect && techSelect.value) ||
    "";
  const stack =
    (stackHidden && stackHidden.value) ||
    (stackSelect && stackSelect.value) ||
    "";
  const release =
    (releaseHidden && releaseHidden.value) ||
    (releaseSelect && releaseSelect.value) ||
    "";
  const params = new URLSearchParams({ q: ref });
  if (tech) params.set("technology", tech);
  if (stack) params.set("stack", stack);
  if (release) params.set("release", release);
  const resp = await fetch(`/api/plans/resolve/?${params.toString()}`, {
    headers: { "X-CSRFToken": getCsrfToken() },
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || "Test Plan not found");
  }
  return data;
}

async function switchPlanContext(evt) {
  if (evt) evt.preventDefault();
  const form = document.getElementById("planContextForm");
  const inputEl =
    document.getElementById("planKeyInput") ||
    (form ? form.querySelector('input[name="plan"]') : null);
  const selectEl = form ? form.querySelector("[data-plan-select]") : null;
  let ref = (inputEl && inputEl.value ? inputEl.value : "").trim();
  if (!ref && selectEl && selectEl.value) {
    ref = selectEl.value.trim();
  }
  if (!ref) {
    showToast("Select a plan from the list, or type a plan key / name", "warn");
    return false;
  }

  const btn = document.getElementById("openPlanBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Opening…";
  }

  try {
    const plan = await resolvePlanRef(ref);
    const techInput = form
      ? form.querySelector('input[name="technology"]')
      : null;
    const techSelect = document.getElementById("technology");
    const stackInput = form ? form.querySelector('input[name="stack"]') : null;
    const stackSelect = document.getElementById("stack");
    const releaseInput = form
      ? form.querySelector('input[name="release"]')
      : null;
    const releaseSelect = document.getElementById("release");
    const tech =
      (techInput && techInput.value) ||
      (techSelect && techSelect.value) ||
      "";
    const stack =
      (stackInput && stackInput.value) ||
      (stackSelect && stackSelect.value) ||
      "";
    const release =
      (releaseInput && releaseInput.value) ||
      (releaseSelect && releaseSelect.value) ||
      "";
    const params = new URLSearchParams();
    if (tech) params.set("technology", tech);
    if (stack) params.set("stack", stack);
    if (release) params.set("release", release);
    const qs = params.toString();
    window.location.href = `/plans/${encodeURIComponent(plan.key)}/${
      qs ? `?${qs}` : ""
    }`;
  } catch (err) {
    showToast(err.message || "Unable to open that Test Plan", "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Open plan";
    }
  }
  return false;
}

function initColumnPickers() {
  document.querySelectorAll("[data-col-picker]").forEach((picker) => {
    if (picker.dataset.bound) return;
    picker.dataset.bound = "1";
    const storageKey = picker.dataset.storageKey || "testdeck_case_cols_v1";
    const wrap = picker.closest(".table-wrap");
    const table =
      (wrap && wrap.querySelector("[data-col-table]")) ||
      document.querySelector("[data-col-table]");
    if (!table) return;

    const toggleBtn = picker.querySelector(".col-picker-toggle");
    const menu = picker.querySelector(".col-picker-menu");
    if (!toggleBtn || !menu) return;

    let saved = {};
    try {
      saved = JSON.parse(localStorage.getItem(storageKey) || "{}") || {};
    } catch (err) {
      saved = {};
    }

    const applyVisibility = () => {
      picker.querySelectorAll("[data-col-toggle]").forEach((cb) => {
        const key = cb.dataset.colToggle;
        if (!key) return;
        const show = !!cb.checked;
        table.querySelectorAll(`[data-col="${key}"]`).forEach((cell) => {
          cell.classList.toggle("col-hidden", !show);
        });
      });
    };

    picker.querySelectorAll("[data-col-toggle]").forEach((cb) => {
      const key = cb.dataset.colToggle;
      if (Object.prototype.hasOwnProperty.call(saved, key)) {
        cb.checked = !!saved[key];
      }
      cb.addEventListener("change", () => {
        const state = {};
        picker.querySelectorAll("[data-col-toggle]").forEach((c) => {
          state[c.dataset.colToggle] = !!c.checked;
        });
        try {
          localStorage.setItem(storageKey, JSON.stringify(state));
        } catch (err) {
          /* ignore quota / private mode */
        }
        applyVisibility();
      });
    });

    applyVisibility();

    const closeMenu = () => {
      menu.hidden = true;
      toggleBtn.setAttribute("aria-expanded", "false");
    };

    toggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = menu.hidden;
      menu.hidden = !open;
      toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });

    // One shared document listener for all pickers (avoid stacking on partial swaps).
    if (!window.__testdeckColPickerDocBound) {
      window.__testdeckColPickerDocBound = true;
      document.addEventListener("click", (e) => {
        document.querySelectorAll("[data-col-picker]").forEach((p) => {
          if (!p.contains(e.target)) {
            const m = p.querySelector(".col-picker-menu");
            const t = p.querySelector(".col-picker-toggle");
            if (m) m.hidden = true;
            if (t) t.setAttribute("aria-expanded", "false");
          }
        });
      });
      document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        document.querySelectorAll("[data-col-picker] .col-picker-menu").forEach((m) => {
          m.hidden = true;
        });
      });
    }
  });
}

function formatEta(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  const s = Math.max(0, Math.round(Number(seconds)));
  if (s < 60) return `~${s}s left`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `~${m}m ${rem}s left` : `~${m}m left`;
  const h = Math.floor(m / 60);
  const mins = m % 60;
  return mins ? `~${h}h ${mins}m left` : `~${h}h left`;
}

function initPlanExcelExport() {
  const startBtn = document.getElementById("planExportStartBtn");
  const box = document.getElementById("planExportProgress");
  if (!startBtn || !box) return;

  const titleEl = document.getElementById("planExportProgressTitle");
  const metaEl = document.getElementById("planExportProgressMeta");
  const detailEl = document.getElementById("planExportProgressDetail");
  const barEl = document.getElementById("planExportProgressBar");
  const downloadBtn = document.getElementById("planExportDownloadBtn");
  const dismissBtn = document.getElementById("planExportDismissBtn");
  const cancelBtn = document.getElementById("planExportCancelBtn");
  let pollTimer = null;
  let activeJobId = "";

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function isActiveStatus(status) {
    return status === "queued" || status === "running";
  }

  function paint(job) {
    box.hidden = false;
    if (job.id) activeJobId = job.id;
    const pct = Math.max(0, Math.min(100, Number(job.percent) || 0));
    if (barEl) barEl.style.width = `${pct}%`;
    if (titleEl) {
      titleEl.textContent =
        job.status === "done"
          ? "Export ready"
          : job.status === "error"
            ? "Export failed"
            : job.status === "cancelled"
              ? "Export cancelled"
              : job.message || "Working…";
    }
    const bits = [];
    if (job.total) bits.push(`${job.done || 0}/${job.total} runs`);
    bits.push(`${pct}%`);
    if (job.status === "running" || job.status === "queued") {
      const eta = formatEta(job.eta_seconds);
      if (eta) bits.push(eta);
    }
    if (metaEl) metaEl.textContent = bits.join(" · ");
    if (detailEl) {
      if (job.status === "error") {
        detailEl.textContent = job.error || "Unknown error";
        detailEl.className = "small alert-error-inline";
      } else if (job.status === "cancelled") {
        detailEl.textContent = "Stopped immediately. No file was written.";
        detailEl.className = "small muted";
      } else if (job.current) {
        detailEl.textContent = `Current: ${job.current}`;
        detailEl.className = "small muted";
      } else {
        detailEl.textContent = job.message || "";
        detailEl.className = "small muted";
      }
    }
    if (downloadBtn) {
      if (job.download_ready) {
        downloadBtn.hidden = false;
        downloadBtn.href = `/api/export-jobs/${encodeURIComponent(job.id)}/download/`;
      } else {
        downloadBtn.hidden = true;
      }
    }
    if (cancelBtn) {
      const canCancel =
        job.cancellable ||
        job.status === "queued" ||
        job.status === "running";
      cancelBtn.hidden = !canCancel;
      cancelBtn.disabled = false;
      cancelBtn.textContent = "Cancel";
    }
    if (dismissBtn) {
      dismissBtn.hidden = !(
        job.status === "done" ||
        job.status === "error" ||
        job.status === "cancelled"
      );
    }
    startBtn.disabled = isActiveStatus(job.status);
    startBtn.textContent = isActiveStatus(job.status)
      ? "Exporting…"
      : "Download plan Excel";
  }

  async function poll(jobId) {
    try {
      const resp = await fetch(`/api/export-jobs/${encodeURIComponent(jobId)}/`);
      const job = await resp.json();
      if (!resp.ok) {
        // Server reload often drops in-memory jobs; treat as interrupted.
        stopPoll();
        paint({
          id: jobId,
          status: "error",
          percent: 0,
          message: "Export interrupted",
          error:
            job.error ||
            "Export job was lost (server may have restarted). Start the export again.",
        });
        return;
      }
      paint(job);
      if (
        job.status === "done" ||
        job.status === "error" ||
        job.status === "cancelled"
      ) {
        stopPoll();
      }
    } catch (err) {
      stopPoll();
      paint({
        status: "error",
        percent: 0,
        message: "Export failed",
        error: err.message || "Progress check failed",
      });
    }
  }

  startBtn.addEventListener("click", async () => {
    const plan = startBtn.dataset.plan || "";
    if (!plan) return;
    stopPoll();
    activeJobId = "";
    startBtn.disabled = true;
    startBtn.textContent = "Starting…";
    paint({
      status: "queued",
      percent: 1,
      message: "Starting export…",
      done: 0,
      total: 0,
      cancellable: true,
    });
    if (downloadBtn) downloadBtn.hidden = true;
    if (dismissBtn) dismissBtn.hidden = true;
    try {
      const resp = await fetch(
        `/api/plans/${encodeURIComponent(plan)}/export/`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
          },
          body: JSON.stringify({ all: 1 }),
        }
      );
      const job = await resp.json();
      if (!resp.ok) throw new Error(job.error || "Unable to start export");
      paint(job);
      pollTimer = setInterval(() => poll(job.id), 1500);
      poll(job.id);
    } catch (err) {
      paint({
        status: "error",
        percent: 0,
        message: "Export failed",
        error: err.message || "Unable to start export",
      });
      startBtn.disabled = false;
      startBtn.textContent = "Download plan Excel";
    }
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      if (!activeJobId) return;
      const jobId = activeJobId;
      const pctNow = barEl
        ? parseFloat(String(barEl.style.width || "0").replace("%", "")) || 0
        : 0;
      // Optimistic UI: stop immediately while the cancel request is in flight.
      stopPoll();
      paint({
        id: jobId,
        status: "cancelled",
        percent: pctNow,
        message: "Export cancelled",
        cancellable: false,
      });
      try {
        const resp = await fetch(
          `/api/export-jobs/${encodeURIComponent(jobId)}/cancel/`,
          {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
          }
        );
        const job = await resp.json();
        if (!resp.ok) throw new Error(job.error || "Unable to cancel");
        paint(job);
      } catch (err) {
        if (detailEl) {
          detailEl.textContent = err.message || "Unable to cancel";
          detailEl.className = "small alert-error-inline";
        }
      }
    });
  }

  if (dismissBtn) {
    dismissBtn.addEventListener("click", () => {
      stopPoll();
      box.hidden = true;
      activeJobId = "";
      startBtn.disabled = false;
      startBtn.textContent = "Download plan Excel";
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("status-summary-data");
  if (el) {
    try {
      const summary = JSON.parse(el.textContent);
      drawStatusChart("statusChart", summary);
    } catch (err) {
      console.warn("Unable to render status chart", err);
    }
  }

  bindCaseTableHandlers(document);
  initPartialNavigation();
  initResumeLastPlan();
  rememberPlanContext();
  initSearchableSelects();
  initContextForms();
  initImportTabs();
  initCustomFields();
  initHtmlImport();
  initFolderImport();
  initZipImport();
  initExcelImport();
  initFailureTriage();
  initPlanExcelExport();
});
