const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1000);

  const result = await page.evaluate(() => {
    buildLevel();
    initPlayer();
    const logs = [];
    keys['ArrowRight'] = true;
    
    for (let i = 0; i < 120; i++) {
      const pg = gravity.name;
      update();
      if (i < 5 || i > 48 || gravity.name !== pg || Math.abs(player.y) > 700) {
        logs.push({
          f:i, x:Math.round(player.x), y:Math.round(player.y),
          vx:Math.round(player.vx*100)/100, vy:Math.round(player.vy*100)/100,
          g:gravity.name, gd:player.grounded, cd:flipCooldown,
          ch:gravity.name!==pg ? pg+'→'+gravity.name : ''
        });
      }
      if (Math.abs(player.y) > 2000 || Math.abs(player.x) > 2000) {
        logs.push({f:i, note:'OUT OF BOUNDS - stopped'});
        break;
      }
    }
    keys['ArrowRight'] = false;
    return logs;
  });

  result.forEach(l => {
    if (l.note) { console.log(l.note); return; }
    const flag = l.ch ? ' *** '+l.ch+' ***' : '';
    console.log('f'+l.f+': x='+l.x+' y='+l.y+' vx='+l.vx+' vy='+l.vy+' g='+l.g+' gnd='+l.gd+' cd='+l.cd+flag);
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
