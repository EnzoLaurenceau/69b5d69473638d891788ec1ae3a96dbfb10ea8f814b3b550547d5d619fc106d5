const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1500);

  // Stop the game loop first to avoid interference
  await page.evaluate(() => { window._origLoop = loop; window.loop = function(){}; });

  const result = await page.evaluate(() => {
    const logs = [];
    keys['ArrowRight'] = true;
    for (let i = 0; i < 15; i++) {
      const pg = gravity.name;
      update();
      const changed = gravity.name !== pg;
      logs.push({
        f:i, x:Math.round(player.x), y:Math.round(player.y),
        vx:Math.round(player.vx*100)/100, vy:Math.round(player.vy*100)/100,
        g:gravity.name, gd:player.grounded, cd:flipCooldown,
        ch:changed?pg+'→'+gravity.name:''
      });
    }
    keys['ArrowRight'] = false;
    return logs;
  });

  result.forEach(l => {
    const flag = l.ch ? ' *** '+l.ch+' ***' : '';
    console.log('f'+l.f+': x='+l.x+' y='+l.y+' vx='+l.vx+' vy='+l.vy+' g='+l.g+' gnd='+l.gd+' cd='+l.cd+flag);
  });

  if (errors.length) console.log('ERRORS:', errors);
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
