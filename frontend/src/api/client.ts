import type {
  JobPosting,
  TrackedApplication,
  CandidateProfile,
  CandidateFact,
  ParsedDocumentResult,
  AnswerBankItem,
  SourceRegistryItem,
  AiStatus,
  SystemStatus,
  ActivityEvent,
  UserSettings,
  ImportPreviewResponse,
  BackgroundTask,
} from '../types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : endpoint;
  const headers = new Headers(options.headers || {});
  
  if (!headers.has('Content-Type') && !(options.body instanceof Uint8Array) && !(options.body instanceof Blob)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await window.fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorData: unknown;
    try {
      errorData = await response.json();
    } catch {
      errorData = await response.text();
    }
    const msg = typeof errorData === 'object' && errorData !== null && 'detail' in errorData
      ? String((errorData as { detail: unknown }).detail)
      : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, msg, errorData);
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export const api = {
  // Jobs
  async getJobs(params?: { search?: string; workplace?: string; tier?: string; sort?: string }): Promise<{ items: JobPosting[]; total: number }> {
    const q = new URLSearchParams();
    if (params?.search) q.append('search', params.search);
    if (params?.workplace) q.append('workplace', params.workplace);
    if (params?.tier) q.append('tier', params.tier);
    if (params?.sort) q.append('sort', params.sort);
    const qs = q.toString();
    return request<{ items: JobPosting[]; total: number }>(`/api/v1/jobs${qs ? `?${qs}` : ''}`);
  },

  async getJob(id: string): Promise<JobPosting> {
    return request<JobPosting>(`/api/v1/jobs/${encodeURIComponent(id)}`);
  },

  async createJob(job: Partial<JobPosting>): Promise<JobPosting> {
    return request<JobPosting>('/api/v1/jobs', {
      method: 'POST',
      body: JSON.stringify(job),
    });
  },

  async seedJobs(): Promise<{ seeded_count: number; message: string }> {
    return request<{ seeded_count: number; message: string }>('/api/v1/jobs/seed', {
      method: 'POST',
    });
  },

  // Applications
  async getApplications(): Promise<TrackedApplication[]> {
    return request<TrackedApplication[]>('/api/v1/applications');
  },

  async getApplication(id: string): Promise<TrackedApplication> {
    return request<TrackedApplication>(`/api/v1/applications/${encodeURIComponent(id)}`);
  },

  async createApplication(data: { job_posting_id: string; notes?: string }): Promise<TrackedApplication> {
    return request<TrackedApplication>('/api/v1/applications', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateApplicationStatus(id: string, target_status: string, note?: string): Promise<TrackedApplication> {
    return request<TrackedApplication>(`/api/v1/applications/${encodeURIComponent(id)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ target_status, note }),
    });
  },

  // Candidate Profile & Ingestion
  async getProfile(): Promise<CandidateProfile> {
    return request<CandidateProfile>('/api/v1/profile');
  },

  async updateProfile(profile: Partial<CandidateProfile>): Promise<CandidateProfile> {
    return request<CandidateProfile>('/api/v1/profile', {
      method: 'PUT',
      body: JSON.stringify(profile),
    });
  },

  async parseDocument(fileBytes: Uint8Array, filename: string): Promise<ParsedDocumentResult> {
    return request<ParsedDocumentResult>('/api/v1/profile/parse-document', {
      method: 'POST',
      headers: {
        'x-filename': filename,
        'Content-Type': 'application/octet-stream',
      },
      body: fileBytes as unknown as BodyInit,
    });
  },

  async mapFact(data: {
    document_version_id: string;
    section_heading: string;
    section_text: string;
    fact_type: string;
    byte_start: number;
    byte_end: number;
  }): Promise<{ fact_id: string; verification_state: string }> {
    return request<{ fact_id: string; verification_state: string }>('/api/v1/profile/map-fact', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getFacts(): Promise<CandidateFact[]> {
    return request<CandidateFact[]>('/api/v1/facts');
  },

  async createFact(data: { fact_type: string; value: Record<string, unknown> }): Promise<CandidateFact> {
    return request<CandidateFact>('/api/v1/facts', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async attachProvenance(factId: string, data: {
    document_version_id: string;
    byte_start: number;
    byte_end: number;
    excerpt: string;
  }): Promise<{ provenance_id: string }> {
    return request<{ provenance_id: string }>(`/api/v1/facts/${encodeURIComponent(factId)}/provenance`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async verifyFact(factId: string): Promise<{ fact_id: string; verification_state: string }> {
    return request<{ fact_id: string; verification_state: string }>(`/api/v1/facts/${encodeURIComponent(factId)}/verify`, {
      method: 'POST',
    });
  },

  async rejectFact(factId: string): Promise<{ fact_id: string; verification_state: string }> {
    return request<{ fact_id: string; verification_state: string }>(`/api/v1/facts/${encodeURIComponent(factId)}/reject`, {
      method: 'POST',
    });
  },

  // Preparation & Tailoring
  async generateTailoredDraft(jobPostingId: string): Promise<{
    tailored_resume: string;
    tailored_cover_letter: string;
    grounded_claims: Array<{ claim: string; fact_id?: string; source_excerpt?: string }>;
  }> {
    return request('/api/v1/preparation/tailor', {
      method: 'POST',
      body: JSON.stringify({ job_posting_id: jobPostingId }),
    });
  },

  async createSubmissionPlan(data: {
    job_posting_id: string;
    resume_text: string;
    cover_letter_text: string;
  }): Promise<{ plan_id: string; plan_hash: string; message: string; is_compensation_eligible?: boolean; is_cooldown_clear?: boolean }> {
    return request('/api/v1/preparation/plan', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async approveSubmissionPlan(planId: string): Promise<{
    plan_id: string;
    application_id?: string;
    review_state: string;
    approval_state: string;
    packet_hash: string;
    reviewed_at: string;
    message: string;
  }> {
    return request(`/api/v1/preparation/plan/${encodeURIComponent(planId)}/approve`, {
      method: 'POST',
    });
  },

  async simulateSubmission(data: {
    job_posting_id: string;
    plan_id?: string;
  }): Promise<{ simulation_id: string; receipt: string; dry_run: boolean; status: string }> {
    return request('/api/v1/preparation/simulate', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async generateRecruiterMessage(jobPostingId: string, tone?: string): Promise<{
    id: string;
    subject: string;
    body: string;
    word_count: number;
    tone: string;
    cited_facts: Array<{ claim_id: string; statement: string }>;
  }> {
    return request('/api/v1/preparation/recruiter-message', {
      method: 'POST',
      body: JSON.stringify({ job_posting_id: jobPostingId, tone: tone || 'Professional & Direct' }),
    });
  },

  async getReadiness(jobPostingId: string): Promise<{
    id: string;
    ready_for_submission: boolean;
    blocking_issues: string[];
    warnings: string[];
    checks: Array<{ name: string; passed: boolean; severity: string; details: string }>;
  }> {
    return request(`/api/v1/preparation/readiness/${encodeURIComponent(jobPostingId)}`);
  },

  // Answer Bank
  async getAnswers(): Promise<AnswerBankItem[]> {
    return request<AnswerBankItem[]>('/api/v1/answers');
  },

  async createAnswer(data: {
    category: string;
    question: string;
    answer: string;
    reuse_consent?: boolean;
  }): Promise<AnswerBankItem> {
    return request<AnswerBankItem>('/api/v1/answers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateAnswer(id: string, data: { reuse_consent?: boolean; answer?: string }): Promise<AnswerBankItem> {
    return request<AnswerBankItem>(`/api/v1/answers/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async revokeAnswer(id: string): Promise<AnswerBankItem> {
    return request<AnswerBankItem>(`/api/v1/answers/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },

  // Sources
  async getSources(): Promise<SourceRegistryItem[]> {
    return request<SourceRegistryItem[]>('/api/v1/sources');
  },

  // AI & Headroom
  async getAiStatus(): Promise<AiStatus> {
    return request<AiStatus>('/api/v1/ai/status');
  },

  async askAi(question: string): Promise<{ answer: string; citations?: string[] }> {
    return request<{ answer: string; citations?: string[] }>('/api/v1/ai/answer-question', {
      method: 'POST',
      body: JSON.stringify({ question }),
    });
  },

  // Settings
  async getSettings(): Promise<UserSettings> {
    return request<UserSettings>('/api/v1/settings');
  },

  async updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
    return request<UserSettings>('/api/v1/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  },

  // Portability
  async exportData(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>('/api/v1/data/export', {
      method: 'POST',
    });
  },

  async previewImport(bundle: Record<string, unknown>): Promise<ImportPreviewResponse> {
    return request<ImportPreviewResponse>('/api/v1/data/import/preview', {
      method: 'POST',
      body: JSON.stringify(bundle),
    });
  },

  async commitImport(data: {
    bundle: Record<string, unknown>;
    preview_token: string;
    overwrite_existing?: boolean;
  }): Promise<{ status: string; restored_counts?: Record<string, number> }> {
    return request('/api/v1/data/import/commit', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // System Diagnostics & Background Tasks
  async getActivity(limit = 20): Promise<ActivityEvent[]> {
    return request<ActivityEvent[]>(`/api/v1/system/activity?limit=${limit}`);
  },

  async getSystemStatus(): Promise<SystemStatus> {
    return request<SystemStatus>('/api/v1/system/status');
  },

  async pauseWorker(): Promise<{ status: string }> {
    return request<{ status: string }>('/api/v1/system/worker/pause', {
      method: 'POST',
    });
  },

  async resumeWorker(): Promise<{ status: string }> {
    return request<{ status: string }>('/api/v1/system/worker/resume', {
      method: 'POST',
    });
  },

  async getTasks(params?: { status?: string; limit?: number }): Promise<BackgroundTask[]> {
    const q = new URLSearchParams();
    if (params?.status) q.append('status', params.status);
    if (params?.limit) q.append('limit', String(params.limit));
    const qs = q.toString();
    return request<BackgroundTask[]>(`/api/v1/system/tasks${qs ? `?${qs}` : ''}`);
  },

  async retryTask(taskId: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/v1/system/tasks/${encodeURIComponent(taskId)}/retry`, {
      method: 'POST',
    });
  },

  async cancelTask(taskId: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/v1/system/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
    });
  },
};
