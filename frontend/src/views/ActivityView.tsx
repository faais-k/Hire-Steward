import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { ActivityEvent } from '../types';

export const ActivityView: React.FC = () => {
  const [activities, setActivities] = useState<ActivityEvent[]>([]);
  const [filterType, setFilterType] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const loadActivities = async () => {
    setLoading(true);
    try {
      const data = await api.getActivity(50);
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

  const filtered = activities.filter((a) => {
    if (filterType && a.event_type !== filterType) return false;
    return true;
  });

  const eventTypes = Array.from(new Set(activities.map((a) => a.event_type)));

  return (
    <main className="view-container" id="activity-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Audit Activity Feed</h2>
            <div className="state-desc">
              Append-only immutable record of all state transitions, matching runs, ingestion operations, and policy checks.
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <select
              className="form-input"
              style={{ width: 'auto', padding: '6px 12px' }}
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              aria-label="Filter activity by event type"
            >
              <option value="">All Event Types ({activities.length})</option>
              {eventTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button type="button" className="btn-secondary" onClick={loadActivities} disabled={loading}>
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>

        <div style={{ marginTop: '16px' }}>
          {filtered.length === 0 ? (
            <div className="state-box" style={{ margin: '40px 0' }}>
              <div className="state-title">No Events Found</div>
              <div className="state-desc">Actions performed in the workbench will appear here in chronological order.</div>
            </div>
          ) : (
            <div className="activity-feed">
              {filtered.map((event, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '12px 14px',
                    borderBottom: '1px solid var(--jp-border)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <span className="badge badge-info" style={{ marginRight: '8px' }}>
                      {event.event_type}
                    </span>
                    <strong style={{ fontSize: '13px' }}>{event.entity_type}</strong>
                    {event.entity_id && (
                      <span style={{ fontSize: '12px', color: 'var(--jp-text-muted)', marginLeft: '6px' }}>
                        ID: {event.entity_id.slice(0, 8)}...
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
                    {new Date(event.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
};
