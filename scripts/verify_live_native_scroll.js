const { chromium } = require('playwright');

async function runAudit() {
  console.log('================================================================');
  console.log('LIVE BROWSER SCROLLING & RESPONSIVENESS VERIFICATION');
  console.log('================================================================');

  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });

  const viewports = [
    { name: '1366x768 (Standard Laptop)', width: 1366, height: 768, scale: 1 },
    { name: '1280x720 (720p HD)', width: 1280, height: 720, scale: 1 },
    { name: '1920x1080 (1080p FHD)', width: 1920, height: 1080, scale: 1 },
    { name: '1366x768 (125% Windows Scaling)', width: 1366, height: 768, scale: 1.25 },
    { name: '1024x768 (Small Desktop)', width: 1024, height: 768, scale: 1 },
    { name: '375x667 (Mobile iPhone SE)', width: 375, height: 667, scale: 1, isMobile: true }
  ];

  const results = {};

  for (const vp of viewports) {
    console.log(`\n>>> Testing Viewport: ${vp.name} (${vp.width}x${vp.height} scale: ${vp.scale})`);
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: vp.scale,
      isMobile: !!vp.isMobile
    });
    const page = await context.newPage();

    // 1. Navigate to live app
    await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });

    // Verify cache header / CSS stylesheet href
    const stylesheetHref = await page.evaluate(() => {
      const link = document.querySelector('link[rel="stylesheet"]');
      return link ? link.getAttribute('href') : null;
    });

    // Navigate to Candidate Profile
    if (vp.isMobile) {
      // On mobile, open sidebar first
      await page.locator('#mobile-menu-btn').click();
      await page.waitForTimeout(200);
      await page.locator('#nav-profile-btn').click();
    } else {
      await page.locator('#nav-profile-btn').click();
    }
    await page.waitForTimeout(400);

    // Get DOM metrics
    const metrics = await page.evaluate(() => {
      const mc = document.getElementById('main-content');
      const pv = document.getElementById('profile-view');
      const form = pv?.querySelector('form');
      const topbar = document.querySelector('.topbar');
      const saveBtn = document.getElementById('save-profile-btn');

      const sMc = mc ? window.getComputedStyle(mc) : null;
      const sPv = pv ? window.getComputedStyle(pv) : null;
      const rSave = saveBtn?.getBoundingClientRect();

      return {
        mainContent: {
          clientHeight: mc?.clientHeight,
          scrollHeight: mc?.scrollHeight,
          scrollTop: mc?.scrollTop,
          overflowY: sMc?.overflowY,
          position: sMc?.position
        },
        profileView: {
          clientHeight: pv?.clientHeight,
          scrollHeight: pv?.scrollHeight,
          overflowY: sPv?.overflowY,
          height: sPv?.height
        },
        formHeight: form?.scrollHeight,
        topbarHeight: topbar?.offsetHeight,
        saveBtn: {
          found: !!saveBtn,
          top: rSave?.top,
          bottom: rSave?.bottom,
          visible: rSave && rSave.width > 0 && rSave.height > 0
        }
      };
    });

    const getScroll = async () => page.evaluate(() => document.getElementById('main-content')?.scrollTop || 0);
    const resetScroll = async () => {
      await page.evaluate(() => {
        const mc = document.getElementById('main-content');
        if (mc) mc.scrollTop = 0;
      });
      await page.waitForTimeout(100);
    };

    const vpResults = { metrics, tests: {} };

    // Test A: Wheel over form (center)
    await resetScroll();
    const centerX = Math.floor(vp.width * 0.5);
    const centerY = Math.floor(vp.height * 0.5);
    await page.mouse.move(centerX, centerY);
    await page.mouse.wheel(0, 450);
    await page.waitForTimeout(150);
    const scrollA = await getScroll();
    vpResults.tests.testA_wheelOverForm = { scroll: scrollA, pass: scrollA > 0 };
    console.log(`  Test A (wheel over form): scrollTop = ${scrollA} (${scrollA > 0 ? 'PASS' : 'FAIL'})`);

    // Test B: Wheel over sticky topbar
    await resetScroll();
    await page.mouse.move(centerX, 20);
    await page.mouse.wheel(0, 450);
    await page.waitForTimeout(150);
    const scrollB = await getScroll();
    vpResults.tests.testB_wheelOverTopbar = { scroll: scrollB, pass: scrollB > 0 };
    console.log(`  Test B (wheel over topbar): scrollTop = ${scrollB} (${scrollB > 0 ? 'PASS' : 'FAIL'})`);

    // Test D: Click inside text input and scroll
    await resetScroll();
    await page.locator('#prof-headline').click();
    await page.waitForTimeout(50);
    await page.mouse.wheel(0, 450);
    await page.waitForTimeout(150);
    const scrollD = await getScroll();
    vpResults.tests.testD_wheelWhileInputFocused = { scroll: scrollD, pass: scrollD > 0 };
    console.log(`  Test D (wheel input focused): scrollTop = ${scrollD} (${scrollD > 0 ? 'PASS' : 'FAIL'})`);

    // Test E: Click empty padding area and scroll
    await resetScroll();
    const rightMarginX = vp.width - 40;
    await page.mouse.click(rightMarginX, centerY);
    await page.waitForTimeout(50);
    await page.mouse.wheel(0, 450);
    await page.waitForTimeout(150);
    const scrollE = await getScroll();
    vpResults.tests.testE_wheelOverPadding = { scroll: scrollE, pass: scrollE > 0 };
    console.log(`  Test E (wheel over padding): scrollTop = ${scrollE} (${scrollE > 0 ? 'PASS' : 'FAIL'})`);

    // Test G: Native PageDown and PageUp keys
    await resetScroll();
    await page.evaluate(() => document.getElementById('main-content')?.focus({ preventScroll: true }));
    await page.keyboard.press('PageDown');
    await page.waitForTimeout(150);
    const scrollG_down = await getScroll();
    await page.evaluate(() => document.getElementById('main-content')?.focus({ preventScroll: true }));
    await page.keyboard.press('PageUp');
    await page.waitForTimeout(150);
    const scrollG_up = await getScroll();
    const passG = scrollG_down > 0 && scrollG_up < scrollG_down;
    vpResults.tests.testG_keyboardPageUpDown = { down: scrollG_down, up: scrollG_up, pass: passG };
    console.log(`  Test G (native PageDown/Up): down=${scrollG_down}, up=${scrollG_up} (${passG ? 'PASS' : 'FAIL'})`);

    // Test H: Scroll to bottom and check Save & Verify button visibility
    await page.evaluate(() => {
      const mc = document.getElementById('main-content');
      if (mc) mc.scrollTop = mc.scrollHeight;
    });
    await page.waitForTimeout(150);
    const saveBtnAtBottom = await page.evaluate(() => {
      const btn = document.getElementById('save-profile-btn');
      if (!btn) return { exists: false };
      const r = btn.getBoundingClientRect();
      const inView = r.top >= 0 && r.bottom <= window.innerHeight;
      return {
        exists: true,
        inViewport: inView,
        rect: { top: r.top, bottom: r.bottom, height: r.height, width: r.width }
      };
    });
    vpResults.tests.testH_saveButtonReachable = {
      ...saveBtnAtBottom,
      pass: saveBtnAtBottom.exists && saveBtnAtBottom.inViewport
    };
    console.log(`  Test H (Save button at bottom): inViewport = ${saveBtnAtBottom.inViewport} (${saveBtnAtBottom.inViewport ? 'PASS' : 'FAIL'})`);

    // Check Opportunities workbench has no outer scrollbar
    if (!vp.isMobile) {
      await page.locator('#nav-opportunities-btn').click();
      await page.waitForTimeout(300);
      const workbenchScrollMetrics = await page.evaluate(() => {
        const mc = document.getElementById('main-content');
        const wb = document.getElementById('workbench-view');
        return {
          mcClientHeight: mc?.clientHeight,
          mcScrollHeight: mc?.scrollHeight,
          hasOuterScroll: mc ? (mc.scrollHeight > mc.clientHeight) : false,
          wbHeight: wb?.offsetHeight
        };
      });
      vpResults.tests.workbenchNoOuterScroll = {
        ...workbenchScrollMetrics,
        pass: !workbenchScrollMetrics.hasOuterScroll
      };
      console.log(`  Workbench outer scrollbar check: hasOuterScroll = ${workbenchScrollMetrics.hasOuterScroll} (${!workbenchScrollMetrics.hasOuterScroll ? 'PASS' : 'FAIL'})`);
    }

    results[vp.name] = vpResults;
    await context.close();
  }

  await browser.close();

  console.log('\n================================================================');
  console.log('SUMMARY OF ALL TEST RESULTS:');
  console.log('================================================================');
  let allPass = true;
  for (const [vpName, vpRes] of Object.entries(results)) {
    console.log(`\n[${vpName}]`);
    for (const [testName, testData] of Object.entries(vpRes.tests)) {
      if (!testData.pass) allPass = false;
      console.log(`  ${testName}: ${testData.pass ? 'PASS' : 'FAIL'}`);
    }
  }

  console.log(`\nOVERALL VERIFICATION: ${allPass ? 'ALL TESTS PASSED!' : 'SOME TESTS FAILED!'}`);
  return { allPass, results };
}

runAudit()
  .then(({ allPass }) => {
    process.exit(allPass ? 0 : 1);
  })
  .catch(err => {
    console.error('Audit failed with error:', err);
    process.exit(1);
  });
