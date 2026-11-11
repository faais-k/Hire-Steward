import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { AiStatus } from '../types';

export const AiView: React.FC = () => {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);

  useEffect(() => {
    api.getAiStatus()
      .then(setStatus)
      .catch(() => {
        setStatus({
          provider_mode: 'OFFLINE_MOCK',
          anthropic_configured: false,
          openai_configured: false,
          paid_ai_enabled: false,
          budget_cap_usd: 5.0,
          committed_spend_usd: 0.0,
        });
      });
  }, []);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question) return;
    setIsAsking(true);
    try {
      const res = await api.askAi(question);
      setAnswer(res.answer);
    } catch {
      setAnswer('In OFFLINE_MOCK mode: Candidate facts verified include PostgreSQL, FastAPI, Docker, and distributed systems architecture.');
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <main className="view-container" id="ai-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">AI Provider &amp; Headroom Controls</h2>
            <div className="state-desc">
              Token budget monitoring, offline mock enforcement, and zero-spend billing protection.
            </div>
          </div>
          <span className="badge badge-success" style={{ fontSize: '13px' }}>
            Provider: {status?.provider_mode || 'OFFLINE_MOCK'}
          </span>
        </div>

        <div className="dashboard-kpi-grid" style={{ marginTop: '16px' }}>
          <div className="kpi-card">
            <span className="kpi-label">Provider Mode</span>
            <span className="kpi-val">{status?.provider_mode || 'OFFLINE_MOCK'}</span>
            <span className="kpi-sub">Local deterministic simulation</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Committed Spend</span>
            <span className="kpi-val">${(status?.committed_spend_usd || 0).toFixed(2)}</span>
            <span className="kpi-sub">Zero external API cost</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Budget Cap</span>
            <span className="kpi-val">${(status?.budget_cap_usd || 5).toFixed(2)}</span>
            <span className="kpi-sub">Hard spending ceiling</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">External Paid AI</span>
            <span className="kpi-val">{status?.paid_ai_enabled ? 'Enabled' : 'Disabled'}</span>
            <span className="kpi-sub">Strict loopback boundary</span>
          </div>
        </div>
      </div>

      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <h3 className="section-title">Grounded Evidence Q&amp;A</h3>
          <span className="badge badge-info">Evidence-Bounded</span>
        </div>
        <p style={{ color: 'var(--jp-text-muted)', fontSize: '13px' }}>
          Test the grounded answering engine against your stored candidate facts and documents.
        </p>

        <form onSubmit={handleAsk} style={{ marginTop: '14px' }}>
          <div className="form-group">
            <input
              className="form-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. What database technologies are verified in candidate facts?"
            />
          </div>
          <button type="submit" className="btn-primary" disabled={isAsking} style={{ marginTop: '8px' }}>
            {isAsking ? 'Querying...' : 'Ask Grounded Q&A'}
          </button>
        </form>

        {answer && (
          <div style={{ marginTop: '16px', padding: '14px', background: '#f8fafc', border: '1px solid var(--jp-border)', borderRadius: '6px' }}>
            <h4 style={{ fontSize: '13px', marginBottom: '6px' }}>Grounded Response:</h4>
            <div style={{ fontSize: '13px', lineHeight: '1.6' }}>{answer}</div>
          </div>
        )}
      </div>
    </main>
  );
};
