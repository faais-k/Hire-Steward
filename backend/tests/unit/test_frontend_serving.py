"""Tests verifying frontend static asset serving, routes, and 13 workbench views."""

from __future__ import annotations

from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_frontend_workbench_serving_and_views() -> None:
    app = create_app()
    with TestClient(app, base_url="http://localhost") as client:
        # 1. Root index.html
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        html = res.text

        # Verify all 13 view containers are present
        views = [
            "overview-view",
            "workbench-view",
            "pipeline-view",
            "preparation-view",
            "profile-view",
            "evidence-view",
            "answers-view",
            "sources-view",
            "ai-view",
            "settings-view",
            "portability-view",
            "activity-view",
            "system-view",
        ]
        for v in views:
            assert f'id="{v}"' in html, f"View container {v} missing in index.html"

        # Verify navigation items
        assert 'id="nav-overview-btn"' in html
        assert 'id="nav-opportunities-btn"' in html
        assert 'id="nav-pipeline-btn"' in html
        assert 'id="nav-preparation-btn"' in html
        assert 'id="nav-profile-btn"' in html
        assert 'id="nav-evidence-btn"' in html
        assert 'id="nav-answers-btn"' in html
        assert 'id="nav-sources-btn"' in html
        assert 'id="nav-ai-btn"' in html
        assert 'id="nav-settings-btn"' in html
        assert 'id="nav-portability-btn"' in html
        assert 'id="nav-activity-btn"' in html
        assert 'id="nav-system-btn"' in html

        # Verify mobile drawer toggle and scaffolding
        assert 'id="mobile-menu-btn"' in html
        assert 'id="app-sidebar"' in html
        assert 'id="sidebar-backdrop"' in html

        # 2. Explicit /workbench route
        res_wb = client.get("/workbench")
        assert res_wb.status_code == 200
        assert "Hire-Steward" in res_wb.text

        # 3. CSS Stylesheet
        res_css = client.get("/app.css")
        assert res_css.status_code == 200
        assert "text/css" in res_css.headers["content-type"]
        assert "--fs-title" in res_css.text
        assert ".dashboard-kpi-grid" in res_css.text
        assert ".toast-container" in res_css.text
        assert ".sidebar.sidebar-open" in res_css.text
        assert ".mobile-menu-btn" in res_css.text
        assert ".sidebar-backdrop" in res_css.text

        # 4. JS Application Script
        res_js = client.get("/app.js")
        assert res_js.status_code == 200
        assert "switchView" in res_js.text
        assert "loadOverviewData" in res_js.text
        assert "loadProfileData" in res_js.text
        assert "openNewAnswerModal" in res_js.text
        assert "toggleAnswerConsent" in res_js.text
        assert "showToast" in res_js.text
        assert 'aria-label="Close dialog"' in res_js.text


def test_homepage_serves_html_and_contains_expected_containers() -> None:
    """Explicit named alias verifying root page serving and all expected containers."""
    test_frontend_workbench_serving_and_views()
