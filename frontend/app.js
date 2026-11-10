/**
 * Hire-Steward Job Discovery & Review Workbench
 * Deterministic evidence-backed job matching frontend.
 * Conforms to design-taste-frontend anti-slop rules.
 */

(() => {
  "use strict";

  // Centralized fetch wrapper. Modern browsers automatically attach Origin: window.location.origin
  // on state-changing requests and forbid manual JavaScript override of the Origin header.
  const _rawFetch = window.fetch.bind(window);
  const fetch = async (url, options = {}) => {
    return _rawFetch(url, options);
  };

  // Non-blocking toast notification system (replaces disruptive browser alerts)
  function showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = `toast-msg toast-${type}`;
    toast.textContent = String(message);
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add("toast-fadeout");
      setTimeout(() => toast.remove(), 400);
    }, 3200);
  }
  const alert = (msg) => showToast(msg, "info");

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
    // Milestone 5: Pipeline & Tracking state
    currentView: "opportunities", // "opportunities" or "pipeline"
    pipelineApplications: [],
    pipelineTotal: 0,
    isLoadingPipeline: false,
    pipelineError: null,
    pipelineFilterStatus: "",
    pipelineSortBy: "updated_at",
    jobTrackingByPostingId: {},
  };

  const VALID_TRANSITIONS = {
    SAVED: ["PREPARING", "READY_FOR_REVIEW", "APPLIED", "ARCHIVED"],
    PREPARING: ["READY_FOR_REVIEW", "APPLIED", "SAVED", "ARCHIVED"],
    READY_FOR_REVIEW: ["PREPARING", "APPLIED", "SAVED", "ARCHIVED"],
    APPLIED: ["INTERVIEWING", "REJECTED", "WITHDRAWN", "ARCHIVED"],
    INTERVIEWING: ["OFFER_RECEIVED", "REJECTED", "WITHDRAWN", "ARCHIVED"],
    OFFER_RECEIVED: ["WITHDRAWN", "ARCHIVED"],
    REJECTED: ["ARCHIVED"],
    WITHDRAWN: ["ARCHIVED"],
    ARCHIVED: ["SAVED"],
  };

  const STATUS_LABELS = {
    SAVED: "Saved",
    PREPARING: "Preparing",
    READY_FOR_REVIEW: "Ready for Review",
    APPLIED: "Applied",
    INTERVIEWING: "Interviewing",
    OFFER_RECEIVED: "Offer Received",
    REJECTED: "Rejected",
    WITHDRAWN: "Withdrawn",
    ARCHIVED: "Archived",
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
    addJobBtn: document.getElementById("add-job-btn"),
    totalVisible: document.getElementById("total-visible"),
    sidebarCount: document.getElementById("sidebar-count"),
    candidateFactsCount: document.getElementById("candidate-facts-count"),
    pipelineCount: document.getElementById("pipeline-count"),
    workbenchView: document.getElementById("workbench-view"),
    pipelineView: document.getElementById("pipeline-view"),
    pipelineCardsContainer: document.getElementById("pipeline-cards-container"),
    pipelineTotalIndicator: document.getElementById("pipeline-total-indicator"),
    pipelineSortSelect: document.getElementById("pipeline-sort-select"),
    pipelineStatusPills: document.querySelectorAll(".pipeline-status-pills .pill-btn"),
    navOpportunitiesBtn: document.getElementById("nav-opportunities-btn"),
    navPipelineBtn: document.getElementById("nav-pipeline-btn"),
    modalContainer: document.getElementById("modal-container"),
    mobileMenuBtn: document.getElementById("mobile-menu-btn"),
    sidebar: document.getElementById("app-sidebar") || document.querySelector(".sidebar"),
    sidebarBackdrop: document.getElementById("sidebar-backdrop"),
  };

  // Mobile Navigation Drawer Lifecycle
  function openMobileSidebar() {
    if (elements.sidebar) {
      elements.sidebar.classList.add("sidebar-open");
    }
    if (elements.sidebarBackdrop) {
      elements.sidebarBackdrop.classList.add("active");
    }
    if (elements.mobileMenuBtn) {
      elements.mobileMenuBtn.setAttribute("aria-expanded", "true");
    }
  }

  function closeMobileSidebar() {
    if (elements.sidebar) {
      elements.sidebar.classList.remove("sidebar-open");
    }
    if (elements.sidebarBackdrop) {
      elements.sidebarBackdrop.classList.remove("active");
    }
    if (elements.mobileMenuBtn) {
      elements.mobileMenuBtn.setAttribute("aria-expanded", "false");
    }
  }

  function toggleMobileSidebar() {
    if (elements.sidebar && elements.sidebar.classList.contains("sidebar-open")) {
      closeMobileSidebar();
    } else {
      openMobileSidebar();
    }
  }

  // Helpers
  function isSafeUrl(url) {
    if (!url || typeof url !== "string") return false;
    const trimmed = url.trim().toLowerCase();
    return trimmed.startsWith("http://") || trimmed.startsWith("https://");
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.style.cssText = "position:fixed; bottom:24px; right:24px; z-index:99999; display:flex; flex-direction:column; gap:8px; max-width:400px; pointer-events:none;";
      document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const bg = type === "error" ? "#fee2e2" : type === "success" ? "#dcfce7" : "#e0e7ff";
    const border = type === "error" ? "#fca5a5" : type === "success" ? "#86efac" : "#c7d2fe";
    const color = type === "error" ? "#991b1b" : type === "success" ? "#166534" : "#3730a3";
    const icon = type === "error" ? "⚠" : type === "success" ? "✓" : "ℹ";

    toast.style.cssText = `background:${bg}; border:1px solid ${border}; color:${color}; padding:10px 14px; border-radius:8px; font-size:12px; font-weight:500; box-shadow:0 4px 12px rgba(0,0,0,0.12); display:flex; align-items:center; gap:8px; pointer-events:auto; transition:opacity 0.25s ease, transform 0.25s ease;`;
    toast.innerHTML = `<span style="font-weight:700; font-size:14px;">${icon}</span><span style="flex:1;">${escapeHtml(String(message))}</span><button type="button" style="background:none; border:none; color:inherit; cursor:pointer; font-size:14px; padding:0 4px; line-height:1;" aria-label="Dismiss">✕</button>`;

    const closeBtn = toast.querySelector("button");
    const removeToast = () => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(8px)";
      setTimeout(() => toast.remove(), 250);
    };
    if (closeBtn) closeBtn.addEventListener("click", removeToast);
    container.appendChild(toast);
    setTimeout(removeToast, 4500);
  }

  // Intercept window.alert inside the app to eliminate blocking browser alert dialogs
  window.alert = function (msg) {
    showToast(msg, "info");
  };

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
      await fetchPipelineApplications();
    } catch (err) {
      showToast(`Error loading demo fixtures: ${err.message}`, "error");
    } finally {
      elements.seedBtn.disabled = false;
      elements.seedBtn.innerHTML = originalText;
    }
  }

  // Application Tracking & Pipeline API Client
  async function fetchJobTracking(postingId) {
    if (!postingId) return null;
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(postingId)}/tracking`);
      if (res.ok) {
        const data = await res.json();
        if (data.tracked && data.application) {
          state.jobTrackingByPostingId[postingId] = data.application;
          return data.application;
        } else {
          state.jobTrackingByPostingId[postingId] = null;
        }
      }
    } catch (e) {
      console.warn("Could not fetch job tracking:", e);
    }
    return null;
  }

  async function fetchPipelineApplications() {
    state.isLoadingPipeline = true;
    state.pipelineError = null;
    if (state.currentView === "pipeline") renderPipelineView();

    try {
      const params = new URLSearchParams();
      if (state.pipelineFilterStatus) {
        params.set("status", state.pipelineFilterStatus);
        if (state.pipelineFilterStatus === "ARCHIVED") {
          params.set("include_archived", "true");
        }
      }
      params.set("sort_by", state.pipelineSortBy);

      const res = await fetch(`/api/v1/applications?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`Failed to load applications: ${res.status}`);
      }
      const data = await res.json();
      state.pipelineApplications = data || [];
      state.pipelineTotal = state.pipelineApplications.length;

      data.forEach(app => {
        state.jobTrackingByPostingId[app.job_posting_id] = app;
      });

      const activeCount = data.filter(
        a => a.status !== "ARCHIVED" && a.status !== "REJECTED" && a.status !== "WITHDRAWN"
      ).length;
      if (elements.pipelineCount) {
        elements.pipelineCount.textContent = activeCount;
      }
      if (elements.pipelineTotalIndicator) {
        elements.pipelineTotalIndicator.textContent = `${state.pipelineTotal} tracked application(s)`;
      }
    } catch (err) {
      state.pipelineError = err.message || "Failed to load pipeline applications";
    } finally {
      state.isLoadingPipeline = false;
      if (state.currentView === "pipeline") renderPipelineView();
    }
  }

  async function trackJobPosting(postingId, initialStatus = "SAVED") {
    try {
      const res = await fetch("/api/v1/applications/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_posting_id: postingId,
          initial_status: initialStatus,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error tracking job: ${res.status}`);
      }
      const app = await res.json();
      state.jobTrackingByPostingId[postingId] = app;
      await fetchPipelineApplications();
      renderJobDetail();
      return app;
    } catch (err) {
      showToast(`Could not track job: ${err.message}`, "error");
    }
  }

  async function transitionAppStatus(applicationId, postingId, targetStatus, expectedVersion) {
    try {
      const body = { target_status: targetStatus };
      if (expectedVersion !== undefined) body.expected_version = expectedVersion;

      const res = await fetch(`/api/v1/applications/${encodeURIComponent(applicationId)}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Transition failed: ${res.status}`);
      }
      const updated = await res.json();
      state.jobTrackingByPostingId[postingId] = updated;
      await fetchPipelineApplications();
      renderJobDetail();
      return updated;
    } catch (err) {
      showToast(`Error updating application status: ${err.message}`, "error");
    }
  }

  async function markMaterialsReviewed(applicationId, postingId, expectedVersion) {
    try {
      const serverDraft = state.draftsByJobId[postingId];
      const localData = getLocalDraftData(postingId, serverDraft);

      const body = {
        reviewed_resume: localData.resume,
        reviewed_cover_letter: localData.coverLetter,
      };
      if (expectedVersion !== undefined) body.expected_version = expectedVersion;

      const res = await fetch(`/api/v1/applications/${encodeURIComponent(applicationId)}/mark-reviewed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error marking reviewed: ${res.status}`);
      }
      const updated = await res.json();
      state.jobTrackingByPostingId[postingId] = updated;
      await fetchPipelineApplications();
      renderJobDetail();
      showToast("Application materials marked reviewed! Status updated to READY_FOR_REVIEW.", "success");
      return updated;
    } catch (err) {
      showToast(`Could not mark materials reviewed: ${err.message}`, "error");
    }
  }

  async function confirmExternalSubmission(
    applicationId,
    postingId,
    resumeMarkdown,
    coverLetterMarkdown,
    notes,
    appliedAt,
    expectedVersion
  ) {
    try {
      const body = {
        resume_markdown: resumeMarkdown,
        cover_letter_markdown: coverLetterMarkdown,
        notes: notes || undefined,
        applied_at: appliedAt || undefined,
      };
      if (expectedVersion !== undefined) body.expected_version = expectedVersion;

      const res = await fetch(
        `/api/v1/applications/${encodeURIComponent(applicationId)}/confirm-submission`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error confirming submission: ${res.status}`);
      }
      const updated = await res.json();
      state.jobTrackingByPostingId[postingId] = updated;
      closeModal();
      state.draftSubTab = "submitted_snapshot";
      await fetchPipelineApplications();
      renderJobDetail();
      showToast("Submission confirmed! Immutable snapshot captured with cryptographic SHA-256 hashes.", "success");
      return updated;
    } catch (err) {
      showToast(`Could not confirm submission: ${err.message}`, "error");
    }
  }

  function openSubmissionModal(postingId) {
    let tracking = state.jobTrackingByPostingId[postingId];
    const serverDraft = state.draftsByJobId[postingId];
    const localData = getLocalDraftData(postingId, serverDraft);
    const detail = state.selectedDetail;
    const title = detail && detail.snapshot ? detail.snapshot.title : "Job Opportunity";
    const employer = detail && detail.posting ? detail.posting.employer_handle : "Employer";

    elements.modalContainer.style.display = "block";
    elements.modalContainer.innerHTML = `
      <div class="modal-backdrop" id="submission-modal-backdrop">
        <div class="modal-dialog">
          <div class="modal-header">
            <div class="modal-title">Confirm External Application Submission</div>
            <button type="button" class="btn-secondary" id="modal-close-btn" style="padding:4px 8px;" aria-label="Close dialog">✕</button>
          </div>
          <div class="modal-body">
            <div class="heuristic-banner" style="background:#fef3c7; border-color:#fde68a; color:#78350f;">
              <strong>Submission Grounding Notice:</strong> Hire-Steward does not automatically transmit applications or contact employers. Only confirm after you have personally submitted this application on the official external employer site.
            </div>

            <div>
              <div style="font-size:12px; font-weight:600; color:var(--text); margin-bottom:2px;">Target Position:</div>
              <div style="font-size:13px; color:var(--text);">${escapeHtml(title)} at <strong>${escapeHtml(employer)}</strong></div>
            </div>

            <div>
              <label for="modal-notes" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Submission Notes (Optional)</label>
              <input type="text" id="modal-notes" class="filter-select" style="width:100%;" placeholder="e.g. Submitted via greenhouse.io career site, direct referral">
            </div>

            <div>
              <div style="font-size:12px; font-weight:600; color:var(--text); margin-bottom:4px;">Frozen Resume Snapshot Preview</div>
              <div class="snapshot-preview-box">${escapeHtml(localData.resume || "(Empty resume content)")}</div>
            </div>

            <div>
              <div style="font-size:12px; font-weight:600; color:var(--text); margin-bottom:4px;">Frozen Cover Letter Snapshot Preview</div>
              <div class="snapshot-preview-box">${escapeHtml(localData.coverLetter || "(Empty cover letter content)")}</div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-secondary" id="modal-cancel-btn">Cancel</button>
            <button type="button" class="btn-primary" id="modal-confirm-submit-btn" style="background:#4338ca;">Confirm Submitted & Freeze Snapshot</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById("modal-close-btn").addEventListener("click", closeModal);
    document.getElementById("modal-cancel-btn").addEventListener("click", closeModal);
    document.getElementById("submission-modal-backdrop").addEventListener("click", e => {
      if (e.target.id === "submission-modal-backdrop") closeModal();
    });

    document.getElementById("modal-confirm-submit-btn").addEventListener("click", async () => {
      const notes = document.getElementById("modal-notes").value;
      if (!tracking) {
        tracking = await trackJobPosting(postingId, "SAVED");
        if (!tracking) return;
      }
      await confirmExternalSubmission(
        tracking.id,
        postingId,
        localData.resume,
        localData.coverLetter,
        notes,
        new Date().toISOString(),
        tracking.version
      );
    });
  }

  function closeModal() {
    elements.modalContainer.style.display = "none";
    elements.modalContainer.innerHTML = "";
  }

  function openJobIntakeModal() {
    elements.modalContainer.style.display = "block";
    elements.modalContainer.innerHTML = `
      <div class="modal-backdrop" id="intake-modal-backdrop">
        <div class="modal-dialog" style="max-width: 640px;">
          <div class="modal-header">
            <div class="modal-title">Add Job Opportunity (Offline Intake)</div>
            <button type="button" class="btn-secondary" id="intake-close-btn" style="padding:4px 8px;" aria-label="Close dialog">✕</button>
          </div>
          <div class="modal-body">
            <div class="heuristic-banner" style="background:#e0e7ff; border-color:#c7d2fe; color:#3730a3; margin-bottom:12px;">
              <strong>Offline User Intake:</strong> Paste any job opportunity to evaluate deterministic fit, inspect requirement coverage, and draft tailored materials. No external websites are contacted and URLs are stored strictly as unverified text references.
            </div>

            <div id="intake-error-banner" style="display:none; padding:8px 12px; background:#fee2e2; border:1px solid #fca5a5; border-radius:6px; color:#991b1b; font-size:12px; margin-bottom:12px;"></div>

            <div style="display:flex; gap:12px; margin-bottom:10px;">
              <div style="flex:2;">
                <label for="intake-title" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Job Title *</label>
                <input type="text" id="intake-title" class="filter-select" style="width:100%; box-sizing:border-box;" placeholder="e.g. Senior Backend Engineer" required maxlength="500">
              </div>
              <div style="flex:1;">
                <label for="intake-employer" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Company / Employer</label>
                <input type="text" id="intake-employer" class="filter-select" style="width:100%; box-sizing:border-box;" placeholder="e.g. Acme Corp" maxlength="128">
              </div>
            </div>

            <div style="display:flex; gap:12px; margin-bottom:10px;">
              <div style="flex:1;">
                <label for="intake-location" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Location</label>
                <input type="text" id="intake-location" class="filter-select" style="width:100%; box-sizing:border-box;" placeholder="e.g. Berlin, Germany or Worldwide" maxlength="256">
              </div>
              <div style="flex:1;">
                <label for="intake-workplace" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Workplace Arrangement</label>
                <select id="intake-workplace" class="filter-select" style="width:100%; box-sizing:border-box;">
                  <option value="">Unspecified</option>
                  <option value="remote">Remote</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="onsite">Onsite</option>
                </select>
              </div>
            </div>

            <div style="margin-bottom:10px;">
              <label for="intake-url" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">
                Reference URL (Optional)
                <span style="font-weight:400; color:var(--muted); font-size:11px;">— stored strictly as text; no network requests made</span>
              </label>
              <input type="url" id="intake-url" class="filter-select" style="width:100%; box-sizing:border-box;" placeholder="https://example.com/careers/job-123" maxlength="2048">
            </div>

            <div style="margin-bottom:4px;">
              <label for="intake-desc" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">
                Job Description &amp; Requirements *
                <span style="font-weight:400; color:var(--muted); font-size:11px;">(min 20 characters)</span>
              </label>
              <textarea id="intake-desc" class="filter-select" style="width:100%; height:160px; font-family:inherit; font-size:12px; line-height:1.4; padding:8px; box-sizing:border-box; resize:vertical;" placeholder="Paste the job requirements, responsibilities, and qualifications here..." required></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-secondary" id="intake-cancel-btn">Cancel</button>
            <button type="button" class="btn-primary" id="intake-submit-btn" style="background:#4338ca;">Save &amp; Match</button>
          </div>
        </div>
      </div>
    `;

    const closeBtn = document.getElementById("intake-close-btn");
    const cancelBtn = document.getElementById("intake-cancel-btn");
    const backdrop = document.getElementById("intake-modal-backdrop");
    const submitBtn = document.getElementById("intake-submit-btn");
    const errorBanner = document.getElementById("intake-error-banner");

    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);
    setTimeout(() => {
      const titleInput = document.getElementById("intake-title");
      if (titleInput) titleInput.focus();
    }, 50);
    backdrop.addEventListener("click", e => {
      if (e.target.id === "intake-modal-backdrop") closeModal();
    });

    submitBtn.addEventListener("click", async () => {
      const title = document.getElementById("intake-title").value.trim();
      const company = document.getElementById("intake-employer").value.trim();
      const location = document.getElementById("intake-location").value.trim();
      const workplace_type = document.getElementById("intake-workplace").value;
      const url = document.getElementById("intake-url").value.trim();
      const description = document.getElementById("intake-desc").value.trim();

      errorBanner.style.display = "none";
      errorBanner.textContent = "";

      if (!title) {
        errorBanner.textContent = "Please enter a job title.";
        errorBanner.style.display = "block";
        document.getElementById("intake-title").focus();
        return;
      }

      if (!description || description.length < 20) {
        errorBanner.textContent = "Job description must be at least 20 characters.";
        errorBanner.style.display = "block";
        document.getElementById("intake-desc").focus();
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Evaluating match...";

      try {
        const payload = {
          title,
          description_plain: description,
          employer_name: company || null,
          location: location || null,
          workplace_type: workplace_type || null,
          canonical_url: url || null,
        };

        const res = await fetch("/api/v1/jobs/intake", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server returned ${res.status}`);
        }

        const data = await res.json();
        closeModal();
        if (state.currentView !== "opportunities") {
          switchView("opportunities");
        }
        await fetchJobs();
        if (data.id) {
          selectJob(data.id, true);
        }
      } catch (err) {
        errorBanner.textContent = err.message || "Failed to add job.";
        errorBanner.style.display = "block";
        submitBtn.disabled = false;
        submitBtn.textContent = "Save & Match";
      }
    });
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
    fetchJobTracking(postingId).then(() => {
      if (state.selectedPostingId === postingId && state.selectedDetail) {
        renderJobDetail();
      }
    });
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
      const gapLabel = (tier === "INSUFFICIENT_DATA") ? "Insufficient data" : (tier === "BLOCKED_OR_CONTRADICTED") ? (gapsCount > 0 ? `${gapsCount} gap${gapsCount > 1 ? "s" : ""} (Blocked)` : "Blocked constraint") : (gapsCount > 0 ? `${gapsCount} gap${gapsCount > 1 ? "s" : ""}` : "All reqs met");

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
            ${job.is_user_entered ? `<span class="tag tag-user">User Added</span>` : ""}
          </div>

          <div class="job-match-row">
            <span class="tier-badge tier-${escapeHtml(tier)}">${escapeHtml(formatTierLabel(tier))}</span>
            <div class="coverage-metric num">${formatPercent(score)}</div>
            <div class="gap-indicator">${escapeHtml(gapLabel)}</div>
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
    const tracking = state.jobTrackingByPostingId[posting.id];
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
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            ${tracking ? `
              <div class="tracking-widget-bar">
                <span class="status-pill status-${escapeHtml(tracking.status)}">
                  ${escapeHtml(STATUS_LABELS[tracking.status] || tracking.status)}
                </span>
                <select class="filter-select" id="detail-tracking-status-select" style="font-size:11px; height:28px; padding:2px 6px;" aria-label="Update tracking status">
                  <option value="" disabled selected>Update status...</option>
                  ${(VALID_TRANSITIONS[tracking.status] || []).map(st => `
                    <option value="${st}">→ ${STATUS_LABELS[st] || st}</option>
                  `).join("")}
                </select>
              </div>
            ` : `
              <button type="button" class="btn-secondary" id="detail-track-job-btn" style="font-size:12px; padding:4px 10px;">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="13" height="13">
                  <path d="M8 2v12M2 8h12" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
                <span>Track Job</span>
              </button>
            `}
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
          ${posting.is_user_entered ? `<span class="tag tag-user">User-Provided (Unverified)</span>` : ""}
          ${snapshot.canonical_url ? (
            isSafeUrl(snapshot.canonical_url) ? `
              <span class="tag" title="${snapshot.is_reference_url_only ? 'User reference URL (stored offline only)' : 'Canonical URL'}">
                🔗 <a href="${escapeHtml(snapshot.canonical_url)}" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:underline;">
                  ${snapshot.is_reference_url_only ? 'Reference Link' : 'Job Source'}
                </a>
              </span>
            ` : `
              <span class="tag" title="Unverified reference URL (non-http)">
                🔗 ${escapeHtml(snapshot.canonical_url)}
              </span>
            `
          ) : ""}
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

    // Attach tracking button / select handlers
    const detailTrackBtn = pane.querySelector("#detail-track-job-btn");
    if (detailTrackBtn) {
      detailTrackBtn.addEventListener("click", () => trackJobPosting(posting.id, "SAVED"));
    }

    const detailTrackingSelect = pane.querySelector("#detail-tracking-status-select");
    if (detailTrackingSelect && tracking) {
      detailTrackingSelect.addEventListener("change", e => {
        const nextStatus = e.target.value;
        if (nextStatus) {
          if (nextStatus === "APPLIED") {
            openSubmissionModal(posting.id);
          } else {
            transitionAppStatus(tracking.id, posting.id, nextStatus, tracking.version);
          }
        }
      });
    }

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

    // Milestone 5: Tracking & External Submission Action Strip
    const tracking = state.jobTrackingByPostingId[postingId];
    html += `
      <div class="draft-actions-strip" style="display:flex; justify-content:space-between; align-items:center; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:10px 14px; margin-bottom:12px; flex-wrap:wrap; gap:10px;">
        <div style="font-size:12px; color:var(--muted); display:flex; align-items:center; gap:8px;">
          <strong>Pipeline Status:</strong>
          ${tracking ? `
            <span class="status-pill status-${escapeHtml(tracking.status)}">${escapeHtml(STATUS_LABELS[tracking.status] || tracking.status)}</span>
            ${tracking.applied_at ? `<span style="font-size:11px; color:var(--faint);">Applied ${formatRelativeTime(tracking.applied_at)}</span>` : ""}
          ` : `
            <span class="status-pill status-SAVED" style="opacity:0.7;">Not Tracked</span>
          `}
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          ${tracking ? `
            <button type="button" class="btn-secondary" id="mark-reviewed-btn" style="font-size:12px;" title="Mark materials verified and advance to READY_FOR_REVIEW">
              Mark Materials Reviewed
            </button>
            <button type="button" class="btn-primary" id="confirm-submission-btn" style="font-size:12px; background:#4338ca;" title="Confirm external submission on employer portal and freeze immutable snapshot">
              Confirm External Application
            </button>
          ` : `
            <button type="button" class="btn-secondary" id="draft-track-btn" style="font-size:12px;">
              Track Application
            </button>
            <button type="button" class="btn-primary" id="confirm-submission-btn" style="font-size:12px; background:#4338ca;">
              Confirm External Application
            </button>
          `}
        </div>
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
        ${tracking && tracking.submitted_resume_snapshot ? `
          <button type="button" class="draft-subtab-btn ${subTab === "submitted_snapshot" ? "active" : ""}" data-subtab="submitted_snapshot" role="tab">Submitted Snapshot (Immutable)</button>
        ` : ""}
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
    } else if (subTab === "submitted_snapshot" && tracking && tracking.submitted_resume_snapshot) {
      html += `
        <div style="display:flex; flex-direction:column; gap:12px; margin-top:8px;">
          <div class="heuristic-banner" style="background:#e0e7ff; border-color:#c7d2fe; color:#3730a3;">
            <strong>Immutable Submission Snapshot:</strong> Frozen on ${new Date(tracking.applied_at || tracking.last_status_change_at).toLocaleString()} when you confirmed external application submission. Further edits to current working drafts do not alter this historical submission record.
          </div>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">
            <span class="sha-pill">Resume SHA-256: <code>${escapeHtml(tracking.submitted_resume_sha256 || "N/A")}</code></span>
            <span class="sha-pill">Cover Letter SHA-256: <code>${escapeHtml(tracking.submitted_cover_letter_sha256 || "N/A")}</code></span>
          </div>
          ${tracking.notes ? `
            <div style="font-size:12px; background:var(--surface); border:1px solid var(--border); padding:10px 12px; border-radius:var(--radius-control); color:var(--text);">
              <strong>Submission Record Notes:</strong> ${escapeHtml(tracking.notes)}
            </div>
          ` : ""}
          <div style="font-weight:600; font-size:12px; margin-top:6px; color:var(--text);">Submitted Resume (Frozen):</div>
          <div class="snapshot-preview-box">${escapeHtml(tracking.submitted_resume_snapshot || "")}</div>
          <div style="font-weight:600; font-size:12px; margin-top:6px; color:var(--text);">Submitted Cover Letter (Frozen):</div>
          <div class="snapshot-preview-box">${escapeHtml(tracking.submitted_cover_letter_snapshot || "")}</div>
        </div>
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

    const tracking = state.jobTrackingByPostingId[posting.id];

    // Tracking & Submission action buttons
    const markRevBtn = pane.querySelector("#mark-reviewed-btn");
    if (markRevBtn && tracking) {
      markRevBtn.addEventListener("click", () => {
        markMaterialsReviewed(tracking.id, posting.id, tracking.version);
      });
    }

    const confirmSubmitBtn = pane.querySelector("#confirm-submission-btn");
    if (confirmSubmitBtn) {
      confirmSubmitBtn.addEventListener("click", () => {
        openSubmissionModal(posting.id);
      });
    }

    const draftTrackBtn = pane.querySelector("#draft-track-btn");
    if (draftTrackBtn) {
      draftTrackBtn.addEventListener("click", () => {
        trackJobPosting(posting.id, "SAVED");
      });
    }

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

  function renderPipelineView() {
    const container = elements.pipelineCardsContainer;
    if (!container) return;

    if (state.isLoadingPipeline) {
      container.innerHTML = `
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div></div>
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div></div>
        <div class="skeleton-card"><div class="skeleton-line short"></div><div class="skeleton-line mid"></div></div>
      `;
      return;
    }

    if (state.pipelineError) {
      container.innerHTML = `
        <div class="state-box" style="grid-column: 1 / -1; margin: 20px;">
          <div class="state-title">Unable to Load Pipeline</div>
          <div class="state-desc">${escapeHtml(state.pipelineError)}</div>
          <button type="button" class="btn-secondary" onclick="fetchPipelineApplications()">Retry</button>
        </div>
      `;
      return;
    }

    if (state.pipelineApplications.length === 0) {
      container.innerHTML = `
        <div class="state-box" style="grid-column: 1 / -1; margin: 40px auto; max-width: 480px;">
          <div class="state-title">No Applications Found</div>
          <div class="state-desc">You don't have any tracked applications matching this filter. Switch to Opportunities to discover and track new job openings.</div>
          <button type="button" class="btn-primary" id="pipeline-go-opportunities-btn" style="margin-top:12px;">Discover Opportunities</button>
        </div>
      `;
      const btn = document.getElementById("pipeline-go-opportunities-btn");
      if (btn) btn.addEventListener("click", () => switchView("opportunities"));
      return;
    }

    let html = "";
    state.pipelineApplications.forEach(app => {
      const allowedTransitions = VALID_TRANSITIONS[app.status] || [];
      const appliedText = app.applied_at ? `Applied: ${formatRelativeTime(app.applied_at)}` : null;
      const statusChangedText = `Updated: ${formatRelativeTime(app.last_status_change_at)}`;
      const deadlineText = app.follow_up_deadline ? `Follow-up: ${new Date(app.follow_up_deadline).toLocaleDateString()}` : null;
      const interviewText = app.next_interview_at ? `Interview: ${new Date(app.next_interview_at).toLocaleString()}` : null;

      html += `
        <div class="pipeline-card" data-app-id="${escapeHtml(app.id)}" data-posting-id="${escapeHtml(app.job_posting_id)}">
          <div class="pipeline-card-header">
            <div>
              <div class="pipeline-card-title">${escapeHtml(app.job_title || "Software Engineering Role")}</div>
              <div class="pipeline-card-employer">${escapeHtml(app.employer_name || "Employer")} • ${escapeHtml(app.location || "Remote")}</div>
            </div>
            <span class="status-pill status-${escapeHtml(app.status)}">${escapeHtml(STATUS_LABELS[app.status] || app.status)}</span>
          </div>

          <div class="pipeline-card-dates">
            <div>${statusChangedText}</div>
            ${appliedText ? `<div><strong>${appliedText}</strong></div>` : ""}
            ${interviewText ? `<div style="color:#7e22ce;"><strong>${interviewText}</strong></div>` : ""}
            ${deadlineText ? `<div style="color:#b45309;">${deadlineText}</div>` : ""}
            ${app.job_lifecycle_status && app.job_lifecycle_status !== "ACTIVE" ? `<div style="color:var(--negative);">Posting status: ${escapeHtml(app.job_lifecycle_status)}</div>` : ""}
          </div>

          ${app.notes ? `
            <div class="pipeline-card-notes">${escapeHtml(app.notes)}</div>
          ` : ""}

          <div class="pipeline-card-actions">
            <div style="display:flex; align-items:center; gap:6px;">
              <select class="filter-select pipeline-card-status-select" style="font-size:11px; height:28px; padding:2px 6px;" data-app-id="${escapeHtml(app.id)}" data-posting-id="${escapeHtml(app.job_posting_id)}" data-version="${app.version}" aria-label="Update status">
                <option value="" disabled selected>Update status...</option>
                ${allowedTransitions.map(st => `
                  <option value="${st}">→ ${STATUS_LABELS[st] || st}</option>
                `).join("")}
              </select>
            </div>
            <button type="button" class="btn-secondary pipeline-open-workbench-btn" style="font-size:11px; padding:4px 8px;" data-posting-id="${escapeHtml(app.job_posting_id)}">
              Open in Workbench
            </button>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;

    // Attach event listeners
    container.querySelectorAll(".pipeline-card-status-select").forEach(sel => {
      sel.addEventListener("change", e => {
        const targetStatus = e.target.value;
        const appId = sel.getAttribute("data-app-id");
        const postingId = sel.getAttribute("data-posting-id");
        const version = parseInt(sel.getAttribute("data-version"), 10);
        if (targetStatus === "APPLIED") {
          selectJob(postingId);
          switchView("opportunities");
          openSubmissionModal(postingId);
        } else {
          transitionAppStatus(appId, postingId, targetStatus, version);
        }
      });
    });

    container.querySelectorAll(".pipeline-open-workbench-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const postingId = btn.getAttribute("data-posting-id");
        selectJob(postingId, true);
        switchView("opportunities");
      });
    });
  }

  const VIEW_HEADINGS = {
    overview: "Overview Dashboard",
    opportunities: "Job Discovery Workbench",
    pipeline: "Application Pipeline",
    preparation: "Application Preparation",
    profile: "Candidate Profile",
    evidence: "Evidence Library",
    answers: "Interview Answer Bank",
    sources: "Job Source Registry",
    ai: "AI & Usage Headroom",
    settings: "Search Policies & Settings",
    portability: "Data Portability & Backup",
    activity: "Activity Log & Audit Feed",
    system: "System Health & Diagnostics",
  };

  const ALL_VIEWS = [
    "overview", "opportunities", "pipeline", "preparation",
    "profile", "evidence", "answers", "sources",
    "ai", "settings", "portability", "activity", "system"
  ];

  function switchView(targetView) {
    closeMobileSidebar();
    state.currentView = targetView;

    // Update headings
    const headingElem = document.getElementById("current-view-heading") || document.querySelector(".topbar-heading");
    if (headingElem) headingElem.textContent = VIEW_HEADINGS[targetView] || "Hire-Steward";

    // Toggle topbar search visibility
    const searchBox = document.getElementById("topbar-search-container");
    if (searchBox) {
      searchBox.style.display = (targetView === "opportunities" || targetView === "pipeline") ? "flex" : "none";
    }

    // Update active nav button
    document.querySelectorAll(".sidebar-nav .nav-item").forEach(btn => {
      const v = btn.getAttribute("data-view");
      const isActive = (v === targetView);
      btn.classList.toggle("active", isActive);
      if (isActive) {
        btn.setAttribute("aria-current", "page");
      } else {
        btn.removeAttribute("aria-current");
      }
    });

    // Hide all view containers
    ALL_VIEWS.forEach(v => {
      const containerId = v === "opportunities" ? "workbench-view" : `${v}-view`;
      const elem = document.getElementById(containerId);
      if (elem) {
        if (v === targetView) {
          elem.style.display = (v === "opportunities" || v === "pipeline") ? "flex" : "flex";
        } else {
          elem.style.display = "none";
        }
      }
    });

    // Trigger view-specific data loader
    if (targetView === "overview") loadOverviewData();
    else if (targetView === "opportunities") fetchJobs();
    else if (targetView === "pipeline") fetchPipelineApplications();
    else if (targetView === "profile") loadProfileData();
    else if (targetView === "evidence") loadEvidenceData();
    else if (targetView === "preparation") loadPreparationData();
    else if (targetView === "settings") loadSettingsData();
    else if (targetView === "answers") loadAnswersData();
    else if (targetView === "sources") loadSourcesData();
    else if (targetView === "ai") loadAiData();
    else if (targetView === "portability") loadPortabilityData();
    else if (targetView === "activity") loadActivityData();
    else if (targetView === "system") loadSystemData();
  }

  // --- 13 View Data Loaders & Handlers ---

  async function loadOverviewData() {
    try {
      const [sysRes, profRes, aiRes, actRes] = await Promise.all([
        fetch("/api/v1/system/status"),
        fetch("/api/v1/profile"),
        fetch("/api/v1/ai/status"),
        fetch("/api/v1/system/activity?limit=5"),
      ]);

      if (sysRes.ok) {
        const sys = await sysRes.json();
        const oCount = document.getElementById("dash-opportunities-count");
        if (oCount) oCount.textContent = sys.metrics ? sys.metrics.total_opportunities : "0";
        const pCount = document.getElementById("dash-pipeline-count");
        if (pCount) pCount.textContent = sys.metrics ? sys.metrics.active_applications : "0";
        const fCount = document.getElementById("dash-facts-count");
        if (fCount) fCount.textContent = sys.metrics ? sys.metrics.candidate_facts : "0";
      }

      if (profRes.ok) {
        const prof = await profRes.json();
        const pct = prof.completeness ? prof.completeness.percentage : 0;
        const pctEl = document.getElementById("dash-profile-pct");
        if (pctEl) pctEl.textContent = `${pct}%`;
        const healthEl = document.getElementById("dash-profile-health-label");
        if (healthEl) healthEl.textContent = pct >= 80 ? "Complete & Verified" : (pct >= 40 ? "Partially Filled" : "Incomplete");
        const sidebarProf = document.getElementById("profile-score-indicator");
        if (sidebarProf) sidebarProf.textContent = `${pct}%`;
      }

      if (aiRes.ok) {
        const ai = await aiRes.json();
        const aiBudget = document.getElementById("dash-ai-budget");
        if (aiBudget) aiBudget.textContent = `$${ai.remaining_budget_usd.toFixed(2)}`;
      }

      if (actRes.ok) {
        const acts = await actRes.json();
        renderActivityList(acts, "overview-activity-feed");
      }
    } catch (err) {
      console.error("Failed to load overview data:", err);
    }
  }

  function addEmploymentRow(d = {}) {
    const container = document.getElementById("prof-exp-container");
    if (!container) return;
    const item = document.createElement("div");
    item.className = "prof-exp-item";
    item.style.cssText = "background:var(--raised); border:1px solid var(--border); border-radius:4px; padding:10px; display:flex; flex-direction:column; gap:8px;";
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:12px; font-weight:600; color:var(--text);">Position</span>
        <button type="button" class="btn-secondary prof-del-btn" style="font-size:10px; padding:2px 6px; color:var(--negative);">Remove</button>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Company *</label>
          <input type="text" class="form-input prof-exp-company" placeholder="e.g. Acme Corp" value="${escapeHtml(d.company || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Role / Title *</label>
          <input type="text" class="form-input prof-exp-role" placeholder="e.g. Senior Software Engineer" value="${escapeHtml(d.role || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Location</label>
          <input type="text" class="form-input prof-exp-loc" placeholder="e.g. Remote / New York" value="${escapeHtml(d.location || '')}">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Start Date</label>
          <input type="text" class="form-input prof-exp-start" placeholder="e.g. 2021-01" value="${escapeHtml(d.start_date || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">End Date</label>
          <input type="text" class="form-input prof-exp-end" placeholder="e.g. Present or 2023-12" value="${escapeHtml(d.end_date || '')}">
        </div>
      </div>
      <div class="form-group">
        <label class="form-label" style="font-size:11px;">Responsibilities & Achievements</label>
        <textarea class="form-textarea prof-exp-desc" style="min-height:48px;" placeholder="Led architecture of core microservices, reduced latency by 35%...">${escapeHtml(d.description || '')}</textarea>
      </div>
    `;
    item.querySelector(".prof-del-btn")?.addEventListener("click", () => item.remove());
    container.appendChild(item);
  }

  function addEducationRow(d = {}) {
    const container = document.getElementById("prof-edu-container");
    if (!container) return;
    const item = document.createElement("div");
    item.className = "prof-edu-item";
    item.style.cssText = "background:var(--raised); border:1px solid var(--border); border-radius:4px; padding:10px; display:flex; flex-direction:column; gap:8px;";
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:12px; font-weight:600; color:var(--text);">Degree / Education</span>
        <button type="button" class="btn-secondary prof-del-btn" style="font-size:10px; padding:2px 6px; color:var(--negative);">Remove</button>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Institution / University *</label>
          <input type="text" class="form-input prof-edu-inst" placeholder="e.g. University of California" value="${escapeHtml(d.institution || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Degree / Credential *</label>
          <input type="text" class="form-input prof-edu-deg" placeholder="e.g. Bachelor of Science" value="${escapeHtml(d.degree || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Field of Study</label>
          <input type="text" class="form-input prof-edu-field" placeholder="e.g. Computer Science" value="${escapeHtml(d.field_of_study || '')}">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">Start Year</label>
          <input type="text" class="form-input prof-edu-start" placeholder="e.g. 2016" value="${escapeHtml(d.start_date || '')}">
        </div>
        <div class="form-group">
          <label class="form-label" style="font-size:11px;">End / Graduation Year</label>
          <input type="text" class="form-input prof-edu-end" placeholder="e.g. 2020" value="${escapeHtml(d.end_date || '')}">
        </div>
      </div>
    `;
    item.querySelector(".prof-del-btn")?.addEventListener("click", () => item.remove());
    container.appendChild(item);
  }

  function addProjectRow(d = {}) {
    const container = document.getElementById("prof-proj-container");
    if (!container) return;
    const item = document.createElement("div");
    item.className = "prof-proj-item";
    item.style.cssText = "background:var(--raised); border:1px solid var(--border); border-radius:4px; padding:8px; display:flex; flex-direction:column; gap:6px;";
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:11px; font-weight:600; color:var(--text);">Project</span>
        <button type="button" class="btn-secondary prof-del-btn" style="font-size:10px; padding:1px 5px; color:var(--negative);">Remove</button>
      </div>
      <div class="form-row">
        <div class="form-group">
          <input type="text" class="form-input prof-proj-title" placeholder="Project Name *" value="${escapeHtml(d.title || '')}">
        </div>
        <div class="form-group">
          <input type="text" class="form-input prof-proj-role" placeholder="Your Role" value="${escapeHtml(d.role || '')}">
        </div>
      </div>
      <div class="form-group">
        <input type="url" class="form-input prof-proj-url" placeholder="Project URL (e.g. GitHub repo)" value="${escapeHtml(d.url || '')}">
      </div>
      <div class="form-group">
        <textarea class="form-textarea prof-proj-desc" style="min-height:40px;" placeholder="Brief description and technologies used...">${escapeHtml(d.description || '')}</textarea>
      </div>
    `;
    item.querySelector(".prof-del-btn")?.addEventListener("click", () => item.remove());
    container.appendChild(item);
  }

  function addCertRow(d = {}) {
    const container = document.getElementById("prof-cert-container");
    if (!container) return;
    const item = document.createElement("div");
    item.className = "prof-cert-item";
    item.style.cssText = "background:var(--raised); border:1px solid var(--border); border-radius:4px; padding:8px; display:flex; flex-direction:column; gap:6px;";
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:11px; font-weight:600; color:var(--text);">Certification</span>
        <button type="button" class="btn-secondary prof-del-btn" style="font-size:10px; padding:1px 5px; color:var(--negative);">Remove</button>
      </div>
      <div class="form-row">
        <div class="form-group">
          <input type="text" class="form-input prof-cert-name" placeholder="Certification Name *" value="${escapeHtml(d.name || '')}">
        </div>
        <div class="form-group">
          <input type="text" class="form-input prof-cert-issuer" placeholder="Issuer (e.g. AWS, CKA)" value="${escapeHtml(d.issuer || '')}">
        </div>
        <div class="form-group">
          <input type="text" class="form-input prof-cert-date" placeholder="Year / Date" value="${escapeHtml(d.issue_date || '')}">
        </div>
      </div>
    `;
    item.querySelector(".prof-del-btn")?.addEventListener("click", () => item.remove());
    container.appendChild(item);
  }

  async function loadProfileData() {
    try {
      const res = await fetch("/api/v1/profile");
      if (!res.ok) return;
      const data = await res.json();
      const p = data.profile || {};
      const c = data.completeness || {};

      const nameIn = document.getElementById("prof-name");
      if (nameIn) nameIn.value = p.name || "";
      const hlIn = document.getElementById("prof-headline");
      if (hlIn) hlIn.value = p.headline || "";
      const sumIn = document.getElementById("prof-summary");
      if (sumIn) sumIn.value = p.summary || "";

      const contact = p.contact_info || {};
      const emIn = document.getElementById("prof-email");
      if (emIn) emIn.value = contact.email || "";
      const phIn = document.getElementById("prof-phone");
      if (phIn) phIn.value = contact.phone || "";
      const locIn = document.getElementById("prof-location");
      if (locIn) locIn.value = contact.location || "";

      const liIn = document.getElementById("prof-linkedin");
      if (liIn) liIn.value = contact.linkedin || "";
      const ghIn = document.getElementById("prof-github");
      if (ghIn) ghIn.value = contact.github || "";
      const portIn = document.getElementById("prof-portfolio");
      if (portIn) portIn.value = contact.portfolio || "";

      const langIn = document.getElementById("prof-languages");
      if (langIn) {
        const langs = Array.isArray(contact.languages) ? contact.languages : [];
        langIn.value = langs.join(", ");
      }

      const skillsIn = document.getElementById("prof-skills");
      if (skillsIn) {
        const sList = (p.skills || []).map(s => typeof s === "string" ? s : s.name).filter(Boolean);
        skillsIn.value = sList.join(", ");
      }

      // Populate dynamic containers
      const expContainer = document.getElementById("prof-exp-container");
      if (expContainer) {
        expContainer.innerHTML = "";
        (p.employment || []).forEach(emp => addEmploymentRow(emp));
      }
      const eduContainer = document.getElementById("prof-edu-container");
      if (eduContainer) {
        eduContainer.innerHTML = "";
        (p.education || []).forEach(edu => addEducationRow(edu));
      }
      const projContainer = document.getElementById("prof-proj-container");
      if (projContainer) {
        projContainer.innerHTML = "";
        (p.projects || []).forEach(prj => addProjectRow(prj));
      }
      const certContainer = document.getElementById("prof-cert-container");
      if (certContainer) {
        certContainer.innerHTML = "";
        (p.certifications || []).forEach(crt => addCertRow(crt));
      }

      // Update completeness meter
      const pct = c.percentage || 0;
      const badge = document.getElementById("profile-completeness-badge");
      if (badge) badge.textContent = `${pct}% Complete`;
      const fill = document.getElementById("profile-completeness-fill");
      if (fill) fill.style.width = `${pct}%`;

      const recBox = document.getElementById("profile-recommendations-box");
      const recList = document.getElementById("profile-recommendations-list");
      if (recBox && recList) {
        if (c.missing_elements && c.missing_elements.length > 0) {
          recList.innerHTML = c.missing_elements.map(m => `<li>${escapeHtml(m)}</li>`).join("");
          recBox.style.display = "block";
        } else {
          recBox.style.display = "none";
        }
      }
    } catch (err) {
      console.error("Failed to load profile:", err);
    }
  }

  async function saveProfileData(e) {
    if (e) e.preventDefault();

    const name = (document.getElementById("prof-name")?.value || "").trim();
    if (!name) {
      showToast("Full Name is required.", "error");
      return;
    }

    const skillsRaw = (document.getElementById("prof-skills")?.value || "")
      .split(",")
      .map(s => s.trim())
      .filter(Boolean)
      .map(name => ({ name }));

    const languagesRaw = (document.getElementById("prof-languages")?.value || "")
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);

    // Collect employment
    const employment = [];
    document.querySelectorAll(".prof-exp-item").forEach(item => {
      const company = (item.querySelector(".prof-exp-company")?.value || "").trim();
      const role = (item.querySelector(".prof-exp-role")?.value || "").trim();
      const location = (item.querySelector(".prof-exp-loc")?.value || "").trim();
      const start_date = (item.querySelector(".prof-exp-start")?.value || "").trim();
      const end_date = (item.querySelector(".prof-exp-end")?.value || "").trim();
      const description = (item.querySelector(".prof-exp-desc")?.value || "").trim();
      if (company || role) {
        employment.push({ company, role, location, start_date, end_date, description });
      }
    });

    // Collect education
    const education = [];
    document.querySelectorAll(".prof-edu-item").forEach(item => {
      const institution = (item.querySelector(".prof-edu-inst")?.value || "").trim();
      const degree = (item.querySelector(".prof-edu-deg")?.value || "").trim();
      const field_of_study = (item.querySelector(".prof-edu-field")?.value || "").trim();
      const start_date = (item.querySelector(".prof-edu-start")?.value || "").trim();
      const end_date = (item.querySelector(".prof-edu-end")?.value || "").trim();
      if (institution || degree) {
        education.push({ institution, degree, field_of_study, start_date, end_date });
      }
    });

    // Collect projects
    const projects = [];
    document.querySelectorAll(".prof-proj-item").forEach(item => {
      const title = (item.querySelector(".prof-proj-title")?.value || "").trim();
      const role = (item.querySelector(".prof-proj-role")?.value || "").trim();
      const url = (item.querySelector(".prof-proj-url")?.value || "").trim();
      const description = (item.querySelector(".prof-proj-desc")?.value || "").trim();
      if (title) {
        projects.push({ title, role, url, description });
      }
    });

    // Collect certs
    const certifications = [];
    document.querySelectorAll(".prof-cert-item").forEach(item => {
      const certName = (item.querySelector(".prof-cert-name")?.value || "").trim();
      const issuer = (item.querySelector(".prof-cert-issuer")?.value || "").trim();
      const issue_date = (item.querySelector(".prof-cert-date")?.value || "").trim();
      if (certName) {
        certifications.push({ name: certName, issuer, issue_date });
      }
    });

    const payload = {
      name: name,
      headline: (document.getElementById("prof-headline")?.value || "").trim(),
      summary: (document.getElementById("prof-summary")?.value || "").trim(),
      contact_info: {
        email: (document.getElementById("prof-email")?.value || "").trim(),
        phone: (document.getElementById("prof-phone")?.value || "").trim(),
        location: (document.getElementById("prof-location")?.value || "").trim(),
        linkedin: (document.getElementById("prof-linkedin")?.value || "").trim(),
        github: (document.getElementById("prof-github")?.value || "").trim(),
        portfolio: (document.getElementById("prof-portfolio")?.value || "").trim(),
        languages: languagesRaw,
      },
      skills: skillsRaw,
      employment: employment,
      education: education,
      projects: projects,
      certifications: certifications,
    };

    try {
      const res = await fetch("/api/v1/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        loadProfileData();
        showToast("Candidate profile successfully updated!", "success");
      } else {
        const errJson = await res.json().catch(() => ({ detail: "Failed to update profile" }));
        showToast("Save failed: " + (errJson.detail || "Validation error"), "error");
      }
    } catch (err) {
      showToast("Error saving candidate profile: " + err, "error");
    }
  }

  async function loadEvidenceData() {
    try {
      const res = await fetch("/api/v1/facts");
      const tbody = document.getElementById("candidate-facts-tbody");
      if (!tbody) return;

      if (!res.ok) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--muted);">Failed to load candidate facts.</td></tr>';
        return;
      }
      const facts = await res.json();

      const totalTag = document.getElementById("facts-total-tag");
      if (totalTag) totalTag.textContent = `${facts.length} Facts`;

      if (facts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--muted);">No candidate facts recorded yet. Upload a resume to extract facts.</td></tr>';
        return;
      }

      tbody.innerHTML = facts.map(f => {
        let valStr = "";
        if (typeof f.value === "string") {
          valStr = f.value;
        } else if (f.value && typeof f.value === "object") {
          valStr = f.value.text || f.value.name || f.value.headline || f.value.heading || JSON.stringify(f.value);
        } else {
          valStr = String(f.value || "");
        }

        let stateBg = "#fef3c7";
        let stateColor = "#92400e";
        if (f.verification_state === "USER_VERIFIED") {
          stateBg = "#dcfce7";
          stateColor = "#166534";
        } else if (f.verification_state === "REJECTED") {
          stateBg = "#fee2e2";
          stateColor = "#b91c1c";
        }

        const prov = (f.value && f.value.source) ? f.value.source : "Document Extraction";

        let actionsHtml = "";
        if (f.verification_state !== "USER_VERIFIED") {
          actionsHtml += `<button type="button" class="btn-secondary" style="font-size:11px; padding:3px 7px; color:var(--positive); font-weight:600;" onclick="verifyCandidateFact('${f.fact_id}')">Verify</button>`;
        }
        if (f.verification_state !== "REJECTED") {
          actionsHtml += `<button type="button" class="btn-secondary" style="font-size:11px; padding:3px 7px; color:var(--negative); font-weight:600; margin-left:4px;" onclick="rejectCandidateFact('${f.fact_id}')">Reject</button>`;
        }

        return `
          <tr>
            <td><span class="tag" style="background:#e0f2fe; color:#0369a1; font-weight:600;">${escapeHtml(f.fact_type)}</span></td>
            <td><strong>${escapeHtml(valStr)}</strong></td>
            <td><span class="tag" style="background:${stateBg}; color:${stateColor}; font-weight:600;">${escapeHtml(f.verification_state)}</span></td>
            <td style="font-size:11px; color:var(--muted);">${escapeHtml(prov)}</td>
            <td style="text-align:right;">${actionsHtml}</td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Failed to load evidence:", err);
    }
  }

  window.verifyCandidateFact = async function(factId) {
    try {
      const res = await fetch(`/api/v1/facts/${factId}/verify`, { method: "POST" });
      if (res.ok) {
        loadEvidenceData();
      } else {
        const err = await res.json().catch(() => ({ detail: "Verification failed" }));
        showToast("Verification failed: " + err.detail, "error");
      }
    } catch (err) {
      showToast("Error verifying fact: " + err, "error");
    }
  };

  window.rejectCandidateFact = async function(factId) {
    try {
      const res = await fetch(`/api/v1/facts/${factId}/reject`, { method: "POST" });
      if (res.ok) {
        loadEvidenceData();
      } else {
        const err = await res.json().catch(() => ({ detail: "Rejection failed" }));
        showToast("Rejection failed: " + err.detail, "error");
      }
    } catch (err) {
      showToast("Error rejecting fact: " + err, "error");
    }
  };

  let currentParsedSections = [];
  let currentDocumentVersionId = null;

  window.mapExtractedSectionToFact = async function(idx) {
    if (!currentParsedSections[idx] || !currentDocumentVersionId) return;
    const sec = currentParsedSections[idx];
    const typeSelect = document.getElementById(`sec-fact-type-${idx}`);
    const factType = typeSelect ? typeSelect.value : "SKILL";

    try {
      const res = await fetch("/api/v1/profile/map-fact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_version_id: currentDocumentVersionId,
          section_heading: sec.heading,
          section_text: sec.text,
          fact_type: factType,
          byte_start: sec.byte_start,
          byte_end: sec.byte_end,
          evidence_hash: sec.evidence_hash,
        }),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: "Mapping failed" }));
        showToast("Mapping failed: " + errJson.detail, "error");
        return;
      }

      const btn = document.getElementById(`sec-map-btn-${idx}`);
      if (btn) {
        btn.textContent = "Mapped (Unreviewed)";
        btn.disabled = true;
        btn.style.opacity = "0.6";
      }
      loadEvidenceData();
      showToast(`Mapped section "${sec.heading}" to ${factType} fact! Review it in the table below.`, "success");
    } catch (err) {
      showToast("Error mapping fact: " + err, "error");
    }
  };

  async function handleFileUpload(file) {
    if (!file) return;
    try {
      const previewBox = document.getElementById("parsed-preview-box");
      const nameDisp = document.getElementById("parsed-filename-display");
      const countDisp = document.getElementById("parsed-count-display");
      const textDisp = document.getElementById("parsed-text-content");
      const sectionsContainer = document.getElementById("parsed-sections-container");

      const arrayBuffer = await file.arrayBuffer();
      const res = await fetch("/api/v1/profile/parse-document", {
        method: "POST",
        headers: { "x-filename": file.name },
        body: arrayBuffer,
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: "Upload failed" }));
        showToast("Extraction failed: " + errJson.detail, "error");
        return;
      }

      const parsed = await res.json();
      currentParsedSections = parsed.sections || [];
      currentDocumentVersionId = parsed.document_version_id || parsed.version_id;

      if (previewBox && textDisp) {
        nameDisp.textContent = parsed.filename;
        countDisp.textContent = `${parsed.sections_count} sections (${parsed.char_count} chars)`;
        textDisp.textContent = parsed.raw_text;

        if (sectionsContainer) {
          sectionsContainer.innerHTML = currentParsedSections.map((sec, idx) => `
            <div style="background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:10px; display:flex; flex-direction:column; gap:6px;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong style="font-size:12px; color:var(--text);">${escapeHtml(sec.heading)}</strong>
                <span style="font-size:11px; color:var(--muted); font-family:monospace;">bytes ${sec.byte_start}..${sec.byte_end}</span>
              </div>
              <div style="font-size:11px; color:var(--muted); max-height:60px; overflow-y:auto; white-space:pre-wrap;">${escapeHtml(sec.text)}</div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
                <div style="display:flex; align-items:center; gap:6px;">
                  <label style="font-size:11px; color:var(--muted);">Fact Type:</label>
                  <select id="sec-fact-type-${idx}" class="form-input" style="font-size:11px; padding:2px 6px; width:auto;">
                    <option value="SKILL">SKILL</option>
                    <option value="EDUCATION">EDUCATION</option>
                    <option value="EMPLOYMENT">EMPLOYMENT</option>
                    <option value="PROJECT">PROJECT</option>
                    <option value="CERTIFICATION">CERTIFICATION</option>
                  </select>
                </div>
                <button type="button" class="btn-primary" id="sec-map-btn-${idx}" style="font-size:11px; padding:3px 10px;" onclick="mapExtractedSectionToFact(${idx})">Map to Evidence Fact</button>
              </div>
            </div>
          `).join("");
        }

        previewBox.style.display = "block";
      }

      // Auto-populate profile summary and skills if empty
      const sumIn = document.getElementById("prof-summary");
      if (sumIn && !sumIn.value) {
        sumIn.value = parsed.raw_text.substring(0, 500) + "...";
      }
      loadEvidenceData();
      showToast(`Successfully extracted ${parsed.sections_count} sections from ${parsed.filename}! You can map sections to candidate facts.`, "success");
    } catch (err) {
      showToast("Error parsing document: " + err, "error");
    }
  }

  async function loadPreparationData() {
    try {
      const select = document.getElementById("prep-job-select");
      if (!select) return;

      const res = await fetch("/api/v1/jobs");
      if (!res.ok) return;
      const data = await res.json();
      const jobs = data.items || [];

      select.innerHTML = '<option value="">-- Choose Opportunity --</option>' +
        jobs.map(j => `<option value="${escapeHtml(j.id)}">${escapeHtml(j.title)} (${escapeHtml(j.employer_handle || "Company")})</option>`).join("");

      if (state.selectedPostingId && jobs.some(j => j.id === state.selectedPostingId)) {
        select.value = state.selectedPostingId;
        const container = document.getElementById("prep-materials-container");
        if (!container || container.style.display === "none") {
          await generatePreparationDraft();
        }
      }
    } catch (err) {
      console.error("Failed to load jobs for prep:", err);
    }
  }

  async function generatePreparationDraft() {
    const select = document.getElementById("prep-job-select");
    const jobId = select ? select.value : "";
    if (!jobId) {
      showToast("Please select a target opportunity from the dropdown first.", "error");
      return;
    }

    try {
      const res = await fetch("/api/v1/ai/generate-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_posting_id: jobId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Draft generation failed" }));
        showToast("Unable to generate draft: " + err.detail, "error");
        return;
      }

      const draft = await res.json();
      const container = document.getElementById("prep-materials-container");
      const rEdit = document.getElementById("prep-resume-editor");
      const cEdit = document.getElementById("prep-cover-editor");
      const claimsDiv = document.getElementById("prep-claims-list");

      if (rEdit) rEdit.value = draft.resume_markdown || "";
      if (cEdit) cEdit.value = draft.cover_letter_markdown || "";

      if (claimsDiv) {
        const addressed = (draft.addressed_requirements || []).map(a => `
          <div style="margin-bottom:8px; padding:10px; border-left:3px solid var(--accent); background:var(--raised);">
            <strong>Requirement:</strong> ${escapeHtml(a.requirement_text)}<br>
            <span style="font-size:11px; color:var(--muted);">${escapeHtml(a.explanation)}</span>
          </div>
        `).join("");
        const gaps = (draft.evidence_gaps || []).map(g => `
          <div style="margin-bottom:8px; padding:10px; border-left:3px solid var(--warning); background:var(--raised);">
            <strong>Unaddressed Gap:</strong> ${escapeHtml(g.requirement_text)}<br>
            <span style="font-size:11px; color:var(--warning);">${escapeHtml(g.gap_explanation)}</span>
          </div>
        `).join("");
        claimsDiv.innerHTML = addressed + (gaps || '<div class="state-desc">Zero gaps detected! Full coverage.</div>');
      }

      if (container) container.style.display = "block";
    } catch (err) {
      showToast("Error generating draft: " + err, "error");
    }
  }

  async function getOrTrackApplicationForJob(jobId) {
    try {
      const trackRes = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/tracking`);
      if (trackRes.ok) {
        const data = await trackRes.json();
        if (data.tracked && data.application) {
          return data.application.id;
        }
      }
      const postRes = await fetch("/api/v1/applications/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_posting_id: jobId }),
      });
      if (postRes.ok) {
        const app = await postRes.json();
        return app.id;
      }
    } catch (e) {
      console.warn("Could not get or track application:", e);
    }
    return null;
  }

  async function createSubmissionPlanFromDraft() {
    const select = document.getElementById("prep-job-select");
    const jobId = select ? select.value : "";
    if (!jobId) {
      showToast("Please select a target opportunity from the dropdown first.", "error");
      return;
    }
    const appId = await getOrTrackApplicationForJob(jobId);
    if (!appId) {
      showToast("Could not find or track application for this job.", "error");
      return;
    }
    try {
      const res = await fetch(`/api/v1/applications/${encodeURIComponent(appId)}/submission-plan`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to generate plan" }));
        showToast("Plan creation failed: " + err.detail, "error");
        return;
      }
      const plan = await res.json();
      const planHash = plan.packet_sha256 || plan.plan_hash || plan.plan_id || "";
      showToast(`Submission plan created: ${planHash.slice(0, 16)}...`, "success");
      const receiptElem = document.getElementById("prep-simulation-receipt");
      if (receiptElem) {
        receiptElem.textContent = `Submission Plan SHA-256: ${planHash}\nResume SHA-256: ${plan.resume_sha256 || "N/A"}\nCover Letter SHA-256: ${plan.cover_letter_sha256 || "N/A"}\nCompensation Eligible: ${plan.is_compensation_eligible}\nStatus: ${plan.status || "PREPARED"}`;
      }
    } catch (err) {
      showToast("Error creating submission plan: " + err, "error");
    }
  }

  async function simulateSubmissionFromDraft() {
    const select = document.getElementById("prep-job-select");
    const jobId = select ? select.value : "";
    if (!jobId) {
      showToast("Please select a target opportunity from the dropdown first.", "error");
      return;
    }
    const appId = await getOrTrackApplicationForJob(jobId);
    if (!appId) {
      showToast("Could not find or track application for this job.", "error");
      return;
    }
    try {
      const res = await fetch(`/api/v1/applications/${encodeURIComponent(appId)}/simulate-submission`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "SUCCESS" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Simulation failed" }));
        showToast("Simulation failed: " + err.detail, "error");
        return;
      }
      const receipt = await res.json();
      showToast("Simulation dry-run completed successfully (READY_FOR_REVIEW preserved).", "success");
      const receiptElem = document.getElementById("prep-simulation-receipt");
      if (receiptElem) {
        receiptElem.textContent = `Simulation Receipt:\nAttempt ID: ${receipt.attempt_id}\nStatus: ${receipt.status}\nDry-Run: ${receipt.is_simulation !== undefined ? receipt.is_simulation : (receipt.mode_used || true)}\nFinal State: ${receipt.application_status} (Never APPLIED)`;
      }
    } catch (err) {
      showToast("Error simulating submission: " + err, "error");
    }
  }

  function initPreparationTabs() {
    const tabResume = document.getElementById("prep-tab-resume");
    const tabCover = document.getElementById("prep-tab-cover");
    const tabClaims = document.getElementById("prep-tab-claims");
    const paneResume = document.getElementById("prep-content-resume");
    const paneCover = document.getElementById("prep-content-cover");
    const paneClaims = document.getElementById("prep-content-claims");

    if (tabResume && tabCover && tabClaims) {
      tabResume.addEventListener("click", () => {
        tabResume.classList.add("active");
        tabCover.classList.remove("active");
        tabClaims.classList.remove("active");
        if (paneResume) paneResume.style.display = "block";
        if (paneCover) paneCover.style.display = "none";
        if (paneClaims) paneClaims.style.display = "none";
      });
      tabCover.addEventListener("click", () => {
        tabCover.classList.add("active");
        tabResume.classList.remove("active");
        tabClaims.classList.remove("active");
        if (paneResume) paneResume.style.display = "none";
        if (paneCover) paneCover.style.display = "block";
        if (paneClaims) paneClaims.style.display = "none";
      });
      tabClaims.addEventListener("click", () => {
        tabClaims.classList.add("active");
        tabResume.classList.remove("active");
        tabCover.classList.remove("active");
        if (paneResume) paneResume.style.display = "none";
        if (paneCover) paneCover.style.display = "none";
        if (paneClaims) paneClaims.style.display = "block";
      });
    }
  }

  async function loadSettingsData() {
    try {
      const res = await fetch("/api/v1/settings");
      if (!res.ok) return;
      const s = await res.json();

      const compIn = document.getElementById("setting-min-comp");
      if (compIn && s.minimum_compensation) compIn.value = s.minimum_compensation.amount || "100000";

      const dailyIn = document.getElementById("setting-daily-cap");
      if (dailyIn) dailyIn.value = s.daily_application_cap || 5;

      const coolIn = document.getElementById("setting-cooldown");
      if (coolIn) coolIn.value = s.same_company_cooldown_days || 30;

      const rolesIn = document.getElementById("setting-target-roles");
      if (rolesIn) rolesIn.value = (s.target_roles || []).join(", ");

      const locsIn = document.getElementById("setting-target-locs");
      if (locsIn) locsIn.value = (s.target_locations || []).join(", ");

      const sponIn = document.getElementById("setting-sponsorship");
      if (sponIn) sponIn.value = s.sponsorship_requirement || "not_required";

      const wpArr = s.workplace_arrangements || ["remote", "hybrid"];
      const rChk = document.getElementById("wp-remote");
      if (rChk) rChk.checked = wpArr.includes("remote");
      const hChk = document.getElementById("wp-hybrid");
      if (hChk) hChk.checked = wpArr.includes("hybrid");
      const oChk = document.getElementById("wp-onsite");
      if (oChk) oChk.checked = wpArr.includes("onsite");
    } catch (err) {
      console.error("Failed to load settings:", err);
    }
  }

  function loadRecommendedDefaults() {
    const rolesIn = document.getElementById("setting-target-roles");
    if (rolesIn) rolesIn.value = "AI Engineer, AI Developer, AI + Backend Developer, Forward Deployed Engineer";

    const locsIn = document.getElementById("setting-target-locs");
    if (locsIn) locsIn.value = "India, Remote";

    const compIn = document.getElementById("setting-min-comp");
    if (compIn) compIn.value = "300000";

    const coolIn = document.getElementById("setting-cooldown");
    if (coolIn) coolIn.value = "30";

    const dailyIn = document.getElementById("setting-daily-cap");
    if (dailyIn) dailyIn.value = "5";

    const sponIn = document.getElementById("setting-sponsorship");
    if (sponIn) sponIn.value = "not_required";

    const rChk = document.getElementById("wp-remote");
    if (rChk) rChk.checked = true;
    const hChk = document.getElementById("wp-hybrid");
    if (hChk) hChk.checked = true;
    const oChk = document.getElementById("wp-onsite");
    if (oChk) oChk.checked = false;

    showToast("Proposed defaults loaded: AI Engineer roles, INR 300,000 min comp, India scope, 30d cooldown. Click 'Save Policies' to confirm.", "info");
  }

  async function saveSettingsData() {
    const roles = (document.getElementById("setting-target-roles")?.value || "")
      .split(",").map(r => r.trim()).filter(Boolean);
    const locs = (document.getElementById("setting-target-locs")?.value || "")
      .split(",").map(l => l.trim()).filter(Boolean);

    const wp = [];
    if (document.getElementById("wp-remote")?.checked) wp.push("remote");
    if (document.getElementById("wp-hybrid")?.checked) wp.push("hybrid");
    if (document.getElementById("wp-onsite")?.checked) wp.push("onsite");

    const payload = {
      minimum_compensation: {
        amount: document.getElementById("setting-min-comp")?.value || "300000.00",
      },
      daily_application_cap: parseInt(document.getElementById("setting-daily-cap")?.value || "5", 10),
      same_company_cooldown_days: parseInt(document.getElementById("setting-cooldown")?.value || "30", 10),
      target_roles: roles,
      target_locations: locs,
      workplace_arrangements: wp,
      sponsorship_requirement: document.getElementById("setting-sponsorship")?.value || "not_required",
    };

    try {
      const res = await fetch("/api/v1/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast("Search policies and compensation gates updated successfully!", "success");
        loadSettingsData();
      } else {
        const errJson = await res.json().catch(() => ({}));
        showToast("Error updating settings: " + (errJson.detail || res.statusText), "error");
      }
    } catch (err) {
      showToast("Error saving settings: " + err, "error");
    }
  }

  function openNewAnswerModal() {
    elements.modalContainer.style.display = "block";
    elements.modalContainer.innerHTML = `
      <div class="modal-backdrop" id="answer-modal-backdrop">
        <div class="modal-dialog" style="max-width: 580px;">
          <div class="modal-header">
            <div class="modal-title">New Interview Response</div>
            <button type="button" class="btn-secondary" id="answer-close-btn" style="padding:4px 8px;" aria-label="Close dialog">✕</button>
          </div>
          <div class="modal-body">
            <div id="answer-error-banner" style="display:none; padding:8px 12px; background:#fee2e2; border:1px solid #fca5a5; border-radius:6px; color:#991b1b; font-size:12px; margin-bottom:12px;"></div>

            <div style="margin-bottom:10px;">
              <label for="answer-cat-select" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Category</label>
              <select id="answer-cat-select" class="form-input" style="width:100%;">
                <option value="general">General</option>
                <option value="technical">Technical</option>
                <option value="behavioral">Behavioral</option>
                <option value="compensation">Compensation</option>
                <option value="work_authorization">Work Authorization</option>
                <option value="experience">Experience</option>
              </select>
            </div>

            <div style="margin-bottom:10px;">
              <label for="answer-question-input" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Question / Prompt *</label>
              <input type="text" id="answer-question-input" class="form-input" style="width:100%; box-sizing:border-box;" placeholder="e.g. Describe your experience with distributed systems." required maxlength="500">
            </div>

            <div style="margin-bottom:12px;">
              <label for="answer-text-input" style="font-size:12px; font-weight:600; color:var(--text); display:block; margin-bottom:4px;">Approved Response *</label>
              <textarea id="answer-text-input" class="form-input" style="width:100%; height:120px; font-family:inherit; font-size:12px; line-height:1.4; padding:8px; box-sizing:border-box; resize:vertical;" placeholder="Enter your approved, factual answer here..." required></textarea>
            </div>

            <div style="display:flex; align-items:center; gap:8px; padding:10px; background:var(--raised); border-radius:6px;">
              <input type="checkbox" id="answer-consent-check" style="cursor:pointer;">
              <label for="answer-consent-check" style="font-size:12px; color:var(--text); cursor:pointer;">
                <strong>Explicit Reuse Consent:</strong> Allow this response to be used in AI-assisted application questionnaires. Defaults to unchecked (consent required).
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-secondary" id="answer-cancel-btn">Cancel</button>
            <button type="button" class="btn-primary" id="answer-save-btn" style="background:#4338ca;">Save Response</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById("answer-close-btn")?.addEventListener("click", closeModal);
    document.getElementById("answer-cancel-btn")?.addEventListener("click", closeModal);
    document.getElementById("answer-modal-backdrop")?.addEventListener("click", e => {
      if (e.target.id === "answer-modal-backdrop") closeModal();
    });

    document.getElementById("answer-save-btn")?.addEventListener("click", async () => {
      const category = document.getElementById("answer-cat-select").value;
      const question = document.getElementById("answer-question-input").value.trim();
      const answer = document.getElementById("answer-text-input").value.trim();
      const reuse_consent = document.getElementById("answer-consent-check").checked;
      const errorBanner = document.getElementById("answer-error-banner");

      errorBanner.style.display = "none";
      if (!question) {
        errorBanner.textContent = "Please enter a question or prompt.";
        errorBanner.style.display = "block";
        document.getElementById("answer-question-input").focus();
        return;
      }
      if (!answer) {
        errorBanner.textContent = "Please enter an answer.";
        errorBanner.style.display = "block";
        document.getElementById("answer-text-input").focus();
        return;
      }

      try {
        const res = await fetch("/api/v1/answers", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ question, answer, category, reuse_consent })
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server responded with ${res.status}`);
        }
        closeModal();
        loadAnswersData();
      } catch (err) {
        errorBanner.textContent = "Failed to save: " + err.message;
        errorBanner.style.display = "block";
      }
    });
  }

  async function loadAnswersData(catFilter = "") {
    try {
      const url = catFilter ? `/api/v1/answers?category=${encodeURIComponent(catFilter)}` : "/api/v1/answers";
      const res = await fetch(url);
      if (!res.ok) return;
      const items = await res.json();

      const countEl = document.getElementById("answers-count");
      if (countEl) countEl.textContent = items.length;

      const container = document.getElementById("answer-cards-container");
      if (!container) return;

      if (items.length === 0) {
        container.innerHTML = '<div class="state-desc" style="grid-column: 1/-1; text-align:center; padding:32px;">No answer bank entries found. Click "+ New Response" to save interview answers.</div>';
        return;
      }

      container.innerHTML = items.map(item => `
        <div class="answer-card" id="answer-card-${item.id}">
          <div class="answer-card-header">
            <span class="tag" style="background:#e0f2fe; color:#0369a1; font-weight:600;">${escapeHtml(item.category)}</span>
            <span style="font-size:11px; color:var(--muted);">
              v${item.version} • ${item.is_revoked ? '<span style="color:var(--negative); font-weight:600;">Permanently Revoked</span>' : (item.reuse_consent ? '<span style="color:var(--positive); font-weight:600;">Consent Granted</span>' : '<span style="color:#b45309; font-weight:600;">Consent Pending</span>')}
            </span>
          </div>
          <div class="answer-card-question">${escapeHtml(item.question)}</div>
          <div class="answer-card-text">${escapeHtml(item.answer)}</div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; gap:8px;">
            <button type="button" class="btn-secondary" style="font-size:11px; padding:4px 8px;" onclick="navigator.clipboard.writeText('${escapeHtml(item.answer.replace(/'/g, "\\'"))}'); showToast('Copied answer to clipboard!', 'success');">Copy Answer</button>
            <div style="display:flex; gap:6px;">
              ${!item.is_revoked ? `
                <button type="button" class="btn-secondary" style="font-size:11px; padding:4px 8px; ${item.reuse_consent ? 'color:#b45309;' : 'color:var(--positive);'}" onclick="toggleAnswerConsent('${item.id}', ${!item.reuse_consent})">
                  ${item.reuse_consent ? 'Revoke Consent' : 'Grant Consent'}
                </button>
                <button type="button" class="btn-secondary" style="font-size:11px; padding:4px 8px; color:var(--negative);" onclick="permanentlyRevokeAnswer('${item.id}')">
                  Permanent Revoke
                </button>
              ` : `
                <span style="font-size:11px; color:var(--muted); font-style:italic;">Revoked (Read-only)</span>
              `}
            </div>
          </div>
        </div>
      `).join("");
    } catch (err) {
      console.error("Failed to load answers:", err);
    }
  }

  window.toggleAnswerConsent = async function(id, consent) {
    try {
      const res = await fetch(`/api/v1/answers/${id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reuse_consent: consent })
      });
      if (res.ok) {
        loadAnswersData();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast("Failed to update consent: " + (err.detail || res.statusText), "error");
      }
    } catch (err) {
      showToast("Error updating consent: " + err, "error");
    }
  };

  window.permanentlyRevokeAnswer = async function(id) {
    if (!confirm("Are you sure you want to permanently revoke this answer? Revocation is permanent and cannot be undone.")) return;
    try {
      const res = await fetch(`/api/v1/answers/${id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ is_revoked: true, reuse_consent: false })
      });
      if (res.ok) {
        loadAnswersData();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast("Failed to revoke: " + (err.detail || res.statusText), "error");
      }
    } catch (err) {
      showToast("Error revoking answer: " + err, "error");
    }
  };

  window.revokeAnswerItem = async function(id) {
    return window.permanentlyRevokeAnswer(id);
  };

  async function loadSourcesData() {
    try {
      const res = await fetch("/api/v1/sources");
      if (!res.ok) return;
      const sources = await res.json();
      const tbody = document.getElementById("source-registry-tbody");
      if (!tbody) return;

      tbody.innerHTML = sources.map(s => `
        <tr>
          <td><strong>${escapeHtml(s.source_name)}</strong></td>
          <td>${escapeHtml(s.display_name)}</td>
          <td><span class="tag" style="background:#f1f5f9; color:#1e293b; font-weight:600;">${escapeHtml(s.capability_status)}</span></td>
          <td>${s.rate_limit_requests_per_minute} req/min</td>
          <td><span class="tag" style="background:#fee2e2; color:#b91c1c; font-weight:600;">DISABLED</span></td>
          <td>
            <button type="button" class="btn-secondary" style="font-size:11px; padding:4px 8px;" onclick="toggleSourceEnabled('${s.source_name}', ${!s.is_enabled})">
              ${s.is_enabled ? "Disable" : "Enable"}
            </button>
          </td>
        </tr>
      `).join("");
    } catch (err) {
      console.error("Failed to load sources:", err);
    }
  }

  window.toggleSourceEnabled = async function(name, enable) {
    try {
      const res = await fetch(`/api/v1/sources/${name}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_enabled: enable }),
      });
      if (res.ok) {
        loadSourcesData();
      }
    } catch (err) {
      showToast("Error updating source: " + err, "error");
    }
  };

  async function loadAiData() {
    try {
      const res = await fetch("/api/v1/ai/status");
      if (!res.ok) return;
      const ai = await res.json();

      const modeEl = document.getElementById("ai-mode-display");
      if (modeEl) modeEl.textContent = ai.active_mode;
      const capEl = document.getElementById("ai-budget-cap");
      if (capEl) capEl.textContent = `$${ai.budget_cap_usd.toFixed(2)}`;
      const spendEl = document.getElementById("ai-committed-spend");
      if (spendEl) spendEl.textContent = `$${ai.committed_spend_usd.toFixed(2)}`;
      const remEl = document.getElementById("ai-remaining-funds");
      if (remEl) remEl.textContent = `$${ai.remaining_budget_usd.toFixed(2)}`;
    } catch (err) {
      console.error("Failed to load AI data:", err);
    }
  }

  async function askAiQuestion() {
    const qIn = document.getElementById("ai-test-question");
    const q = qIn ? qIn.value.trim() : "";
    if (!q) {
      showToast("Please enter a question to resolve.", "error");
      return;
    }

    try {
      const res = await fetch("/api/v1/ai/answer-question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!res.ok) return;
      const ans = await res.json();

      const box = document.getElementById("ai-answer-result-box");
      const srcTag = document.getElementById("ai-answer-source-tag");
      const confTag = document.getElementById("ai-confidence-tag");
      const textEl = document.getElementById("ai-answer-text");

      if (srcTag) srcTag.textContent = ans.source;
      if (confTag) confTag.textContent = `Confidence: ${(ans.confidence * 100).toFixed(0)}%`;
      if (textEl) textEl.textContent = ans.answer;
      if (box) box.style.display = "block";
    } catch (err) {
      showToast("Error resolving answer: " + err, "error");
    }
  }

  function loadPortabilityData() {
    // Portability view is bound via event listeners
  }

  async function exportFullBackup() {
    try {
      const res = await fetch("/api/v1/data/export", { method: "POST" });
      if (!res.ok) {
        showToast("Export failed", "error");
        return;
      }
      const bundle = await res.json();
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `hire-steward-backup-${new Date().toISOString().substring(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast("Error downloading backup: " + err, "error");
    }
  }

  let stagedImportBundle = null;
  let stagedPreviewToken = null;

  async function handleImportFile(file) {
    if (!file) return;
    try {
      const text = await file.text();
      const bundle = JSON.parse(text);
      stagedImportBundle = bundle;

      const res = await fetch("/api/v1/data/import/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bundle),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Invalid backup format" }));
        showToast("Validation error: " + err.detail, "error");
        return;
      }

      const prev = await res.json();
      stagedPreviewToken = prev.preview_token;
      const modalBox = document.getElementById("import-preview-modal-box");
      const detailsEl = document.getElementById("import-preview-details");

      if (detailsEl) {
        detailsEl.innerHTML = `
          <div><strong>Format Version:</strong> ${escapeHtml(prev.format_version)}</div>
          <div><strong>Checksum Integrity:</strong> ${prev.checksum_verified ? '<span class="tag" style="background:#dcfce7; color:#166534;">Verified OK</span>' : '<span class="tag" style="background:#fee2e2; color:#b91c1c;">Mismatch</span>'}</div>
          <div><strong>Preview Token:</strong> <code style="font-size:11px;">${escapeHtml(prev.preview_token ? prev.preview_token.substring(0, 16) + '...' : 'none')}</code></div>
          <div style="margin-top:6px;"><strong>Records:</strong> Profile: ${prev.new_counts.candidate_profile || 0}, Answers: ${prev.new_counts.answer_bank_items || 0}, Facts: ${prev.new_counts.candidate_facts || 0}, Applications: ${prev.new_counts.tracked_applications || 0}</div>
          <div style="margin-top:4px;"><strong>Collisions:</strong> Profile: ${prev.collision_counts.candidate_profile || 0}, Answers: ${prev.collision_counts.answer_bank_items || 0}, Facts: ${prev.collision_counts.candidate_facts || 0}</div>
          <div style="margin-top:4px; color:var(--muted);">Existing records will be safely updated and restored atomically.</div>
        `;
      }
      if (modalBox) modalBox.style.display = "block";
    } catch (err) {
      showToast("Error reading backup JSON: " + err, "error");
    }
  }

  async function confirmImportCommit() {
    if (!stagedImportBundle) return;
    try {
      const res = await fetch("/api/v1/data/import/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bundle: stagedImportBundle,
          preview_token: stagedPreviewToken,
          overwrite_existing: true,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Restore failed" }));
        showToast("Restore failed: " + err.detail, "error");
        return;
      }

      showToast("Backup successfully restored! Refreshing state...", "success");
      document.getElementById("import-preview-modal-box").style.display = "none";
      loadOverviewData();
      switchView("overview");
    } catch (err) {
      showToast("Error committing restore: " + err, "error");
    }
  }

  async function loadActivityData() {
    try {
      const res = await fetch("/api/v1/system/activity?limit=50");
      if (!res.ok) return;
      const acts = await res.json();
      renderActivityList(acts, "full-activity-feed");
    } catch (err) {
      console.error("Failed to load activity:", err);
    }
  }

  function renderActivityList(items, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML = '<div class="state-desc" style="padding:16px;">No recent events recorded.</div>';
      return;
    }

    container.innerHTML = items.map(act => `
      <div class="activity-item">
        <div class="activity-item-header">
          <span class="tag" style="background:#e0f2fe; color:#0369a1; font-size:10px;">${escapeHtml(act.type || "EVENT")}</span>
          <span class="num">${new Date(act.timestamp).toLocaleString()}</span>
        </div>
        <div class="activity-item-title">${escapeHtml(act.title || "")}</div>
        <div class="activity-item-detail">${escapeHtml(act.detail || "")}</div>
      </div>
    `).join("");
  }

  async function loadSystemData() {
    try {
      const res = await fetch("/api/v1/system/status");
      if (!res.ok) return;
      const sys = await res.json();

      const stVal = document.getElementById("sys-status-val");
      if (stVal) stVal.textContent = sys.status === "healthy" ? "Healthy" : "Degraded";
      const dbVal = document.getElementById("sys-db-val");
      if (dbVal) dbVal.textContent = sys.database?.connected ? "Connected (OK)" : "Offline";
      const strVal = document.getElementById("sys-storage-val");
      if (strVal) strVal.textContent = sys.storage?.writable ? "Writable (OK)" : "Read-Only";
      const strPath = document.getElementById("sys-storage-path");
      if (strPath) strPath.textContent = sys.storage?.path || "Local Storage";
      const jobVal = document.getElementById("sys-total-jobs");
      if (jobVal) jobVal.textContent = sys.metrics?.total_opportunities || 0;
    } catch (err) {
      console.error("Failed to load system data:", err);
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
    if (elements.searchInput) {
      elements.searchInput.addEventListener("input", e => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          state.filters.search = e.target.value.trim();
          fetchJobs();
        }, 250);
      });
    }

    // Workplace filter
    if (elements.workplaceFilter) {
      elements.workplaceFilter.addEventListener("change", e => {
        state.filters.workplace = e.target.value;
        fetchJobs();
      });
    }

    // Sort select
    if (elements.sortSelect) {
      elements.sortSelect.addEventListener("change", e => {
        state.filters.sort = e.target.value;
        fetchJobs();
      });
    }

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
    if (elements.addJobBtn) {
      elements.addJobBtn.addEventListener("click", openJobIntakeModal);
    }

    // All 13 Sidebar Navigation Buttons
    document.querySelectorAll(".sidebar-nav .nav-item").forEach(btn => {
      btn.addEventListener("click", () => {
        closeMobileSidebar();
        const view = btn.getAttribute("data-view");
        if (view) switchView(view);
      });
    });

    // Quick Action Card Links
    document.getElementById("qa-upload-resume")?.addEventListener("click", () => switchView("evidence"));
    document.getElementById("qa-explore-jobs")?.addEventListener("click", () => switchView("opportunities"));
    document.getElementById("qa-view-pipeline")?.addEventListener("click", () => switchView("pipeline"));
    document.getElementById("qa-backup-data")?.addEventListener("click", () => switchView("portability"));

    // Candidate Profile Save & Reset
    document.getElementById("candidate-profile-form")?.addEventListener("submit", saveProfileData);
    document.getElementById("prof-reset-btn")?.addEventListener("click", loadProfileData);
    document.getElementById("prof-add-exp-btn")?.addEventListener("click", () => addEmploymentRow({}));
    document.getElementById("prof-add-edu-btn")?.addEventListener("click", () => addEducationRow({}));
    document.getElementById("prof-add-proj-btn")?.addEventListener("click", () => addProjectRow({}));
    document.getElementById("prof-add-cert-btn")?.addEventListener("click", () => addCertRow({}));

    // Evidence Library Dropzone & Browse
    const dropzone = document.getElementById("document-dropzone");
    const fileInput = document.getElementById("document-file-input");
    document.getElementById("browse-doc-btn")?.addEventListener("click", () => fileInput?.click());
    fileInput?.addEventListener("change", e => {
      if (e.target.files && e.target.files[0]) handleFileUpload(e.target.files[0]);
    });
    if (dropzone) {
      dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.style.borderColor = "var(--accent)"; });
      dropzone.addEventListener("dragleave", e => { e.preventDefault(); dropzone.style.borderColor = "var(--control)"; });
      dropzone.addEventListener("drop", e => {
        e.preventDefault();
        dropzone.style.borderColor = "var(--control)";
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
          handleFileUpload(e.dataTransfer.files[0]);
        }
      });
    }

    // Answer Bank New Response & Filter Pills
    document.getElementById("add-answer-btn")?.addEventListener("click", openNewAnswerModal);
    document.querySelectorAll("#answer-cat-pills button").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#answer-cat-pills button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const cat = btn.getAttribute("data-cat") || "";
        loadAnswersData(cat);
      });
    });

    // Preparation Generate, Plan & Simulation
    document.getElementById("prep-job-select")?.addEventListener("change", e => {
      state.selectedPostingId = e.target.value || null;
    });
    document.getElementById("prep-generate-btn")?.addEventListener("click", generatePreparationDraft);
    document.getElementById("prep-create-plan-btn")?.addEventListener("click", createSubmissionPlanFromDraft);
    document.getElementById("prep-simulate-btn")?.addEventListener("click", simulateSubmissionFromDraft);
    initPreparationTabs();

    // Settings Save
    document.getElementById("load-recommended-defaults-btn")?.addEventListener("click", loadRecommendedDefaults);
    document.getElementById("save-settings-btn")?.addEventListener("click", saveSettingsData);

    // AI Question Answering
    document.getElementById("ai-ask-btn")?.addEventListener("click", askAiQuestion);

    // Export & Import Buttons
    document.getElementById("export-download-btn")?.addEventListener("click", exportFullBackup);
    const importFileInput = document.getElementById("import-file-input");
    document.getElementById("import-browse-btn")?.addEventListener("click", () => importFileInput?.click());
    importFileInput?.addEventListener("change", e => {
      if (e.target.files && e.target.files[0]) handleImportFile(e.target.files[0]);
    });
    document.getElementById("import-confirm-btn")?.addEventListener("click", confirmImportCommit);
    document.getElementById("import-cancel-btn")?.addEventListener("click", () => {
      const box = document.getElementById("import-preview-modal-box");
      if (box) box.style.display = "none";
    });

    // Refresh Buttons
    document.getElementById("dash-refresh-activity")?.addEventListener("click", () => loadOverviewData());
    document.getElementById("refresh-activity-btn")?.addEventListener("click", () => loadActivityData());

    // Pipeline status filter pills
    if (elements.pipelineStatusPills) {
      elements.pipelineStatusPills.forEach(btn => {
        btn.addEventListener("click", () => {
          elements.pipelineStatusPills.forEach(b => {
            b.classList.remove("active");
            b.setAttribute("aria-selected", "false");
          });
          btn.classList.add("active");
          btn.setAttribute("aria-selected", "true");
          state.pipelineFilterStatus = btn.getAttribute("data-pipeline-status") || "";
          fetchPipelineApplications();
        });
      });
    }

    // Pipeline sort select
    if (elements.pipelineSortSelect) {
      elements.pipelineSortSelect.addEventListener("change", e => {
        state.pipelineSortBy = e.target.value;
        fetchPipelineApplications();
      });
    }

    // Mobile navigation drawer controls
    if (elements.mobileMenuBtn) {
      elements.mobileMenuBtn.addEventListener("click", e => {
        e.stopPropagation();
        toggleMobileSidebar();
      });
    }

    if (elements.sidebarBackdrop) {
      elements.sidebarBackdrop.addEventListener("click", () => {
        closeMobileSidebar();
      });
    }

    document.addEventListener("click", e => {
      if (elements.sidebar && elements.sidebar.classList.contains("sidebar-open")) {
        if (!elements.sidebar.contains(e.target) && (!elements.mobileMenuBtn || !elements.mobileMenuBtn.contains(e.target))) {
          closeMobileSidebar();
        }
      }
    });

    const mql = window.matchMedia("(min-width: 901px)");
    if (mql.addEventListener) {
      mql.addEventListener("change", e => {
        if (e.matches) closeMobileSidebar();
      });
    } else if (mql.addListener) {
      mql.addListener(e => {
        if (e.matches) closeMobileSidebar();
      });
    }

    // Keyboard shortcuts
    window.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (state.currentView !== "opportunities") {
          switchView("opportunities");
        }
        elements.searchInput.focus();
        elements.searchInput.select();
      } else if (e.key === "Escape") {
        if (elements.modalContainer && elements.modalContainer.style.display !== "none") {
          closeModal();
        } else if (elements.detailPane.classList.contains("mobile-visible")) {
          elements.detailPane.classList.remove("mobile-visible");
        } else if (elements.sidebar && elements.sidebar.classList.contains("sidebar-open")) {
          closeMobileSidebar();
        } else if (document.activeElement === elements.searchInput) {
          elements.searchInput.blur();
        }
      }
    });
  }

  // Initialization
  setupEventListeners();
  switchView("overview");
})();
