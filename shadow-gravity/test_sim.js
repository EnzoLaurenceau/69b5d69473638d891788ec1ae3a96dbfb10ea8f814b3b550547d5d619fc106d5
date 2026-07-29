const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  // Directly simulate game ticks instead of using keyboard
  const result = await page.evaluate(() => {
    const TILE = 32;
    const logs = [];
    
    // Simulate pressing right for 60 frames
    keys['ArrowRight'] = true;
    
    for (let frame = 0; frame < 60; frame++) {
      const preX = player.x;
      const preY = player.y;
      const preVx = player.vx;
      const preVy = player.vy;
      const preGrav = gravity.name;
      const preGrounded = player.grounded;
      
      update();
      
      const postX = player.x;
      const postY = player.y;
      const postVx = player.vx;
      const postVy = player.vy;
      const postGrav = gravity.name;
      const postGrounded = player.grounded;
      
      // Log first 10 frames and any frame where grav changes
      if (frame < 15 || preGrav !== postGrav || Math.abs(postX) > 1000 || Math.abs(postY) > 700) {
        logs.push({
          f: frame,
          x: Math.round(postX),
          y: Math.round(postY),
          col: Math.floor(postX / TILE),
          row: Math.floor(postY / TILE),
          vx: Math.round(postVx * 100) / 100,
          vy: Math.round(postVy * 100) / 100,
          g: postGrav,
          gr: postGrounded,
        });
      }
    }
    
    keys['ArrowRight'] = false;
    
    return {
      finalCol: Math.floor(player.x / TILE),
      finalRow: Math.floor(player.y / TILE),
      finalGrav: gravity.name,
      finalGrounded: player.grounded,
      logs: logs,
    };
  });

  console.log('SIMULATION RESULT:');
  console.log('Final: col', result.finalCol, 'row', result.finalRow, 'grav', result.finalGrav, 'grounded', result.finalGrounded);
  console.log('\nFrame log:');
  result.logs.forEach(l => {
    console.log(`  f${l.f}: col=${l.col} row=${l.row} x=${l.x} y=${l.y} vx=${l.vx} vy=${l.vy} grav=${l.g} ground=${l.gr}`);
  });

  if (errors.length) console.log('\nJS ERRORS:', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
