const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1000);

  // Inject debug logger into update
  await page.evaluate(() => {
    window._debugLog = [];
    const origUpdate = update;
    window.update = function() {
      const pre = {x:player.x, y:player.y, vx:player.vx, vy:player.vy, g:gravity.name, gd:player.grounded};
      origUpdate();
      const post = {x:player.x, y:player.y, vx:player.vx, vy:player.vy, g:gravity.name, gd:player.grounded};
      if (window._debugLog.length < 20) {
        window._debugLog.push({pre, post});
      }
    };
    // Reset
    buildLevel();
    initPlayer();
  });

  // Run 5 frames
  await page.evaluate(() => {
    keys['ArrowRight'] = true;
    for (let i = 0; i < 5; i++) update();
    keys['ArrowRight'] = false;
  });

  const log = await page.evaluate(() => window._debugLog);
  
  log.forEach((l, i) => {
    console.log('Frame ' + i + ':');
    console.log('  PRE:  x=' + Math.round(l.pre.x) + ' y=' + Math.round(l.pre.y) + ' vx=' + Math.round(l.pre.vx*100)/100 + ' vy=' + Math.round(l.pre.vy*100)/100 + ' g=' + l.pre.g + ' gnd=' + l.pre.gd);
    console.log('  POST: x=' + Math.round(l.post.x) + ' y=' + Math.round(l.post.y) + ' vx=' + Math.round(l.post.vx*100)/100 + ' vy=' + Math.round(l.post.vy*100)/100 + ' g=' + l.post.g + ' gnd=' + l.post.gd);
    // Check what tiles surround the player
    const p = l.post;
    const TILE = 32;
    const cL = Math.floor(p.x/TILE), cR = Math.floor((p.x+22-0.001)/TILE);
    const rT = Math.floor(p.y/TILE), rB = Math.floor((p.y+22-0.001)/TILE);
    console.log('  Tiles: cL=' + cL + ' cR=' + cR + ' rT=' + rT + ' rB=' + rB);
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
