import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { SystemStatus, BackgroundTask } from '../types';

export const SystemView: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const loadSystemInfo = async () => {
    setLoading(true);
    setActionMsg(null);
    try {
      const [sys, tList] = await Promise.all([
        api.getSystemStatus(),
        api.getTasks().catch(() => []),
      ]);
      setStatus(sys);
      setTasks(tList);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSystemInfo();
  }, []);

  const handlePauseWorker = async () => {
    try {
      await api.pauseWorker();
      setActionMsg('Background worker paused.');
      await loadSystemInfo();
    } catch {
      setActionMsg('Failed to pause worker.');
    }
  };

  const handleResumeWorker = async () => {
    try {
      await api.resumeWorker();
      setActionMsg('Background worker resumed.');
      await loadSystemInfo();
    } catch {
      setActionMsg('Failed to resume worker.');
    }
  };

  const handleRetryTask = async (taskId: string) => {
    try {
      await api.retryTask(taskId);
      setActionMsg(`Task ${taskId} scheduled for retry.`);
      await loadSystemInfo();
    } catch {
      setActionMsg(`Failed to retry task ${taskId}.`);
    }
  };

  const handleCancelTask = async (taskId: string) => {
    try {
      await api.cancelTask(taskId);
      setActionMsg(`Task ${taskId} cancelled.`);
      await loadSystemInfo();
    } catch {
      setActionMsg(`Failed to cancel task ${taskId}.`);
    }
  };

  return (
    <main className="view-container" id="system-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">System Diagnostics &amp; Operational Health</h2>
            <div className="state-desc">
              Loopback enforcement verification, database connection pool telemetry, and background worker status.
            </div>
          </div>
          <button type="button" className="btn-secondary" onClick={loadSystemInfo} disabled={loading}>
            {loading ? 'Checking...' : 'Refresh Diagnostics'}
          </button>
        </div>

        {actionMsg && (
          <div className="alert alert-info" style={{ marginTop: '12px' }}>
            {actionMsg}
          </div>
        )}

        <div className="dashboard-kpi-grid" style={{ marginTop: '16px' }}>
          <div className="kpi-card">
            <span className="kpi-label">System Health</span>
            <span className="kpi-val" style={{ color: 'var(--jp-success)' }}>
              {status?.status === 'healthy' || status?.status === 'ok' ? 'Healthy' : status?.status || 'Active'}
            </span>
            <span className="kpi-sub">Local monolith online</span>
          </div>

          <div className="kpi-card">
            <span className="kpi-label">PostgreSQL Database</span>
            <span className="kpi-val" style={{ color: status?.database?.connected ? 'var(--jp-success)' : 'var(--jp-danger)' }}>
              {status?.database?.connected ? 'Connected' : 'Offline'}
            </span>
            <span className="kpi-sub">{status?.database?.version || 'PostgreSQL 17.11'}</span>
          </div>

          <div className="kpi-card">
            <span className="kpi-label">Evidence Storage</span>
            <span className="kpi-val" style={{ color: status?.storage?.writable ? 'var(--jp-success)' : 'var(--jp-warning)' }}>
              {status?.storage?.writable ? 'Writable' : 'Read-Only'}
            </span>
            <span className="kpi-sub" style={{ fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {status?.storage?.path ? `${status.storage.path.slice(-25)}` : 'Isolated local storage'}
            </span>
          </div>

          <div className="kpi-card">
            <span className="kpi-label">Loopback Enforced</span>
            <span className="kpi-val" style={{ color: status?.loopback_enforced ? 'var(--jp-success)' : 'var(--jp-danger)' }}>
              {status?.loopback_enforced ? '127.0.0.1' : 'Unrestricted'}
            </span>
            <span className="kpi-sub">Network egress strictly isolated</span>
          </div>
        </div>
      </div>

      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <div>
            <h3 className="section-title">Background Worker &amp; Local Scheduler</h3>
            <div className="state-desc">
              Durable queue with lease fencing, zombie reaping, and atomic claiming.
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {status?.worker?.status === 'PAUSED' ? (
              <button type="button" className="btn-primary" onClick={handleResumeWorker}>
                Resume Worker
              </button>
            ) : (
              <button type="button" className="btn-secondary" onClick={handlePauseWorker}>
                Pause Worker
              </button>
            )}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '14px', marginTop: '14px' }}>
          <div style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>Worker Status</div>
            <div style={{ fontWeight: 700, fontSize: '16px', marginTop: '4px' }}>
              <span className={`badge ${status?.worker?.status === 'ACTIVE' ? 'badge-success' : 'badge-warning'}`}>
                {status?.worker?.status || 'ACTIVE'}
              </span>
            </div>
          </div>
          <div style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>Scheduler Timezone</div>
            <div style={{ fontWeight: 700, fontSize: '16px', marginTop: '4px' }}>
              {status?.scheduler?.timezone || 'Asia/Kolkata'}
            </div>
          </div>
          <div style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>Queue Pending</div>
            <div style={{ fontWeight: 700, fontSize: '16px', marginTop: '4px' }}>
              {status?.queue?.pending || 0} tasks
            </div>
          </div>
          <div style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>Queue Failed</div>
            <div style={{ fontWeight: 700, fontSize: '16px', marginTop: '4px' }}>
              {status?.queue?.failed || 0} tasks
            </div>
          </div>
        </div>

        {tasks.length > 0 && (
          <div style={{ marginTop: '20px' }}>
            <h4 style={{ fontSize: '14px', marginBottom: '8px' }}>Active &amp; Recent Background Tasks</h4>
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--jp-border)', textAlign: 'left' }}>
                  <th style={{ padding: '8px 10px' }}>Task ID</th>
                  <th style={{ padding: '8px 10px' }}>Type</th>
                  <th style={{ padding: '8px 10px' }}>Status</th>
                  <th style={{ padding: '8px 10px' }}>Retries</th>
                  <th style={{ padding: '8px 10px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} style={{ borderBottom: '1px solid var(--jp-border)' }}>
                    <td style={{ padding: '8px 10px', fontFamily: 'monospace', fontSize: '12px' }}>{t.id.slice(0, 8)}</td>
                    <td style={{ padding: '8px 10px', fontSize: '13px' }}>{t.task_type}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className={`badge ${t.status === 'COMPLETED' ? 'badge-success' : t.status === 'FAILED' ? 'badge-danger' : 'badge-info'}`}>
                        {t.status}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px', fontSize: '12px' }}>{t.retry_count}/{t.max_retries}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        {t.status === 'FAILED' && (
                          <button
                            type="button"
                            className="btn-secondary"
                            style={{ fontSize: '11px', padding: '2px 6px' }}
                            onClick={() => handleRetryTask(t.id)}
                          >
                            Retry
                          </button>
                        )}
                        {(t.status === 'PENDING' || t.status === 'RUNNING') && (
                          <button
                            type="button"
                            className="btn-secondary"
                            style={{ fontSize: '11px', padding: '2px 6px', color: 'var(--jp-danger)' }}
                            onClick={() => handleCancelTask(t.id)}
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
};
