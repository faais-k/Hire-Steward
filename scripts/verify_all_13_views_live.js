const { chromium } = require('playwright');

async function testAll13Views() {
  console.log('Testing all 13 screens live on http://127.0.0.1:8000/ ...');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({
    viewport: { width: 1366, height: 768 }
  });

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(`Console Error: ${msg.text()}`);
      console.error('PAGE ERROR:', msg.text());
    }
  });

  page.on('pageerror', err => {
    errors.push(`Page Error: ${err.message}`);
    console.error('UNCAUGHT EXCEPTION:', err);
  });

  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  const views = [
    { id: 'overview', btn: '#nav-overview-btn', selector: '#overview-view' },
    { id: 'opportunities', btn: '#nav-opportunities-btn', selector: '#workbench-view' },
    { id: 'pipeline', btn: '#nav-pipeline-btn', selector: '#pipeline-view' },
    { id: 'preparation', btn: '#nav-preparation-btn', selector: '#preparation-view' },
    { id: 'profile', btn: '#nav-profile-btn', selector: '#profile-view' },
    { id: 'evidence', btn: '#nav-evidence-btn', selector: '#evidence-view' },
    { id: 'answers', btn: '#nav-answers-btn', selector: '#answers-view' },
    { id: 'sources', btn: '#nav-sources-btn', selector: '#sources-view' },
    { id: 'ai', btn: '#nav-ai-btn', selector: '#ai-view' },
    { id: 'settings', btn: '#nav-settings-btn', selector: '#settings-view' },
    { id: 'portability', btn: '#nav-portability-btn', selector: '#portability-view' },
    { id: 'activity', btn: '#nav-activity-btn', selector: '#activity-view' },
    { id: 'system', btn: '#nav-system-btn', selector: '#system-view' }
  ];

  const viewReport = [];

  for (const v of views) {
    console.log(`Navigating to view: ${v.id}...`);
    await page.locator(v.btn).click();
    await page.waitForTimeout(200);

    const el = page.locator(v.selector);
    const visible = await el.isVisible();
    const metrics = await page.evaluate((sel) => {
      const mc = document.getElementById('main-content');
      const target = document.querySelector(sel);
      return {
        mcScrollTop: mc?.scrollTop,
        mcScrollHeight: mc?.scrollHeight,
        mcClientHeight: mc?.clientHeight,
        targetHeight: target?.offsetHeight
      };
    }, v.selector);

    viewReport.push({
      view: v.id,
      visible,
      metrics
    });
    console.log(`  -> ${v.id}: visible=${visible}, mcScrollHeight=${metrics.mcScrollHeight}, mcClientHeight=${metrics.mcClientHeight}`);
  }

  await browser.close();

  console.log('\n--- 13 VIEWS SUMMARY ---');
  let pass = true;
  for (const r of viewReport) {
    if (!r.visible) pass = false;
    console.log(`View [${r.view}]: ${r.visible ? 'OK' : 'NOT VISIBLE'}`);
  }

  if (errors.length > 0) {
    console.error('Errors encountered:', errors);
    pass = false;
  }

  console.log(`\nALL 13 VIEWS TEST: ${pass ? 'PASSED' : 'FAILED'}`);
  process.exit(pass ? 0 : 1);
}

testAll13Views().catch(err => {
  console.error(err);
  process.exit(1);
});
