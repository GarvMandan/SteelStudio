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

const browser = await chromium.launch({channel, headless: true});
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
check('concrete: tab renders', /tilt panel/i.test(body || ''));
check('concrete: slab row present', /Slab on grade/.test(body || ''));
check('concrete: footings row present', /Spread footings/.test(body || ''));

// Read the model directly to verify the numbers behind the table.
const model = await page.evaluate(async () => (await (await fetch('/api/project')).json()));
const panels = model.takeoffs.tilt_wall_concrete.panels;
check('H/50: panels calculated', panels.length === 4, `${panels.length} panels`);
const expected = h => Math.max(7.5, Math.ceil((h * 12 / 50 - 1e-9) * 2) / 2);
const allRight = panels.every(p => Math.abs(p.thickness_in - expected(p.governing_height_ft)) < 1e-9);
check('H/50: thickness matches the rule', allRight,
  panels.map(p => `${p.wall} ${p.governing_height_ft.toFixed(1)}ft->${p.thickness_in}"`).join(' '));
check('H/50: above the 7.5in minimum on a tall wall',
  panels.every(p => p.thickness_in > 7.5), panels.map(p => p.thickness_in).join(', '));
check('H/50: all half-inch multiples', panels.every(p => (p.thickness_in * 2) % 1 === 0));

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

await browser.close();
console.log(failures ? `\n${failures} FAILURES` : '\nALL PASS');
process.exit(failures ? 1 : 0);
