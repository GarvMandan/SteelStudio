/* Browser checks for the restored desktop features: autosave and crash
 * recovery, the snow lookup, and additional load layer editing.
 *
 * Expects a server already running; pass its URL as argv[2].
 */
import {chromium} from '@playwright/test';

const URL = process.argv[2] || 'http://127.0.0.1:8802';
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

await page.goto(URL, {waitUntil: 'networkidle'});
await page.getByRole('button', {name: 'Loads & foundations'}).click();
await page.waitForTimeout(400);

// --- Snow lookup -------------------------------------------------------
check('snow: city field present', await page.getByLabel('City', {exact: true}).isVisible());
check('snow: state field present', await page.getByLabel('State', {exact: true}).isVisible());
const lookupBtn = page.getByRole('button', {name: /Look up ground snow load/});
check('snow: button disabled with no location', await lookupBtn.isDisabled());

await page.getByLabel('City', {exact: true}).fill('Denver');
await page.getByLabel('State', {exact: true}).fill('CO');
check('snow: button enabled once located', await lookupBtn.isEnabled());
await lookupBtn.click();
await page.waitForSelector('.snow-result, .snow-problem', {timeout: 40000});
const resultText = await page.locator('.snow-result').first().textContent().catch(() => '');
check('snow: returned a value', /\d+(\.\d+)?\s*psf/.test(resultText || ''), (resultText || '').slice(0, 60));
const snowField = page.getByLabel('Ground snow load', {exact: true});
const snowValue = Number(await snowField.inputValue());
check('snow: wrote into the load field', snowValue > 0, `${snowValue} psf`);

// Paste fallback
await page.getByRole('button', {name: /Paste its output instead/}).click();
await page.getByLabel('Paste ASCE output', {exact: true}).fill('Elevation 1,200 ft\nGround Snow Load: 47 psf');
await page.getByRole('button', {name: /Read snow load from text/}).click();
await page.waitForTimeout(1200);
check('snow: paste parsed correctly (47, not 1)',
  Number(await snowField.inputValue()) === 47, await snowField.inputValue());

// --- Load layers -------------------------------------------------------
await page.getByRole('button', {name: /Add load layer/}).click();
await page.waitForTimeout(300);
check('layers: name editable', await page.getByLabel('Layer name', {exact: true}).isVisible());
check('layers: colour editable', await page.getByLabel('Layer colour', {exact: true}).isVisible());
await page.getByLabel('Layer name', {exact: true}).fill('Racking');
await page.getByLabel('Layer load', {exact: true}).fill('12');

const bayButtons = page.locator('.load-layers .bay-map button');
const bayCount = await bayButtons.count();
check('layers: bay map rendered', bayCount > 0, `${bayCount} bays`);
await bayButtons.first().click();
await page.waitForTimeout(250);
check('layers: bay toggles on', await bayButtons.first().getAttribute('aria-pressed') === 'true');
await page.getByRole('button', {name: /^Select all bays$/}).click();
await page.waitForTimeout(250);
const pressed = await page.locator('.load-layers .bay-map button[aria-pressed="true"]').count();
check('layers: select-all works', pressed === bayCount, `${pressed}/${bayCount}`);

// --- Autosave ----------------------------------------------------------
await page.waitForTimeout(11000); // one autosave interval
const stored = await page.evaluate(() => localStorage.getItem('steel-studio:draft:v1'));
check('autosave: wrote to localStorage', !!stored);
let saved = null;
try { saved = JSON.parse(stored); } catch { /* handled by the check below */ }
check('autosave: stored a project', !!saved?.project);
check('autosave: kept the layer edit',
  (saved?.project?.additional_load_layers || []).some(l => l.name === 'Racking'));
check('autosave: recorded a timestamp', !!saved?.savedAt);

// --- Crash recovery ----------------------------------------------------
await page.reload({waitUntil: 'networkidle'});
await page.waitForTimeout(1500);
const banner = page.locator('.recovery-banner');
check('recovery: banner offered after reload', await banner.isVisible());
await page.getByRole('button', {name: /^Restore$/}).click();
await page.waitForTimeout(2500);
await page.getByRole('button', {name: 'Loads & foundations'}).click();
await page.waitForTimeout(500);
const names = await page.locator('.layer-tabs button span').allTextContents();
check('recovery: restored the layer', names.includes('Racking'), names.join(', '));

await browser.close();
console.log(failures ? `\n${failures} FAILURES` : '\nALL PASS');
process.exit(failures ? 1 : 0);
