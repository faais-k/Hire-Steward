import React, { useState } from 'react';
import type { JobPosting } from '../types';

interface AddJobModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (jobData: Partial<JobPosting>) => Promise<void>;
}

export const AddJobModal: React.FC<AddJobModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
}) => {
  const [title, setTitle] = useState('');
  const [employer, setEmployer] = useState('');
  const [location, setLocation] = useState('');
  const [workplace, setWorkplace] = useState<'remote' | 'hybrid' | 'on_site'>('remote');
  const [url, setUrl] = useState('');
  const [desc, setDesc] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title || !employer || !desc) return;
    setIsSubmitting(true);
    try {
      await onSubmit({
        title,
        employer_name: employer,
        location: location || null,
        workplace_type: workplace,
        url: url || null,
        description_text: desc,
      });
      // reset
      setTitle('');
      setEmployer('');
      setLocation('');
      setUrl('');
      setDesc('');
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      id="intake-modal-backdrop"
      className="modal-backdrop active"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal-content"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-intake-title"
      >
        <div className="modal-header">
          <h2 id="modal-intake-title" className="modal-title">Manual Job Intake</h2>
          <button
            type="button"
            className="modal-close"
            aria-label="Close dialog"
            onClick={onClose}
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label htmlFor="intake-title" className="form-label">Job Title *</label>
              <input
                id="intake-title"
                className="form-input"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Principal AI Platform Engineer"
              />
            </div>

            <div className="form-group">
              <label htmlFor="intake-employer" className="form-label">Employer Name *</label>
              <input
                id="intake-employer"
                className="form-input"
                required
                value={employer}
                onChange={(e) => setEmployer(e.target.value)}
                placeholder="e.g. Autonomous Core Labs"
              />
            </div>

            <div className="form-row" style={{ display: 'flex', gap: '12px' }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="intake-location" className="form-label">Location</label>
                <input
                  id="intake-location"
                  className="form-input"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g. Remote / San Francisco"
                />
              </div>

              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="intake-workplace" className="form-label">Workplace Type</label>
                <select
                  id="intake-workplace"
                  className="form-input"
                  value={workplace}
                  onChange={(e) => setWorkplace(e.target.value as 'remote' | 'hybrid' | 'on_site')}
                >
                  <option value="remote">Remote</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="on_site">On-Site</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="intake-url" className="form-label">Posting URL</label>
              <input
                id="intake-url"
                type="url"
                className="form-input"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://..."
              />
            </div>

            <div className="form-group">
              <label htmlFor="intake-desc" className="form-label">Job Description Text *</label>
              <textarea
                id="intake-desc"
                className="form-input form-textarea"
                rows={6}
                required
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                placeholder="Paste the full job requirements and role description..."
              />
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn-secondary"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              id="intake-submit-btn"
              className="btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Submitting...' : 'Save Job Posting'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
