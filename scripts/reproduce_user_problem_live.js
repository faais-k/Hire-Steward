const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1
  });
  const page = await context.newPage();

  page.on('console', msg => console.log('PAGE CONSOLE:', msg.text()));

  console.log('Navigating to http://127.0.0.1:8000/ ...');
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

  // Navigate to Candidate Profile
  console.log('Clicking nav profile...');
  await page.locator('#nav-profile-btn').click();
  await page.waitForTimeout(500);

  // SECTION 3: Inspect DOM ancestor hierarchy & computed styles
  console.log('\n=== SECTION 3: INSPECT ACTUAL SCROLL OWNERSHIP & ANCESTORS ===');
  const ancestors = await page.evaluate(() => {
    const profileView = document.getElementById('profile-view');
    const profileForm = profileView?.querySelector('form');

    const getMetrics = (el, name) => {
      if (!el) return null;
      const s = window.getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return {
        name,
        tagName: el.tagName,
        id: el.id,
        className: el.className,
        clientHeight: el.clientHeight,
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop,
        overflowY: s.overflowY,
        overflowX: s.overflowX,
        height: s.height,
        minHeight: s.minHeight,
        maxHeight: s.maxHeight,
        position: s.position,
        display: s.display,
        flex: s.flex,
        rect: { top: r.top, left: r.left, width: r.width, height: r.height, bottom: r.bottom, right: r.right }
      };
    };

    const chain = [];
    let curr = profileForm || profileView;
    while (curr) {
      chain.push(getMetrics(curr, curr.id || curr.className || curr.tagName));
      curr = curr.parentElement;
    }

    const docEl = document.documentElement;
    const bodyEl = document.body;

    return {
      window: { innerWidth: window.innerWidth, innerHeight: window.innerHeight },
      scrollingElement: document.scrollingElement?.tagName,
      docScrollHeight: docEl.scrollHeight,
      docClientHeight: docEl.clientHeight,
      bodyScrollHeight: bodyEl.scrollHeight,
      bodyClientHeight: bodyEl.clientHeight,
      ancestorChain: chain
    };
  });
  console.log(JSON.stringify(ancestors, null, 2));

  // Check event listeners on window, document, profileView, etc.
  const eventDiag = await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    const mc = document.querySelector('.main-content');
    const topbar = document.querySelector('.topbar');

    // Check if any element at (600, 300) intercepts pointer
    const elAtCenter = document.elementFromPoint(600, 300);
    const elAtRight = document.elementFromPoint(1350, 300);

    return {
      elAtCenter: { tag: elAtCenter?.tagName, id: elAtCenter?.id, class: elAtCenter?.className },
      elAtRight: { tag: elAtRight?.tagName, id: elAtRight?.id, class: elAtRight?.className }
    };
  });
  console.log('\n=== POINTER HIT TESTS ===', JSON.stringify(eventDiag, null, 2));

  // SECTION 2: Exact Tests A through H
  console.log('\n=== SECTION 2: TESTS A THROUGH H ===');

  const getScrollPositions = async () => {
    return await page.evaluate(() => {
      const pv = document.getElementById('profile-view');
      const mc = document.querySelector('.main-content');
      const doc = document.documentElement;
      const body = document.body;
      return {
        pvScrollTop: pv?.scrollTop,
        mcScrollTop: mc?.scrollTop,
        docScrollTop: doc?.scrollTop,
        bodyScrollTop: body?.scrollTop
      };
    });
  };

  const resetScroll = async () => {
    await page.evaluate(() => {
      const pv = document.getElementById('profile-view');
      if (pv) pv.scrollTop = 0;
      const mc = document.querySelector('.main-content');
      if (mc) mc.scrollTop = 0;
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(100);
  };

  // Test A: Mouse pointer over profile form and physically scroll wheel
  await resetScroll();
  console.log('--- Test A: Mouse over profile form (x: 600, y: 300), scroll wheel 400px ---');
  await page.mouse.move(600, 300);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(200);
  const resA = await getScrollPositions();
  console.log('Result A:', resA);

  // Test B: Pointer over topbar and scroll
  await resetScroll();
  console.log('--- Test B: Mouse over topbar (x: 500, y: 24), scroll wheel 400px ---');
  await page.mouse.move(500, 24);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(200);
  const resB = await getScrollPositions();
  console.log('Result B:', resB);

  // Test C: Pointer over sidebar and scroll
  await resetScroll();
  console.log('--- Test C: Mouse over sidebar (x: 100, y: 300), scroll wheel 400px ---');
  await page.mouse.move(100, 300);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(200);
  const resC = await getScrollPositions();
  console.log('Result C:', resC);

  // Test D: Click inside a text input and scroll
  await resetScroll();
  console.log('--- Test D: Click inside #prof-headline text input and scroll wheel 400px ---');
  await page.locator('#prof-headline').click();
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(200);
  const resD = await getScrollPositions();
  console.log('Result D:', resD);

  // Test E: Click on an empty area of the profile and scroll
  await resetScroll();
  console.log('--- Test E: Click on empty area (x: 1200, y: 200) and scroll wheel 400px ---');
  await page.mouse.click(1200, 200);
  await page.waitForTimeout(100);
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(200);
  const resE = await getScrollPositions();
  console.log('Result E:', resE);

  // Test F: Use the browser scrollbar by dragging it
  await resetScroll();
  console.log('--- Test F: Drag scrollbar at right edge (x: 1360, y: 80 down to y: 400) ---');
  // Check where the scrollbar thumb is
  await page.mouse.move(1362, 80);
  await page.mouse.down();
  await page.mouse.move(1362, 400, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(200);
  const resF = await getScrollPositions();
  console.log('Result F:', resF);

  // Test G: Use Page Down and Page Up
  await resetScroll();
  console.log('--- Test G: Page Down and Page Up ---');
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(200);
  const resG1 = await getScrollPositions();
  console.log('Result G (after PageDown):', resG1);
  await page.keyboard.press('PageUp');
  await page.waitForTimeout(200);
  const resG2 = await getScrollPositions();
  console.log('Result G (after PageUp):', resG2);

  // Test H: Navigate to bottom and attempt to reach Save & Verify Profile
  await resetScroll();
  console.log('--- Test H: Scroll to bottom and reach Save & Verify Profile ---');
  await page.evaluate(() => {
    const pv = document.getElementById('profile-view');
    if (pv) pv.scrollTop = pv.scrollHeight;
  });
  await page.waitForTimeout(200);
  const saveBtnMetrics = await page.evaluate(() => {
    const btn = document.getElementById('save-profile-btn');
    const pv = document.getElementById('profile-view');
    const r = btn?.getBoundingClientRect();
    const pvr = pv?.getBoundingClientRect();
    return {
      exists: !!btn,
      visible: !!btn && r.width > 0 && r.height > 0,
      btnRect: r,
      pvRect: pvr,
      inViewport: r ? (r.top >= 0 && r.bottom <= window.innerHeight) : false,
      inContainer: r && pvr ? (r.top >= pvr.top && r.bottom <= pvr.bottom) : false
    };
  });
  console.log('Save button metrics at bottom:', saveBtnMetrics);

  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
