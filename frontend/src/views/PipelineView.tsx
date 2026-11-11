import React, { useState } from 'react';
import type { TrackedApplication } from '../types';

interface PipelineViewProps {
  applications: TrackedApplication[];
  onTransitionStatus: (appId: string, targetStatus: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  onSelectJobForPrep?: (jobId: string) => void;
}

const STAGES = [
  'SAVED',
  'PREPARING',
  'READY_FOR_REVIEW',
  'APPLIED',
  'INTERVIEWING',
  'OFFER_RECEIVED',
  'REJECTED',
  'WITHDRAWN',
  'ARCHIVED',
];

const VALID_TRANSITIONS: Record<string, string[]> = {
  SAVED: ['PREPARING', 'READY_FOR_REVIEW', 'ARCHIVED'],
  PREPARING: ['READY_FOR_REVIEW', 'SAVED', 'ARCHIVED'],
  READY_FOR_REVIEW: ['PREPARING', 'APPLIED', 'SAVED', 'ARCHIVED'],
  APPLIED: ['INTERVIEWING', 'REJECTED', 'WITHDRAWN', 'ARCHIVED'],
  INTERVIEWING: ['OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED'],
  OFFER_RECEIVED: ['WITHDRAWN', 'ARCHIVED'],
  REJECTED: ['ARCHIVED'],
  WITHDRAWN: ['ARCHIVED'],
  ARCHIVED: ['SAVED'],
};

export const PipelineView: React.FC<PipelineViewProps> = ({
  applications,
  onTransitionStatus,
  onRefresh,
}) => {
  const [filterStage, setFilterStage] = useState<string>('');
  const [selectedApp, setSelectedApp] = useState<TrackedApplication | null>(null);
  const [transitioningId, setTransitioningId] = useState<string | null>(null);

  const filteredApps = applications.filter((app) => {
    if (filterStage && app.status !== filterStage) return false;
    return true;
  });

  const handleStatusChange = async (appId: string, newStatus: string) => {
    setTransitioningId(appId);
    try {
      await onTransitionStatus(appId, newStatus);
      await onRefresh();
    } finally {
      setTransitioningId(null);
    }
  };

  return (
    <main className="view-container" id="pipeline-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Application Pipeline</h2>
            <div className="state-desc">Track and control your application lifecycle with strict, auditable state transitions.</div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <select
              className="form-input"
              style={{ width: 'auto', padding: '6px 12px' }}
              value={filterStage}
              onChange={(e) => setFilterStage(e.target.value)}
              aria-label="Filter applications by stage"
            >
              <option value="">All Stages ({applications.length})</option>
              {STAGES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')} ({applications.filter((a) => a.status === s).length})
                </option>
              ))}
            </select>
            <button type="button" className="btn-secondary" onClick={onRefresh}>
              Refresh
            </button>
          </div>
        </div>

        {applications.length === 0 ? (
          <div className="state-box" style={{ margin: '40px 0' }}>
            <div className="state-title">No Applications Tracked Yet</div>
            <div className="state-desc">
              Visit the Opportunities tab and click "Track Opportunity" to add a job to your pipeline.
            </div>
          </div>
        ) : (
          <div className="pipeline-table-container">
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--jp-border)', textAlign: 'left' }}>
                  <th style={{ padding: '10px 14px' }}>Job &amp; Employer</th>
                  <th style={{ padding: '10px 14px' }}>Status</th>
                  <th style={{ padding: '10px 14px' }}>Last Updated</th>
                  <th style={{ padding: '10px 14px' }}>Available Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredApps.map((app) => {
                  const allowed = VALID_TRANSITIONS[app.status] || [];
                  const isTransitioning = transitioningId === app.id;

                  return (
                    <tr
                      key={app.id}
                      style={{ borderBottom: '1px solid var(--jp-border)', cursor: 'pointer' }}
                      onClick={() => setSelectedApp(app)}
                    >
                      <td style={{ padding: '12px 14px' }}>
                        <div style={{ fontWeight: 600 }}>{app.job?.title || `Job ${app.job_posting_id.slice(0, 8)}`}</div>
                        <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
                          {app.job?.employer_name || 'Direct Employer'}
                        </div>
                      </td>
                      <td style={{ padding: '12px 14px' }}>
                        <span className={`badge badge-status badge-${app.status.toLowerCase()}`}>
                          {app.status.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td style={{ padding: '12px 14px', fontSize: '13px', color: 'var(--jp-text-muted)' }}>
                        {new Date(app.updated_at).toLocaleDateString()}
                      </td>
                      <td style={{ padding: '12px 14px' }} onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {allowed.map((next) => (
                            <button
                              key={next}
                              type="button"
                              className="btn-secondary"
                              style={{ fontSize: '11px', padding: '4px 8px' }}
                              disabled={isTransitioning}
                              onClick={() => handleStatusChange(app.id, next)}
                            >
                              → {next.replace(/_/g, ' ')}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedApp && (
        <div className="section-card" style={{ marginTop: '20px' }}>
          <div className="section-header">
            <h3 className="section-title">Application Audit History: {selectedApp.job?.title || selectedApp.id}</h3>
            <button type="button" className="btn-secondary" onClick={() => setSelectedApp(null)}>
              Close
            </button>
          </div>
          <div style={{ padding: '10px 0' }}>
            {(!selectedApp.history || selectedApp.history.length === 0) ? (
              <div style={{ color: 'var(--jp-text-muted)', fontSize: '13px' }}>
                Initial status: {selectedApp.status} (Created at {new Date(selectedApp.created_at).toLocaleString()})
              </div>
            ) : (
              <ul style={{ listStyle: 'none', padding: 0 }}>
                {selectedApp.history.map((h, i) => (
                  <li key={i} style={{ padding: '8px 0', borderBottom: '1px solid var(--jp-border)', fontSize: '13px' }}>
                    <span style={{ fontWeight: 600 }}>{h.from_status} → {h.to_status}</span>
                    <span style={{ color: 'var(--jp-text-muted)', marginLeft: '12px' }}>
                      {new Date(h.created_at).toLocaleString()}
                    </span>
                    {h.note && <div style={{ color: 'var(--jp-text-muted)', marginTop: '2px' }}>Note: {h.note}</div>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </main>
  );
};
