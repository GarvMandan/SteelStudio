/* Browser checks for the concrete trade: tilt wall thickness (H/50),
 * slab on grade, the column safety factor, and the concrete solids being
 * visible and toggleable in the 3D model.
 *
 * Expects a server already running; pass its URL as argv[2].
 */
import {chromium} from '@playwright/test';

const URL = process.argv[2] || 'http://127.0.0.1:8806';
const channel = process.env.BROWSER_CHANNEL || 'msedge';
let failures = 0;

function check(name, ok, detail = '') {
  if (!ok) failures++;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`);
}

const browser = await chromium.launch({channel, headless: false});
const context = await browser.newContext();
const page = await context.newPage();
page.on('pageerror', e => { failures++; console.log('  PAGE ERROR:', e.message); });
page.on('dialog', d => d.accept());

// A tall building so the H/50 rule governs rather than the 7.5in minimum.
await page.goto(URL, {waitUntil: 'networkidle'});
await page.getByLabel('New project name').waitFor({timeout: 30000});
await page.getByLabel('New project name').fill('Concrete checks');
await page.getByRole('button', {name: /Add project/}).click();
await page.getByRole('button', {name: /Add building/}).waitFor({timeout: 30000});
await page.getByRole('button', {name: /Add building/}).click();
await page.getByLabel('Building name', {exact: true}).waitFor({timeout: 30000});
await page.getByLabel('Building name', {exact: true}).fill('Tall warehouse');
await page.getByLabel('Clear height', {exact: true}).fill('45');
await page.getByRole('button', {name: /Create building/}).click();
await page.waitForSelector('.topbar', {timeout: 30000});
await page.waitForTimeout(7000);

// --- Concrete takeoff table -------------------------------------------
await page.getByRole('button', {name: 'Takeoffs'}).click();
await page.waitForTimeout(700);
await page.getByRole('button', {name: 'Concrete', exact: true}).click();
await page.waitForTimeout(600);
const body = await page.locator('.takeoff-report').textContent();
check('concrete: tab renders', /tilt wall/i.test(body || ''));
check('concrete: slab row present', /Slab on grade/.test(body || ''));
check('concrete: footings row present', /Spread footings/.test(body || ''));

// Read the model directly to verify the numbers behind the table.
const model = await page.evaluate(async () => (await (await fetch('/api/project')).json()));
const panels = model.takeoffs.tilt_wall_concrete.panels;
check('walls: one panel per perimeter segment', panels.length >= 4, `${panels.length} panels`);

// Sloped elevations must step with the roof, not sit at one height.
const elevations = model.takeoffs.tilt_wall_concrete.elevations;
check('walls: east and west step with the roof',
  elevations.filter(e => (e.wall === 'East' || e.wall === 'West') && e.stepped).length === 2,
  elevations.map(e => `${e.wall}:${e.stepped ? 'stepped' : 'flat'}`).join(' '));
check('walls: stepped elevations span a height range',
  elevations.filter(e => e.stepped).every(e => e.max_height_ft - e.min_height_ft > 0.01));
const expected = h => Math.max(7.5, Math.ceil((h * 12 / 50 - 1e-9) * 2) / 2);
const clear = model.takeoffs.tilt_wall_concrete.clear_height_ft;
const want = expected(clear);
check('thickness matches clear-height/50',
  panels.every(p => Math.abs(p.thickness_in - want) < 1e-9),
  `clear ${clear} ft -> ${want}"`);
check('thickness uses clear height, not panel height',
  panels.every(p => p.height_ft > clear),
  `clear ${clear} vs panel heights ${panels.map(p => p.height_ft.toFixed(1)).join('/')}`);
check('all thicknesses are half-inch multiples',
  panels.every(p => (p.thickness_in * 2) % 1 === 0));
check('never below the 7.5 in minimum', panels.every(p => p.thickness_in >= 7.5));

const slab = model.takeoffs.slab;
check('slab: default 6 in', slab.thickness_in === 6, `${slab.thickness_in} in`);
check('slab: volume matches area x thickness',
  Math.abs(slab.volume_cy - slab.area_sf * (slab.thickness_in / 12) / 27) < 0.01);

// --- Column safety factor ---------------------------------------------
const safety = model.takeoffs.column_safety;
check('columns: factor is 1.18', safety.factor === 1.18, String(safety.factor));
check('columns: factored = unfactored x 1.18',
  safety.columns.every(c => Math.abs(c.required_capacity_factored_kips - c.required_capacity_kips * 1.18) < 0.01));
check('columns: engine results left unfactored',
  model.results.columns.column_calculations[0].required_capacity_factored_kips === undefined);
await page.getByRole('button', {name: 'Footings', exact: true}).click();
await page.waitForTimeout(500);
const footHead = await page.locator('.takeoff-report thead').textContent();
check('columns: both values shown in the footings table',
  /Load \(kips\)/.test(footHead || '') && /Factored/.test(footHead || ''), footHead?.trim().slice(0, 70));

// --- 3D model ----------------------------------------------------------
await page.locator('.view-switch').getByRole('button', {name: /3D review/}).click();
await page.locator('.canvas-mount canvas').waitFor({timeout: 30000});
await page.waitForTimeout(3000);
check('3D: concrete solids in the model',
  (model.concrete_solids || []).length > 0, `${(model.concrete_solids || []).length} solids`);
const kinds = new Set((model.concrete_solids || []).map(s => s.type));
check('3D: slab, footings and tilt walls all present',
  ['slab', 'footing', 'tilt_wall'].every(k => kinds.has(k)), [...kinds].join(', '));

await page.locator('.viewport-actions button:has-text("Display")').first().click();
await page.waitForSelector('dialog', {timeout: 15000});
await page.waitForTimeout(500);
const dialog = await page.locator('dialog').textContent();
check('3D: concrete toggles offered',
  /Slab on grade/.test(dialog || '') && /Spread footings/.test(dialog || '') && /Tilt wall panels/.test(dialog || ''));

// Toggling a layer must actually change what the scene draws.
const visible = async () => await page.evaluate(() => {
  const scene = window.__steelScene;
  return scene ? scene.concreteMeshes.filter(m => m.visible).length : -1;
});
await page.getByLabel('Slab on grade').uncheck();
await page.waitForTimeout(500);
const after = await visible(), total = (model.concrete_solids || []).length;
check('3D: unchecking slab hides those meshes', after === -1 || after < total, `${after} of ${total} visible`);
await page.getByLabel('Slab on grade').check();
await page.waitForTimeout(500);
check('3D: rechecking restores them', (await visible()) === -1 || (await visible()) === total);

// Close the Display dialog: while open it intercepts pointer events, so
// canvas clicks below would never reach the model.
await page.keyboard.press('Escape');
await page.waitForTimeout(700);

// Regression: hovering a concrete solid used to read .section on an object
// that has none, throwing and blanking the whole app.
const cbox = await page.locator('.canvas-mount canvas').boundingBox();
for (let i = 0; i < 12; i++) {
  await page.mouse.move(cbox.x + cbox.width * (0.2 + 0.05 * i), cbox.y + cbox.height * (0.45 + 0.03 * (i % 6)));
  await page.waitForTimeout(140);
}
check('3D: app survives hovering concrete',
  (await page.locator('body').textContent()).length > 200);

const picked = await page.evaluate(() => {
  const s = window.__steelScene, m = s.concreteMeshes.find(x => x.userData.member.type === 'footing');
  if (!m) return null;
  // Hide everything that could sit between the camera and the footing.
  s.settings.joist = false; s.settings.girder = false; s.settings.column = false;
  s.settings.slab = false; s.settings.tilt_wall = false; s.setSettings({});
  s.camera.position.set(m.position.x + 6, m.position.y + 6, m.position.z + 6);
  s.controls.target.copy(m.position); s.controls.update(); s.tween = null;
  return m.userData.member.id;
});
await page.waitForTimeout(1600);
const at = await page.evaluate(id => {
  const s = window.__steelScene;
  const m = s.concreteMeshes.find(x => x.userData.member.id === id);
  if (!m) return null;
  const v = m.position.clone().project(s.camera);
  const r = s.renderer.domElement.getBoundingClientRect();
  return {x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height};
}, picked);
if (at) await page.mouse.click(at.x, at.y);
await page.waitForTimeout(1200);
check('3D: selecting a footing opens the concrete inspector',
  (await page.locator('.concrete-inspect').count()) === 1, picked || 'no footing');
check('3D: app still alive after selecting concrete',
  (await page.locator('body').textContent()).length > 200);

// Removing bays must move the wall to the new perimeter, not leave it on
// the original bounding rectangle.
const wallBefore = await page.evaluate(async () => {
  const d = await (await fetch('/api/project')).json();
  return {area: d.takeoffs.tilt_wall_concrete.summary.total_area_sf,
          slab: d.takeoffs.slab.area_sf,
          active: d.bays.filter(b => b.active).length};
});
await page.keyboard.press('Escape');
await page.waitForTimeout(600);
await page.locator('.view-switch').getByRole('button', {name: /Building layout/}).click();
await page.waitForTimeout(1200);
await page.getByRole('button', {name: 'Footprint', exact: true}).click();
await page.waitForTimeout(500);
// Toggle off two bays that are currently ACTIVE. Picking blindly can hit a
// bay that is already inactive and switch it back on, so read the state first.
const targets = await page.evaluate(async () => {
  const d = await (await fetch('/api/project')).json();
  return d.bays.filter(b => b.active).slice(0, 2).map(b => b.id);
});
let removed = 0;
for (const id of targets) {
  const cell = page.locator(`.plan-editor *:text-is("${id}")`).first();
  if (await cell.count()) { await cell.click({force: true}); removed++; }
  await page.waitForTimeout(1200);
}
check('walls: both target bays were clickable', removed === 2, `${targets.join(',')} ${removed}/2`);
await page.waitForTimeout(8000);
const wallAfter = await page.evaluate(async () => {
  const d = await (await fetch('/api/project')).json();
  return {area: d.takeoffs.tilt_wall_concrete.summary.total_area_sf,
          slab: d.takeoffs.slab.area_sf,
          active: d.bays.filter(b => b.active).length,
          total: d.bays.length};
});
check('walls: exactly two bays removed', wallAfter.active === wallBefore.active - 2,
  `${wallBefore.active} -> ${wallAfter.active} of ${wallAfter.total}`);
// A notch can add return walls, so the area may rise or fall -- what
// matters is that the wall responds to the footprint at all.
check('walls: wall area follows the new perimeter', wallAfter.area !== wallBefore.area,
  `${Math.round(wallBefore.area)} -> ${Math.round(wallAfter.area)} sf`);
check('walls: slab follows the new footprint', wallAfter.slab < wallBefore.slab,
  `${Math.round(wallBefore.slab)} -> ${Math.round(wallAfter.slab)} sf`);

await browser.close();
console.log(failures ? `\n${failures} FAILURES` : '\nALL PASS');
process.exit(failures ? 1 : 0);
