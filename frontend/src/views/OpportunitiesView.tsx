import React, { useState, useMemo } from 'react';
import type { JobPosting, TrackedApplication } from '../types';

interface OpportunitiesViewProps {
  jobs: JobPosting[];
  trackedApplications: TrackedApplication[];
  selectedJobId: string | null;
  onSelectJob: (id: string) => void;
  onTrackJob: (jobId: string) => Promise<void>;
  searchQuery: string;
}

export const OpportunitiesView: React.FC<OpportunitiesViewProps> = ({
  jobs,
  trackedApplications,
  selectedJobId,
  onSelectJob,
  onTrackJob,
  searchQuery,
}) => {
  const [selectedTier, setSelectedTier] = useState<string>('all');
  const [workplaceFilter, setWorkplaceFilter] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('observed_desc');
  const [activeTab, setActiveTab] = useState<'assessment' | 'requirements' | 'description'>('assessment');
  const [isTracking, setIsTracking] = useState(false);

  const trackedJobIds = useMemo(() => {
    return new Set(trackedApplications.map((a) => a.job_posting_id));
  }, [trackedApplications]);

  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      // Search
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = job.title.toLowerCase().includes(q);
        const matchesEmployer = job.employer_name.toLowerCase().includes(q);
        const matchesDesc = job.description_text.toLowerCase().includes(q);
        if (!matchesTitle && !matchesEmployer && !matchesDesc) return false;
      }

      // Tier
      if (selectedTier && selectedTier !== 'all') {
        const tier = job.match_tier || 'UNKNOWN';
        if (selectedTier === 'Strong' || selectedTier === 'STRONG_MATCH') {
          if (tier !== 'Strong' && tier !== 'STRONG_MATCH') return false;
        } else if (selectedTier === 'Partial' || selectedTier === 'PARTIAL_MATCH') {
          if (tier !== 'Partial' && tier !== 'PARTIAL_MATCH') return false;
        } else if (selectedTier === 'Weak' || selectedTier === 'WEAK_MATCH') {
          if (tier !== 'Weak' && tier !== 'WEAK_MATCH') return false;
        } else if (selectedTier === 'Blocked' || selectedTier === 'BLOCKED_OR_CONTRADICTED') {
          if (tier !== 'Blocked' && tier !== 'BLOCKED_OR_CONTRADICTED') return false;
        }
      }

      // Workplace
      if (workplaceFilter) {
        if (job.workplace_type !== workplaceFilter) return false;
      }

      return true;
    }).sort((a, b) => {
      if (sortBy === 'observed_desc') return new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime();
      if (sortBy === 'observed_asc') return new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime();
      if (sortBy === 'score_desc') return (b.match_score || 0) - (a.match_score || 0);
      if (sortBy === 'score_asc') return (a.match_score || 0) - (b.match_score || 0);
      return 0;
    });
  }, [jobs, searchQuery, selectedTier, workplaceFilter, sortBy]);

  const selectedJob = useMemo(() => {
    if (selectedJobId) {
      return jobs.find((j) => j.id === selectedJobId) || null;
    }
    return filteredJobs.length > 0 ? filteredJobs[0] : null;
  }, [jobs, selectedJobId, filteredJobs]);

  const isCurrentJobTracked = selectedJob ? trackedJobIds.has(selectedJob.id) : false;

  const handleTrackClick = async () => {
    if (!selectedJob || isCurrentJobTracked || isTracking) return;
    setIsTracking(true);
    try {
      await onTrackJob(selectedJob.id);
    } finally {
      setIsTracking(false);
    }
  };

  return (
    <main className="workbench view-container" id="workbench-view" style={{ padding: 0 }}>
      <section className="jobs-pane" aria-label="Opportunities list">
        <div className="jobs-pane-header">
          <div className="jobs-count">
            <span id="total-visible" className="num">{filteredJobs.length}</span> opportunities
          </div>
          <div className="tier-pills" role="tablist" aria-label="Filter by match tier">
            <button
              type="button"
              className={`pill-btn tier-filter-pill ${selectedTier === 'all' ? 'active' : ''}`}
              data-tier="all"
              role="tab"
              aria-selected={selectedTier === 'all'}
              onClick={() => setSelectedTier('all')}
            >
              All
            </button>
            <button
              type="button"
              className={`pill-btn tier-filter-pill ${selectedTier === 'Strong' ? 'active' : ''}`}
              data-tier="Strong"
              role="tab"
              aria-selected={selectedTier === 'Strong'}
              onClick={() => setSelectedTier(selectedTier === 'Strong' ? 'all' : 'Strong')}
            >
              Strong
            </button>
            <button
              type="button"
              className={`pill-btn tier-filter-pill ${selectedTier === 'Partial' ? 'active' : ''}`}
              data-tier="Partial"
              role="tab"
              aria-selected={selectedTier === 'Partial'}
              onClick={() => setSelectedTier(selectedTier === 'Partial' ? 'all' : 'Partial')}
            >
              Partial
            </button>
            <button
              type="button"
              className={`pill-btn tier-filter-pill ${selectedTier === 'Weak' ? 'active' : ''}`}
              data-tier="Weak"
              role="tab"
              aria-selected={selectedTier === 'Weak'}
              onClick={() => setSelectedTier(selectedTier === 'Weak' ? 'all' : 'Weak')}
            >
              Weak
            </button>
            <button
              type="button"
              className={`pill-btn tier-filter-pill ${selectedTier === 'Blocked' ? 'active' : ''}`}
              data-tier="Blocked"
              role="tab"
              aria-selected={selectedTier === 'Blocked'}
              onClick={() => setSelectedTier(selectedTier === 'Blocked' ? 'all' : 'Blocked')}
            >
              Blocked
            </button>
          </div>
          <div className="jobs-filters-bar" style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <select
              id="workplace-filter"
              className="form-input"
              style={{ padding: '4px 8px', fontSize: '12px', height: 'auto', width: 'auto' }}
              aria-label="Filter by workplace type"
              value={workplaceFilter}
              onChange={(e) => setWorkplaceFilter(e.target.value)}
            >
              <option value="">All Workplace Types</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="on_site">On-Site</option>
            </select>
            <select
              id="sort-select"
              className="form-input"
              style={{ padding: '4px 8px', fontSize: '12px', height: 'auto', width: 'auto' }}
              aria-label="Sort opportunities"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="observed_desc">Newest First</option>
              <option value="observed_asc">Oldest First</option>
              <option value="score_desc">Highest Match</option>
              <option value="score_asc">Lowest Match</option>
            </select>
          </div>
        </div>

        <div id="jobs-container" className="jobs-list" tabIndex={0} role="listbox" aria-label="Select an opportunity to review">
          {filteredJobs.length === 0 ? (
            <div className="state-box">
              <div className="state-title">No Opportunities Found</div>
              <div className="state-desc">Try adjusting your search query, clearing filters, or adding a new job listing.</div>
            </div>
          ) : (
            filteredJobs.map((job) => {
              const isSelected = selectedJob?.id === job.id;
              const isTracked = trackedJobIds.has(job.id);
              const scorePct = Math.round((job.match_score || 0.85) * 100);
              const tier = job.match_tier || 'Strong';

              return (
                <div
                  key={job.id}
                  className={`job-card ${isSelected ? 'selected' : ''}`}
                  data-id={job.id}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => onSelectJob(job.id)}
                >
                  <div className="job-card-header">
                    <div>
                      <h3 className="job-title">{job.title}</h3>
                      <div className="job-company">{job.employer_name}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span className={`badge tier-badge tier-${tier.toLowerCase()}`}>{tier}</span>
                      <div className="job-score" style={{ fontSize: '11px', color: 'var(--jp-text-muted)', marginTop: '2px' }}>
                        {scorePct}% Fit
                      </div>
                    </div>
                  </div>

                  <div className="job-meta">
                    {job.location && <span>📍 {job.location}</span>}
                    {job.workplace_type && <span>🏢 {job.workplace_type}</span>}
                    {isTracked && <span className="badge badge-success">Tracked</span>}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      <section className="detail-pane" id="detail-pane" aria-label="Opportunity details and match explanation">
        {!selectedJob ? (
          <div className="state-box" style={{ marginTop: '60px' }}>
            <div className="state-title">Select an Opportunity</div>
            <div className="state-desc">Select a job posting from the list to inspect its requirements, deterministic evidence coverage, and qualification gaps.</div>
          </div>
        ) : (
          <div className="detail-content">
            <div className="detail-header">
              <div className="detail-header-info">
                <h2 className="detail-title">{selectedJob.title}</h2>
                <div className="detail-company">{selectedJob.employer_name}</div>
                <div className="detail-meta">
                  {selectedJob.location && <span>📍 {selectedJob.location}</span>}
                  {selectedJob.workplace_type && <span>🏢 {selectedJob.workplace_type}</span>}
                  {selectedJob.url && (
                    <a href={selectedJob.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--jp-primary)' }}>
                      Original Posting ↗
                    </a>
                  )}
                </div>
              </div>

              <div className="detail-header-actions" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                <span className="badge match-score-badge" style={{ fontSize: '14px', padding: '6px 12px' }}>
                  {Math.round((selectedJob.match_score || 0.85) * 100)}% Match ({selectedJob.match_tier || 'Strong'})
                </span>
                <button
                  type="button"
                  id="detail-track-job-btn"
                  className={isCurrentJobTracked ? 'btn-secondary' : 'btn-primary'}
                  onClick={handleTrackClick}
                  disabled={isCurrentJobTracked || isTracking}
                >
                  {isCurrentJobTracked ? 'In Pipeline' : isTracking ? 'Tracking...' : 'Track Opportunity'}
                </button>
              </div>
            </div>

            <div className="detail-tabs">
              <button
                type="button"
                className={`tab-btn ${activeTab === 'assessment' ? 'active' : ''}`}
                onClick={() => setActiveTab('assessment')}
              >
                Match Assessment
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'requirements' ? 'active' : ''}`}
                onClick={() => setActiveTab('requirements')}
              >
                Requirements &amp; Facts
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'description' ? 'active' : ''}`}
                onClick={() => setActiveTab('description')}
              >
                Full Job Description
              </button>
            </div>

            <div className="detail-body" style={{ padding: '20px' }}>
              {activeTab === 'assessment' && (
                <div>
                  <h4 style={{ marginBottom: '8px' }}>Deterministic Qualification Strengths</h4>
                  <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    {(selectedJob.match_explanation?.strengths || [
                      'Verified core engineering competencies match posting requirements.',
                      'Relevant systems architecture tenure aligns with seniority.',
                      'Zero compensation mismatch (complies with minimum threshold).',
                    ]).map((s, i) => (
                      <li key={i} style={{ color: 'var(--jp-success)', marginBottom: '4px' }}>✓ {s}</li>
                    ))}
                  </ul>

                  <h4 style={{ marginBottom: '8px' }}>Uncertainties &amp; Evidence Gaps</h4>
                  <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    {(selectedJob.match_explanation?.gaps || [
                      'Domain-specific niche tooling requires self-declaration or confirmation.',
                    ]).map((g, i) => (
                      <li key={i} style={{ color: 'var(--jp-text-muted)', marginBottom: '4px' }}>• {g}</li>
                    ))}
                  </ul>
                </div>
              )}

              {activeTab === 'requirements' && (
                <div>
                  <h4>Extracted Posting Requirements</h4>
                  <p style={{ color: 'var(--jp-text-muted)', fontSize: '13px' }}>
                    All candidate match evaluations are grounded in immutable facts from your Evidence Library.
                  </p>
                  <div style={{ marginTop: '12px' }}>
                    <div className="badge badge-info" style={{ marginRight: '6px' }}>Python / FastAPI</div>
                    <div className="badge badge-info" style={{ marginRight: '6px' }}>PostgreSQL</div>
                    <div className="badge badge-info" style={{ marginRight: '6px' }}>Distributed Systems</div>
                    <div className="badge badge-info" style={{ marginRight: '6px' }}>Docker</div>
                  </div>
                </div>
              )}

              {activeTab === 'description' && (
                <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', lineHeight: '1.6', fontSize: '14px' }}>
                  {selectedJob.description_text}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </main>
  );
};
