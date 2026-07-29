const pw = require('C:\nvm4w\nodejs\node_modules\omniroute\node_modules\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  // Add debug logging to the game
  const result = await page.evaluate(() => {
    const TILE = 32;
    const debugLog = [];
    
    // Override moveAndCollide to add logging
    const origMoveAndCollide = moveAndCollide;
    const origDoFlip = doFlip;
    const origCheckWallToggle = checkWallToggle;
    
    window.doFlip = function(newG) {
      debugLog.push({type:'FLIP', from: gravity.name, to: newG.name, frame: debugLog.length});
      origDoFlip.call(this, newG);
    };
    
    window.checkWallToggle = function() {
      const before = gravity.name;
      origCheckWallToggle.call(this);
      if (gravity.name !== before) {
        debugLog.push({type:'WALL_TOGGLE', from: before, to: gravity.name, frame: debugLog.length});
      }
    };
    
    // Run 10 frames with right arrow held
    keys['ArrowRight'] = true;
    for (let i = 0; i < 10; i++) {
      const preX = player.x;
      const preY = player.y;
      const preVx = player.vx;
      const preVy = player.vy;
      const preGrav = gravity.name;
      
      update();
      
      debugLog.push({
        type: 'FRAME',
        f: i,
        x: Math.round(player.x*10)/10,
        y: Math.round(player.y*10)/10,
        vx: Math.round(player.vx*100)/100,
        vy: Math.round(player.vy*100)/100,
        grav: gravity.name,
        grounded: player.grounded,
        cooldown: flipCooldown,
      });
    }
    keys['ArrowRight'] = false;
    
    return debugLog;
  });

  result.forEach(log => {
    if (log.type === 'FLIP') {
      console.log(`*** FLIP: ${log.from} → ${log.to} ***`);
    } else if (log.type === 'WALL_TOGGLE') {
      console.log(`*** WALL_TOGGLE: ${log.from} → ${log.to} ***`);
    } else {
      console.log(`  f${log.f}: x=${log.x} y=${log.y} vx=${log.vx} vy=${log.vy} g=${log.grav} gnd=${log.grounded} cd=${log.cooldown}`);
    }
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
