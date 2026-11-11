const { chromium } = require('playwright');

async function testSaveButtonClick() {
  console.log('Testing Save & Verify Profile button reachability and clickability at 100% zoom...');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1
  });

  page.on('console', msg => console.log('PAGE CONSOLE:', msg.text()));

  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(400);

  // Scroll to bottom using natural mouse wheel
  console.log('Scrolling down using mouse wheel...');
  for (let i = 0; i < 5; i++) {
    await page.mouse.move(700, 400);
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(100);
  }

  const scrollPos = await page.evaluate(() => document.getElementById('main-content')?.scrollTop);
  console.log('Final scrollTop after natural wheel scrolls:', scrollPos);

  const saveBtn = page.locator('#save-profile-btn');
  const isVisible = await saveBtn.isVisible();
  console.log('Save button isVisible:', isVisible);

  const box = await saveBtn.boundingBox();
  console.log('Save button boundingBox:', box);

  const inViewport = box && (box.y >= 0 && box.y + box.height <= 768);
  console.log('Save button fully within 768px viewport:', inViewport);

  // Click the save button
  console.log('Clicking #save-profile-btn...');
  await saveBtn.click();
  await page.waitForTimeout(800);

  const toastVisible = await page.evaluate(() => {
    const toast = document.querySelector('.toast, .notification, [role="status"]');
    return toast ? toast.textContent : null;
  });
  console.log('Toast message after clicking Save:', toastVisible);

  await browser.close();
  console.log('Test completed successfully.');
}

testSaveButtonClick().catch(console.error);
