import React from 'react';

interface TopbarProps {
  onToggleSidebar: () => void;
  isSidebarOpen: boolean;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onSeedFixtures: () => void;
  onOpenAddJobModal: () => void;
  isSeeding: boolean;
}

export const Topbar: React.FC<TopbarProps> = ({
  onToggleSidebar,
  isSidebarOpen,
  searchQuery,
  onSearchChange,
  onSeedFixtures,
  onOpenAddJobModal,
  isSeeding,
}) => {
  return (
    <header className="topbar">
      <div className="topbar-title">
        <button
          type="button"
          id="mobile-menu-btn"
          className="mobile-menu-btn"
          aria-label="Toggle navigation"
          aria-expanded={isSidebarOpen}
          aria-controls="app-sidebar"
          onClick={onToggleSidebar}
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <h1 className="topbar-heading">Job Discovery Workbench</h1>
        <span
          className="tag"
          id="view-mode-badge"
          style={{ background: '#fef3c7', color: '#92400e', fontWeight: 600 }}
        >
          Offline Safe
        </span>
      </div>

      <div className="topbar-search" id="topbar-search-container">
        <input
          type="search"
          id="search-input"
          placeholder="Search title, skills, employer..."
          aria-label="Search job opportunities"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        <span className="kbd-hint">Ctrl K</span>
      </div>

      <div className="filter-group">
        <button
          type="button"
          id="seed-btn"
          className="btn-secondary"
          title="Seed synthetic demo fixtures into local database"
          onClick={onSeedFixtures}
          disabled={isSeeding}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="14" height="14" aria-hidden="true">
            <path d="M8 2v12M2 8h12" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
          <span>{isSeeding ? 'Seeding...' : 'Load Demo Fixtures'}</span>
        </button>

        <button
          type="button"
          id="add-job-btn"
          className="btn-primary"
          style={{ background: '#4338ca', gap: '6px' }}
          title="Add a user-supplied job for offline matching and review"
          onClick={onOpenAddJobModal}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" width="14" height="14" aria-hidden="true">
            <path d="M8 3v10M3 8h10" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span>+ Add Job</span>
        </button>
      </div>
    </header>
  );
};
