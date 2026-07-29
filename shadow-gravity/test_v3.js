const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1000);

  // Kill ALL animation frames
  await page.evaluate(() => {
    // Override rAF to prevent game loop
    const origRAF = window.requestAnimationFrame;
    window.requestAnimationFrame = function() { return 0; };
    window._origRAF = origRAF;
  });

  // Wait for any pending rAF to settle
  await page.waitForTimeout(200);

  // Reset game state cleanly
  await page.evaluate(() => {
    buildLevel();
    initPlayer();
  });

  // Now simulate with no interference
  const result = await page.evaluate(() => {
    const logs = [];
    keys['ArrowRight'] = true;
    
    for (let i = 0; i < 15; i++) {
      const pg = gravity.name;
      const px = player.x, py = player.y;
      update();
      logs.push({
        f:i,
        preX: Math.round(px), preY: Math.round(py),
        x: Math.round(player.x), y: Math.round(player.y),
        vx: Math.round(player.vx*100)/100, vy: Math.round(player.vy*100)/100,
        g: gravity.name, gd: player.grounded, cd: flipCooldown,
        ch: gravity.name !== pg ? pg+'→'+gravity.name : ''
      });
    }
    keys['ArrowRight'] = false;
    return logs;
  });

  result.forEach(l => {
    const flag = l.ch ? ' *** '+l.ch+' ***' : '';
    console.log('f'+l.f+': ('+l.preX+','+l.preY+')→('+l.x+','+l.y+') vx='+l.vx+' vy='+l.vy+' g='+l.g+' gnd='+l.gd+flag);
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
