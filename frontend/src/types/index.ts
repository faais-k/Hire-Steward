export interface JobPosting {
  id: string;
  title: string;
  employer_name: string;
  location: string | null;
  workplace_type: 'remote' | 'hybrid' | 'on_site' | null;
  employment_type: string | null;
  description_text: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  url: string | null;
  observed_at: string;
  match_tier?: string;
  match_score?: number;
  match_explanation?: {
    strengths?: string[];
    gaps?: string[];
    raw_score?: number;
    tier?: string;
    missing_critical?: string[];
  };
}

export interface CandidateExperience {
  company: string;
  role: string;
  location?: string;
  start_date: string;
  end_date: string;
  description: string;
}

export interface CandidateEducation {
  institution: string;
  degree: string;
  field_of_study: string;
  start_year: string;
  end_year: string;
}

export interface CandidateProject {
  title: string;
  role: string;
  url?: string;
  description: string;
}

export interface CandidateCertification {
  name: string;
  issuer: string;
  issue_date: string;
}

export interface CandidateProfile {
  id?: string;
  name?: string;
  full_name?: string;
  headline?: string;
  summary?: string;
  contact_info?: {
    email?: string;
    phone?: string;
    location?: string;
    linkedin?: string;
    github?: string;
    portfolio?: string;
    languages?: string[];
  };
  contact_email?: string;
  email?: string;
  phone?: string;
  location?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
  skills?: string[] | Array<{ name: string; category?: string; proficiency_level?: string; years_experience?: number }>;
  languages?: string[];
  employment?: CandidateExperience[];
  experiences?: CandidateExperience[];
  education?: CandidateEducation[];
  educations?: CandidateEducation[];
  projects?: CandidateProject[];
  certifications?: CandidateCertification[];
  profile?: Record<string, unknown>;
  completeness?: {
    score?: number;
    percentage?: number;
    is_complete?: boolean;
    missing_elements?: string[];
    strengths?: string[];
    details?: Record<string, boolean>;
  };
}

export interface FactProvenance {
  provenance_id?: string;
  document_version_id: string;
  byte_start: number;
  byte_end: number;
  excerpt: string;
  created_at?: string;
}

export interface CandidateFact {
  fact_id: string;
  fact_type: string;
  value: Record<string, unknown>;
  verification_state: 'UNREVIEWED' | 'USER_VERIFIED' | 'REJECTED';
  confidence_score?: number;
  provenance?: FactProvenance[];
  created_at?: string;
}

export interface DocumentSection {
  heading: string;
  text: string;
  byte_start: number;
  byte_end: number;
}

export interface ParsedDocumentResult {
  document_id: string;
  document_version_id: string;
  filename: string;
  content_type: string;
  original_sha256: string;
  text_artifact_sha256?: string;
  sections_count?: number;
  sections?: DocumentSection[];
  text_content?: string;
}

export interface ApplicationHistory {
  from_status: string;
  to_status: string;
  created_at: string;
  note: string | null;
}

export interface TrackedApplication {
  id: string;
  job_posting_id: string;
  status: string;
  notes: string | null;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
  job?: JobPosting;
  history?: ApplicationHistory[];
}

export interface AnswerBankItem {
  id: string;
  category: string;
  question: string;
  answer: string;
  reuse_consent: boolean;
  is_revoked: boolean;
  created_at: string;
  updated_at: string;
}

export interface SourceRegistryItem {
  id: string;
  name: string;
  source_type: string;
  base_url?: string;
  status: string;
  active_gate: string | null;
  rate_limit_per_minute?: number;
}

export interface AiStatus {
  provider_mode: string;
  anthropic_configured: boolean;
  openai_configured: boolean;
  paid_ai_enabled: boolean;
  budget_cap_usd: number;
  committed_spend_usd: number;
}

export interface SystemStatus {
  status: string;
  database?: {
    connected: boolean;
    version?: string;
  };
  storage?: {
    writable: boolean;
    path: string;
  };
  loopback_enforced: boolean;
  worker?: {
    status: string;
    last_heartbeat?: string;
    active_tasks?: number;
  };
  scheduler?: {
    status: string;
    timezone?: string;
    next_run?: string;
  };
  queue?: {
    pending: number;
    failed: number;
  };
}

export interface ActivityEvent {
  event_type: string;
  entity_type: string;
  entity_id?: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface BackgroundTask {
  id: string;
  task_type: string;
  status: string;
  idempotency_key?: string;
  retry_count: number;
  max_retries: number;
  created_at: string;
  error_message?: string;
}

export interface UserSettings {
  application_cooldown_days: number;
  daily_submission_cap: number;
  same_company_cooldown_days?: number;
  daily_application_cap?: number;
  minimum_compensation?: {
    amount: string;
    currency?: string;
  };
}

export interface ImportPreviewResponse {
  preview_token: string;
  collision_counts?: Record<string, number>;
  incoming_counts?: Record<string, number>;
}
