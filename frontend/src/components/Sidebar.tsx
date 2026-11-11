import React from 'react';

interface SidebarProps {
  currentView: string;
  onSelectView: (view: string) => void;
  isOpen: boolean;
  onClose: () => void;
  opportunitiesCount: number;
  pipelineCount: number;
  evidenceCount: number;
  profileScore: number;
  answersCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onSelectView,
  isOpen,
  onClose,
  opportunitiesCount,
  pipelineCount,
  evidenceCount,
  profileScore,
  answersCount,
}) => {
  const handleNavClick = (view: string) => {
    onSelectView(view);
    onClose();
  };

  return (
    <>
      <aside
        className={`sidebar ${isOpen ? 'sidebar-open open' : ''}`}
        id="app-sidebar"
        aria-label="Application navigation"
      >
        <div className="brand">
          <div className="brand-icon" aria-hidden="true">H</div>
          <div className="brand-name">Hire-Steward</div>
          <span className="scope-badge">Local</span>
        </div>

        <nav className="sidebar-nav">
          <div className="sidebar-section-title">Core Workflow</div>
          <button
            type="button"
            className={`nav-item ${currentView === 'overview' ? 'active' : ''}`}
            id="nav-overview-btn"
            data-view="overview"
            aria-current={currentView === 'overview' ? 'page' : undefined}
            onClick={() => handleNavClick('overview')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <rect x="2" y="2" width="5" height="5" rx="1" strokeWidth="1.5" />
              <rect x="9" y="2" width="5" height="5" rx="1" strokeWidth="1.5" />
              <rect x="2" y="9" width="5" height="5" rx="1" strokeWidth="1.5" />
              <rect x="9" y="9" width="5" height="5" rx="1" strokeWidth="1.5" />
            </svg>
            <span>Overview</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'opportunities' ? 'active' : ''}`}
            id="nav-opportunities-btn"
            data-view="opportunities"
            aria-current={currentView === 'opportunities' ? 'page' : undefined}
            onClick={() => handleNavClick('opportunities')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <rect x="2" y="3" width="12" height="10" rx="1.5" strokeWidth="1.5" />
              <path d="M5 6h6M5 9h4" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>Opportunities</span>
            <span className="nav-count num" id="sidebar-count">{opportunitiesCount}</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'pipeline' ? 'active' : ''}`}
            id="nav-pipeline-btn"
            data-view="pipeline"
            aria-current={currentView === 'pipeline' ? 'page' : undefined}
            onClick={() => handleNavClick('pipeline')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M2 4h12M2 8h12M2 12h12" strokeWidth="1.5" strokeLinecap="round" />
              <circle cx="5" cy="4" r="1.5" fill="currentColor" />
              <circle cx="9" cy="8" r="1.5" fill="currentColor" />
              <circle cx="13" cy="12" r="1.5" fill="currentColor" />
            </svg>
            <span>Pipeline</span>
            <span className="nav-count num" id="pipeline-count">{pipelineCount}</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'preparation' ? 'active' : ''}`}
            id="nav-preparation-btn"
            data-view="preparation"
            aria-current={currentView === 'preparation' ? 'page' : undefined}
            onClick={() => handleNavClick('preparation')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M11 2H4a1 1 0 00-1 1v10a1 1 0 001 1h8a1 1 0 001-1V5l-2-3z" strokeWidth="1.5" />
              <path d="M11 2v3h2M5 8h6M5 11h4" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>Preparation</span>
          </button>

          <div className="sidebar-section-title">Candidate Profile</div>
          <button
            type="button"
            className={`nav-item ${currentView === 'profile' ? 'active' : ''}`}
            id="nav-profile-btn"
            data-view="profile"
            aria-current={currentView === 'profile' ? 'page' : undefined}
            onClick={() => handleNavClick('profile')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <circle cx="8" cy="5" r="3" strokeWidth="1.5" />
              <path d="M3 14c0-2.5 2.2-4 5-4s5 1.5 5 4" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>Candidate Profile</span>
            <span className="nav-count num" id="profile-score-indicator">{profileScore}%</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'evidence' ? 'active' : ''}`}
            id="nav-evidence-btn"
            data-view="evidence"
            aria-current={currentView === 'evidence' ? 'page' : undefined}
            onClick={() => handleNavClick('evidence')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M3 3h10v10H3z" strokeWidth="1.5" />
              <path d="M6 7l2 2 3-4" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>Evidence Library</span>
            <span className="nav-count num" id="candidate-facts-count">{evidenceCount}</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'answers' ? 'active' : ''}`}
            id="nav-answers-btn"
            data-view="answers"
            aria-current={currentView === 'answers' ? 'page' : undefined}
            onClick={() => handleNavClick('answers')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M2 3h12v7a1 1 0 01-1 1H5l-3 3V3z" strokeWidth="1.5" />
              <circle cx="5" cy="7" r="0.8" fill="currentColor" />
              <circle cx="8" cy="7" r="0.8" fill="currentColor" />
              <circle cx="11" cy="7" r="0.8" fill="currentColor" />
            </svg>
            <span>Answer Bank</span>
            <span className="nav-count num" id="answers-count">{answersCount}</span>
          </button>

          <div className="sidebar-section-title">Management &amp; Tools</div>
          <button
            type="button"
            className={`nav-item ${currentView === 'sources' ? 'active' : ''}`}
            id="nav-sources-btn"
            data-view="sources"
            aria-current={currentView === 'sources' ? 'page' : undefined}
            onClick={() => handleNavClick('sources')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <circle cx="8" cy="8" r="6" strokeWidth="1.5" />
              <path d="M2 8h12M8 2a10 10 0 010 12M8 2a10 10 0 000 12" strokeWidth="1.2" />
            </svg>
            <span>Source Registry</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'ai' ? 'active' : ''}`}
            id="nav-ai-btn"
            data-view="ai"
            aria-current={currentView === 'ai' ? 'page' : undefined}
            onClick={() => handleNavClick('ai')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M8 1v3M8 12v3M1 8h3M12 8h3M3.5 3.5l2 2M10.5 10.5l2 2M3.5 12.5l2-2M10.5 5.5l2-2" strokeWidth="1.5" strokeLinecap="round" />
              <circle cx="8" cy="8" r="2.5" fill="currentColor" />
            </svg>
            <span>AI &amp; Usage</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'settings' ? 'active' : ''}`}
            id="nav-settings-btn"
            data-view="settings"
            aria-current={currentView === 'settings' ? 'page' : undefined}
            onClick={() => handleNavClick('settings')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <circle cx="8" cy="8" r="2.5" strokeWidth="1.5" />
              <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>Settings &amp; Policy</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'portability' ? 'active' : ''}`}
            id="nav-portability-btn"
            data-view="portability"
            aria-current={currentView === 'portability' ? 'page' : undefined}
            onClick={() => handleNavClick('portability')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M8 2v8M4 7l4 4 4-4M2 13h12" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>Export &amp; Import</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'activity' ? 'active' : ''}`}
            id="nav-activity-btn"
            data-view="activity"
            aria-current={currentView === 'activity' ? 'page' : undefined}
            onClick={() => handleNavClick('activity')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <circle cx="8" cy="8" r="6" strokeWidth="1.5" />
              <path d="M8 4.5V8l2.5 1.5" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>Activity Log</span>
          </button>

          <button
            type="button"
            className={`nav-item ${currentView === 'system' ? 'active' : ''}`}
            id="nav-system-btn"
            data-view="system"
            aria-current={currentView === 'system' ? 'page' : undefined}
            onClick={() => handleNavClick('system')}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <rect x="2" y="3" width="12" height="7" rx="1" strokeWidth="1.5" />
              <path d="M5 13h6M8 10v3" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>System Health</span>
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className="fixture-notice">
            <strong>Local-First Mode</strong><br />
            Loopback enforced. External scraping &amp; telemetry disabled.
          </div>
        </div>
      </aside>

      <div
        id="sidebar-backdrop"
        className={`sidebar-backdrop ${isOpen ? 'active' : ''}`}
        aria-hidden="true"
        onClick={onClose}
      />
    </>
  );
};
