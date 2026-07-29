const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  // Check initial position and level data
  const debug = await page.evaluate(() => {
    const TILE = 32;
    return {
      canvasW: document.getElementById('gameCanvas').width,
      canvasH: document.getElementById('gameCanvas').height,
      playerX: player.x,
      playerY: player.y,
      playerW: player.w,
      playerH: player.h,
      pxCol: Math.floor(player.x / TILE),
      pyRow: Math.floor(player.y / TILE),
      gravDir: gravity.name,
      levelRows: level.length,
      levelCols: level[0].length,
      // Check the floor where player starts
      floorTiles: [level[18][1], level[18][2], level[18][3], level[18][4], level[18][5]],
      playerStartFloor: level[18][2],
      // Check row the player is on
      playerRow: level[Math.floor(player.y / TILE)],
      wallCol13: level.map(r => r[13]),
      wallCol14: level.map(r => r[14]),
    };
  });
  console.log('DEBUG:', JSON.stringify(debug, null, 2));

  if (errors.length) console.log('ERRORS:', errors);
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
