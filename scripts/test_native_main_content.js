const { chromium } = require('playwright');

async function testNativeMainContent() {
  console.log('Testing Native .main-content scroll architecture...');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1
  });
  const page = await context.newPage();

  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Apply clean native styles
  await page.addStyleTag({
    content: `
      html, body {
        height: 100%;
        margin: 0;
        overflow: hidden;
      }
      .app {
        height: 100vh;
        height: 100dvh;
        display: grid;
        grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
        overflow: hidden;
      }
      .sidebar {
        height: 100vh;
        overflow-y: auto;
        overflow-x: hidden;
      }
      .main-content {
        height: 100vh !important;
        height: 100dvh !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        position: relative !important;
        display: flex !important;
        flex-direction: column !important;
        scrollbar-width: thin !important;
      }
      .main-content:focus {
        outline: none !important;
      }
      .topbar {
        position: sticky !important;
        top: 0 !important;
        z-index: 50 !important;
        flex-shrink: 0 !important;
      }
      .view-wrapper {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        flex: none !important;
        display: block !important;
      }
      .view-container {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        flex: none !important;
        display: flex !important;
        flex-direction: column !important;
        padding: 24px 32px !important;
      }
      .workbench {
        height: calc(100vh - 48px) !important;
        overflow: hidden !important;
      }
    `
  });

  // Ensure .main-content has tabindex="-1"
  await page.evaluate(() => {
    const mc = document.querySelector('.main-content');
    if (mc) mc.setAttribute('tabindex', '-1');
  });

  // Navigate to Candidate Profile
  await page.locator('#nav-profile-btn').click();
  // Focus main-content after navigation
  await page.evaluate(() => {
    document.querySelector('.main-content')?.focus({ preventScroll: true });
  });
  await page.waitForTimeout(300);

  const getScroll = async () => page.evaluate(() => document.querySelector('.main-content')?.scrollTop);
  const reset = async () => page.evaluate(() => { document.querySelector('.main-content').scrollTop = 0; });

  // Metric measurements
  const initialMetrics = await page.evaluate(() => {
    const mc = document.querySelector('.main-content');
    const pv = document.getElementById('profile-view');
    const form = document.getElementById('candidate-profile-form');
    return {
      mainContent: { ch: mc.clientHeight, sh: mc.scrollHeight, st: mc.scrollTop },
      profileView: { ch: pv.clientHeight, sh: pv.scrollHeight },
      form: { ch: form.clientHeight, sh: form.scrollHeight }
    };
  });
  console.log('INITIAL METRICS:', initialMetrics);

  // Test A: Wheel over form (x: 600, y: 300)
  await reset();
  await page.mouse.move(600, 300);
  await page.mouse.wheel(0, 450);
  await page.waitForTimeout(150);
  const scrollA = await getScroll();
  console.log('Test A (wheel over form):', scrollA);

  // Test B: Wheel over topbar (x: 500, y: 24)
  await reset();
  await page.mouse.move(500, 24);
  await page.mouse.wheel(0, 450);
  await page.waitForTimeout(150);
  const scrollB = await getScroll();
  console.log('Test B (wheel over topbar):', scrollB);

  // Test C: Wheel over empty padding (x: 1300, y: 300)
  await reset();
  await page.mouse.move(1300, 300);
  await page.mouse.wheel(0, 450);
  await page.waitForTimeout(150);
  const scrollC = await getScroll();
  console.log('Test C (wheel over padding):', scrollC);

  // Test D: Wheel while input is focused
  await reset();
  await page.locator('#prof-headline').click();
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, 450);
  await page.waitForTimeout(150);
  const scrollD = await getScroll();
  console.log('Test D (wheel while input focused):', scrollD);

  // Test E: Native PageDown key
  await reset();
  await page.evaluate(() => document.querySelector('.main-content')?.focus({ preventScroll: true }));
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(150);
  const scrollE = await getScroll();
  console.log('Test E (native PageDown):', scrollE);

  // Test F: Native PageUp key
  await page.keyboard.press('PageUp');
  await page.waitForTimeout(150);
  const scrollF = await getScroll();
  console.log('Test F (native PageUp):', scrollF);

  // Test G: Scroll to bottom and check Save button
  await page.evaluate(() => {
    const mc = document.querySelector('.main-content');
    mc.scrollTop = mc.scrollHeight;
  });
  await page.waitForTimeout(150);
  const saveBtnMetrics = await page.evaluate(() => {
    const btn = document.getElementById('save-profile-btn');
    const r = btn?.getBoundingClientRect();
    return {
      visible: !!btn && r.width > 0 && r.height > 0,
      rect: r,
      inViewport: r ? (r.top >= 0 && r.bottom <= window.innerHeight) : false
    };
  });
  console.log('Test G (Save button at bottom):', saveBtnMetrics);

  await browser.close();
  console.log('Native main-content test finished.');
}

testNativeMainContent().catch(console.error);
