import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { UserSettings } from '../types';

export const SettingsView: React.FC = () => {
  const [cooldownDays, setCooldownDays] = useState<number>(30);
  const [dailyCap, setDailyCap] = useState<number>(5);
  const [minCompAmount, setMinCompAmount] = useState<string>('300000.00');
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings()
      .then((s: UserSettings) => {
        if (s) {
          setCooldownDays(s.application_cooldown_days || s.same_company_cooldown_days || 30);
          setDailyCap(s.daily_submission_cap || s.daily_application_cap || 5);
          if (s.minimum_compensation?.amount) {
            setMinCompAmount(s.minimum_compensation.amount);
          }
        }
      })
      .catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setFeedback(null);
    try {
      await api.updateSettings({
        application_cooldown_days: cooldownDays,
        daily_submission_cap: dailyCap,
        same_company_cooldown_days: cooldownDays,
        daily_application_cap: dailyCap,
        minimum_compensation: { amount: minCompAmount, currency: 'INR' },
      });
      setFeedback('Settings successfully saved.');
    } catch {
      setFeedback('Settings update failed.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <main className="view-container" id="settings-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Application Policies &amp; Thresholds</h2>
            <div className="state-desc">
              Deterministic safeguards to prevent application spam, duplicate submissions, and underpaid positions.
            </div>
          </div>
        </div>

        {feedback && (
          <div className="alert alert-info" style={{ marginTop: '12px' }}>
            {feedback}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ marginTop: '16px', maxWidth: '600px' }}>
          <div className="form-group">
            <label htmlFor="settings-cooldown" className="form-label">
              Employer Application Cooldown (Days)
            </label>
            <input
              id="settings-cooldown"
              type="number"
              className="form-input"
              value={cooldownDays}
              onChange={(e) => setCooldownDays(Number(e.target.value))}
              min={1}
              max={365}
            />
            <span style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
              Prevents submitting multiple applications to the exact same employer within this window.
            </span>
          </div>

          <div className="form-group" style={{ marginTop: '14px' }}>
            <label htmlFor="settings-daily-cap" className="form-label">
              Daily Submission Cap
            </label>
            <input
              id="settings-daily-cap"
              type="number"
              className="form-input"
              value={dailyCap}
              onChange={(e) => setDailyCap(Number(e.target.value))}
              min={1}
              max={100}
            />
            <span style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
              Maximum tailored application plans permitted per 24-hour cycle.
            </span>
          </div>

          <div className="form-group" style={{ marginTop: '14px' }}>
            <label htmlFor="settings-min-comp" className="form-label">
              Minimum Compensation Floor (INR)
            </label>
            <input
              id="settings-min-comp"
              className="form-input"
              value={minCompAmount}
              onChange={(e) => setMinCompAmount(e.target.value)}
              placeholder="e.g. 400000.00"
            />
            <span style={{ fontSize: '12px', color: 'var(--jp-text-muted)' }}>
              Deterministic filter: jobs below this verified compensation threshold are automatically disqualified.
            </span>
          </div>

          <div style={{ marginTop: '20px' }}>
            <button type="submit" className="btn-primary" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
};
