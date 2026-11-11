const { chromium } = require('playwright');

async function testArchitecture() {
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

  // Apply the clean CSS architecture:
  // 1. .main-content owns vertical scrolling: overflow-y: auto; overflow-x: hidden; height: 100vh;
  // 2. .topbar is sticky: position: sticky; top: 0; z-index: 50;
  // 3. .view-wrapper has NO height constraints and NO overflow: visible
  // 4. .view-container has NO height constraints and NO overflow: visible
  await page.addStyleTag({
    content: `
      .main-content {
        height: 100vh !important;
        height: 100dvh !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        display: block !important;
      }
      .topbar {
        position: sticky !important;
        top: 0 !important;
        z-index: 50 !important;
      }
      .view-wrapper {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        flex: none !important;
        display: block;
      }
      .view-container {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        flex: none !important;
      }
      .workbench {
        height: calc(100vh - 48px) !important;
        overflow: hidden !important;
      }
    `
  });

  // Navigate to Candidate Profile
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(500);

  // Measure metrics
  const metrics = await page.evaluate(() => {
    const mc = document.querySelector('.main-content');
    const pv = document.getElementById('profile-view');
    const topbar = document.querySelector('.topbar');
    return {
      mainContent: {
        ch: mc?.clientHeight,
        sh: mc?.scrollHeight,
        st: mc?.scrollTop,
        overflowY: window.getComputedStyle(mc).overflowY
      },
      profileView: {
        ch: pv?.clientHeight,
        sh: pv?.scrollHeight,
        st: pv?.scrollTop,
        overflowY: window.getComputedStyle(pv).overflowY
      },
      topbar: {
        position: window.getComputedStyle(topbar).position,
        top: window.getComputedStyle(topbar).top
      }
    };
  });
  console.log('METRICS WITH CLEAN ARCHITECTURE:', JSON.stringify(metrics, null, 2));

  // Perform Tests A, B, C, D, E, F, G, H on .main-content
  const getScroll = async () => page.evaluate(() => document.querySelector('.main-content')?.scrollTop);
  const reset = async () => page.evaluate(() => { document.querySelector('.main-content').scrollTop = 0; });

  // Test A: Mouse over profile form (x: 600, y: 300), scroll wheel 400px
  await reset();
  await page.mouse.move(600, 300);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(150);
  console.log('Test A (wheel over form):', await getScroll());

  // Test B: Mouse over topbar (x: 500, y: 24), scroll wheel 400px
  await reset();
  await page.mouse.move(500, 24);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(150);
  console.log('Test B (wheel over topbar):', await getScroll());

  // Test C: Mouse over sidebar (x: 100, y: 300), scroll wheel 400px
  await reset();
  await page.mouse.move(100, 300);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(150);
  console.log('Test C (wheel over sidebar):', await getScroll());

  // Test D: Click inside a text input and scroll
  await reset();
  await page.locator('#prof-headline').click();
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(150);
  console.log('Test D (wheel while input focused):', await getScroll());

  // Test E: Click empty area and scroll
  await reset();
  await page.mouse.click(1200, 200);
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(150);
  console.log('Test E (wheel after empty click):', await getScroll());

  // Test F: Drag scrollbar at right edge (x: 1362, y: 80 to y: 300)
  await reset();
  await page.mouse.move(1362, 80);
  await page.mouse.down();
  await page.mouse.move(1362, 300, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(150);
  console.log('Test F (drag scrollbar):', await getScroll());

  // Test G: PageDown and PageUp
  await reset();
  // Click inside main-content to focus
  await page.mouse.click(600, 300);
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(150);
  const stPageDown = await getScroll();
  console.log('Test G (PageDown):', stPageDown);
  await page.keyboard.press('PageUp');
  await page.waitForTimeout(150);
  const stPageUp = await getScroll();
  console.log('Test G (PageUp):', stPageUp);

  // Test H: Reach bottom and Save button
  await page.evaluate(() => {
    const mc = document.querySelector('.main-content');
    mc.scrollTop = mc.scrollHeight;
  });
  await page.waitForTimeout(150);
  const saveBtnVisible = await page.evaluate(() => {
    const btn = document.getElementById('save-profile-btn');
    const r = btn?.getBoundingClientRect();
    return r ? (r.top >= 0 && r.bottom <= window.innerHeight && r.width > 0) : false;
  });
  console.log('Test H (Save button visible at bottom):', saveBtnVisible);

  await browser.close();
}

testArchitecture().catch(console.error);
