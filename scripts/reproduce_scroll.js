const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 }
  });
  const page = await context.newPage();

  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

  console.log('Navigating to http://127.0.0.1:8000/ ...');
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
  console.log('Document title:', await page.title());

  // Click on Candidate Profile in navigation
  console.log('Navigating to Candidate Profile...');
  const profileNav = page.locator('button.nav-item:has-text("Candidate Profile")');
  await profileNav.click();
  await page.waitForTimeout(1000);

  // Measure scroll metrics
  const metrics = await page.evaluate(() => {
    const root = document.getElementById('root');
    const app = document.querySelector('.app');
    const mainContent = document.querySelector('.main-content');
    const profileView = document.getElementById('profile-view');
    const saveBtn = document.getElementById('save-profile-btn');

    const getComputed = (el) => {
      if (!el) return null;
      const s = window.getComputedStyle(el);
      return {
        display: s.display,
        height: s.height,
        maxHeight: s.maxHeight,
        minHeight: s.minHeight,
        overflow: s.overflow,
        overflowY: s.overflowY,
        boxSizing: s.boxSizing
      };
    };

    return {
      window: { innerWidth: window.innerWidth, innerHeight: window.innerHeight },
      documentElement: {
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
        scrollTop: document.documentElement.scrollTop
      },
      body: {
        clientHeight: document.body.clientHeight,
        scrollHeight: document.body.scrollHeight,
        scrollTop: document.body.scrollTop
      },
      app: {
        clientHeight: app?.clientHeight,
        scrollHeight: app?.scrollHeight,
        scrollTop: app?.scrollTop,
        styles: getComputed(app)
      },
      mainContent: {
        clientHeight: mainContent?.clientHeight,
        scrollHeight: mainContent?.scrollHeight,
        scrollTop: mainContent?.scrollTop,
        styles: getComputed(mainContent)
      },
      profileParent: {
        tag: profileView?.parentElement?.tagName,
        className: profileView?.parentElement?.className,
        clientHeight: profileView?.parentElement?.clientHeight,
        scrollHeight: profileView?.parentElement?.scrollHeight,
        styles: getComputed(profileView?.parentElement)
      },
      profileView: {
        clientHeight: profileView?.clientHeight,
        scrollHeight: profileView?.scrollHeight,
        scrollTop: profileView?.scrollTop,
        styles: getComputed(profileView),
        rect: profileView?.getBoundingClientRect()
      },
      saveBtn: {
        rect: saveBtn?.getBoundingClientRect(),
        visibleInViewport: saveBtn ? (
          saveBtn.getBoundingClientRect().top >= 0 &&
          saveBtn.getBoundingClientRect().bottom <= window.innerHeight
        ) : false
      }
    };
  });

  console.log('SCROLL METRICS:', JSON.stringify(metrics, null, 2));

  // Test mousewheel scrolling
  console.log('Testing mousewheel scrolling...');
  // Move mouse over center of profile view
  await page.mouse.move(500, 300);
  await page.mouse.wheel(0, 500);
  await page.waitForTimeout(500);

  const afterWheel = await page.evaluate(() => {
    const profileView = document.getElementById('profile-view');
    const mainContent = document.querySelector('.main-content');
    return {
      profileViewScrollTop: profileView?.scrollTop,
      mainContentScrollTop: mainContent?.scrollTop,
      bodyScrollTop: document.body.scrollTop,
      docScrollTop: document.documentElement.scrollTop
    };
  });
  console.log('AFTER WHEEL 500px:', JSON.stringify(afterWheel, null, 2));

  // Test Keyboard PageDown
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(500);
  const afterPageDown = await page.evaluate(() => {
    const profileView = document.getElementById('profile-view');
    return { profileViewScrollTop: profileView?.scrollTop };
  });
  console.log('AFTER PAGE DOWN:', JSON.stringify(afterPageDown, null, 2));

  await browser.close();
}

main().catch(err => {
  console.error('ERROR:', err);
  process.exit(1);
});
