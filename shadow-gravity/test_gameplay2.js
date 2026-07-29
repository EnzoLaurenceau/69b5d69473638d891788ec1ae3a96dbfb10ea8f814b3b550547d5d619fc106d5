const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(500);

  async function gs() {
    return page.evaluate(() => ({
      px: Math.round(player.x), py: Math.round(player.y),
      vx: Math.round(player.vx*100)/100, vy: Math.round(player.vy*100)/100,
      grounded: player.grounded, grav: gravity.name, deaths: deaths||0,
    }));
  }

  let s = await gs();
  console.log('INIT:', JSON.stringify(s));

  // 1. Marcher vers la droite et sauter vers le mur
  console.log('\n=== FLIP #1 : Bas → Droite ===');
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(1200);
  await page.keyboard.press('Space');
  await page.waitForTimeout(800);
  await page.keyboard.up('ArrowRight');
  await page.waitForTimeout(500);
  s = await gs();
  console.log('After jumping toward wall:', JSON.stringify(s));

  // 2. Si toujours gravité bas, essayer de wall-toggle (presser vers le mur)
  if (s.grav === 'Bas') {
    console.log('Trying wall toggle (pressing right toward wall)...');
    await page.keyboard.down('ArrowRight');
    await page.waitForTimeout(1000);
    await page.keyboard.up('ArrowRight');
    s = await gs();
    console.log('After wall toggle attempt:', JSON.stringify(s));
  }

  await page.screenshot({ path: 'C:\\Users\\Jack\\Documents\\LaForge\\shadow-gravity\\test_flip1.png' });

  if (s.grav !== 'Bas') {
    console.log('✅ Flip #1 succeeded! Gravity:', s.grav);

    // 3. Maintenant monter le mur
    console.log('\n=== Climbing wall (gravity:', s.grav, ') ===');
    await page.keyboard.down('ArrowUp');
    await page.waitForTimeout(2000);
    await page.keyboard.up('ArrowUp');
    s = await gs();
    console.log('After climbing:', JSON.stringify(s));

    // 4. Essayer d'atteindre le plafond
    console.log('\n=== FLIP #2 : Droite → Haut ===');
    await page.keyboard.press('Space'); // sauter vers le haut (perpendiculaire)
    await page.waitForTimeout(500);
    await page.keyboard.down('ArrowUp');
    await page.waitForTimeout(1500);
    await page.keyboard.up('ArrowUp');
    await page.waitForTimeout(500);
    s = await gs();
    console.log('After trying to reach ceiling:', JSON.stringify(s));

    await page.screenshot({ path: 'C:\\Users\\Jack\\Documents\\LaForge\\shadow-gravity\\test_flip2.png' });
  }

  console.log('\nFinal state:', JSON.stringify(s));
  if (errors.length) console.log('JS ERRORS:', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
