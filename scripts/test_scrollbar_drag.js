const { chromium } = require('playwright');

async function testScrollbarDrag() {
  console.log('Testing scrollbar interaction on .main-content...');
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
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(400);

  // Measure initial scroll
  const initialScroll = await page.evaluate(() => document.getElementById('main-content')?.scrollTop);
  console.log('Initial scrollTop:', initialScroll);

  // Click on the scrollbar track at the far right edge halfway down the screen (x: 1362, y: 400)
  // On Windows Chrome, clicking the scrollbar track triggers a PageDown or jump
  await page.mouse.click(1362, 400);
  await page.waitForTimeout(200);

  const scrollAfterTrackClick = await page.evaluate(() => document.getElementById('main-content')?.scrollTop);
  console.log('ScrollTop after scrollbar track click at (1362, 400):', scrollAfterTrackClick);

  // Now test mouse wheel over various coordinates
  await page.mouse.move(800, 300);
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(150);
  const scrollAfterWheel = await page.evaluate(() => document.getElementById('main-content')?.scrollTop);
  console.log('ScrollTop after wheel:', scrollAfterWheel);

  await browser.close();
  console.log('Scrollbar interaction test completed.');
}

testScrollbarDrag().catch(console.error);
