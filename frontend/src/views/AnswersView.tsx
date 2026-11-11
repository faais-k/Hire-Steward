import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { AnswerBankItem } from '../types';

interface AnswersViewProps {
  onAnswersUpdated: (count: number) => void;
}

export const AnswersView: React.FC<AnswersViewProps> = ({ onAnswersUpdated }) => {
  const [answers, setAnswers] = useState<AnswerBankItem[]>([]);
  const [newQuestion, setNewQuestion] = useState('');
  const [newAnswer, setNewAnswer] = useState('');
  const [newCategory, setNewCategory] = useState('technical');
  const [reuseConsent, setReuseConsent] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadAnswers = async () => {
    try {
      const data = await api.getAnswers();
      setAnswers(data);
      onAnswersUpdated(data.length);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadAnswers();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newQuestion || !newAnswer) return;
    setIsCreating(true);
    setActionError(null);
    try {
      await api.createAnswer({
        category: newCategory,
        question: newQuestion,
        answer: newAnswer,
        reuse_consent: reuseConsent,
      });
      setNewQuestion('');
      setNewAnswer('');
      setReuseConsent(false);
      await loadAnswers();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to create answer');
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleConsent = async (id: string, currentConsent: boolean) => {
    setActionError(null);
    try {
      await api.updateAnswer(id, { reuse_consent: !currentConsent });
      await loadAnswers();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Cannot re-grant consent on a revoked answer.');
    }
  };

  const handleRevoke = async (id: string) => {
    setActionError(null);
    try {
      await api.revokeAnswer(id);
      await loadAnswers();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Revocation failed');
    }
  };

  return (
    <main className="view-container" id="answers-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Answer Bank &amp; Reusable Responses</h2>
            <div className="state-desc">
              Candidate answers to recurring screening questions with strict explicit consent tracking and permanent revocation.
            </div>
          </div>
        </div>

        {actionError && (
          <div className="alert alert-danger" style={{ marginTop: '12px' }}>
            {actionError}
          </div>
        )}

        <form onSubmit={handleCreate} style={{ marginTop: '16px' }}>
          <div className="form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 3fr', gap: '12px' }}>
            <div className="form-group">
              <label htmlFor="answer-category" className="form-label">Category</label>
              <select
                id="answer-category"
                className="form-input"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
              >
                <option value="technical">Technical</option>
                <option value="behavioral">Behavioral</option>
                <option value="logistics">Logistics &amp; Availability</option>
                <option value="compensation">Compensation Expectations</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="answer-question" className="form-label">Screening Question *</label>
              <input
                id="answer-question"
                className="form-input"
                required
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="e.g. How do you guarantee zero-data-loss in PostgreSQL schema migrations?"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="answer-text" className="form-label">Candidate Answer *</label>
            <textarea
              id="answer-text"
              className="form-input form-textarea"
              rows={3}
              required
              value={newAnswer}
              onChange={(e) => setNewAnswer(e.target.value)}
              placeholder="Your approved, factual answer..."
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '12px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px' }}>
              <input
                type="checkbox"
                checked={reuseConsent}
                onChange={(e) => setReuseConsent(e.target.checked)}
              />
              <span>Grant Explicit Reuse Consent for Autonomous Preparation</span>
            </label>

            <button type="submit" className="btn-primary" disabled={isCreating}>
              {isCreating ? 'Saving...' : '+ Add Question &amp; Answer'}
            </button>
          </div>
        </form>
      </div>

      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <h3 className="section-title">Stored Answers ({answers.length})</h3>
          <button type="button" className="btn-secondary" onClick={loadAnswers}>
            Refresh
          </button>
        </div>

        {answers.length === 0 ? (
          <div className="state-box" style={{ margin: '40px 0' }}>
            <div className="state-title">Answer Bank is Empty</div>
            <div className="state-desc">Add responses to common interview and application questions to speed up preparation.</div>
          </div>
        ) : (
          <div className="answers-list" style={{ marginTop: '12px' }}>
            {answers.map((item) => (
              <div
                key={item.id}
                style={{
                  border: '1px solid var(--jp-border)',
                  borderRadius: '6px',
                  padding: '16px',
                  marginBottom: '12px',
                  background: item.is_revoked ? '#fff5f5' : '#ffffff',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <span className="badge badge-info" style={{ marginRight: '8px', textTransform: 'capitalize' }}>
                      {item.category}
                    </span>
                    <strong style={{ fontSize: '14px' }}>{item.question}</strong>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    {item.is_revoked ? (
                      <span className="badge badge-danger">Consent Permanently Revoked</span>
                    ) : item.reuse_consent ? (
                      <span className="badge badge-success">Reuse Consent Granted</span>
                    ) : (
                      <span className="badge badge-warning">No Reuse Consent</span>
                    )}

                    {!item.is_revoked && (
                      <>
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ fontSize: '11px', padding: '4px 8px' }}
                          onClick={() => handleToggleConsent(item.id, item.reuse_consent)}
                        >
                          {item.reuse_consent ? 'Revoke Consent' : 'Grant Consent'}
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ fontSize: '11px', padding: '4px 8px', color: 'var(--jp-danger)' }}
                          onClick={() => handleRevoke(item.id)}
                          title="Permanently revoke consent (cannot be undone)"
                        >
                          Permanently Revoke
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div style={{ marginTop: '10px', fontSize: '13px', lineHeight: '1.5', color: 'var(--jp-text)' }}>
                  {item.answer}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
};
