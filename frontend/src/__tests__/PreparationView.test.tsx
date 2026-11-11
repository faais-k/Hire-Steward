import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PreparationView } from '../views/PreparationView';
import { api, ApiError } from '../api/client';
import type { JobPosting } from '../types';

const mockJobs: JobPosting[] = [
  {
    id: 'job-101',
    title: 'Senior Distributed Systems Engineer',
    employer_name: 'CloudScale Inc',
    location: 'Remote',
    workplace_type: 'remote',
    employment_type: 'Full-time',
    description_text: 'Build resilient distributed backends with strict safety gates.',
    salary_min: 150000,
    salary_max: 200000,
    salary_currency: 'USD',
    url: 'https://example.com/jobs/101',
    observed_at: '2026-11-10T12:00:00Z',
    match_score: 0.95,
    match_tier: 'Top Match',
  },
];

describe('PreparationView Fail-Closed Error Handling & Safety Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('preserves user input and displays error banner on HTTP 422 POLICY_BLOCKED when saving plan', async () => {
    vi.spyOn(api, 'createSubmissionPlan').mockRejectedValueOnce(
      new ApiError(422, 'POLICY_BLOCKED: Compensation below hard floor')
    );

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const resumeEditor = document.getElementById('prep-resume-editor') as HTMLTextAreaElement;
    const coverEditor = document.getElementById('prep-cover-editor') as HTMLTextAreaElement;

    fireEvent.change(resumeEditor, { target: { value: '# My Custom Reviewed Resume' } });
    fireEvent.change(coverEditor, { target: { value: 'Dear CloudScale Team' } });

    const savePlanBtn = document.getElementById('prep-create-plan-btn')!;
    fireEvent.click(savePlanBtn);

    await waitFor(() => {
      const banner = document.getElementById('prep-error-banner');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText('POLICY_BLOCKED')).toBeInTheDocument();
      expect(screen.getByText('Submission Policy Gate Blocked')).toBeInTheDocument();
      expect(screen.getByText(/Compensation below hard floor/)).toBeInTheDocument();
      expect(document.getElementById('prep-retry-btn')).toBeInTheDocument();
    });

    // Verify user entered text is preserved
    expect(resumeEditor.value).toBe('# My Custom Reviewed Resume');
    expect(coverEditor.value).toBe('Dear CloudScale Team');

    // Crucial: No fabricated receipt or hash
    const receipt = document.getElementById('prep-simulation-receipt');
    expect(receipt).not.toBeInTheDocument();
  });

  it('displays API_UNAVAILABLE on network connection failure and allows retry', async () => {
    const mockPlan = vi.spyOn(api, 'createSubmissionPlan')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({
        plan_id: 'real-plan-xyz',
        plan_hash: 'a'.repeat(64),
        message: 'Signed',
        is_compensation_eligible: true,
        is_cooldown_clear: true,
      });

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const resumeEditor = document.getElementById('prep-resume-editor') as HTMLTextAreaElement;
    fireEvent.change(resumeEditor, { target: { value: '# Verified Resume' } });

    const savePlanBtn = document.getElementById('prep-create-plan-btn')!;
    fireEvent.click(savePlanBtn);

    await waitFor(() => {
      expect(screen.getByText('API_UNAVAILABLE')).toBeInTheDocument();
      expect(screen.getByText('Backend Service Unavailable')).toBeInTheDocument();
    });

    // Click retry
    const retryBtn = document.getElementById('prep-retry-btn')!;
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(mockPlan).toHaveBeenCalledTimes(2);
      expect(screen.queryByText('API_UNAVAILABLE')).not.toBeInTheDocument();
      const receipt = document.getElementById('prep-simulation-receipt');
      expect(receipt).toBeInTheDocument();
      expect(receipt?.textContent).toContain('real-plan-xyz');
    });
  });

  it('never fabricates passing readiness report on HTTP 500 error', async () => {
    vi.spyOn(api, 'getReadiness').mockRejectedValueOnce(
      new ApiError(500, 'Internal Server Error: Database pool timeout')
    );

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const readinessBtn = document.getElementById('prep-readiness-btn')!;
    fireEvent.click(readinessBtn);

    await waitFor(() => {
      const banner = document.getElementById('prep-error-banner');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText('Server Error (HTTP 500)')).toBeInTheDocument();
      expect(screen.getByText(/Database pool timeout/)).toBeInTheDocument();
    });

    // Crucial: No fabricated passing readiness badge
    expect(screen.queryByText('READY FOR SUBMISSION')).not.toBeInTheDocument();
    expect(document.getElementById('prep-readiness-card')).not.toBeInTheDocument();
  });

  it('never fabricates generic recruiter message on HTTP 404', async () => {
    vi.spyOn(api, 'generateRecruiterMessage').mockRejectedValueOnce(
      new ApiError(404, 'POSTING_NOT_FOUND')
    );

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const recruiterBtn = document.getElementById('prep-recruiter-btn')!;
    fireEvent.click(recruiterBtn);

    await waitFor(() => {
      expect(screen.getByText('VALIDATION_FAILURE')).toBeInTheDocument();
      expect(screen.getByText('Target Resource Not Found')).toBeInTheDocument();
    });

    // Crucial: No generic placeholder recruiter card or message body rendered
    expect(document.getElementById('prep-recruiter-card')).not.toBeInTheDocument();
  });

  it('displays honest simulation error on HTTP 422 SIMULATION_POLICY_BLOCKED without fabricating success', async () => {
    vi.spyOn(api, 'simulateSubmission').mockRejectedValueOnce(
      new ApiError(422, 'POLICY_BLOCKED: Simulation rejected by policy gate: Active cooldown in effect')
    );

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const simulateBtn = document.getElementById('prep-simulate-btn')!;
    fireEvent.click(simulateBtn);

    await waitFor(() => {
      expect(screen.getByText('POLICY_BLOCKED')).toBeInTheDocument();
      expect(screen.getByText(/Active cooldown in effect/)).toBeInTheDocument();
    });

    // Must NOT show fake success receipt
    expect(screen.queryByText(/SUCCESS_DRY_RUN/)).not.toBeInTheDocument();
    expect(document.getElementById('prep-simulation-receipt')).not.toBeInTheDocument();
  });

  it('renders validated simulation receipt only upon true backend success', async () => {
    vi.spyOn(api, 'simulateSubmission').mockResolvedValueOnce({
      simulation_id: 'attempt-real-uuid',
      receipt: 'Simulated ATS Submission Receipt (Dry-Run)\nPlan ID: real-plan\nReceipt ID: sim_rec_12345\nStatus: SIMULATED_SUCCESS',
      dry_run: true,
      status: 'SIMULATED_SUCCESS',
    });

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const simulateBtn = document.getElementById('prep-simulate-btn')!;
    fireEvent.click(simulateBtn);

    await waitFor(() => {
      const receipt = document.getElementById('prep-simulation-receipt');
      expect(receipt).toBeInTheDocument();
      expect(receipt?.textContent).toContain('sim_rec_12345');
      expect(receipt?.textContent).toContain('SIMULATED_SUCCESS');
      expect(screen.getByText(/Dry-run simulation completed: SIMULATED_SUCCESS/)).toBeInTheDocument();
    });
  });

  it('displays readiness report with blocking issues honestly when returned by backend', async () => {
    vi.spyOn(api, 'getReadiness').mockResolvedValueOnce({
      id: 'rep-1',
      ready_for_submission: false,
      blocking_issues: ['Compensation below hard floor or unverified', 'Active cooldown period with employer'],
      warnings: ['2 unreviewed facts in profile'],
      checks: [
        { name: 'Compensation Policy Gate', passed: false, severity: 'BLOCKING', details: 'Compensation below floor.' },
        { name: 'Employer Cooldown Gate', passed: false, severity: 'BLOCKING', details: 'Cooldown active.' },
        { name: 'Evidence Truthfulness Check', passed: true, severity: 'INFO', details: 'Evidence grounded.' },
      ],
    });

    render(
      <PreparationView
        jobs={mockJobs}
        selectedJobId="job-101"
        onSelectJob={() => {}}
      />
    );

    const readinessBtn = document.getElementById('prep-readiness-btn')!;
    fireEvent.click(readinessBtn);

    await waitFor(() => {
      const card = document.getElementById('prep-readiness-card');
      expect(card).toBeInTheDocument();
      expect(screen.getByText('REQUIRES REVIEW')).toBeInTheDocument();
      expect(screen.getByText('Compensation below hard floor or unverified')).toBeInTheDocument();
      expect(screen.getByText('Active cooldown period with employer')).toBeInTheDocument();
    });
  });
});
