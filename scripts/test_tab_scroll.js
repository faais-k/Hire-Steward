const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Navigate to Candidate Profile
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(500);

  // Focus the first field: #prof-name
  await page.locator('#prof-name').focus();

  console.log('Tabbing through profile form fields...');
  let currentActiveId = '';
  let tabCount = 0;
  const tabHistory = [];

  while (tabCount < 40) {
    tabCount++;
    await page.keyboard.press('Tab');
    await page.waitForTimeout(50);
    const activeInfo = await page.evaluate(() => {
      const el = document.activeElement;
      const pv = document.getElementById('profile-view');
      const r = el?.getBoundingClientRect();
      const pvr = pv?.getBoundingClientRect();
      const inView = r && pvr ? (r.top >= pvr.top && r.bottom <= pvr.bottom) : false;
      return {
        id: el?.id,
        tag: el?.tagName,
        type: el?.type,
        className: el?.className,
        inView,
        scrollTop: pv?.scrollTop,
        rectTop: r?.top
      };
    });

    tabHistory.push(activeInfo);
    if (activeInfo.tag === 'BUTTON' && activeInfo.type === 'submit') {
      console.log(`Reached Submit Button at tab ${tabCount}!`, activeInfo);
      break;
    }
  }

  console.log('Tab count total:', tabCount);
  console.log('Final 5 tabs:', tabHistory.slice(-5));

  await browser.close();
}

main().catch(console.error);
