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

  const pv = await page.evaluate(() => {
    const el = document.getElementById('profile-view');
    const r = el.getBoundingClientRect();
    return {
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      scrollTop: el.scrollTop
    };
  });
  console.log('ProfileView rect:', pv);

  // Test wheel at various points:
  // Point A: Left area (x = 300, y = 150)
  // Point B: Center card (x = 600, y = 300)
  // Point C: Textarea (summary)
  // Point D: Right area near scrollbar (x = 1355, y = 300)
  // Point E: Topbar (x = 500, y = 20) -> should it scroll? No, but does it trap?
  // Point F: Sidebar (x = 100, y = 300)

  const testPoints = [
    { name: 'Profile left area', x: 300, y: 150 },
    { name: 'Profile center card', x: 600, y: 300 },
    { name: 'Profile right near scrollbar', x: 1355, y: 300 },
    { name: 'Sidebar', x: 100, y: 300 },
    { name: 'Topbar', x: 500, y: 20 }
  ];

  for (const pt of testPoints) {
    // Reset scroll
    await page.evaluate(() => { document.getElementById('profile-view').scrollTop = 0; });
    await page.waitForTimeout(100);

    await page.mouse.move(pt.x, pt.y);
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(150);

    const st = await page.evaluate(() => document.getElementById('profile-view').scrollTop);
    console.log(`Wheel at ${pt.name} (${pt.x}, ${pt.y}): scrollTop = ${st}`);
  }

  // Now test: What element is actually receiving the wheel event at these points?
  const elementsUnderPointer = await page.evaluate((points) => {
    return points.map(pt => {
      const el = document.elementFromPoint(pt.x, pt.y);
      return {
        point: pt.name,
        tag: el?.tagName,
        id: el?.id,
        className: el?.className
      };
    });
  }, testPoints);
  console.log('Elements under pointer:', elementsUnderPointer);

  await browser.close();
}

main().catch(console.error);
