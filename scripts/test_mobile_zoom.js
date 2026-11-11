const { chromium } = require('playwright');

async function testMobileAndZoom() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });

  // Mobile test
  console.log('Testing mobile (375x667)...');
  const mobileCtx = await browser.newContext({
    viewport: { width: 375, height: 667 }
  });
  const mobilePage = await mobileCtx.newPage();
  await mobilePage.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Open sidebar via #mobile-menu-btn
  const toggle = mobilePage.locator('#mobile-menu-btn');
  console.log('Mobile menu btn visible:', await toggle.isVisible());
  await toggle.click();
  await mobilePage.waitForTimeout(300);

  const profileNav = mobilePage.locator('button.nav-item:has-text("Candidate Profile")');
  console.log('Profile nav visible after toggle:', await profileNav.isVisible());
  await profileNav.click();
  await mobilePage.waitForTimeout(500);

  const mobileDiag = await mobilePage.evaluate(() => {
    const pv = document.getElementById('profile-view');
    const mainContent = document.querySelector('.main-content');
    return {
      window: { w: window.innerWidth, h: window.innerHeight },
      pv: {
        ch: pv?.clientHeight,
        sh: pv?.scrollHeight,
        st: pv?.scrollTop,
        maxHeight: window.getComputedStyle(pv).maxHeight,
        overflowY: window.getComputedStyle(pv).overflowY
      }
    };
  });
  console.log('MOBILE DIAG:', JSON.stringify(mobileDiag, null, 2));

  // Test touch drag / wheel on mobile
  await mobilePage.mouse.move(180, 300);
  await mobilePage.mouse.wheel(0, 400);
  await mobilePage.waitForTimeout(200);
  const mobileStAfterWheel = await mobilePage.evaluate(() => document.getElementById('profile-view')?.scrollTop);
  console.log('MOBILE ST AFTER WHEEL:', mobileStAfterWheel);

  await mobileCtx.close();

  // Test 125% zoom on 1366x768
  console.log('Testing 125% zoom on 1366x768...');
  const zoomCtx = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1.25
  });
  const zoomPage = await zoomCtx.newPage();
  await zoomPage.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
  await zoomPage.locator('button.nav-item:has-text("Candidate Profile")').click();
  await zoomPage.waitForTimeout(500);

  const zoomDiag = await zoomPage.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      ch: pv?.clientHeight,
      sh: pv?.scrollHeight,
      st: pv?.scrollTop
    };
  });
  console.log('ZOOM DIAG:', JSON.stringify(zoomDiag, null, 2));

  await zoomCtx.close();
  await browser.close();
}

testMobileAndZoom().catch(console.error);
