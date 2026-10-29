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
    draftSubTab: "resume",
    draftViewMode: "edit",
    draftsByJobId: {},
    isLoadingDraft: false,
    draftError: null,
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

  // Application Preparation Client & Persistence
  async function fetchApplicationDraft(jobId) {
    state.isLoadingDraft = true;
    state.draftError = null;
    renderJobDetail();

    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/application-draft`, {
        headers: { "Accept": "application/json" },
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned ${res.status}`);
      }
      const data = await res.json();
      state.draftsByJobId[jobId] = data;
    } catch (err) {
      state.draftError = err.message || "Failed to load application draft.";
    } finally {
      state.isLoadingDraft = false;
      renderJobDetail();
    }
  }

  function getDraftStorageKey(jobId) {
    return `hire_steward_draft_${jobId}`;
  }

  function getLocalDraftData(jobId, serverDraft) {
    if (!serverDraft) return { resume: "", coverLetter: "", isEdited: false, updatedAt: null };
    try {
      const raw = localStorage.getItem(getDraftStorageKey(jobId));
      if (raw) {
        const parsed = JSON.parse(raw);
        return {
          resume: parsed.resume !== undefined ? parsed.resume : serverDraft.resume_markdown,
          coverLetter: parsed.cover_letter !== undefined ? parsed.cover_letter : serverDraft.cover_letter_markdown,
          isEdited: true,
          updatedAt: parsed.updated_at,
        };
      }
    } catch {}
    return {
      resume: serverDraft.resume_markdown,
      coverLetter: serverDraft.cover_letter_markdown,
      isEdited: false,
      updatedAt: null,
    };
  }

  function saveLocalDraft(jobId, resume, coverLetter) {
    try {
      const payload = {
        resume,
        cover_letter: coverLetter,
        updated_at: new Date().toISOString(),
      };
      localStorage.setItem(getDraftStorageKey(jobId), JSON.stringify(payload));
    } catch (e) {
      console.warn("Failed to save draft to localStorage", e);
    }
  }

  function resetLocalDraft(jobId) {
    try {
      localStorage.removeItem(getDraftStorageKey(jobId));
    } catch (e) {
      console.warn("Failed to remove draft from localStorage", e);
    }
  }

  async function copyTextToClipboard(text, btnElement) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    const origHtml = btnElement.innerHTML;
    btnElement.textContent = "Copied!";
    setTimeout(() => {
      btnElement.innerHTML = origHtml;
    }, 1500);
  }

  function exportMarkdownFile(filename, content) {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function renderMarkdown(md) {
    if (!md) return "";
    const lines = md.split("\n");
    let html = "";
    let inList = false;

    for (let rawLine of lines) {
      let line = escapeHtml(rawLine);

      if (line.startsWith("# ")) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<h1>${line.slice(2)}</h1>`;
        continue;
      }
      if (line.startsWith("## ")) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<h2>${line.slice(3)}</h2>`;
        continue;
      }
      if (line.startsWith("### ")) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<h3>${line.slice(4)}</h3>`;
        continue;
      }
      if (line.startsWith("- ") || line.startsWith("* ")) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${formatInlineMarkdown(line.slice(2))}</li>`;
        continue;
      }

      if (inList) { html += "</ul>"; inList = false; }

      if (line.trim() === "") continue;

      html += `<p>${formatInlineMarkdown(line)}</p>`;
    }

    if (inList) { html += "</ul>"; }
    return html;
  }

  function formatInlineMarkdown(text) {
    let formatted = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    formatted = formatted.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    formatted = formatted.replace(/\*(.+?)\*/g, "<em>$1</em>");
    formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, href) => {
      const cleanHref = href.trim();
      const lowerHref = cleanHref.toLowerCase();
      if (
        lowerHref.startsWith("http://") ||
        lowerHref.startsWith("https://") ||
        lowerHref.startsWith("mailto:")
      ) {
        return `<a href="${cleanHref}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      }
      return `${label} (${cleanHref})`;
    });
    return formatted;
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
          <div style="display:flex; align-items:center; gap:8px;">
            <button type="button" class="btn-primary" id="header-prepare-btn" title="Synthesize evidence-grounded resume and cover letter">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="13" height="13">
                <path d="M11 2H5a2 2 0 00-2 2v8a2 2 0 002 2h6a2 2 0 002-2V4a2 2 0 00-2-2zM5 5h6M5 8h6M5 11h4" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <span>Prepare Application</span>
            </button>
            <span class="tier-badge tier-${escapeHtml(assessment.fit_tier)}" style="font-size:12px; padding:4px 8px;">
              ${escapeHtml(formatTierLabel(assessment.fit_tier))}
            </span>
          </div>
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
          <button type="button" class="tab-btn ${state.activeTab === "draft" ? "active" : ""}" data-tab="draft" role="tab">Application Draft</button>
        </div>

        <div id="tab-content-area">
          ${renderTabContent(state.activeTab, { posting, reqEvals, prefEvals, gaps, uncertainties, snapshot, assessment })}
        </div>
      </div>
    `;

    // Attach header prepare button handler
    const headerPrepareBtn = pane.querySelector("#header-prepare-btn");
    if (headerPrepareBtn) {
      headerPrepareBtn.addEventListener("click", () => {
        state.activeTab = "draft";
        renderJobDetail();
        if (!state.draftsByJobId[posting.id]) {
          fetchApplicationDraft(posting.id);
        }
      });
    }

    // Attach tab click handlers
    pane.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        state.activeTab = btn.getAttribute("data-tab");
        renderJobDetail();
        if (state.activeTab === "draft" && !state.draftsByJobId[posting.id] && !state.isLoadingDraft) {
          fetchApplicationDraft(posting.id);
        }
      });
    });

    // Attach draft event handlers if draft tab is active
    if (state.activeTab === "draft") {
      attachDraftEventListeners(pane, posting);
    }

    // Attach mobile back button handler
    const backBtn = pane.querySelector("#mobile-back-btn");
    if (backBtn) {
      backBtn.addEventListener("click", () => {
        elements.detailPane.classList.remove("mobile-visible");
      });
    }
  }

  function renderTabContent(tab, data) {
    if (tab === "draft") {
      return renderDraftTab(data.posting.id, data.snapshot, data.posting);
    }

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

  function renderDraftTab(postingId, snapshot, posting) {
    if (state.isLoadingDraft) {
      return `
        <div style="padding: 24px 0; text-align: center;">
          <div class="skeleton-line" style="margin-bottom:8px;"></div>
          <div class="skeleton-line mid" style="margin-bottom:8px;"></div>
          <div style="font-size:12px; color:var(--muted); margin-top:12px;">Synthesizing evidence-grounded application materials...</div>
        </div>
      `;
    }

    if (state.draftError) {
      return `
        <div class="state-box" style="margin: 16px 0;">
          <div class="state-title">Draft Preparation Error</div>
          <div class="state-desc">${escapeHtml(state.draftError)}</div>
          <button type="button" class="btn-secondary" id="retry-draft-btn">Retry</button>
        </div>
      `;
    }

    const serverDraft = state.draftsByJobId[postingId];
    if (!serverDraft) {
      return `
        <div style="padding: 24px 0; text-align: center;">
          <div style="font-size:12px; color:var(--muted); margin-bottom:12px;">Click below to synthesize a tailored, evidence-grounded application draft.</div>
          <button type="button" class="btn-primary" id="start-draft-btn">Synthesize Tailored Draft</button>
        </div>
      `;
    }

    // If insufficient evidence
    if (!serverDraft.has_sufficient_evidence) {
      return `
        <div class="draft-container">
          <div class="warning-box" style="background:var(--negative-bg); border-color:#fca5a5; color:var(--negative-ink); padding:14px; border-radius:var(--radius-card);">
            <div style="font-weight:700; font-size:13px; margin-bottom:4px;">Cannot Generate Truthful Application Materials</div>
            <div style="font-size:12px; line-height:1.45;">${escapeHtml(serverDraft.draft_explanation)}</div>
            <div style="font-size:11px; margin-top:8px; font-weight:600; opacity:0.85;">${escapeHtml(serverDraft.heuristic_notice)}</div>
          </div>

          <h3 style="font-size:13px; font-weight:600; color:var(--text); margin-top:8px;">Identified Qualification Gaps (${serverDraft.evidence_gaps.length})</h3>
          <div style="font-size:12px; color:var(--muted); margin-bottom:8px;">The candidate profile has no supporting evidence for these stated requirements:</div>
          <div>
            ${serverDraft.evidence_gaps.map(gap => `
              <div class="req-item-card">
                <div class="req-item-header">
                  <span class="req-item-title">${escapeHtml(gap.requirement_text)}</span>
                  <span class="status-badge status-INSUFFICIENT_EVIDENCE">No Evidence</span>
                </div>
                <div style="font-size:11px; color:var(--muted);">${escapeHtml(gap.gap_explanation)}</div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    // Has sufficient evidence
    const localData = getLocalDraftData(postingId, serverDraft);
    const subTab = state.draftSubTab || "resume";
    const viewMode = state.draftViewMode || "edit";

    let html = `<div class="draft-container">`;

    // Unreviewed warning banner if applicable
    if (serverDraft.unreviewed_claims && serverDraft.unreviewed_claims.length > 0) {
      html += `
        <div class="heuristic-banner" style="background:var(--warning-bg); border-color:#fde68a; color:var(--warning-ink); margin-bottom:8px;" role="alert">
          <strong>Verification Notice:</strong> ${serverDraft.unreviewed_claims.length} statement(s) in this draft rely on candidate facts currently marked UNREVIEWED. Please verify them before submitting.
        </div>
      `;
    }

    // Conflicted notice if applicable
    if (serverDraft.conflicted_claims && serverDraft.conflicted_claims.length > 0) {
      html += `
        <div class="heuristic-banner" style="background:var(--neutral-bg); border-color:var(--border); color:var(--muted); margin-bottom:8px;">
          <strong>Excluded Conflicts:</strong> ${serverDraft.conflicted_claims.length} conflicted candidate fact(s) were excluded to maintain truthfulness.
        </div>
      `;
    }

    // Local draft isolation notice
    html += `
      <div class="heuristic-banner" style="background:var(--surface-subtle); border-color:var(--border); color:var(--muted); font-size:11px; margin-bottom:10px;">
        <strong>Local Draft Storage:</strong> Working drafts and user edits are saved in this browser's local storage. Local drafts can persist across browser restarts, can be cleared by the user or browser data settings, and may be accessible to scripts running on the same origin (not encrypted private storage). Edits do not alter underlying candidate evidence records, verification states, or server database models.
      </div>
    `;

    // Sub-tabs navigation
    html += `
      <div class="draft-subtabs" role="tablist">
        <button type="button" class="draft-subtab-btn ${subTab === "resume" ? "active" : ""}" data-subtab="resume" role="tab">Tailored Resume</button>
        <button type="button" class="draft-subtab-btn ${subTab === "cover_letter" ? "active" : ""}" data-subtab="cover_letter" role="tab">Tailored Cover Letter</button>
        <button type="button" class="draft-subtab-btn ${subTab === "addressed" ? "active" : ""}" data-subtab="addressed" role="tab">Addressed Qualifications (${serverDraft.addressed_requirements.length})</button>
        <button type="button" class="draft-subtab-btn ${subTab === "gaps" ? "active" : ""}" data-subtab="gaps" role="tab">Evidence Gaps (${serverDraft.evidence_gaps.length})</button>
        <button type="button" class="draft-subtab-btn ${subTab === "traceability" ? "active" : ""}" data-subtab="traceability" role="tab">Traceability Audit</button>
      </div>
    `;

    // Sub-tab content
    if (subTab === "resume") {
      const currentText = localData.resume;
      html += `
        <div class="draft-toolbar">
          <div class="draft-toolbar-left">
            <button type="button" class="btn-secondary" id="toggle-view-btn">
              ${viewMode === "edit" ? "Preview Markdown" : "Edit Markdown"}
            </button>
            <span class="save-pill" id="draft-save-pill">
              ${localData.isEdited ? "Autosaved in browser" : "Grounded server draft"}
            </span>
          </div>
          <div class="draft-toolbar-right">
            ${localData.isEdited ? `<button type="button" class="btn-secondary" id="reset-draft-btn" title="Reset edits back to server-generated version">Reset to Original</button>` : ""}
            <button type="button" class="btn-secondary" id="copy-draft-btn">Copy Resume</button>
            <button type="button" class="btn-secondary" id="export-draft-btn">Export Markdown</button>
          </div>
        </div>

        ${viewMode === "edit" ? `
          <textarea class="draft-editor-textarea" id="resume-textarea" aria-label="Edit tailored resume markdown">${escapeHtml(currentText)}</textarea>
        ` : `
          <div class="draft-rendered-preview">${renderMarkdown(currentText)}</div>
        `}
      `;
    } else if (subTab === "cover_letter") {
      const currentText = localData.coverLetter;
      html += `
        <div class="draft-toolbar">
          <div class="draft-toolbar-left">
            <button type="button" class="btn-secondary" id="toggle-view-btn">
              ${viewMode === "edit" ? "Preview Markdown" : "Edit Markdown"}
            </button>
            <span class="save-pill" id="draft-save-pill">
              ${localData.isEdited ? "Autosaved in browser" : "Grounded server draft"}
            </span>
          </div>
          <div class="draft-toolbar-right">
            ${localData.isEdited ? `<button type="button" class="btn-secondary" id="reset-draft-btn" title="Reset edits back to server-generated version">Reset to Original</button>` : ""}
            <button type="button" class="btn-secondary" id="copy-draft-btn">Copy Cover Letter</button>
            <button type="button" class="btn-secondary" id="export-draft-btn">Export Markdown</button>
          </div>
        </div>

        ${viewMode === "edit" ? `
          <textarea class="draft-editor-textarea" id="cover-textarea" aria-label="Edit tailored cover letter markdown">${escapeHtml(currentText)}</textarea>
        ` : `
          <div class="draft-rendered-preview">${renderMarkdown(currentText)}</div>
        `}
      `;
    } else if (subTab === "addressed") {
      html += `
        <div style="font-size:12px; color:var(--muted); margin-bottom:10px;">
          The following job requirements are directly addressed by verified candidate facts in this draft:
        </div>
        ${serverDraft.addressed_requirements.map(item => `
          <div class="req-item-card">
            <div class="req-item-header">
              <span class="req-item-title">${escapeHtml(item.requirement_text)}</span>
              <span class="status-badge status-MET">Addressed</span>
            </div>
            <div style="font-size:11px; color:var(--muted); margin-bottom:6px;">${escapeHtml(item.explanation)}</div>
            <div>
              ${item.supporting_claims.map(c => `
                <span class="claim-chip" title="Fact ID: ${escapeHtml(c.fact_id)}">
                  <span>${escapeHtml(c.statement)}</span>
                  <span style="color:var(--faint); font-size:10px;">[${escapeHtml(c.verification_state)}]</span>
                  ${c.is_unreviewed ? `<span style="color:var(--warning-ink); font-weight:700;">[UNREVIEWED]</span>` : ""}
                  <span style="color:var(--accent); font-size:10px;">${c.provenance_count} span(s)</span>
                </span>
              `).join("")}
            </div>
          </div>
        `).join("")}
      `;
    } else if (subTab === "gaps") {
      html += `
        <div style="font-size:12px; color:var(--muted); margin-bottom:10px;">
          The following job requirements lack recorded candidate evidence. The draft honestly acknowledges these without fabricating experience:
        </div>
        ${serverDraft.evidence_gaps.map(gap => `
          <div class="req-item-card">
            <div class="req-item-header">
              <span class="req-item-title">${escapeHtml(gap.requirement_text)}</span>
              <span class="status-badge status-INSUFFICIENT_EVIDENCE">No Evidence</span>
            </div>
            <div style="font-size:11px; color:var(--muted);">${escapeHtml(gap.gap_explanation)}</div>
          </div>
        `).join("")}
      `;
    } else if (subTab === "traceability") {
      html += `
        <div class="detail-panel">
          <div class="panel-header">
            <span class="panel-title">Evidence Traceability & Audit Ledger</span>
            <span class="panel-sub">Strict Provenance</span>
          </div>
          <div style="font-size:12px; color:var(--text); line-height:1.5; margin-bottom:12px;">
            ${escapeHtml(serverDraft.draft_explanation)}
          </div>
          <div style="font-size:11px; color:var(--faint); line-height:1.45; border-top:1px dashed var(--rule); padding-top:8px;">
            ${escapeHtml(serverDraft.heuristic_notice)}
          </div>
        </div>

        ${serverDraft.unreviewed_claims.length > 0 ? `
          <div style="margin-top:12px;">
            <div style="font-size:12px; font-weight:600; color:var(--warning); margin-bottom:6px;">Unreviewed Claims Requiring User Confirmation (${serverDraft.unreviewed_claims.length})</div>
            ${serverDraft.unreviewed_claims.map(u => `
              <div class="req-item-card">
                <span class="req-item-title">${escapeHtml(u.statement)}</span>
                <div style="font-size:11px; color:var(--muted);">Relevance: ${escapeHtml(u.relevance_reason)} | Provenance: ${u.provenance_count} span(s)</div>
              </div>
            `).join("")}
          </div>
        ` : ""}

        ${serverDraft.conflicted_claims.length > 0 ? `
          <div style="margin-top:12px;">
            <div style="font-size:12px; font-weight:600; color:var(--negative); margin-bottom:6px;">Excluded Conflicted Candidate Facts (${serverDraft.conflicted_claims.length})</div>
            ${serverDraft.conflicted_claims.map(c => `
              <div class="req-item-card">
                <span class="req-item-title">${escapeHtml(c.statement)}</span>
                <div style="font-size:11px; color:var(--muted);">${escapeHtml(c.relevance_reason)}</div>
              </div>
            `).join("")}
          </div>
        ` : ""}
      `;
    }

    html += `</div>`;
    return html;
  }

  function attachDraftEventListeners(pane, posting) {
    const serverDraft = state.draftsByJobId[posting.id];

    // Start / Retry draft buttons
    const startBtn = pane.querySelector("#start-draft-btn");
    if (startBtn) {
      startBtn.addEventListener("click", () => fetchApplicationDraft(posting.id));
    }
    const retryBtn = pane.querySelector("#retry-draft-btn");
    if (retryBtn) {
      retryBtn.addEventListener("click", () => fetchApplicationDraft(posting.id));
    }

    if (!serverDraft || !serverDraft.has_sufficient_evidence) return;

    const localData = getLocalDraftData(posting.id, serverDraft);

    // Subtab navigation
    pane.querySelectorAll(".draft-subtab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        state.draftSubTab = btn.getAttribute("data-subtab");
        renderJobDetail();
      });
    });

    // Toggle view mode (Edit vs Preview)
    const toggleViewBtn = pane.querySelector("#toggle-view-btn");
    if (toggleViewBtn) {
      toggleViewBtn.addEventListener("click", () => {
        state.draftViewMode = (state.draftViewMode === "edit" ? "preview" : "edit");
        renderJobDetail();
      });
    }

    // Resume textarea auto-save
    const resumeTextarea = pane.querySelector("#resume-textarea");
    if (resumeTextarea) {
      resumeTextarea.addEventListener("input", e => {
        saveLocalDraft(posting.id, e.target.value, localData.coverLetter);
        const pill = pane.querySelector("#draft-save-pill");
        if (pill) pill.textContent = "Autosaved in browser";
      });
    }

    // Cover letter textarea auto-save
    const coverTextarea = pane.querySelector("#cover-textarea");
    if (coverTextarea) {
      coverTextarea.addEventListener("input", e => {
        saveLocalDraft(posting.id, localData.resume, e.target.value);
        const pill = pane.querySelector("#draft-save-pill");
        if (pill) pill.textContent = "Autosaved in browser";
      });
    }

    // Reset to original draft
    const resetBtn = pane.querySelector("#reset-draft-btn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        if (confirm("Reset this application draft back to the original server-generated version? Local edits will be lost.")) {
          resetLocalDraft(posting.id);
          state.draftViewMode = "edit";
          renderJobDetail();
        }
      });
    }

    // Copy draft
    const copyBtn = pane.querySelector("#copy-draft-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const textToCopy = state.draftSubTab === "cover_letter" ? localData.coverLetter : localData.resume;
        copyTextToClipboard(textToCopy, copyBtn);
      });
    }

    // Export draft
    const exportBtn = pane.querySelector("#export-draft-btn");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => {
        const filename = `${posting.employer_handle || "application"}_${posting.id.slice(0, 8)}_draft.md`;
        const exportContent = [
          `# Tailored Application Draft: ${serverDraft.job_title} at ${serverDraft.employer_handle}`,
          `*Generated deterministically from verified candidate evidence on ${serverDraft.generated_at}*`,
          "",
          "---",
          "",
          "## Tailored Resume",
          "",
          localData.resume,
          "",
          "---",
          "",
          "## Tailored Cover Letter",
          "",
          localData.coverLetter,
        ].join("\n");
        exportMarkdownFile(filename, exportContent);
      });
    }
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
