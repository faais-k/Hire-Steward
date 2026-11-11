import React, { useState, useEffect, useCallback } from 'react';
import { api } from './api/client';
import type { JobPosting, TrackedApplication } from './types';
import { Sidebar } from './components/Sidebar';
import { Topbar } from './components/Topbar';
import { AddJobModal } from './components/AddJobModal';
import { ToastContainer, type ToastMessage } from './components/Toast';

import { OverviewView } from './views/OverviewView';
import { OpportunitiesView } from './views/OpportunitiesView';
import { PipelineView } from './views/PipelineView';
import { PreparationView } from './views/PreparationView';
import { ProfileView } from './views/ProfileView';
import { EvidenceView } from './views/EvidenceView';
import { AnswersView } from './views/AnswersView';
import { SourcesView } from './views/SourcesView';
import { AiView } from './views/AiView';
import { SettingsView } from './views/SettingsView';
import { PortabilityView } from './views/PortabilityView';
import { ActivityView } from './views/ActivityView';
import { SystemView } from './views/SystemView';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<string>('overview');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isAddJobOpen, setIsAddJobOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSeeding, setIsSeeding] = useState(false);

  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [trackedApplications, setTrackedApplications] = useState<TrackedApplication[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const [factsCount, setFactsCount] = useState(0);
  const [profileScore, setProfileScore] = useState(0);
  const [answersCount, setAnswersCount] = useState(0);

  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((text: string, type: 'info' | 'success' | 'error' | 'warning' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, text, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const data = await api.getJobs();
      setJobs(data.items || []);
      if (!selectedJobId && data.items?.length > 0) {
        setSelectedJobId(data.items[0].id);
      }
    } catch {
      // ignore
    }
  }, [selectedJobId]);

  const loadApplications = useCallback(async () => {
    try {
      const data = await api.getApplications();
      setTrackedApplications(data || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadJobs();
    loadApplications();

    api.getFacts().then((f) => setFactsCount(f.length)).catch(() => {});
    api.getAnswers().then((a) => setAnswersCount(a.length)).catch(() => {});
    api.getProfile().then((p) => {
      if (p?.completeness?.percentage) setProfileScore(p.completeness.percentage);
    }).catch(() => {});
  }, [loadJobs, loadApplications]);

  // Scroll to top and focus main container when switching views
  useEffect(() => {
    const mainEl = document.getElementById('main-content');
    if (mainEl) {
      mainEl.scrollTop = 0;
      mainEl.focus({ preventScroll: true });
    }
  }, [currentView]);

  // Keyboard shortcut listener (Ctrl+K search, Escape modals)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const searchEl = document.getElementById('search-input') as HTMLInputElement | null;
        if (searchEl) {
          searchEl.focus();
          searchEl.select();
        }
        return;
      }
      if (e.key === 'Escape') {
        setIsAddJobOpen(false);
        setIsSidebarOpen(false);
        return;
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSeedFixtures = async () => {
    setIsSeeding(true);
    try {
      const res = await api.seedJobs();
      showToast(res.message || 'Demo fixtures seeded successfully!', 'success');
      await loadJobs();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Seeding failed', 'error');
    } finally {
      setIsSeeding(false);
    }
  };

  const handleCreateJob = async (jobData: Partial<JobPosting>) => {
    try {
      const created = await api.createJob(jobData);
      showToast(`Job "${created.title}" added to workbench!`, 'success');
      await loadJobs();
      setSelectedJobId(created.id);
      setCurrentView('opportunities');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Failed to create job', 'error');
    }
  };

  const handleTrackJob = async (jobId: string) => {
    try {
      await api.createApplication({ job_posting_id: jobId });
      showToast('Opportunity added to application pipeline.', 'success');
      await loadApplications();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Tracking failed', 'error');
    }
  };

  const handleTransitionStatus = async (appId: string, targetStatus: string) => {
    try {
      await api.updateApplicationStatus(appId, targetStatus);
      showToast(`Application transitioned to ${targetStatus}.`, 'success');
      await loadApplications();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Status transition failed', 'error');
    }
  };

  return (
    <div className="app">
      <Sidebar
        currentView={currentView}
        onSelectView={setCurrentView}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        opportunitiesCount={jobs.length}
        pipelineCount={trackedApplications.length}
        evidenceCount={factsCount}
        profileScore={profileScore}
        answersCount={answersCount}
      />

      <div className="main-content" id="main-content" tabIndex={-1}>
        <Topbar
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          isSidebarOpen={isSidebarOpen}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onSeedFixtures={handleSeedFixtures}
          onOpenAddJobModal={() => setIsAddJobOpen(true)}
          isSeeding={isSeeding}
        />

        {/* View 1: Overview Dashboard */}
        <div className="view-wrapper" style={{ display: currentView === 'overview' ? 'block' : 'none' }}>
          <OverviewView
            onNavigate={setCurrentView}
            opportunitiesCount={jobs.length}
            pipelineCount={trackedApplications.length}
            factsCount={factsCount}
            profileScore={profileScore}
          />
        </div>

        {/* View 2: Opportunities Workbench */}
        <div className="view-wrapper" style={{ display: currentView === 'opportunities' ? 'flex' : 'none', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <OpportunitiesView
            jobs={jobs}
            trackedApplications={trackedApplications}
            selectedJobId={selectedJobId}
            onSelectJob={setSelectedJobId}
            onTrackJob={handleTrackJob}
            searchQuery={searchQuery}
          />
        </div>

        {/* View 3: Application Pipeline */}
        <div className="view-wrapper" style={{ display: currentView === 'pipeline' ? 'block' : 'none' }}>
          <PipelineView
            applications={trackedApplications}
            onTransitionStatus={handleTransitionStatus}
            onRefresh={loadApplications}
            onSelectJobForPrep={(jobId) => {
              setSelectedJobId(jobId);
              setCurrentView('preparation');
            }}
          />
        </div>

        {/* View 4: Preparation */}
        <div className="view-wrapper" style={{ display: currentView === 'preparation' ? 'block' : 'none' }}>
          <PreparationView
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelectJob={setSelectedJobId}
          />
        </div>

        {/* View 5: Candidate Profile */}
        <div className="view-wrapper" style={{ display: currentView === 'profile' ? 'block' : 'none' }}>
          <ProfileView onProfileUpdated={setProfileScore} />
        </div>

        {/* View 6: Evidence Library */}
        <div className="view-wrapper" style={{ display: currentView === 'evidence' ? 'block' : 'none' }}>
          <EvidenceView onFactsUpdated={setFactsCount} />
        </div>

        {/* View 7: Answer Bank */}
        <div className="view-wrapper" style={{ display: currentView === 'answers' ? 'block' : 'none' }}>
          <AnswersView onAnswersUpdated={setAnswersCount} />
        </div>

        {/* View 8: Source Registry */}
        <div className="view-wrapper" style={{ display: currentView === 'sources' ? 'block' : 'none' }}>
          <SourcesView />
        </div>

        {/* View 9: AI & Usage */}
        <div className="view-wrapper" style={{ display: currentView === 'ai' ? 'block' : 'none' }}>
          <AiView />
        </div>

        {/* View 10: Settings & Policy */}
        <div className="view-wrapper" style={{ display: currentView === 'settings' ? 'block' : 'none' }}>
          <SettingsView />
        </div>

        {/* View 11: Export & Import */}
        <div className="view-wrapper" style={{ display: currentView === 'portability' ? 'block' : 'none' }}>
          <PortabilityView />
        </div>

        {/* View 12: Activity Log */}
        <div className="view-wrapper" style={{ display: currentView === 'activity' ? 'block' : 'none' }}>
          <ActivityView />
        </div>

        {/* View 13: System Health */}
        <div className="view-wrapper" style={{ display: currentView === 'system' ? 'block' : 'none' }}>
          <SystemView />
        </div>
      </div>

      <AddJobModal
        isOpen={isAddJobOpen}
        onClose={() => setIsAddJobOpen(false)}
        onSubmit={handleCreateJob}
      />

      <ToastContainer toasts={toasts} />
    </div>
  );
};
