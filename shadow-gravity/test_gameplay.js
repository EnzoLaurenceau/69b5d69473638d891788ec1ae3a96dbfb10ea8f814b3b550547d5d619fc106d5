const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1000);

  // Helper to get game state
  async function getState() {
    return page.evaluate(() => ({
      px: Math.round(player.x),
      py: Math.round(player.y),
      vx: Math.round(player.vx * 100) / 100,
      vy: Math.round(player.vy * 100) / 100,
      grounded: player.grounded,
      grav: gravity.name,
      deaths: deaths || 0,
    }));
  }

  // Initial state
  let s = await getState();
  console.log('INIT:', JSON.stringify(s));

  // Simulate: move right for 60 frames (~1 second)
  console.log('\n--- Moving right toward the wall ---');
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(1500);
  await page.keyboard.up('ArrowRight');
  s = await getState();
  console.log('After moving right:', JSON.stringify(s));

  // Now jump toward the wall
  console.log('\n--- Jumping toward the wall ---');
  await page.keyboard.down('ArrowRight');
  await page.keyboard.press('Space');
  await page.waitForTimeout(1000);
  await page.keyboard.up('ArrowRight');
  s = await getState();
  console.log('After jump-right:', JSON.stringify(s));

  // Keep holding right to ensure hitting the wall
  console.log('\n--- Holding right to hit wall ---');
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(2000);
  await page.keyboard.up('ArrowRight');
  s = await getState();
  console.log('After holding right:', JSON.stringify(s));

  // Take screenshot after attempted flip
  await page.screenshot({ path: 'C:\\Users\\Jack\\Documents\\LaForge\\shadow-gravity\\screenshot3.png', fullPage: false });
  
  if (s.grav !== 'Bas') {
    console.log('\n✅ GRAVITY FLIP DETECTED! Gravity is now:', s.grav);
  } else {
    console.log('\n⚠️ Gravity still Bas. Player at:', s.px, s.py, 'grounded:', s.grounded);
    // Try jumping higher
    console.log('\n--- Trying bigger jump ---');
    await page.keyboard.press('Space');
    await page.waitForTimeout(200);
    await page.keyboard.down('ArrowRight');
    await page.waitForTimeout(2000);
    await page.keyboard.up('ArrowRight');
    s = await getState();
    console.log('After bigger attempt:', JSON.stringify(s));
  }

  if (errors.length) console.log('\nJS ERRORS:', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
