const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  const result = await page.evaluate(() => {
    const logs = [];
    const origDoFlip = doFlip;
    const origCheckWallToggle = checkWallToggle;
    
    window.doFlip = function(newG) {
      logs.push({t:'FLIP', from:gravity.name, to:newG.name});
      origDoFlip(newG);
    };
    
    window.checkWallToggle = function() {
      const before = gravity.name;
      origCheckWallToggle();
      if (gravity.name !== before) logs.push({t:'TOGGLE', from:before, to:gravity.name});
    };
    
    keys['ArrowRight'] = true;
    for (let i = 0; i < 10; i++) {
      update();
      logs.push({
        t:'F', f:i,
        x:Math.round(player.x*10)/10, y:Math.round(player.y*10)/10,
        vx:Math.round(player.vx*100)/100, vy:Math.round(player.vy*100)/100,
        g:gravity.name, gd:player.grounded, cd:flipCooldown
      });
    }
    keys['ArrowRight'] = false;
    return logs;
  });

  result.forEach(l => {
    if(l.t==='FLIP') console.log('*** FLIP: '+l.from+' -> '+l.to);
    else if(l.t==='TOGGLE') console.log('*** TOGGLE: '+l.from+' -> '+l.to);
    else console.log('  f'+l.f+': x='+l.x+' y='+l.y+' vx='+l.vx+' vy='+l.vy+' g='+l.g+' gnd='+l.gd+' cd='+l.cd);
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
