import React, { useState } from 'react';
import { api } from '../api/client';
import type { ImportPreviewResponse } from '../types';

export const PortabilityView: React.FC = () => {
  const [exportedJson, setExportedJson] = useState<string>('');
  const [importJson, setImportJson] = useState<string>('');
  const [previewData, setPreviewData] = useState<ImportPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const data = await api.exportData();
      setExportedJson(JSON.stringify(data, null, 2));
    } catch {
      // ignore
    } finally {
      setIsExporting(false);
    }
  };

  const handlePreviewImport = async () => {
    if (!importJson) return;
    setIsPreviewing(true);
    setCommitResult(null);
    try {
      const parsed = JSON.parse(importJson);
      const res = await api.previewImport(parsed);
      setPreviewData(res);
    } catch {
      setPreviewData(null);
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleCommitImport = async () => {
    if (!importJson || !previewData?.preview_token) return;
    setIsCommitting(true);
    try {
      const parsed = JSON.parse(importJson);
      const res = await api.commitImport({
        bundle: parsed,
        preview_token: previewData.preview_token,
        overwrite_existing: true,
      });
      setCommitResult(`Import committed successfully. Status: ${res.status}`);
    } catch {
      setCommitResult('Import commit failed.');
    } finally {
      setIsCommitting(false);
    }
  };

  return (
    <main className="view-container" id="portability-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Data Export &amp; Backup</h2>
            <div className="state-desc">
              Generate a local, unencrypted JSON bundle with authenticated manifest checksum.
            </div>
          </div>
          <button
            type="button"
            className="btn-primary"
            onClick={handleExport}
            disabled={isExporting}
          >
            {isExporting ? 'Generating Export...' : 'Export Complete Backup'}
          </button>
        </div>

        {exportedJson && (
          <div style={{ marginTop: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '13px', fontWeight: 600 }}>Export Bundle JSON:</span>
              <button
                type="button"
                className="btn-secondary"
                style={{ fontSize: '12px', padding: '3px 8px' }}
                onClick={() => {
                  const blob = new Blob([exportedJson], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `hire-steward-backup-${new Date().toISOString().slice(0, 10)}.json`;
                  a.click();
                }}
              >
                Download File
              </button>
            </div>
            <textarea
              className="form-input form-textarea"
              rows={8}
              readOnly
              value={exportedJson}
              style={{ fontFamily: 'monospace', fontSize: '12px' }}
            />
          </div>
        )}
      </div>

      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <div>
            <h3 className="section-title">Import &amp; Restore (Dry-Run Preview Gate)</h3>
            <div className="state-desc">
              Safe restoration with collision detection. A dry-run preview must pass before any database writes.
            </div>
          </div>
        </div>

        <div style={{ marginTop: '14px' }}>
          <label className="form-label">Paste Export Bundle JSON to Restore:</label>
          <textarea
            className="form-input form-textarea"
            rows={6}
            value={importJson}
            onChange={(e) => setImportJson(e.target.value)}
            placeholder="Paste backup JSON bundle here..."
            style={{ fontFamily: 'monospace', fontSize: '12px' }}
          />

          <div style={{ marginTop: '12px', display: 'flex', gap: '10px' }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={handlePreviewImport}
              disabled={!importJson || isPreviewing}
            >
              {isPreviewing ? 'Evaluating Preview...' : '1. Dry-Run Import Preview'}
            </button>

            {previewData && (
              <button
                type="button"
                className="btn-primary"
                onClick={handleCommitImport}
                disabled={isCommitting}
              >
                {isCommitting ? 'Committing...' : '2. Commit Verified Restore'}
              </button>
            )}
          </div>

          {previewData && (
            <div style={{ marginTop: '16px', padding: '12px', background: '#f8fafc', border: '1px solid var(--jp-border)', borderRadius: '6px' }}>
              <div style={{ fontWeight: 600, color: 'var(--jp-info)' }}>
                ✓ Dry-Run Preview Token: <code>{previewData.preview_token}</code>
              </div>
              {previewData.collision_counts && (
                <div style={{ fontSize: '12px', marginTop: '6px' }}>
                  Collisions detected: {Object.keys(previewData.collision_counts).length} entities (will overwrite if confirmed).
                </div>
              )}
            </div>
          )}

          {commitResult && (
            <div className="alert alert-success" style={{ marginTop: '14px' }}>
              {commitResult}
            </div>
          )}
        </div>
      </div>
    </main>
  );
};
