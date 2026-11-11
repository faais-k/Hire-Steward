import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { CandidateFact, ParsedDocumentResult } from '../types';

interface EvidenceViewProps {
  onFactsUpdated: (count: number) => void;
}

export const EvidenceView: React.FC<EvidenceViewProps> = ({ onFactsUpdated }) => {
  const [facts, setFacts] = useState<CandidateFact[]>([]);
  const [lastUploadedDoc, setLastUploadedDoc] = useState<ParsedDocumentResult | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const loadFacts = async () => {
    try {
      const data = await api.getFacts();
      setFacts(data);
      onFactsUpdated(data.length);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadFacts();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);
    try {
      const buffer = await file.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      const res = await api.parseDocument(bytes, file.name);
      setLastUploadedDoc(res);
      await loadFacts();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  const handleVerify = async (factId: string) => {
    try {
      await api.verifyFact(factId);
      await loadFacts();
    } catch {
      // ignore
    }
  };

  const handleReject = async (factId: string) => {
    try {
      await api.rejectFact(factId);
      await loadFacts();
    } catch {
      // ignore
    }
  };

  return (
    <main className="view-container" id="evidence-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Evidence Library &amp; Document Ingestion</h2>
            <div className="state-desc">
              All claims, skills, and qualifications must be grounded in immutable source documents (PDF, DOCX, MD, TXT, CSV, XLSX).
            </div>
          </div>
          <div>
            <label className="btn-primary" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <input
                type="file"
                style={{ display: 'none' }}
                accept=".pdf,.docx,.txt,.md,.csv,.xlsx"
                onChange={handleFileUpload}
                disabled={isUploading}
              />
              {isUploading ? 'Parsing Document...' : 'Upload Evidence Document'}
            </label>
          </div>
        </div>

        {uploadError && (
          <div className="alert alert-danger" style={{ marginTop: '12px' }}>
            {uploadError}
          </div>
        )}

        {lastUploadedDoc && (
          <div style={{ marginTop: '16px', padding: '12px', background: '#f8fafc', border: '1px solid var(--jp-border)', borderRadius: '6px' }}>
            <div style={{ fontWeight: 600, color: 'var(--jp-success)' }}>
              ✓ Document Successfully Ingested: {lastUploadedDoc.filename}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--jp-text-muted)', marginTop: '4px' }}>
              SHA-256: <code>{lastUploadedDoc.original_sha256}</code> | Version: <code>{lastUploadedDoc.document_version_id}</code>
            </div>
            {lastUploadedDoc.sections && lastUploadedDoc.sections.length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600 }}>Extracted Sections ({lastUploadedDoc.sections.length}): </span>
                {lastUploadedDoc.sections.map((s, i) => (
                  <span key={i} className="badge badge-info" style={{ marginRight: '4px', fontSize: '11px' }}>
                    {s.heading}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="section-card" style={{ marginTop: '20px' }}>
        <div className="section-header">
          <h3 className="section-title">Verified &amp; Pending Candidate Facts ({facts.length})</h3>
          <button type="button" className="btn-secondary" onClick={loadFacts}>
            Refresh
          </button>
        </div>

        {facts.length === 0 ? (
          <div className="state-box" style={{ margin: '40px 0' }}>
            <div className="state-title">No Candidate Facts Recorded</div>
            <div className="state-desc">Upload a resume or transcript to automatically parse and extract verifiable facts.</div>
          </div>
        ) : (
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--jp-border)', textAlign: 'left' }}>
                <th style={{ padding: '10px 12px' }}>Type</th>
                <th style={{ padding: '10px 12px' }}>Extracted Fact Content</th>
                <th style={{ padding: '10px 12px' }}>Status</th>
                <th style={{ padding: '10px 12px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {facts.map((f) => (
                <tr key={f.fact_id} style={{ borderBottom: '1px solid var(--jp-border)' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, fontSize: '13px' }}>
                    {f.fact_type}
                  </td>
                  <td style={{ padding: '10px 12px', fontSize: '13px' }}>
                    <div>{JSON.stringify(f.value)}</div>
                    {f.provenance && f.provenance.length > 0 && (
                      <div style={{ fontSize: '11px', color: 'var(--jp-text-muted)', marginTop: '2px' }}>
                        Excerpt: "{f.provenance[0].excerpt}" (bytes {f.provenance[0].byte_start}–{f.provenance[0].byte_end})
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <span className={`badge ${f.verification_state === 'USER_VERIFIED' ? 'badge-success' : f.verification_state === 'REJECTED' ? 'badge-danger' : 'badge-warning'}`}>
                      {f.verification_state}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      {f.verification_state !== 'USER_VERIFIED' && (
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ fontSize: '11px', padding: '3px 8px' }}
                          onClick={() => handleVerify(f.fact_id)}
                        >
                          Verify
                        </button>
                      )}
                      {f.verification_state !== 'REJECTED' && (
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ fontSize: '11px', padding: '3px 8px', color: 'var(--jp-danger)' }}
                          onClick={() => handleReject(f.fact_id)}
                        >
                          Reject
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
};
