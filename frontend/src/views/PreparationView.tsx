import React, { useState, useEffect } from 'react';
import { api, ApiError } from '../api/client';
import type { JobPosting } from '../types';

interface PreparationViewProps {
  jobs: JobPosting[];
  selectedJobId: string | null;
  onSelectJob: (jobId: string) => void;
}

interface ReadinessReport {
  id: string;
  ready_for_submission: boolean;
  blocking_issues: string[];
  warnings: string[];
  checks: Array<{ name: string; passed: boolean; severity: string; details: string }>;
}

export interface ActionError {
  action: 'tailor' | 'plan' | 'approve' | 'simulate' | 'recruiter' | 'readiness';
  category: 'API_UNAVAILABLE' | 'VALIDATION_FAILURE' | 'INSUFFICIENT_EVIDENCE' | 'POLICY_BLOCKED' | 'SERVER_ERROR';
  title: string;
  message: string;
  retryFn: () => void;
}

export type WorkflowStage =
  | 'DRAFT'
  | 'PLAN_CREATED'
  | 'REVIEW_REQUIRED'
  | 'APPROVED'
  | 'SIMULATION_SUCCESS'
  | 'SIMULATION_FAILED';

export function parseActionError(
  err: unknown,
  action: ActionError['action'],
  retryFn: () => void
): ActionError {
  let status = 0;
  let detail = '';

  if (err instanceof ApiError) {
    status = err.status;
    detail = err.message || '';
  } else if (err && typeof err === 'object') {
    if ('status' in err) {
      status = Number((err as { status: unknown }).status) || 0;
    }
    if ('message' in err) {
      detail = String((err as { message: unknown }).message || '');
    }
  } else if (err instanceof Error) {
    detail = err.message;
  } else {
    detail = String(err);
  }

  let category: ActionError['category'] = 'SERVER_ERROR';
  let title = 'Request Failed';

  const lower = detail.toLowerCase();
  if (status === 0 || lower.includes('failed to fetch') || lower.includes('networkerror') || lower.includes('connection refused')) {
    category = 'API_UNAVAILABLE';
    title = 'Backend Service Unavailable';
    detail = 'Unable to reach the local Hire-Steward backend at http://127.0.0.1:8000/. Verify the server process is active.';
  } else if (status === 422 || status === 400) {
    if (
      detail.includes('POLICY_BLOCKED') ||
      detail.includes('COOLDOWN') ||
      detail.includes('COMPENSATION') ||
      detail.includes('hard floor') ||
      detail.includes('unpaid')
    ) {
      category = 'POLICY_BLOCKED';
      title = 'Submission Policy Gate Blocked';
    } else if (
      detail.includes('EVIDENCE') ||
      detail.includes('INSUFFICIENT') ||
      detail.includes('SNAPSHOT_NOT_FOUND') ||
      detail.includes('UNVERIFIED')
    ) {
      category = 'INSUFFICIENT_EVIDENCE';
      title = 'Insufficient Candidate Evidence';
    } else {
      category = 'VALIDATION_FAILURE';
      title = 'Validation Failure';
    }
  } else if (status === 404) {
    category = 'VALIDATION_FAILURE';
    title = 'Target Resource Not Found';
    detail = detail || 'The selected job posting or submission plan was not found in the workspace database.';
  } else if (status >= 500) {
    category = 'SERVER_ERROR';
    title = `Server Error (HTTP ${status})`;
  }

  return {
    action,
    category,
    title,
    message: detail,
    retryFn,
  };
}

