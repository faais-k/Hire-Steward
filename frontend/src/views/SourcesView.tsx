import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { SourceRegistryItem } from '../types';

export const SourcesView: React.FC = () => {
  const [sources, setSources] = useState<SourceRegistryItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadSources = async () => {
    setLoading(true);
    try {
      const data = await api.getSources();
      setSources(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSources();
  }, []);

  return (
    <main className="view-container" id="sources-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Source Registry &amp; Connectors</h2>
            <div className="state-desc">
              Configured job discovery connectors and source provenance boundaries.
            </div>
          </div>
          <button type="button" className="btn-secondary" onClick={loadSources} disabled={loading}>
            {loading ? 'Refreshing...' : 'Refresh Sources'}
          </button>
        </div>

        <div style={{ marginTop: '16px' }}>
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--jp-border)', textAlign: 'left' }}>
                <th style={{ padding: '10px 14px' }}>Source Name</th>
                <th style={{ padding: '10px 14px' }}>Type</th>
                <th style={{ padding: '10px 14px' }}>Status</th>
                <th style={{ padding: '10px 14px' }}>Active Gate</th>
                <th style={{ padding: '10px 14px' }}>Rate Limit</th>
              </tr>
            </thead>
            <tbody>
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ padding: '24px', textAlign: 'center', color: 'var(--jp-text-muted)' }}>
                    No remote sources active (offline loopback mode).
                  </td>
                </tr>
              ) : (
                sources.map((s) => (
                  <tr key={s.id || s.name} style={{ borderBottom: '1px solid var(--jp-border)' }}>
                    <td style={{ padding: '12px 14px', fontWeight: 600 }}>{s.name}</td>
                    <td style={{ padding: '12px 14px', fontSize: '13px' }}>{s.source_type}</td>
                    <td style={{ padding: '12px 14px' }}>
                      <span className={`badge ${s.status === 'ACTIVE' ? 'badge-success' : 'badge-warning'}`}>
                        {s.status}
                      </span>
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: '13px' }}>
                      {s.active_gate ? <span className="badge badge-info">{s.active_gate}</span> : 'None'}
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: '13px', color: 'var(--jp-text-muted)' }}>
                      {s.rate_limit_per_minute ? `${s.rate_limit_per_minute} req/min` : 'Uncapped'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="alert alert-info" style={{ marginTop: '20px' }}>
          <strong>Source Isolation &amp; Safety:</strong> External scraping and live ATS submissions are permanently disabled in this local environment. All ingestion flows through manual entry or audited fixtures.
        </div>
      </div>
    </main>
  );
};
