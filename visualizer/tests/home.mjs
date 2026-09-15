/* Browser checks for the estimator home page: projects, buildings,
 * guided setup, and round-tripping a design through the workspace.
 *
 * Expects a server already running; pass its URL as argv[2].
 */
import {chromium} from '@playwright/test';

const URL = process.argv[2] || 'http://127.0.0.1:8804';
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

await page.goto(URL, {waitUntil: 'networkidle'});
await page.waitForTimeout(800);

// --- Home page ---------------------------------------------------------
check('home: opens on the estimator, not a grid',
  await page.getByRole('heading', {name: 'Building Estimator'}).isVisible());
check('home: empty state shown', await page.locator('.home-empty').isVisible());

await page.getByLabel('New project name').fill('Project Shark');
await page.getByRole('button', {name: /Add project/}).click();
await page.waitForTimeout(900);
check('project: created and expanded', await page.locator('.project-card.open').isVisible());

// --- Guided setup ------------------------------------------------------
await page.getByRole('button', {name: /Add building/}).click();
await page.waitForTimeout(400);
check('setup: form opens', await page.getByRole('heading', {name: 'New building'}).isVisible());
check('setup: live preview rendered', await page.locator('.setup-preview svg').isVisible());

const caption = () => page.locator('.preview-caption strong').textContent();
check('setup: default 240x160 at 40ft = 6x4 bays', (await caption()) === '6 × 4 bays', await caption());

await page.getByLabel('Building width', {exact: true}).fill('300');
await page.getByLabel('Bay spacing across', {exact: true}).fill('50');
await page.waitForTimeout(350);
check('setup: preview follows input (6x4)', (await caption()) === '6 × 4 bays', await caption());

// A size that cannot fit in 24 bays must be refused, not silently truncated.
await page.getByLabel('Building width', {exact: true}).fill('2000');
await page.getByLabel('Bay spacing across', {exact: true}).fill('10');
await page.waitForTimeout(350);
check('setup: over-24-bay warning', await page.locator('.snow-problem').isVisible());
check('setup: create disabled while invalid',
  await page.getByRole('button', {name: /Create building/}).isDisabled());

await page.getByLabel('Building width', {exact: true}).fill('300');
await page.getByLabel('Bay spacing across', {exact: true}).fill('50');
await page.getByLabel('Building length', {exact: true}).fill('200');
await page.getByLabel('Bay spacing along', {exact: true}).fill('50');
await page.getByLabel('Clear height', {exact: true}).fill('32');
await page.getByLabel('Building name', {exact: true}).fill('Warehouse A');
await page.waitForTimeout(300);
check('setup: 300x200 at 50ft = 6x4 bays', (await caption()) === '6 × 4 bays', await caption());

await page.getByRole('button', {name: /Create building/}).click();
await page.waitForSelector('.topbar', {timeout: 30000});
await page.waitForTimeout(6000);

// --- Designer ----------------------------------------------------------
check('designer: opened for the new building',
  (await page.locator('.topbar .brand small').textContent()) === 'Warehouse A');
await page.getByRole('button', {name: 'Grid & dimensions'}).click();
await page.waitForTimeout(700);
const xs = await page.locator('input[id^="span-x-"]').count();
const ys = await page.locator('input[id^="span-y-"]').count();
check('designer: guided geometry applied', xs === 6 && ys === 4, `${xs} x ${ys} bays`);
const firstSpan = await page.locator('#span-x-0').inputValue();
check('designer: bay spacing is 50 ft', Number(firstSpan) === 50, firstSpan);
await page.keyboard.press('Escape');

// --- Back home, and persistence ---------------------------------------
await page.locator('.topbar .brand').click();
await page.waitForTimeout(1200);
check('home: returns to the project list',
  await page.getByRole('heading', {name: 'Building Estimator'}).isVisible());
await page.locator('.project-head').click();
await page.waitForTimeout(600);
check('home: building card listed', await page.locator('.building-card').isVisible());
const stats = await page.locator('.building-stats').first().textContent();
check('home: real quantities persisted', /members/.test(stats || ''), stats);
check('home: steel shows in progress',
  (await page.locator('.trade-chip.in_progress').count()) > 0);
check('home: other trades not started',
  (await page.locator('.trade-chip:not(.in_progress):not(.complete)').count()) >= 4);

// Reopen: the saved design must come back, not the defaults.
await page.locator('.building-open').click();
await page.waitForSelector('.topbar', {timeout: 30000});
await page.waitForTimeout(5000);
await page.getByRole('button', {name: 'Grid & dimensions'}).click();
await page.waitForTimeout(700);
const reopened = await page.locator('input[id^="span-x-"]').count();
check('reopen: saved design restored', reopened === 6, `${reopened} x bays`);

await browser.close();
console.log(failures ? `\n${failures} FAILURES` : '\nALL PASS');
process.exit(failures ? 1 : 0);
