const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  async function gs() {
    return page.evaluate(() => ({
      px: Math.round(player.x * 10) / 10,
      py: Math.round(player.y * 10) / 10,
      col: Math.floor(player.x / 32),
      row: Math.floor(player.y / 32),
      vx: Math.round(player.vx * 100) / 100,
      vy: Math.round(player.vy * 100) / 100,
      grounded: player.grounded,
      grav: gravity.name,
      cooldown: flipCooldown,
    }));
  }

  let s = await gs();
  console.log('INIT:', JSON.stringify(s));

  // Test 1: Just move right, no jump, for a short time
  console.log('\n--- Press right for 500ms ---');
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(500);
  await page.keyboard.up('ArrowRight');
  await page.waitForTimeout(100);
  s = await gs();
  console.log('After 500ms right:', JSON.stringify(s));

  // Test 2: Jump then press right
  console.log('\n--- Jump + right for 800ms ---');
  await page.keyboard.press('Space');
  await page.waitForTimeout(50);
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(800);
  await page.keyboard.up('ArrowRight');
  await page.waitForTimeout(200);
  s = await gs();
  console.log('After jump+right:', JSON.stringify(s));

  // Check if position is valid (within level)
  const valid = s.col >= 0 && s.col < 30 && s.row >= 0 && s.row < 20;
  console.log('Position valid:', valid, '| col:', s.col, 'row:', s.row);

  if (s.grav !== 'Bas') {
    console.log('✅ Gravity flipped to:', s.grav);
    
    // Now try to move along the wall
    console.log('\n--- Moving along wall (pressing up) ---');
    await page.keyboard.down('ArrowUp');
    await page.waitForTimeout(1000);
    await page.keyboard.up('ArrowUp');
    await page.waitForTimeout(200);
    s = await gs();
    console.log('After climbing wall:', JSON.stringify(s));
    console.log('Position valid:', s.col >= 0 && s.col < 30 && s.row >= 0 && s.row < 20);
  }

  await page.screenshot({ path: 'C:\\Users\\Jack\\Documents\\LaForge\\shadow-gravity\\test_pos.png' });
  
  if (errors.length) console.log('\nJS ERRORS:', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
