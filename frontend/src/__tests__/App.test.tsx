import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';

// Mock the API client
vi.mock('../api/client', () => {
  return {
    api: {
      getJobs: vi.fn().mockResolvedValue({
        items: [
          {
            id: 'job-1',
            title: 'Staff Distributed Systems Engineer',
            employer_name: 'TechCorp Labs',
            location: 'Remote',
            workplace_type: 'remote',
            description_text: 'Building mission critical distributed systems.',
            observed_at: '2026-11-10T12:00:00Z',
            match_score: 0.92,
            match_tier: 'Strong',
          },
        ],
        total: 1,
      }),
      getApplications: vi.fn().mockResolvedValue([
        {
          id: 'app-1',
          job_posting_id: 'job-1',
          status: 'SAVED',
          created_at: '2026-11-10T12:00:00Z',
          updated_at: '2026-11-10T12:00:00Z',
          job: {
            id: 'job-1',
            title: 'Staff Distributed Systems Engineer',
            employer_name: 'TechCorp Labs',
          },
        },
      ]),
      getProfile: vi.fn().mockResolvedValue({
        full_name: 'Jane Doe',
        headline: 'Principal Engineer',
        summary: 'Experienced architect',
        contact_email: 'jane@example.com',
        skills: ['Python', 'PostgreSQL'],
        languages: ['English'],
        experiences: [],
        educations: [],
        projects: [],
        certifications: [],
        completeness: { percentage: 85 },
      }),
      getFacts: vi.fn().mockResolvedValue([
        {
          fact_id: 'fact-1',
          fact_type: 'SKILL',
          value: { name: 'PostgreSQL' },
          verification_state: 'USER_VERIFIED',
        },
      ]),
      getAnswers: vi.fn().mockResolvedValue([
        {
          id: 'ans-1',
          category: 'technical',
          question: 'PostgreSQL replication experience?',
          answer: 'Streaming WAL replication.',
          reuse_consent: true,
          is_revoked: false,
        },
      ]),
      getSources: vi.fn().mockResolvedValue([
        {
          id: 'src-1',
          name: 'Manual Intake',
          source_type: 'MANUAL',
          status: 'ACTIVE',
          active_gate: null,
        },
      ]),
      getAiStatus: vi.fn().mockResolvedValue({
        provider_mode: 'OFFLINE_MOCK',
        anthropic_configured: false,
        openai_configured: false,
        paid_ai_enabled: false,
        budget_cap_usd: 5.0,
        committed_spend_usd: 0.0,
      }),
      getSettings: vi.fn().mockResolvedValue({
        application_cooldown_days: 30,
        daily_submission_cap: 5,
        same_company_cooldown_days: 30,
        daily_application_cap: 5,
      }),
      getActivity: vi.fn().mockResolvedValue([
        {
          event_type: 'JOB_INGESTED',
          entity_type: 'job_posting',
          entity_id: 'job-1',
          created_at: '2026-11-10T12:00:00Z',
        },
      ]),
      getSystemStatus: vi.fn().mockResolvedValue({
        status: 'healthy',
        database: { connected: true, version: 'PostgreSQL 17.11' },
        storage: { writable: true, path: '/tmp/evidence' },
        loopback_enforced: true,
        worker: { status: 'ACTIVE', active_tasks: 0 },
        scheduler: { status: 'RUNNING', timezone: 'Asia/Kolkata' },
        queue: { pending: 0, failed: 0 },
      }),
      getTasks: vi.fn().mockResolvedValue([]),
    },
  };
});

describe('Hire-Steward React Application', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders application navigation and brand header', async () => {
    render(<App />);

    expect(screen.getAllByText('Hire-Steward').length).toBeGreaterThan(0);
    expect(screen.getByText('Job Discovery Workbench')).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getAllByText('Opportunities').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Pipeline').length).toBeGreaterThan(0);
  });

  it('navigates across core screens on sidebar clicks', async () => {
    render(<App />);

    await waitFor(() => {
      expect(document.getElementById('nav-opportunities-btn')).toBeInTheDocument();
    });

    // Click Opportunities
    const oppBtn = document.getElementById('nav-opportunities-btn')!;
    fireEvent.click(oppBtn);

    await waitFor(() => {
      const workbench = document.getElementById('workbench-view');
      expect(workbench).toBeInTheDocument();
      expect(workbench?.parentElement?.style.display).toBe('flex');
    });

    // Click Pipeline
    const pipeBtn = document.getElementById('nav-pipeline-btn')!;
    fireEvent.click(pipeBtn);

    await waitFor(() => {
      const pipelineView = document.getElementById('pipeline-view');
      expect(pipelineView).toBeInTheDocument();
      expect(pipelineView?.parentElement?.style.display).toBe('block');
    });

    // Click Evidence Library
    const evidenceBtn = document.getElementById('nav-evidence-btn')!;
    fireEvent.click(evidenceBtn);

    await waitFor(() => {
      const evidenceView = document.getElementById('evidence-view');
      expect(evidenceView).toBeInTheDocument();
      expect(evidenceView?.parentElement?.style.display).toBe('block');
    });

    // Click System Health
    const systemBtn = document.getElementById('nav-system-btn')!;
    fireEvent.click(systemBtn);

    await waitFor(() => {
      const systemView = document.getElementById('system-view');
      expect(systemView).toBeInTheDocument();
      expect(systemView?.parentElement?.style.display).toBe('block');
    });
  });

  it('opens and closes the manual Add Job modal', async () => {
    render(<App />);

    const addBtn = screen.getByRole('button', { name: /\+ Add Job/i });
    fireEvent.click(addBtn);

    expect(screen.getByText('Manual Job Intake')).toBeInTheDocument();
    expect(document.getElementById('intake-title')).toBeInTheDocument();
    expect(document.getElementById('intake-employer')).toBeInTheDocument();

    const closeBtn = screen.getByLabelText('Close dialog');
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByText('Manual Job Intake')).not.toBeInTheDocument();
    });
  });
});
