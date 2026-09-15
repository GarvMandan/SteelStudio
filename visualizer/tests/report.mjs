import {chromium} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const args=[resolve('../visualizer.py'),'--no-browser','--port','0'];
if(process.env.STEEL_REPORT_PROJECT)args.push('--project',process.env.STEEL_REPORT_PROJECT);
const server=spawn(process.env.PYTHON||resolve('../.venv/Scripts/python.exe'),args,{cwd:resolve('..'),windowsHide:true});
const url=await new Promise((resolve,reject)=>{
 const timer=setTimeout(()=>reject(new Error('Report test server startup timed out')),30000);
 server.stdout.on('data',chunk=>{const match=String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});server.on('error',reject);
});
let browser;
try{
 browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1060}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 // The app opens on the estimator home page; create a building first.
 await page.goto(url);
 await page.getByLabel('New project name').waitFor({timeout:30000});
 await page.getByLabel('New project name').fill('Report checks');
 await page.getByRole('button',{name:/Add project/}).click();
 await page.getByRole('button',{name:/Add building/}).waitFor({timeout:30000});
 await page.getByRole('button',{name:/Add building/}).click();
 await page.getByLabel('Building name',{exact:true}).waitFor({timeout:30000});
 await page.getByLabel('Building name',{exact:true}).fill('Report building');
 await page.getByRole('button',{name:/Create building/}).click();
 await page.getByRole('img',{name:'Editable building plan',exact:true}).waitFor({timeout:60000});
 const original=await(await page.request.get(url+'/api/project')).json();
 await page.getByRole('button',{name:'3D review',exact:true}).click();await page.locator('.canvas-mount canvas').waitFor();
 await page.getByRole('button',{name:'Plan - north up',exact:true}).click();await page.waitForTimeout(750);
 const label=async text=>await page.locator('.scene-labels .axis-label').filter({hasText:new RegExp(`^${text}$`)}).boundingBox();
 const north=await label('A'),south=await label(String.fromCharCode(65+original.project.y_spans_ft.length));
 const west=await label('1'),east=await label(String(original.project.x_spans_ft.length+1));
 assert.ok(north.y<south.y,'Row A must appear north / above later lettered rows in 3D plan view');
 assert.ok(west.x<east.x,'Numbered grids must increase to the right');
 await page.screenshot({path:'test-results/north-up-3d.png'});
 console.log('PASS 3D north-up view matches the building plan along both axes');
 await page.getByRole('button',{name:'Isometric',exact:true}).click();await page.waitForTimeout(700);
 await page.screenshot({path:'test-results/corrected-isometric.png'});
 // Hidden viewport layers cannot remove members from the report capture.
 await page.getByRole('button',{name:'Display',exact:true}).click();await page.getByLabel('Open-web joists',{exact:false}).uncheck();await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 await page.getByRole('button',{name:'PDF report',exact:true}).click();
 const revision=process.env.STEEL_REPORT_REVISION||'02';
 await page.getByLabel('Revision',{exact:true}).fill(revision);
 let payload;
 page.on('request',r=>{if(r.url().endsWith('/api/report'))payload=r.postDataJSON();});
 const response=page.waitForResponse(r=>r.url().endsWith('/api/report'));
 const downloadPromise=page.waitForEvent('download',{timeout:120000});
 await page.getByRole('button',{name:'Download PDF',exact:true}).click();
 const pdfResponse=await response;
 assert.equal(pdfResponse.status(),200,await pdfResponse.text().then(s=>s.slice(0,400)));
 assert.match(pdfResponse.headers()['content-type'],/application\/pdf/);
 const download=await downloadPromise;
 const bytes=await readFile(await download.path());assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
 await mkdir('../tmp/pdfs',{recursive:true});
 await writeFile('../tmp/pdfs/browser-report.pdf',bytes);
 await writeFile('../tmp/pdfs/report-model.png',Buffer.from(payload.model_image.split(',')[1],'base64'));
 await writeFile('../tmp/pdfs/report-project.json',JSON.stringify(payload.project,null,2));
 if(process.env.STEEL_REPORT_OUTPUT){await mkdir(resolve(process.env.STEEL_REPORT_OUTPUT,'..'),{recursive:true});await writeFile(process.env.STEEL_REPORT_OUTPUT,bytes);}
 assert.deepEqual(payload.project.x_spans_ft,original.project.x_spans_ft);
 assert.deepEqual(payload.project.mezzanines,original.project.mezzanines);
 assert.equal(payload.report.revision,revision);assert.ok(payload.model_image.length>10000);
 await page.locator('dialog').waitFor({state:'detached'});
 assert.equal(await page.locator('.canvas-mount canvas').count(),1,'Offscreen report canvas must be disposed');
 await page.getByRole('button',{name:'Display',exact:true}).click();
 assert.equal(await page.getByLabel('Open-web joists',{exact:false}).isChecked(),false,'Export must preserve viewport layer choices');
 await page.getByRole('button',{name:'Close dialog',exact:true}).click();
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'PASS',report:download.suggestedFilename(),bytes:bytes.length,project:original.project.name,members:original.members.length,checks:['north-up axis orientation','3D model PNG capture','PDF export response','project snapshot preserved','viewport layers preserved','offscreen renderer disposal','no browser errors']},null,2));
}finally{await browser?.close();server.kill();}
