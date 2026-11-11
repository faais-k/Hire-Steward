const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const screens = [
  { id: 'overview', name: 'Overview Dashboard', navId: '#nav-overview-btn', viewId: '#overview-view' },
  { id: 'opportunities', name: 'Opportunities Workbench', navId: '#nav-opportunities-btn', viewId: '#workbench-view' },
  { id: 'pipeline', name: 'Application Pipeline', navId: '#nav-pipeline-btn', viewId: '#pipeline-view' },
  { id: 'preparation', name: 'Application Preparation', navId: '#nav-preparation-btn', viewId: '#preparation-view' },
  { id: 'profile', name: 'Candidate Profile', navId: '#nav-profile-btn', viewId: '#profile-view' },
  { id: 'evidence', name: 'Evidence Library', navId: '#nav-evidence-btn', viewId: '#evidence-view' },
  { id: 'answers', name: 'Answer Bank', navId: '#nav-answers-btn', viewId: '#answers-view' },
  { id: 'sources', name: 'Source Registry', navId: '#nav-sources-btn', viewId: '#sources-view' },
  { id: 'ai', name: 'AI & Usage Diagnostics', navId: '#nav-ai-btn', viewId: '#ai-view' },
  { id: 'settings', name: 'Settings & Policy', navId: '#nav-settings-btn', viewId: '#settings-view' },
  { id: 'portability', name: 'Export & Portability', navId: '#nav-portability-btn', viewId: '#portability-view' },
  { id: 'activity', name: 'Activity Log', navId: '#nav-activity-btn', viewId: '#activity-view' },
  { id: 'system', name: 'System Health', navId: '#nav-system-btn', viewId: '#system-view' }
];

async function runAudit() {
  console.log('Starting Hire-Steward Full UI Audit...');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });

  const results = {
    timestamp: new Date().toISOString(),
    browser: 'Chrome 131+ (Blink Engine)',
    screensTested: [],
    workflowsTested: [],
    consoleErrors: [],
    networkFailures: []
  };

  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 }
  });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') {
      results.consoleErrors.push(msg.text());
    }
  });

  page.on('response', res => {
    if (res.status() >= 400 && !res.url().includes('favicon.ico')) {
      results.networkFailures.push({ url: res.url(), status: res.status() });
    }
  });

  console.log('Navigating to http://127.0.0.1:8000/ ...');
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // 1. Audit Every Screen
  for (const s of screens) {
    console.log(`Auditing screen: ${s.name} (${s.id})...`);
    const navBtn = page.locator(s.navId);
    await navBtn.click();
    await page.waitForTimeout(300);

    const viewLoc = page.locator(s.viewId);
    const isVisible = await viewLoc.isVisible();

    // Check scroll capability
    const scrollInfo = await page.evaluate((viewId) => {
      const el = document.querySelector(viewId);
      if (!el) return null;
      return {
        clientHeight: el.clientHeight,
        scrollHeight: el.scrollHeight,
        isScrollable: el.scrollHeight > el.clientHeight,
        scrollTop: el.scrollTop
      };
    }, s.viewId);

    // Test PageDown keyboard scrolling on this view
    await page.keyboard.press('PageDown');
    await page.waitForTimeout(100);
    const stAfterPageDown = await page.evaluate((viewId) => {
      const el = document.querySelector(viewId);
      return el ? el.scrollTop : 0;
    }, s.viewId);

    // Reset scroll
    await page.evaluate((viewId) => {
      const el = document.querySelector(viewId);
      if (el) el.scrollTop = 0;
    }, s.viewId);

    results.screensTested.push({
      screen: s.name,
      id: s.id,
      navSelector: s.navId,
      viewSelector: s.viewId,
      rendered: isVisible,
      scrollMetrics: scrollInfo,
      keyboardPageDownScrollTop: stAfterPageDown,
      status: isVisible ? 'PASS' : 'FAIL'
    });
  }

  // 2. Interactive Workflows
  console.log('Testing Interactive Workflow: Modal Open/Escape...');
  const addJobBtn = page.locator('button:has-text("+ Add Job")');
  await addJobBtn.click();
  await page.waitForTimeout(200);
  const modalVisible = await page.locator('#intake-modal-backdrop').isVisible();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  const modalClosed = !(await page.locator('#intake-modal-backdrop').isVisible());
  results.workflowsTested.push({
    workflow: 'Add Job Modal Open & Escape Dismiss',
    status: modalVisible && modalClosed ? 'PASS' : 'FAIL'
  });

  // 3. Search Bar Shortcut (Ctrl+K)
  console.log('Testing Keyboard Shortcut Ctrl+K...');
  await page.keyboard.press('Control+k');
  await page.waitForTimeout(200);
  const isSearchFocused = await page.evaluate(() => {
    return document.activeElement?.id === 'search-input';
  });
  results.workflowsTested.push({
    workflow: 'Keyboard Shortcut Ctrl+K focuses Search Bar',
    status: isSearchFocused ? 'PASS' : 'FAIL'
  });

  // 4. Opportunities Tier Filter & Selection
  console.log('Testing Opportunities Tier Filter...');
  await page.locator('#nav-opportunities-btn').click();
  await page.waitForTimeout(300);
  const strongPill = page.locator('.tier-filter-pill[data-tier="Strong"]');
  if (await strongPill.isVisible()) {
    await strongPill.click();
    await page.waitForTimeout(200);
    const isActive = await strongPill.evaluate(el => el.classList.contains('active'));
    results.workflowsTested.push({
      workflow: 'Opportunities Tier Filtering (Strong)',
      status: isActive ? 'PASS' : 'FAIL'
    });
    // Click All to restore
    await page.locator('.tier-filter-pill[data-tier="all"]').click();
  }

  // 5. Candidate Profile Persistence Read-Check
  console.log('Checking Candidate Profile Persistence Integrity...');
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(300);
  const profName = await page.locator('#prof-name').inputValue();
  const profEmail = await page.locator('#prof-email').inputValue();
  const profScore = await page.locator('#profile-completeness-badge').textContent();
  const isProfileIntact = profName.length > 0 && profScore.includes('%');
  results.workflowsTested.push({
    workflow: 'Candidate Profile Data Integrity Verification',
    details: { name: profName, email: profEmail, score: profScore },
    status: isProfileIntact ? 'PASS' : 'FAIL'
  });

  // 6. Mobile Viewport Drawer Test
  console.log('Testing Mobile Viewport Responsive Drawer...');
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(200);
  const menuBtn = page.locator('#mobile-menu-btn');
  const menuVisible = await menuBtn.isVisible();
  await menuBtn.click();
  await page.waitForTimeout(200);
  const sidebarOpen = await page.locator('#app-sidebar').evaluate(el => el.classList.contains('sidebar-open'));

  // Click on the backdrop to the right of the 260px drawer (x = 320, y = 300)
  await page.mouse.click(320, 300);
  await page.waitForTimeout(200);
  const sidebarClosed = !(await page.locator('#app-sidebar').evaluate(el => el.classList.contains('sidebar-open')));
  results.workflowsTested.push({
    workflow: 'Mobile 375px Navigation Drawer & Backdrop Dismiss',
    status: menuVisible && sidebarOpen && sidebarClosed ? 'PASS' : 'FAIL'
  });

  await browser.close();
  console.log('Audit completed successfully.');
  return results;
}

runAudit().then(res => {
  fs.writeFileSync('audit_results.json', JSON.stringify(res, null, 2), 'utf-8');
  console.log('Audit results saved to audit_results.json');
}).catch(err => {
  console.error('Audit failed:', err);
  process.exit(1);
});
