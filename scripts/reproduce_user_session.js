const { chromium } = require('playwright');

async function testUserSession() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();

  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Navigate to Candidate Profile
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(500);

  // Check initial completeness
  const initialBadge = await page.locator('#profile-completeness-badge').textContent();
  console.log('Initial completeness badge:', initialBadge);

  // Check existing fields
  const initialName = await page.locator('#prof-name').inputValue();
  console.log('Initial name:', initialName);

  // Check scroll metrics with existing 100% data
  const initialScroll = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      sh: pv?.scrollHeight,
      ch: pv?.clientHeight,
      st: pv?.scrollTop
    };
  });
  console.log('Initial scroll:', initialScroll);

  // Now, what if we click "Add Work Experience"?
  console.log('Clicking Add Experience...');
  await page.locator('#prof-add-exp-btn').click();
  await page.waitForTimeout(200);

  const scrollAfterAddExp = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      sh: pv?.scrollHeight,
      ch: pv?.clientHeight,
      st: pv?.scrollTop
    };
  });
  console.log('Scroll after Add Experience:', scrollAfterAddExp);

  // Can the user scroll to the new experience fields?
  const expRoles = page.locator('.prof-exp-role');
  const expCount = await expRoles.count();
  console.log('Total experience cards:', expCount);

  const lastExp = expRoles.nth(expCount - 1);
  const lastExpBox = await lastExp.boundingBox();
  console.log('Last experience bounding box:', lastExpBox);

  // Try to click last experience role
  // If it's outside viewport, Playwright will auto-scroll it into view.
  console.log('Attempting to fill last experience role...');
  await lastExp.fill('Senior Test Engineer');
  console.log('Successfully filled last experience role!');

  const scrollAfterFill = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    return {
      sh: pv?.scrollHeight,
      ch: pv?.clientHeight,
      st: pv?.scrollTop
    };
  });
  console.log('Scroll after filling last experience:', scrollAfterFill);

  // Can we reach the Save button?
  const saveBtn = page.locator('button:has-text("Save & Verify Profile")');
  console.log('Save button exists:', await saveBtn.count());
  const saveBox = await saveBtn.boundingBox();
  console.log('Save button bounding box:', saveBox);

  // Check if save button is visible in the viewport right now
  const isSaveInViewport = await page.evaluate(() => {
    const btn = document.querySelector('button[type="submit"]');
    const r = btn.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight;
  });
  console.log('Is Save button visible in viewport before scrolling down?:', isSaveInViewport);

  // Try scrolling down using mousewheel
  await page.mouse.move(600, 300);
  await page.mouse.wheel(0, 1500);
  await page.waitForTimeout(300);

  const isSaveInViewportAfterWheel = await page.evaluate(() => {
    const btn = document.querySelector('button[type="submit"]');
    const r = btn.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight;
  });
  console.log('Is Save button visible in viewport after mouse wheel?:', isSaveInViewportAfterWheel);

  await context.close();
  await browser.close();
}

testUserSession().catch(console.error);
