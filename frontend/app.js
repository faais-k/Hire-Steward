/**
 * Hire-Steward Job Discovery & Review Workbench
 * Deterministic evidence-backed job matching frontend.
 * Conforms to design-taste-frontend anti-slop rules.
 */

(() => {
  "use strict";

  // Application State
  const state = {
    jobs: [],
    total: 0,
    selectedPostingId: null,
    selectedDetail: null,
    isLoadingList: false,
    isLoadingDetail: false,
    listError: null,
    detailError: null,
    candidateEvidenceCount: 0,
    activeTab: "assessment",
    filters: {
      search: "",
      workplace: "",
      tier: "",
      sort: "observed_desc",
    },
  };

  // DOM Elements
  const elements = {
    jobsContainer: document.getElementById("jobs-container"),
    detailPane: document.getElementById("detail-pane"),
    searchInput: document.getElementById("search-input"),
    workplaceFilter: document.getElementById("workplace-filter"),
    sortSelect: document.getElementById("sort-select"),
    tierPills: document.querySelectorAll(".tier-pills .pill-btn"),
    seedBtn: document.getElementById("seed-btn"),
    totalVisible: document.getElementById("total-visible"),
    sidebarCount: document.getElementById("sidebar-count"),
    candidateFactsCount: document.getElementById("candidate-facts-count"),
  };

  // Helpers
  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatRelativeTime(isoString) {
    if (!isoString) return "Recently";
    try {
      const d = new Date(isoString);
      const now = new Date();
      const diffMs = now - d;
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 60) return `${Math.max(1, diffMins)}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      const diffDays = Math.floor(diffHours / 24);
      if (diffDays < 30) return `${diffDays}d ago`;
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch {
      return "Recently";
    }
  }

  function formatTierLabel(tier) {
    switch (tier) {
      case "STRONG_MATCH": return "Strong Match";
      case "PARTIAL_MATCH": return "Partial Match";
      case "WEAK_MATCH": return "Weak Match";
      case "BLOCKED_OR_CONTRADICTED": return "Blocked / Conflict";
      case "INSUFFICIENT_DATA": return "Insufficient Data";
      default: return tier || "Unknown";
    }
  }

  function formatPercent(val) {
    if (val === null || val === undefined) return "--";
    return `${(val * 100).toFixed(1)}%`;
  }

  // API Client
  async function fetchJobs() {
    state.isLoadingList = true;
    state.listError = null;
    renderJobsList();

    try {
      const params = new URLSearchParams();
      if (state.filters.search) params.set("search", state.filters.search);
      if (state.filters.workplace) params.set("workplace_type", state.filters.workplace);
      if (state.filters.tier) params.set("tier", state.filters.tier);
      if (state.filters.sort) params.set("sort_by", state.filters.sort);
      params.set("limit", "100");

      const res = await fetch(`/api/v1/jobs?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`);
      }

      const data = await res.json();
      state.jobs = data.items || [];
      state.total = data.total || 0;
      state.candidateEvidenceCount = data.candidate_evidence_count || 0;

      // Update counters
      elements.totalVisible.textContent = state.total;
      elements.sidebarCount.textContent = state.total;
      elements.candidateFactsCount.textContent = state.candidateEvidenceCount;

      // Auto-select first job if none selected or previous selection no longer exists
      if (state.jobs.length > 0) {
        const stillSelected = state.jobs.some(j => j.id === state.selectedPostingId);
        if (!stillSelected) {
          selectJob(state.jobs[0].id);
        }
      } else {
        state.selectedPostingId = null;
        state.selectedDetail = null;
        renderJobDetail();
      }
    } catch (err) {
      state.listError = err.message || "Failed to load opportunities";
    } finally {
      state.isLoadingList = false;
      renderJobsList();
    }
  }

  async function fetchJobDetail(postingId) {
    if (!postingId) return;
    state.isLoadingDetail = true;
    state.detailError = null;
    renderJobDetail();

    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(postingId)}`);
      if (!res.ok) {
        throw new Error(`Failed to load details: ${res.status}`);
      }
      state.selectedDetail = await res.json();
    } catch (err) {
      state.detailError = err.message;
    } finally {
      state.isLoadingDetail = false;
      renderJobDetail();
    }
  }

  async function seedDemoFixtures() {
    const originalText = elements.seedBtn.innerHTML;
    elements.seedBtn.disabled = true;
    elements.seedBtn.innerHTML = `<span>Loading Fixtures...</span>`;

    try {
      const res = await fetch("/api/v1/jobs/seed-fixtures", {
        method: "POST",
        headers: {
          "Origin": window.location.origin,
          "Content-Type": "application/json",
        },
      });

      if (!res.ok) {
        throw new Error(`Seed failed: ${res.status}`);
      }

      await fetchJobs();
    } catch (err) {
      alert(`Error loading demo fixtures: ${err.message}`);
    } finally {
      elements.seedBtn.disabled = false;
      elements.seedBtn.innerHTML = originalText;
    }
  }

  function selectJob(postingId, isUserClick = false) {
    state.selectedPostingId = postingId;
    renderJobsList();
    fetchJobDetail(postingId);
    if (isUserClick && window.innerWidth <= 900) {
      elements.detailPane.classList.add("mobile-visible");
    }
  }

  // Render Functions
  function renderJobsList() {
    const container = elements.jobsContainer;

    if (state.isLoadingList) {
      container.innerHTML = `
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div><div class="skeleton-line"></div></div>
      `;
      return;
    }

    if (state.listError) {
      container.innerHTML = `
        <div class="state-box" style="margin: 20px;">
          <div class="state-title">Unable to Load Jobs</div>
          <div class="state-desc">${escapeHtml(state.listError)}</div>
          <button type="button" class="btn-secondary" id="retry-btn">Retry</button>
        </div>
      `;
      const retryBtn = document.getElementById("retry-btn");
      if (retryBtn) retryBtn.addEventListener("click", fetchJobs);
      return;
    }

    if (state.jobs.length === 0) {
      if (state.filters.search || state.filters.workplace || state.filters.tier) {
        container.innerHTML = `
          <div class="state-box" style="margin: 20px;">
            <div class="state-title">No Matching Opportunities</div>
            <div class="state-desc">No job opportunities match your active filter criteria.</div>
            <button type="button" class="btn-secondary" id="clear-filters-btn">Clear Filters</button>
          </div>
        `;
        const clearBtn = document.getElementById("clear-filters-btn");
        if (clearBtn) clearBtn.addEventListener("click", clearFilters);
      } else {
        container.innerHTML = `
          <div class="state-box" style="margin: 20px;">
            <div class="state-title">No Discovered Jobs Found</div>
            <div class="state-desc">The local database does not contain any persisted job postings yet. You can load synthetic fixtures to explore matching capabilities.</div>
            <button type="button" class="btn-secondary" id="empty-seed-btn">Load Demo Fixtures</button>
          </div>
        `;
        const emptySeedBtn = document.getElementById("empty-seed-btn");
        if (emptySeedBtn) emptySeedBtn.addEventListener("click", seedDemoFixtures);
      }
      return;
    }

    let html = "";
    for (const job of state.jobs) {
      const isSelected = job.id === state.selectedPostingId;
      const assessment = job.assessment || {};
      const tier = assessment.fit_tier || "INSUFFICIENT_DATA";
      const score = assessment.overall_score;
      const gapsCount = assessment.gaps_count || 0;

      const wpLabel = job.workplace_type ? job.workplace_type.charAt(0).toUpperCase() + job.workplace_type.slice(1) : "Unspecified";
      const locLabel = job.location || "Location not stated";

      html += `
        <div class="job-card ${isSelected ? "selected" : ""}" data-id="${escapeHtml(job.id)}" role="option" aria-selected="${isSelected}">
          <div class="job-card-header">
            <span class="job-employer">${escapeHtml(job.employer_handle || "Company")}</span>
            <span class="job-time">${formatRelativeTime(job.last_observed_at)}</span>
          </div>

          <div class="job-title">${escapeHtml(job.title)}</div>

          <div class="job-meta-row">
            <span class="tag">${escapeHtml(wpLabel)}</span>
            <span class="tag">${escapeHtml(locLabel)}</span>
            ${job.is_synthetic_fixture ? `<span class="tag" style="background:#fef3c7; color:#78350f;">Synthetic</span>` : ""}
          </div>

          <div class="job-match-row">
            <span class="tier-badge tier-${escapeHtml(tier)}">${escapeHtml(formatTierLabel(tier))}</span>
            <div class="coverage-metric num">${formatPercent(score)}</div>
            <div class="gap-indicator">${gapsCount > 0 ? `${gapsCount} gap${gapsCount > 1 ? "s" : ""}` : "All reqs met"}</div>
          </div>
        </div>
      `;
    }

    container.innerHTML = html;

    // Attach click events
    container.querySelectorAll(".job-card").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.getAttribute("data-id");
        selectJob(id, true);
      });
    });
  }

  function renderJobDetail() {
    const pane = elements.detailPane;

    if (state.isLoadingDetail) {
      pane.innerHTML = `
        <div class="detail-header">
          <div class="skeleton-line mid"></div>
          <div class="skeleton-line short"></div>
        </div>
        <div class="detail-panel"><div class="skeleton-line"></div><div class="skeleton-line mid"></div></div>
      `;
      return;
    }

    if (state.detailError) {
      pane.innerHTML = `
        <div class="state-box">
          <div class="state-title">Error Loading Job Detail</div>
          <div class="state-desc">${escapeHtml(state.detailError)}</div>
          <button type="button" class="btn-secondary" onclick="window.location.reload()">Retry</button>
        </div>
      `;
      return;
    }

    if (!state.selectedDetail) {
      pane.innerHTML = `
        <div class="state-box" style="margin-top: 60px;">
          <div class="state-title">Select an Opportunity</div>
          <div class="state-desc">Select an opportunity from the list to review its stated requirements and deterministic candidate fit explanation.</div>
        </div>
      `;
      return;
    }

    const { posting, snapshot, assessment } = state.selectedDetail;
    const scores = assessment.scores || {};
    const reqEvals = assessment.required_evaluations || [];
    const prefEvals = assessment.preferred_evaluations || [];
    const gaps = assessment.qualification_gaps || [];
    const uncertainties = assessment.uncertainties || [];

    // Header & Meta
    const wpLabel = snapshot.workplace_type ? snapshot.workplace_type.charAt(0).toUpperCase() + snapshot.workplace_type.slice(1) : "Unspecified";

    pane.innerHTML = `
      <button type="button" class="btn-secondary mobile-back-btn" id="mobile-back-btn" aria-label="Back to opportunities list">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="14" height="14">
          <path d="M10 13L5 8l5-5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>Back to List</span>
      </button>

      <!-- Header Card -->
      <div class="detail-header">
        <div class="detail-title-row">
          <div>
            <h2 class="detail-title">${escapeHtml(snapshot.title)}</h2>
            <div class="detail-employer">${escapeHtml(posting.employer_handle)} • ${escapeHtml(snapshot.department || snapshot.team || "Engineering")}</div>
          </div>
          <span class="tier-badge tier-${escapeHtml(assessment.fit_tier)}" style="font-size:12px; padding:4px 8px;">
            ${escapeHtml(formatTierLabel(assessment.fit_tier))}
          </span>
        </div>

        <div class="detail-tags">
          <span class="tag">${escapeHtml(wpLabel)}</span>
          <span class="tag">${escapeHtml(snapshot.location || "Location unstated")}</span>
          <span class="tag">${escapeHtml(snapshot.commitment || "Full-time")}</span>
          <span class="tag">Status: ${escapeHtml(posting.lifecycle_status)}</span>
          ${posting.is_synthetic_fixture ? `<span class="tag" style="background:#fef3c7; color:#78350f;">Synthetic Fixture</span>` : ""}
        </div>
      </div>

      <!-- Heuristic Notice Banner -->
      <div class="heuristic-banner" role="note">
        <strong>Deterministic Evidence Heuristic:</strong> ${escapeHtml(assessment.heuristic_notice)}
      </div>

      <!-- KPI Summary Strip -->
      <div class="kpi-strip" role="region" aria-label="Match score summary">
        <div class="kpi-item">
          <div class="kpi-label">Evidence Coverage</div>
          <div class="kpi-value num">${formatPercent(assessment.overall_score)}</div>
          <div class="kpi-sub">Composite Weight</div>
        </div>
        <div class="kpi-item">
          <div class="kpi-label">Required Qualifications</div>
          <div class="kpi-value num">${formatPercent(scores.required_coverage)}</div>
          <div class="kpi-sub">70% Weight Share</div>
        </div>
        <div class="kpi-item">
          <div class="kpi-label">Preferred Qualifications</div>
          <div class="kpi-value num">${formatPercent(scores.preferred_coverage)}</div>
          <div class="kpi-sub">20% Weight Share</div>
        </div>
        <div class="kpi-item">
          <div class="kpi-label">Confidence Rating</div>
          <div class="kpi-value">${escapeHtml(assessment.confidence_level)}</div>
          <div class="kpi-sub">${assessment.confidence_reasons ? assessment.confidence_reasons.length : 0} reason(s) noted</div>
        </div>
      </div>

      <!-- Calculation Basis Card -->
      <div class="detail-panel">
        <div class="panel-header">
          <span class="panel-title">Calculation Basis & Scoring Model</span>
          <span class="panel-sub">${escapeHtml(assessment.scoring_version || "v1.0.0-deterministic")}</span>
        </div>
        <p style="font-size:12px; color:var(--muted); line-height:1.4;">${escapeHtml(scores.calculation_basis || assessment.overall_explanation)}</p>

        ${assessment.confidence_reasons && assessment.confidence_reasons.length > 0 ? `
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--rule);">
            <div style="font-size:11px; font-weight:600; color:var(--faint); margin-bottom:4px;">CONFIDENCE AUDIT REASONS</div>
            <ul style="padding-left:16px; margin:0; font-size:11px; color:var(--muted);">
              ${assessment.confidence_reasons.map(r => `<li>${escapeHtml(r)}</li>`).join("")}
            </ul>
          </div>
        ` : ""}
      </div>

      <!-- Main Navigation Tabs -->
      <div class="detail-panel" style="padding-bottom: 8px;">
        <div class="tabs-bar" role="tablist">
          <button type="button" class="tab-btn ${state.activeTab === "assessment" ? "active" : ""}" data-tab="assessment" role="tab">Match Assessment (${reqEvals.length + prefEvals.length})</button>
          <button type="button" class="tab-btn ${state.activeTab === "description" ? "active" : ""}" data-tab="description" role="tab">Stated Description</button>
          <button type="button" class="tab-btn ${state.activeTab === "grounding" ? "active" : ""}" data-tab="grounding" role="tab">Candidate Grounding</button>
        </div>

        <div id="tab-content-area">
          ${renderTabContent(state.activeTab, { reqEvals, prefEvals, gaps, uncertainties, snapshot, assessment })}
        </div>
      </div>
    `;

    // Attach tab click handlers
    pane.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        state.activeTab = btn.getAttribute("data-tab");
        renderJobDetail();
      });
    });

    // Attach mobile back button handler
    const backBtn = pane.querySelector("#mobile-back-btn");
    if (backBtn) {
      backBtn.addEventListener("click", () => {
        elements.detailPane.classList.remove("mobile-visible");
      });
    }
  }

  function renderTabContent(tab, data) {
    if (tab === "description") {
      const lists = data.snapshot.lists_json || [];
      return `
        <div style="padding-top: 8px;">
          <div style="font-size:13px; line-height:1.5; color:var(--text); white-space:pre-wrap; margin-bottom:16px;">
            ${escapeHtml(data.snapshot.description_plain || "No description provided.")}
          </div>

          ${lists.map(sec => `
            <div style="margin-bottom:14px;">
              <h3 style="font-size:13px; font-weight:600; margin-bottom:6px;">${escapeHtml(sec.title || "Section")}</h3>
              <ul style="padding-left:18px; margin:0; font-size:12px; color:var(--muted); line-height:1.4;">
                ${(sec.items || []).map(item => `<li>${escapeHtml(item)}</li>`).join("")}
              </ul>
            </div>
          `).join("")}
        </div>
      `;
    }

    if (tab === "grounding") {
      const allMatchedFacts = [];
      const evals = [...data.reqEvals, ...data.prefEvals];
      for (const ev of evals) {
        if (ev.matched_facts) {
          for (const f of ev.matched_facts) {
            if (!allMatchedFacts.some(x => x.fact_id === f.fact_id)) {
              allMatchedFacts.push(f);
            }
          }
        }
      }

      if (allMatchedFacts.length === 0) {
        return `
          <div style="padding: 16px 0; text-align: center; color: var(--muted); font-size: 12px;">
            No candidate facts matched this posting's qualifications.
          </div>
        `;
      }

      return `
        <div style="padding-top: 8px;">
          <div style="font-size: 12px; color: var(--muted); margin-bottom: 12px;">
            Candidate facts supporting the deterministic match score for this opportunity:
          </div>

          ${allMatchedFacts.map(f => `
            <div class="evidence-box" style="margin-bottom: 8px; padding: 8px 12px;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:600; font-size:12px;">${escapeHtml(f.label)}</span>
                <span class="provenance-tag ${f.provenance_count > 0 ? "prov-VERIFIED" : "prov-MISSING"}">
                  ${f.provenance_count > 0 ? `${f.provenance_count} Byte Span Provenance` : "Missing Document Provenance"}
                </span>
              </div>
              <div style="font-size:11px; color:var(--faint); margin-top:4px;">
                Type: ${escapeHtml(f.fact_type)} • State: <strong>${escapeHtml(f.verification_state)}</strong>
              </div>
            </div>
          `).join("")}
        </div>
      `;
    }

    // Default: "assessment" tab
    let html = `<div style="padding-top: 8px;">`;

    // Required Qualifications
    html += `<h2 style="font-size:12px; font-weight:700; color:var(--faint); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:10px;">Mandatory Required Qualifications (${data.reqEvals.length})</h2>`;

    if (data.reqEvals.length === 0) {
      html += `<div style="font-size:12px; color:var(--muted); margin-bottom:12px;">No structured required qualifications extracted from posting.</div>`;
    } else {
      for (const ev of data.reqEvals) {
        html += renderRequirementCard(ev);
      }
    }

    // Preferred Qualifications
    if (data.prefEvals.length > 0) {
      html += `<h2 style="font-size:12px; font-weight:700; color:var(--faint); text-transform:uppercase; letter-spacing:0.04em; margin:16px 0 10px;">Preferred Qualifications (${data.prefEvals.length})</h2>`;
      for (const ev of data.prefEvals) {
        html += renderRequirementCard(ev);
      }
    }

    // Qualification Gaps Box
    if (data.gaps.length > 0) {
      html += `
        <div class="warning-box" style="margin-top: 16px;">
          <strong style="color:var(--negative);">Identified Qualification Gaps (${data.gaps.length}):</strong>
          <ul style="padding-left:18px; margin:6px 0 0; font-size:11px;">
            ${data.gaps.map(g => `<li>${escapeHtml(g)}</li>`).join("")}
          </ul>
        </div>
      `;
    }

    html += `</div>`;
    return html;
  }

  function renderRequirementCard(ev) {
    const isMet = ev.status === "MET";
    const isContradicted = ev.status === "CONTRADICTED";
    const isInsufficient = ev.status === "INSUFFICIENT_EVIDENCE";

    let statusClass = `status-${ev.status}`;
    let statusText = ev.status;
    if (isInsufficient) statusText = "Insufficient Evidence";

    return `
      <div class="req-item">
        <div class="req-header">
          <div class="req-text">${escapeHtml(ev.text)}</div>
          <span class="status-badge ${statusClass}">${escapeHtml(statusText)}</span>
        </div>

        <div class="req-explanation">${escapeHtml(ev.explanation)}</div>

        ${ev.matched_facts && ev.matched_facts.length > 0 ? `
          <div class="evidence-box">
            <div style="font-weight:600; color:var(--faint); margin-bottom:4px;">Supporting Candidate Evidence:</div>
            ${ev.matched_facts.map(f => `
              <div class="evidence-fact">
                <span>• ${escapeHtml(f.label)} (${escapeHtml(f.verification_state)})</span>
                <span class="provenance-tag ${f.provenance_count > 0 ? "prov-VERIFIED" : "prov-MISSING"}">
                  ${f.provenance_count > 0 ? `${f.provenance_count} span(s)` : "Missing provenance"}
                </span>
              </div>
            `).join("")}
          </div>
        ` : ""}

        ${ev.is_uncertain ? `
          <div style="font-size:11px; color:#b45309; margin-top:4px;">
            [!] Flagged with evaluation uncertainty. Requires human review or interview verification.
          </div>
        ` : ""}
      </div>
    `;
  }

  function clearFilters() {
    elements.searchInput.value = "";
    elements.workplaceFilter.value = "";
    state.filters.search = "";
    state.filters.workplace = "";
    state.filters.tier = "";

    elements.tierPills.forEach(p => {
      p.classList.toggle("active", p.getAttribute("data-tier") === "");
      p.setAttribute("aria-selected", p.getAttribute("data-tier") === "" ? "true" : "false");
    });

    fetchJobs();
  }

  // Event Listeners
  function setupEventListeners() {
    // Search input with debounce
    let searchTimeout;
    elements.searchInput.addEventListener("input", e => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        state.filters.search = e.target.value.trim();
        fetchJobs();
      }, 250);
    });

    // Workplace filter
    elements.workplaceFilter.addEventListener("change", e => {
      state.filters.workplace = e.target.value;
      fetchJobs();
    });

    // Sort select
    elements.sortSelect.addEventListener("change", e => {
      state.filters.sort = e.target.value;
      fetchJobs();
    });

    // Tier pills
    elements.tierPills.forEach(btn => {
      btn.addEventListener("click", () => {
        elements.tierPills.forEach(b => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");

        state.filters.tier = btn.getAttribute("data-tier") || "";
        fetchJobs();
      });
    });

    // Seed fixtures button
    elements.seedBtn.addEventListener("click", seedDemoFixtures);

    // Keyboard shortcuts
    window.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        elements.searchInput.focus();
        elements.searchInput.select();
      } else if (e.key === "Escape") {
        if (elements.detailPane.classList.contains("mobile-visible")) {
          elements.detailPane.classList.remove("mobile-visible");
        } else if (document.activeElement === elements.searchInput) {
          elements.searchInput.blur();
        }
      }
    });
  }

  // Initialization
  setupEventListeners();
  fetchJobs();
})();
