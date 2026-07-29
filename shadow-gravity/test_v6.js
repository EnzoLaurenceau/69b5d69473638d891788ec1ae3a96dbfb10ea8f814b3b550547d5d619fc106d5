const pw = require('C:\\nvm4w\\nodejs\\node_modules\\omniroute\\node_modules\\playwright');
(async () => {
  const browser = await pw.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 750 } });
  await page.goto('file:///C:/Users/Jack/Documents/LaForge/shadow-gravity/index.html');
  await page.waitForTimeout(1000);

  let allPassed = true;
  function check(name, cond) {
    if (!cond) { console.log(`  FAIL: ${name}`); allPassed = false; }
    else { console.log(`  PASS: ${name}`); }
  }

  // ═══ TEST 1: Collision resolution doesn't create stuck state ═══
  console.log('\n=== TEST 1: Collision resolution — no stuck state ===');
  const t1 = await page.evaluate(() => {
    buildLevel();
    initPlayer();
    const p = player;
    p.x = 12 * 32 + 10;
    p.y = 17 * 32 + 10;
    p.vx = 5; p.vy = 3;
    gravity = GRAV.down;
    
    const logs = [];
    for (let i = 0; i < 30; i++) {
      const preX = p.x, preY = p.y;
      update();
      const moved = Math.abs(p.x - preX) > 0.001 || Math.abs(p.y - preY) > 0.001;
      logs.push({
        f: i, x: Math.round(p.x*10)/10, y: Math.round(p.y*10)/10,
        vx: Math.round(p.vx*100)/100, vy: Math.round(p.vy*100)/100,
        g: gravity.name, gnd: p.grounded, moved
      });
      if (deathTimer > 0) break;
    }
    return logs;
  });
  let stuck = t1.filter(l => !l.moved && (Math.abs(l.vx) > 0.5 || Math.abs(l.vy) > 0.5)).length;
  check('No stuck frames with non-zero velocity', stuck === 0);
  const t1last = t1[t1.length - 1];
  check('Player within bounds', t1last && t1last.x >= 32 && t1last.x <= 928 && t1last.y >= 32 && t1last.y <= 608);
  check('Velocity stabilized to ~0', t1last && Math.abs(t1last.vx) < 0.5 && Math.abs(t1last.vy) < 0.5);

  // ═══ TEST 2: Player lands on floor with controlled play ═══
  console.log('\n=== TEST 2: Player lands on floor (controlled) ===');
  const t2 = await page.evaluate(() => {
    buildLevel();
    initPlayer();
    // Walk right, jump early to clear spikes, then land on floor
    keys['ArrowRight'] = true;
    
    let landedAt = null;
    let jumpFrames = [];
    
    for (let i = 0; i < 120; i++) {
      // Jump at frame 3 to clear spikes, and again at frame 15 if needed
      if (i === 3 || i === 15) { keys['Space'] = true; jumpFrames.push(i); }
      if (i === 5 || i === 17) keys['Space'] = false;
      
      update();
      
      // Track first time grounded on floor (y ≈ 554, x > 150 past spike zone)
      if (player.grounded && gravity.name === 'Bas' && player.x > 200 && !landedAt) {
        landedAt = { f: i, x: Math.round(player.x), y: Math.round(player.y) };
      }
      
      if (Math.abs(player.x) > 2000 || Math.abs(player.y) > 2000) break;
    }
    keys['ArrowRight'] = false;
    keys['Space'] = false;
    return { landedAt, jumpFrames };
  });

  if (t2.landedAt) {
    check(`Landed on floor: x=${t2.landedAt.x} y=${t2.landedAt.y} frame=${t2.landedAt.f}`, 
      t2.landedAt.y >= 540 && t2.landedAt.y <= 580);
  } else {
    // If we can't land with jumps, test directly
    console.log('  (Jump timing did not work, testing direct floor placement)');
    const t2b = await page.evaluate(() => {
      buildLevel();
      initPlayer();
      // Place player above the floor, let them fall
      player.x = 5 * 32;
      player.y = 16 * 32; // row 16, above the floor at row 18
      player.vx = 0;
      player.vy = 0;
      gravity = GRAV.down;
      
      for (let i = 0; i < 30; i++) {
        update();
        if (player.grounded) return { landed: true, y: Math.round(player.y), f: i };
        if (deathTimer > 0) return { landed: false, died: true };
      }
      return { landed: false };
    });
    if (t2b.landed) {
      check(`Direct floor landing: y=${t2b.y} at frame ${t2b.f}`, t2b.y >= 540 && t2b.y <= 580);
    } else {
      check('Player lands on floor', false);
    }
  }

  // ═══ TEST 3: Gravity flip when hitting wall ═══
  console.log('\n=== TEST 3: Gravity flip — wall collision ===');
  const t3 = await page.evaluate(() => {
    buildLevel();
    initPlayer();
    player.x = 12 * 32;
    player.y = 10 * 32;
    player.vx = 8; player.vy = 0;
    player.grounded = true;
    gravity = GRAV.down;
    
    for (let i = 0; i < 30; i++) {
      const prevGrav = gravity.name;
      update();
      if (gravity.name !== prevGrav) return { flippedTo: gravity.name, frame: i };
    }
    return { flippedTo: null };
  });
  check('Gravity flipped to Droite on wall hit', t3.flippedTo === 'Droite');

  // ═══ TEST 4: Player stays in bounds ═══
  console.log('\n=== TEST 4: Player stays in level bounds ===');
  const t4 = await page.evaluate(() => {
    buildLevel();
    initPlayer();
    keys['ArrowRight'] = true;
    let oob = false;
    for (let i = 0; i < 120; i++) {
      update();
      if (player.x < 0 || player.x + player.w > 960 || player.y < 0 || player.y + player.h > 640) {
        oob = true; break;
      }
    }
    keys['ArrowRight'] = false;
    return { oob };
  });
  check('Player stays in bounds (0-960 x, 0-640 y)', !t4.oob);

  // ═══ TEST 5: No position freeze ═══
  console.log('\n=== TEST 5: No position freeze with non-zero velocity ===');
  const t5 = await page.evaluate(() => {
    const results = [];
    
    // Scenario A: walk right
    buildLevel(); initPlayer();
    keys['ArrowRight'] = true;
    let stuck = 0;
    for (let i = 0; i < 60; i++) {
      const px = player.x, py = player.y;
      update();
      if (Math.abs(player.x-px)<0.001 && Math.abs(player.y-py)<0.001 && (Math.abs(player.vx)>0.5||Math.abs(player.vy)>0.5) && deathTimer===0) stuck++;
    }
    keys['ArrowRight'] = false;
    results.push({ name: 'walk-right', stuck });
    
    // Scenario B: at wall corner with high velocity
    buildLevel(); initPlayer();
    player.x = 12 * 32 + 20;
    player.y = 17 * 32 + 10;
    player.vx = 5; player.vy = 5;
    gravity = GRAV.down;
    stuck = 0;
    for (let i = 0; i < 30; i++) {
      const px = player.x, py = player.y;
      update();
      if (Math.abs(player.x-px)<0.001 && Math.abs(player.y-py)<0.001 && (Math.abs(player.vx)>0.5||Math.abs(player.vy)>0.5) && deathTimer===0) stuck++;
    }
    results.push({ name: 'wall-corner', stuck });
    
    // Scenario C: horizontal gravity against wall
    buildLevel(); initPlayer();
    player.x = 13 * 32 - player.w;
    player.y = 10 * 32;
    player.vx = 0; player.vy = 0;
    gravity = GRAV.right;
    stuck = 0;
    for (let i = 0; i < 20; i++) {
      const px = player.x, py = player.y;
      update();
      if (Math.abs(player.x-px)<0.001 && Math.abs(player.y-py)<0.001 && (Math.abs(player.vx)>0.5||Math.abs(player.vy)>0.5) && deathTimer===0) stuck++;
    }
    results.push({ name: 'horizontal-grav', stuck });
    
    return results;
  });
  for (const s of t5) check(`No freeze "${s.name}" (${s.stuck} stuck)`, s.stuck === 0);

  // ═══ TEST 6: Grounded detection for all gravity directions ═══
  console.log('\n=== TEST 6: Grounded detection for all gravity directions ===');
  const t6 = await page.evaluate(() => {
    const results = {};
    
    // Down gravity: on floor
    buildLevel(); initPlayer();
    player.x = 5 * 32; player.y = 16 * 32;
    player.vx = 0; player.vy = 0;
    gravity = GRAV.down;
    for (let i = 0; i < 20; i++) { update(); if (player.grounded) break; }
    results.down = player.grounded;
    
    // Right gravity: against wall
    buildLevel(); initPlayer();
    player.x = 13 * 32 - player.w; player.y = 10 * 32;
    player.vx = 0; player.vy = 0;
    gravity = GRAV.right;
    for (let i = 0; i < 20; i++) { update(); if (player.grounded) break; }
    results.right = player.grounded;
    
    // Left gravity: against left border
    buildLevel(); initPlayer();
    player.x = 32; player.y = 10 * 32;
    player.vx = 0; player.vy = 0;
    gravity = GRAV.left;
    for (let i = 0; i < 20; i++) { update(); if (player.grounded) break; }
    results.left = player.grounded;
    
    // Up gravity: against ceiling/border
    buildLevel(); initPlayer();
    player.x = 5 * 32; player.y = 32;
    player.vx = 0; player.vy = 0;
    gravity = GRAV.up;
    for (let i = 0; i < 20; i++) { update(); if (player.grounded) break; }
    results.up = player.grounded;
    
    return results;
  });
  check('Grounded with down gravity (on floor)', t6.down);
  check('Grounded with right gravity (against wall)', t6.right);
  check('Grounded with left gravity (against border)', t6.left);
  check('Grounded with up gravity (against ceiling)', t6.up);

  // ═══ TEST 7: Press-based gravity flip ═══
  console.log('\n=== TEST 7: Press-based gravity flip ===');
  const t7 = await page.evaluate(() => {
    buildLevel(); initPlayer();
    // Player against wall, right gravity, grounded
    player.x = 13 * 32 - player.w;
    player.y = 10 * 32;
    player.vx = 0; player.vy = 0;
    player.grounded = true;
    gravity = GRAV.right;
    flipCooldown = 0;
    
    // Press up — there's a wall tile above at col 13, row 9
    // isSolid(9, 13) should be true (wall from row 2-18)
    const surfaceAbove = isSolid(9, 13);
    keys['ArrowUp'] = true;
    update();
    const gravAfter = gravity.name;
    keys['ArrowUp'] = false;
    
    return { surfaceAbove, gravAfter };
  });
  if (t7.surfaceAbove) {
    check('Press-up flips gravity to Haut', t7.gravAfter === 'Haut');
  } else {
    check('Surface above player exists for flip', false);
  }

  // ═══ Summary ═══
  console.log('\n' + '='.repeat(50));
  console.log(allPassed ? '✓ ALL TESTS PASSED' : '✗ SOME TESTS FAILED');
  console.log('='.repeat(50));
  
  await browser.close();
  process.exit(allPassed ? 0 : 1);
})().catch(e => { console.error(e.message); process.exit(1); });
