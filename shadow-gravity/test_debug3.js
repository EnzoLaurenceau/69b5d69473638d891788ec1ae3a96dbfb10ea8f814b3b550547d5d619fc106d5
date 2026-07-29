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
    
    for (let i = 0; i < 80; i++) {
      const preX = player.x, preY = player.y;
      const preVx = player.vx, preVy = player.vy;
      const preGrav = gravity.name;
      const preGnd = player.grounded;
      const preDt = deathTimer;
      
      update();
      
      // Log every frame with detailed info
      // Check which tiles the player overlaps
      const TILE = 32;
      const cL = Math.floor(player.x / TILE);
      const cR = Math.floor((player.x + player.w - 0.001) / TILE);
      const rT = Math.floor(player.y / TILE);
      const rB = Math.floor((player.y + player.h - 0.001) / TILE);
      const tiles = [];
      for (let r = rT; r <= rB; r++) {
        for (let c = cL; c <= cR; c++) {
          const val = (r >= 0 && r < 20 && c >= 0 && c < 30) ? level[r][c] : '?';
          tiles.push(`(${r},${c})=${val}`);
        }
      }
      
      const moved = (Math.abs(player.x - preX) > 0.01 || Math.abs(player.y - preY) > 0.01);
      
      if (i < 10 || i === 48 || i === 49 || i === 50 || deathTimer > 0 || !moved) {
        logs.push({
          f: i,
          x: Math.round(player.x * 10) / 10,
          y: Math.round(player.y * 10) / 10,
          vx: Math.round(player.vx * 100) / 100,
          vy: Math.round(player.vy * 100) / 100,
          g: gravity.name,
          gd: player.grounded,
          dt: deathTimer,
          moved: moved,
          tiles: tiles.join(' '),
          ch: gravity.name !== preGrav ? preGrav + '->' + gravity.name : ''
        });
      }
      
      if (Math.abs(player.y) > 2000 || Math.abs(player.x) > 2000) {
        logs.push({f: i, note: 'OUT OF BOUNDS'});
        break;
      }
    }
    keys['ArrowRight'] = false;
    return logs;
  });

  result.forEach(l => {
    if (l.note) { console.log(l.note); return; }
    const flag = l.ch ? ' *** ' + l.ch + ' ***' : '';
    const stuck = !l.moved && l.dt === 0 ? ' [STUCK!]' : (l.dt > 0 ? ' [DEAD]' : '');
    console.log(`f${l.f}: x=${l.x} y=${l.y} vx=${l.vx} vy=${l.vy} g=${l.g} gnd=${l.gd} dt=${l.dt}${stuck}${flag}`);
    if (!l.moved && l.dt === 0) {
      console.log(`  tiles: ${l.tiles}`);
    }
  });

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
