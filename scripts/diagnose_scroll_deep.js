const { chromium } = require('playwright');

async function testViewport(browser, width, height, zoom = 1) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: zoom
  });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Navigate to profile (handling mobile drawer if width <= 900)
  if (width <= 900) {
    const mobileBtn = page.locator('#mobile-menu-btn');
    if (await mobileBtn.isVisible()) {
      await mobileBtn.click();
      await page.waitForTimeout(200);
    }
  }

  const profileNav = page.locator('#nav-profile-btn');
  await profileNav.click();
  await page.waitForTimeout(300);

  const diag = await page.evaluate(() => {
    const profileView = document.getElementById('profile-view');
    const saveBtn = document.getElementById('save-profile-btn');
    const app = document.querySelector('.app');
    const mainContent = document.querySelector('.main-content');
    const wrapper = profileView ? profileView.parentElement : null;

    const isVisibleInContainer = (el, container) => {
      if (!el || !container) return false;
      const elRect = el.getBoundingClientRect();
      const cRect = container.getBoundingClientRect();
      return (
        elRect.top >= cRect.top &&
        elRect.bottom <= cRect.bottom &&
        elRect.left >= cRect.left &&
        elRect.right <= cRect.right
      );
    };

    return {
      window: { w: window.innerWidth, h: window.innerHeight },
      app: {
        ch: app?.clientHeight,
        sh: app?.scrollHeight,
        overflow: window.getComputedStyle(app).overflow
      },
      mainContent: {
        ch: mainContent?.clientHeight,
        sh: mainContent?.scrollHeight,
        overflow: window.getComputedStyle(mainContent).overflow
      },
      wrapper: {
        tag: wrapper?.tagName,
        className: wrapper?.className,
        ch: wrapper?.clientHeight,
        sh: wrapper?.scrollHeight,
        display: window.getComputedStyle(wrapper).display,
        overflow: window.getComputedStyle(wrapper).overflow,
        flex: window.getComputedStyle(wrapper).flex,
        height: window.getComputedStyle(wrapper).height
      },
      profileView: {
        ch: profileView?.clientHeight,
        sh: profileView?.scrollHeight,
        st: profileView?.scrollTop,
        overflowY: window.getComputedStyle(profileView).overflowY,
        maxHeight: window.getComputedStyle(profileView).maxHeight,
        height: window.getComputedStyle(profileView).height
      },
      saveBtnInitialVisible: isVisibleInContainer(saveBtn, profileView),
      maxScrollPossible: (profileView?.scrollHeight || 0) - (profileView?.clientHeight || 0)
    };
  });

  // Test 1: Keyboard PageDown immediately after navigation
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(100);
  const stAfterPageDown = await page.evaluate(() => document.getElementById('profile-view')?.scrollTop);

  // Test 2: Mouse wheel scrolling over form card
  await page.mouse.move(Math.min(width - 50, 500), 300);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(100);
  const stAfterWheel = await page.evaluate(() => document.getElementById('profile-view')?.scrollTop);

  // Test 3: Scroll to bottom
  await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    if (pv) pv.scrollTop = pv.scrollHeight;
  });
  await page.waitForTimeout(100);
  const finalSt = await page.evaluate(() => document.getElementById('profile-view')?.scrollTop);

  // Test 4: Can Save button be clicked?
  const saveBtn = page.locator('#save-profile-btn');
  const isSaveBtnVisibleAtBottom = await page.evaluate(() => {
    const btn = document.getElementById('save-profile-btn');
    const pv = document.getElementById('profile-view');
    if (!btn || !pv) return false;
    const sRect = btn.getBoundingClientRect();
    const pRect = pv.getBoundingClientRect();
    return sRect.top >= pRect.top && sRect.bottom <= pRect.bottom;
  });

  await context.close();
  return {
    viewport: `${width}x${height} (zoom ${zoom})`,
    diag,
    stAfterPageDown,
    stAfterWheel,
    finalSt,
    isSaveBtnVisibleAtBottom
  };
}

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });

  const viewports = [
    { w: 1366, h: 768, zoom: 1 },
    { w: 1280, h: 720, zoom: 1 },
    { w: 1920, h: 1080, zoom: 1 },
    { w: 1024, h: 768, zoom: 1 },
    { w: 375, h: 667, zoom: 1 }, // mobile
    { w: 1366, h: 768, zoom: 1.25 } // 125% zoom
  ];

  const results = [];
  for (const vp of viewports) {
    const res = await testViewport(browser, vp.w, vp.h, vp.zoom);
    results.push(res);
    console.log(`PASS: ${res.viewport} -> PageDown: ${res.stAfterPageDown}px, Wheel: ${res.stAfterWheel}px, Bottom: ${res.finalSt}px, SaveBtnVisible: ${res.isSaveBtnVisibleAtBottom}`);
  }

  console.log('\nFULL SUMMARY:\n', JSON.stringify(results, null, 2));
  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
