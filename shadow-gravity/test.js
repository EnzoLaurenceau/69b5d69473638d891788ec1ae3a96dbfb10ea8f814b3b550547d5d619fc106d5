const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'C:\\Users\\Jack\\Documents\\LaForge\\shadow-gravity\\screenshot2.png', fullPage: false });
  const info = await page.evaluate(() => ({
    title: document.title,
    gravArrow: document.getElementById('grav-arrow')?.textContent,
    gravLabel: document.getElementById('grav-label')?.textContent,
    playerX: typeof player !== 'undefined' ? Math.round(player.x) : null,
    playerY: typeof player !== 'undefined' ? Math.round(player.y) : null,
    levelOk: typeof level !== 'undefined' && level.length === 20,
    won: typeof won !== 'undefined' ? won : null,
    wallCol13: typeof level !== 'undefined' ? level[10][13] : null,
    wallCol14: typeof level !== 'undefined' ? level[10][14] : null,
    portal: typeof level !== 'undefined' ? level[17][21] : null,
    ceilingBlocks: typeof level !== 'undefined' ? [level[2][15], level[2][20], level[2][25]] : null,
  }));
  console.log(JSON.stringify(info, null, 2));
  if (errors.length) console.log('ERRORS:', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
