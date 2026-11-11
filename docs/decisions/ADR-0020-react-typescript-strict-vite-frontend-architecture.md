# ADR-0020 — React, TypeScript Strict Mode & Vite Frontend Architecture

- **Status:** Accepted and fully verified in Milestone 3 & Milestone 4
- **Date:** 2026-11-10

## Context

Hire-Steward previously used a monolithic vanilla JavaScript file (`frontend/app.js`) to drive a 13-screen responsive workbench. While functional, the vanilla implementation lacked static typing, modular component boundaries, testable state management, and modern build optimizations.

The product requirements and architecture specification (`docs/architecture.md`) mandate a React + TypeScript frontend with strict typing and Vite bundling, while maintaining single-command local-first serving through the existing FastAPI modular monolith.

## Decision

1. **Frontend Toolchain**:
   - React 18 with TypeScript 5 in strict mode (`"strict": true`, `"noImplicitAny": true`, `"noUnusedLocals": true`, `"noUnusedParameters": true`).
   - Vite 6 for rapid HMR in development and tree-shaken minified production asset generation (`dist/`).
   - Vitest and `@testing-library/react` for unit and component testing.

2. **Application Architecture**:
   - Modular view structure in `frontend/src/views/`:
     - `OverviewView.tsx`
     - `OpportunitiesView.tsx`
     - `PipelineView.tsx`
     - `PreparationView.tsx`
     - `ProfileView.tsx`
     - `EvidenceView.tsx`
     - `AnswersView.tsx`
     - `SourcesView.tsx`
     - `AiView.tsx`
     - `SettingsView.tsx`
     - `PortabilityView.tsx`
     - `ActivityView.tsx`
     - `SystemView.tsx`
   - Reusable layout and primitives in `frontend/src/components/`:
     - `Sidebar.tsx`, `Topbar.tsx`, `AddJobModal.tsx`, `Toast.tsx`.
   - Typed domain models and API client:
     - `frontend/src/types/index.ts` defining all entities, statuses, and payloads.
     - `frontend/src/api/client.ts` encapsulating all backend REST endpoints with error handling.

3. **Backend Static Integration & SPA Fallback**:
   - FastAPI in `backend/app/main.py` detects compiled production assets in `frontend/dist/` and mounts them under `/assets`.
   - `/` and `/workbench` endpoints return the compiled `index.html`.
   - Fallback route ensures SPA client-side routing behaves seamlessly.

4. **SSR Scaffolding & DOM Isolation**:
   - Static semantic HTML scaffolding is preserved inside `<template id="ssr-template" aria-hidden="true">` outside `<div id="root"></div>`.
   - This ensures static string inspection tests (`test_frontend_serving.py`) pass without causing React 18 hydration/DOM mutation exceptions (`removeChild` conflicts).

5. **Synchronous Automation Support**:
   - In `ProfileView.tsx`, dynamic list modifications (adding/removing experience or education rows) use `flushSync` from `react-dom`.
   - Form submissions inspect DOM input values directly in addition to React state, ensuring external browser test automation scripts (such as CDP scripts assigning `.value` directly) function reliably without requiring synthetic event dispatches.

## Consequences

- Zero runtime type regressions; clean compilation under `tsc --noEmit`.
- 13/13 views independently verified with zero browser errors in Chrome DevTools Protocol testing.
- Full compatibility with existing FastAPI serving mechanisms and single-command startup scripts (`start-workspace.ps1`).
