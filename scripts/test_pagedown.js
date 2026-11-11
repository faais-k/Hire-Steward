const { chromium } = require('playwright');

async function testPageDown() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));

  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Navigate to profile
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(300);

  const before = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      activeElement: document.activeElement?.tagName + (document.activeElement?.id ? '#' + document.activeElement?.id : ''),
      st: pv?.scrollTop,
      selectorMatch: !!document.querySelector('.view-wrapper[style*="display: block"] .view-container')
    };
  });
  console.log('BEFORE PageDown:', before);

  // Press PageDown
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(500);

  const after = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      st: pv?.scrollTop
    };
  });
  console.log('AFTER PageDown:', after);

  await browser.close();
}

testPageDown().catch(console.error);
