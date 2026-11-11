import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ActivityEvent } from '../types';

interface OverviewViewProps {
  onNavigate: (view: string) => void;
  opportunitiesCount: number;
  pipelineCount: number;
  factsCount: number;
  profileScore: number;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  onNavigate,
  opportunitiesCount,
  pipelineCount,
  factsCount,
  profileScore,
}) => {
  const [activities, setActivities] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(false);

  const loadActivities = async () => {
    setLoading(true);
    try {
      const data = await api.getActivity(10);
      setActivities(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadActivities();
  }, []);

  return (
    <main className="view-container" id="overview-view">
      <div className="dashboard-kpi-grid">
        <div className="kpi-card">
          <span className="kpi-label">Opportunities</span>
          <span className="kpi-val" id="dash-opportunities-count">{opportunitiesCount}</span>
          <span className="kpi-sub">Persisted job postings</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Active Pipeline</span>
          <span className="kpi-val" id="dash-pipeline-count">{pipelineCount}</span>
          <span className="kpi-sub">Applications tracked</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Candidate Facts</span>
          <span className="kpi-val" id="dash-facts-count">{factsCount}</span>
          <span className="kpi-sub">Verified credentials</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Profile Health</span>
          <span className="kpi-val" id="dash-profile-pct">{profileScore}%</span>
          <span className="kpi-sub" id="dash-profile-health-label">
            {profileScore >= 80 ? 'Verified & Ready' : profileScore > 0 ? 'In Progress' : 'Incomplete'}
          </span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">AI Budget Left</span>
          <span className="kpi-val" id="dash-ai-budget">$5.00</span>
          <span className="kpi-sub">Cap: $5.00 (Offline Mock)</span>
        </div>
      </div>

      <div className="section-card">
        <div className="section-header">
          <h2 className="section-title">Quick Actions &amp; Workflows</h2>
        </div>
        <div className="quick-actions-grid">
          <button
            type="button"
            className="action-card"
            id="qa-upload-resume"
            onClick={() => onNavigate('evidence')}
          >
            <div className="action-icon">📄</div>
            <div className="action-title">Upload Resume &amp; Documents</div>
            <div className="action-desc">Parse PDF, DOCX, Markdown, CSV, XLSX to extract candidate facts &amp; build profile.</div>
          </button>
          <button
            type="button"
            className="action-card"
            id="qa-explore-jobs"
            onClick={() => onNavigate('opportunities')}
          >
            <div className="action-icon">🔍</div>
            <div className="action-title">Review Opportunities</div>
            <div className="action-desc">Inspect match tiers, qualification gaps, and compensation requirements.</div>
          </button>
          <button
            type="button"
            className="action-card"
            id="qa-view-pipeline"
            onClick={() => onNavigate('pipeline')}
          >
            <div className="action-icon">📊</div>
            <div className="action-title">Manage Pipeline</div>
            <div className="action-desc">Move applications through stages with dry-run simulations.</div>
          </button>
          <button
            type="button"
            className="action-card"
            id="qa-backup-data"
            onClick={() => onNavigate('portability')}
          >
            <div className="action-icon">💾</div>
            <div className="action-title">Export Safe Backup</div>
            <div className="action-desc">Download complete local JSON bundle with manifest checksum.</div>
          </button>
        </div>
      </div>

      <div className="section-card">
        <div className="section-header">
          <h2 className="section-title">Recent Activity Timeline</h2>
          <button
            type="button"
            className="btn-secondary"
            id="dash-refresh-activity"
            onClick={loadActivities}
            disabled={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        <div id="overview-activity-feed" className="activity-feed">
          {activities.length === 0 ? (
            <div className="state-desc">No recent activity events recorded yet.</div>
          ) : (
            activities.map((a, i) => (
              <div key={i} className="activity-item">
                <span className="activity-badge">{a.event_type}</span>
                <span className="activity-entity">{a.entity_type} {a.entity_id ? `(${a.entity_id.slice(0, 8)})` : ''}</span>
                <span className="activity-time">{new Date(a.created_at).toLocaleTimeString()}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  );
};