export const PreparationView: React.FC<PreparationViewProps> = ({
  jobs,
  selectedJobId,
  onSelectJob,
}) => {
  const [currentJobId, setCurrentJobId] = useState<string>(selectedJobId || (jobs[0]?.id || ''));
  const [resumeText, setResumeText] = useState<string>('');
  const [coverText, setCoverText] = useState<string>('');
  const [claims, setClaims] = useState<Array<{ claim: string; fact_id?: string; source_excerpt?: string }>>([]);
  const [simulationReceipt, setSimulationReceipt] = useState<string>('');
  const [createdPlanId, setCreatedPlanId] = useState<string>('');
  const [planHash, setPlanHash] = useState<string>('');
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>('DRAFT');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);

  // Recruiter Outreach State
  const [recruiterSubject, setRecruiterSubject] = useState<string>('');
  const [recruiterBody, setRecruiterBody] = useState<string>('');
  const [isGeneratingRecruiter, setIsGeneratingRecruiter] = useState(false);
  const [copiedRecruiter, setCopiedRecruiter] = useState(false);

  // Readiness State
  const [readinessReport, setReadinessReport] = useState<ReadinessReport | null>(null);
  const [isLoadingReadiness, setIsLoadingReadiness] = useState(false);

  // Fail-Closed Feedback States
  const [currentError, setCurrentError] = useState<ActionError | null>(null);
  const [successNotice, setSuccessNotice] = useState<string>('');

  useEffect(() => {
    if (selectedJobId && selectedJobId !== currentJobId) {
      setCurrentJobId(selectedJobId);
      setReadinessReport(null);
      setCurrentError(null);
      setSuccessNotice('');
      setWorkflowStage('DRAFT');
      setCreatedPlanId('');
      setPlanHash('');
    } else if (!currentJobId && jobs.length > 0) {
      setCurrentJobId(jobs[0].id);
      setReadinessReport(null);
      setCurrentError(null);
      setSuccessNotice('');
      setWorkflowStage('DRAFT');
      setCreatedPlanId('');
      setPlanHash('');
    }
  }, [selectedJobId, jobs]);

  const handleMaterialChange = (type: 'resume' | 'cover', value: string) => {
    if (type === 'resume') {
      setResumeText(value);
    } else {
      setCoverText(value);
    }
    if (workflowStage !== 'DRAFT' || createdPlanId) {
      setWorkflowStage('DRAFT');
      setCreatedPlanId('');
      setPlanHash('');
      setSimulationReceipt('');
      setSuccessNotice('Materials modified: previous plan and approval invalidated. Create a new plan to review and approve.');
    }
  };

  const handleGenerate = async () => {
    if (!currentJobId) return;
    setIsGenerating(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.generateTailoredDraft(currentJobId);
      setResumeText(res.tailored_resume || '');
      setCoverText(res.tailored_cover_letter || '');
      setClaims(res.grounded_claims || []);
      setWorkflowStage('DRAFT');
      setCreatedPlanId('');
      setPlanHash('');
      setSuccessNotice('Tailored resume and cover letter successfully generated from verified facts.');
    } catch (err) {
      // Form data is preserved; error is surfaced explicitly without fabricating content
      setCurrentError(parseActionError(err, 'tailor', handleGenerate));
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCreatePlan = async () => {
    if (!currentJobId) return;
    setIsPlanning(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.createSubmissionPlan({
        job_posting_id: currentJobId,
        resume_text: resumeText,
        cover_letter_text: coverText,
      });
      setCreatedPlanId(res.plan_id);
      setPlanHash(res.plan_hash);
      setWorkflowStage('PLAN_CREATED');
      setSimulationReceipt(
        `Frozen Submission Plan Created (Unapproved)\n` +
        `Plan ID: ${res.plan_id}\n` +
        `Packet SHA-256: ${res.plan_hash}\n` +
        `Compensation Gate: ${res.is_compensation_eligible ? 'ELIGIBLE' : 'INELIGIBLE'}\n` +
        `Cooldown Gate: ${res.is_cooldown_clear ? 'CLEAR' : 'BLOCKED'}\n` +
        `Approval Status: REVIEW_REQUIRED (Explicit candidate approval required before simulation)`
      );
      setSuccessNotice('Submission plan successfully frozen with verified SHA-256 hash. Review materials and explicitly approve below.');
    } catch (err) {
      // Never fabricate plan IDs or hashes on failure
      setCreatedPlanId('');
      setPlanHash('');
      setSimulationReceipt('');
      setWorkflowStage('DRAFT');
      setCurrentError(parseActionError(err, 'plan', handleCreatePlan));
    } finally {
      setIsPlanning(false);
    }
  };

  const handleApprove = async () => {
    if (!createdPlanId) return;
    setIsApproving(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.approveSubmissionPlan(createdPlanId);
      setWorkflowStage('APPROVED');
      setSimulationReceipt(
        `Plan Approved by Candidate\n` +
        `Plan ID: ${res.plan_id}\n` +
        `Review State: ${res.review_state}\n` +
        `Approval State: ${res.approval_state}\n` +
        `Packet SHA-256: ${res.packet_hash}\n` +
        `Reviewed At: ${res.reviewed_at}\n` +
        `Status: Authenticated for safe loopback dry-run dispatch.`
      );
      setSuccessNotice('Submission plan and frozen materials explicitly approved by candidate. Dry-run simulation unlocked.');
    } catch (err) {
      setWorkflowStage('REVIEW_REQUIRED');
      setCurrentError(parseActionError(err, 'approve', handleApprove));
    } finally {
      setIsApproving(false);
    }
  };

  const handleSimulate = async () => {
    if (!currentJobId) return;
    if (workflowStage !== 'APPROVED') {
      setWorkflowStage('REVIEW_REQUIRED');
      setCurrentError({
        action: 'simulate',
        category: 'POLICY_BLOCKED',
        title: 'Simulation Blocked: Approval Required',
        message: 'Explicit candidate approval is required before running simulated ATS dispatch. Review and approve the frozen plan first.',
        retryFn: handleSimulate,
      });
      return;
    }
    setIsSimulating(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.simulateSubmission({
        job_posting_id: currentJobId,
        plan_id: createdPlanId || undefined,
      });
      setSimulationReceipt(res.receipt);
      if (res.status === 'SIMULATED_SUCCESS' || res.status === 'COMPLETED' || res.status === 'SUCCESS') {
        setWorkflowStage('SIMULATION_SUCCESS');
        setSuccessNotice(`Dry-run simulation completed: ${res.status}`);
      } else {
        setWorkflowStage('SIMULATION_FAILED');
        setSuccessNotice(`Dry-run simulation recorded: ${res.status}`);
      }
    } catch (err) {
      setWorkflowStage('SIMULATION_FAILED');
      setSimulationReceipt('');
      setCurrentError(parseActionError(err, 'simulate', handleSimulate));
    } finally {
      setIsSimulating(false);
    }
  };

  const handleGenerateRecruiter = async () => {
    if (!currentJobId) return;
    setIsGeneratingRecruiter(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.generateRecruiterMessage(currentJobId, 'Professional & Direct');
      setRecruiterSubject(res.subject);
      setRecruiterBody(res.body);
      setSuccessNotice('Personalized recruiter outreach draft generated from verified candidate facts.');
    } catch (err) {
      // Never fabricate generic template text on failure
      setRecruiterSubject('');
      setRecruiterBody('');
      setCurrentError(parseActionError(err, 'recruiter', handleGenerateRecruiter));
    } finally {
      setIsGeneratingRecruiter(false);
    }
  };

  const handleCopyRecruiter = () => {
    const fullText = `Subject: ${recruiterSubject}\n\n${recruiterBody}`;
    navigator.clipboard.writeText(fullText);
    setCopiedRecruiter(true);
    setTimeout(() => setCopiedRecruiter(false), 2000);
  };

  const handleCheckReadiness = async () => {
    if (!currentJobId) return;
    setIsLoadingReadiness(true);
    setCurrentError(null);
    setSuccessNotice('');
    try {
      const res = await api.getReadiness(currentJobId);
      setReadinessReport(res);
      setSuccessNotice(
        res.ready_for_submission
          ? 'Readiness audit passed: All deterministic safety gates satisfied.'
          : 'Readiness audit complete: Review required before submission.'
      );
    } catch (err) {
      // Never fabricate passing readiness report on failure
      setReadinessReport(null);
      setCurrentError(parseActionError(err, 'readiness', handleCheckReadiness));
    } finally {
      setIsLoadingReadiness(false);
    }
  };

  return (
    <main className="view-container" id="preparation-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Application Preparation &amp; Materials Tailoring</h2>
            <div className="state-desc">
              Generate evidence-grounded resume drafts, cover letters, recruiter outreach, and submission audits.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <label htmlFor="prep-job-select" style={{ fontSize: '13px', fontWeight: 600 }}>
              Opportunity:
            </label>
            <select
              id="prep-job-select"
              className="form-input"
              style={{ width: 'auto', minWidth: '220px' }}
              value={currentJobId}
              onChange={(e) => {
                setCurrentJobId(e.target.value);
                onSelectJob(e.target.value);
              }}
            >
              <option value="">Select an opportunity...</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title} — {j.employer_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Workflow Stage Bar */}
        <div
          id="prep-workflow-status"
          style={{
            marginTop: '12px',
            padding: '10px 14px',
            borderRadius: '6px',
            background: 'var(--jp-surface-2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '13px',
            flexWrap: 'wrap',
            gap: '8px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600 }}>Workflow Stage:</span>
            <span
              id="prep-stage-badge"
              className={`badge ${
                workflowStage === 'APPROVED' || workflowStage === 'SIMULATION_SUCCESS'
                  ? 'badge-success'
                  : workflowStage === 'SIMULATION_FAILED'
                  ? 'badge-danger'
                  : workflowStage === 'REVIEW_REQUIRED'
                  ? 'badge-warning'
                  : workflowStage === 'PLAN_CREATED'
                  ? 'badge-info'
                  : 'badge-secondary'
              }`}
            >
              {workflowStage}
            </span>
            {workflowStage === 'PLAN_CREATED' && (
              <span className="badge badge-warning" id="prep-review-required-tag">REVIEW_REQUIRED</span>
            )}
            {workflowStage === 'APPROVED' && (
              <span style={{ color: 'var(--jp-text-muted)', fontSize: '12px' }}>
                (Explicit candidate approval active — simulation unlocked)
              </span>
            )}
          </div>
          {createdPlanId && (
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
              Plan ID: <code style={{ fontSize: '11px' }}>{createdPlanId.slice(0, 8)}...</code>
              {planHash && (
                <> | Packet SHA: <code style={{ fontSize: '11px' }}>{planHash.slice(0, 10)}...</code></>
              )}
            </div>
          )}
        </div>

        {/* Action Controls */}
        <div style={{ marginTop: '16px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button
            type="button"
            id="prep-generate-btn"
            className="btn-primary"
            onClick={handleGenerate}
            disabled={!currentJobId || isGenerating}
          >
            {isGenerating ? 'Generating Drafts...' : '1. Generate Tailored Draft'}
          </button>

          <button
            type="button"
            id="prep-create-plan-btn"
            className="btn-secondary"
            onClick={handleCreatePlan}
            disabled={!resumeText || isPlanning}
          >
            {isPlanning ? 'Saving Plan...' : '2. Save to Pipeline Plan'}
          </button>

          <button
            type="button"
            id="prep-approve-btn"
            className={`btn-secondary ${workflowStage === 'APPROVED' ? 'btn-success' : ''}`}
            onClick={handleApprove}
            disabled={!createdPlanId || workflowStage === 'APPROVED' || isApproving}
            title={!createdPlanId ? 'Create a submission plan first' : 'Explicit candidate approval of frozen materials'}
          >
            {isApproving ? 'Approving...' : workflowStage === 'APPROVED' ? '✓ Plan Approved' : '3. Approve Frozen Plan & Materials'}
          </button>

          <button
            type="button"
            id="prep-simulate-btn"
            className="btn-secondary"
            onClick={handleSimulate}
            disabled={workflowStage !== 'APPROVED' || isSimulating}
            title={workflowStage !== 'APPROVED' ? 'Simulation disabled: Candidate must explicitly approve frozen plan first' : 'Run safe loopback dry-run'}
          >
            {isSimulating ? 'Simulating...' : '4. Simulate Submission (Dry-Run)'}
          </button>

          <button
            type="button"
            id="prep-recruiter-btn"
            className="btn-secondary"
            onClick={handleGenerateRecruiter}
            disabled={!currentJobId || isGeneratingRecruiter}
          >
            {isGeneratingRecruiter ? 'Drafting...' : '5. Draft Recruiter Message'}
          </button>

          <button
            type="button"
            id="prep-readiness-btn"
            className="btn-secondary"
            onClick={handleCheckReadiness}
            disabled={!currentJobId || isLoadingReadiness}
          >
            {isLoadingReadiness ? 'Auditing...' : '6. Audit Submission Readiness'}
          </button>
        </div>

        {/* Fail-Closed Action Error Alert */}
        {currentError && (
          <div
            id="prep-error-banner"
            style={{
              marginTop: '16px',
              padding: '14px',
              borderRadius: '6px',
              background: '#fef2f2',
              border: '1px solid #f87171',
              color: '#991b1b',
              fontSize: '13px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className={`badge ${currentError.category === 'POLICY_BLOCKED' ? 'badge-danger' : 'badge-warning'}`}>
                  {currentError.category}
                </span>
                <strong style={{ fontSize: '14px' }}>{currentError.title}</strong>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  id="prep-retry-btn"
                  className="btn-secondary"
                  onClick={currentError.retryFn}
                  style={{ fontSize: '12px', padding: '4px 10px' }}
                >
                  Retry Action
                </button>
                <button
                  type="button"
                  id="prep-dismiss-error-btn"
                  onClick={() => setCurrentError(null)}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#991b1b',
                    fontWeight: 700,
                  }}
                >
                  ✕
                </button>
              </div>
            </div>
            <div style={{ marginTop: '8px', lineHeight: 1.5 }}>
              {currentError.message}
            </div>
          </div>
        )}

        {/* Success Notice Banner */}
        {successNotice && (
          <div
            id="prep-success-banner"
            style={{
              marginTop: '16px',
              padding: '12px 14px',
              borderRadius: '6px',
              background: '#f0fdf4',
              border: '1px solid #86efac',
              color: '#166534',
              fontSize: '13px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>✓ {successNotice}</span>
            <button
              type="button"
              onClick={() => setSuccessNotice('')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#166534', fontWeight: 700 }}
            >
              ✕
            </button>
          </div>
        )}

        {/* Submission & Simulation Receipt */}
        {simulationReceipt && (
          <div style={{ marginTop: '16px' }}>
            <h4 style={{ fontSize: '13px', marginBottom: '4px' }}>Submission &amp; Dry-Run Receipt:</h4>
            <pre
              id="prep-simulation-receipt"
              style={{
                background: '#f8fafc',
                border: '1px solid var(--jp-border)',
                padding: '12px',
                borderRadius: '6px',
                fontSize: '12px',
                whiteSpace: 'pre-wrap',
                fontFamily: 'monospace',
              }}
            >
              {simulationReceipt}
            </pre>
          </div>
        )}
      </div>

      {/* Recruiter Outreach Card */}
      {(recruiterSubject || recruiterBody) && (
        <div className="section-card" id="prep-recruiter-card" style={{ marginTop: '20px' }}>
          <div className="section-header">
            <div>
              <h3 className="section-title">Personalized Recruiter Outreach Message</h3>
              <div className="state-desc">Evidence-grounded message for hiring team outreach.</div>
            </div>
            <button
              type="button"
              id="prep-copy-recruiter-btn"
              className="btn-secondary"
              onClick={handleCopyRecruiter}
              style={{ fontSize: '12px', padding: '6px 12px' }}
            >
              {copiedRecruiter ? '✓ Copied to Clipboard' : 'Copy Message'}
            </button>
          </div>

          <div style={{ marginTop: '12px' }}>
            <label htmlFor="prep-recruiter-subject" style={{ fontSize: '12px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>
              Subject Line:
            </label>
            <input
              id="prep-recruiter-subject"
              type="text"
              className="form-input"
              value={recruiterSubject}
              onChange={(e) => setRecruiterSubject(e.target.value)}
              style={{ marginBottom: '12px' }}
            />
            <label htmlFor="prep-recruiter-body" style={{ fontSize: '12px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>
              Message Body:
            </label>
            <textarea
              id="prep-recruiter-body"
              className="form-input form-textarea"
              rows={8}
              value={recruiterBody}
              onChange={(e) => setRecruiterBody(e.target.value)}
            />
          </div>
        </div>
      )}

      {/* Submission Readiness Audit Card */}
      {readinessReport && (
        <div className="section-card" id="prep-readiness-card" style={{ marginTop: '20px' }}>
          <div className="section-header">
            <div>
              <h3 className="section-title">Submission Readiness Policy Audit</h3>
              <div className="state-desc">Deterministic pre-flight verification against safety invariants.</div>
            </div>
            <span
              id="prep-readiness-badge"
              className={`badge ${readinessReport.ready_for_submission ? 'badge-success' : 'badge-warning'}`}
            >
              {readinessReport.ready_for_submission ? 'READY FOR SUBMISSION' : 'REQUIRES REVIEW'}
            </span>
          </div>

          {readinessReport.blocking_issues.length > 0 && (
            <div id="prep-blocking-issues" style={{ marginTop: '12px', padding: '10px', background: '#fef2f2', border: '1px solid #f87171', borderRadius: '6px', color: '#991b1b', fontSize: '13px' }}>
              <strong>Blocking Issues:</strong>
              <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                {readinessReport.blocking_issues.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ marginTop: '16px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--jp-border)', textAlign: 'left' }}>
                  <th style={{ padding: '8px 4px' }}>Policy Check</th>
                  <th style={{ padding: '8px 4px' }}>Status</th>
                  <th style={{ padding: '8px 4px' }}>Severity</th>
                  <th style={{ padding: '8px 4px' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {readinessReport.checks.map((chk, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '8px 4px', fontWeight: 500 }}>{chk.name}</td>
                    <td style={{ padding: '8px 4px' }}>
                      <span className={`badge ${chk.passed ? 'badge-success' : 'badge-danger'}`}>
                        {chk.passed ? 'PASS' : 'FAIL'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 4px', color: chk.severity === 'BLOCKING' ? '#dc2626' : 'inherit' }}>
                      {chk.severity}
                    </td>
                    <td style={{ padding: '8px 4px', color: 'var(--jp-text-muted)' }}>{chk.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Editor Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '20px' }}>
        <div className="section-card">
          <div className="section-header">
            <div>
              <h3 className="section-title">Tailored Resume Markdown</h3>
              <div className="state-desc">Reviewed application resume.</div>
            </div>
          </div>
          <textarea
            id="prep-resume-editor"
            className="form-input form-textarea"
            rows={16}
            value={resumeText}
            onChange={(e) => handleMaterialChange('resume', e.target.value)}
            placeholder="Click '1. Generate Tailored Draft' or paste your customized resume here..."
          />
        </div>

        <div className="section-card">
          <div className="section-header">
            <div>
              <h3 className="section-title">Tailored Cover Letter Markdown</h3>
              <div className="state-desc">Evidence-aligned cover letter.</div>
            </div>
          </div>
          <textarea
            id="prep-cover-editor"
            className="form-input form-textarea"
            rows={16}
            value={coverText}
            onChange={(e) => handleMaterialChange('cover', e.target.value)}
            placeholder="Click '1. Generate Tailored Draft' or draft your cover letter here..."
          />
        </div>
      </div>

      {/* Claims Grounding Ledger */}
      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <div>
            <h3 className="section-title">Grounding Ledger &amp; Fact Verification</h3>
            <div className="state-desc">Traceability from tailored statements back to verified evidence.</div>
          </div>
        </div>
        <div id="prep-claims-list">
          {claims.length === 0 ? (
            <div style={{ color: 'var(--jp-text-muted)', fontSize: '13px' }}>
              No claims evaluated yet. Click '1. Generate Tailored Draft' to see factual citations.
            </div>
          ) : (
            <ul style={{ paddingLeft: '20px' }}>
              {claims.map((c, i) => (
                <li key={i} style={{ marginBottom: '8px', fontSize: '13px' }}>
                  <strong>{c.claim}</strong>
                  {c.source_excerpt && (
                    <div style={{ color: 'var(--jp-text-muted)', fontSize: '12px' }}>
                      Anchor: {c.source_excerpt}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </main>
  );
};
