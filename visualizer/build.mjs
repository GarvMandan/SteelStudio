import { build } from 'esbuild';
import { mkdir, copyFile, rm } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
await build({ entryPoints: ['src/main.jsx'], bundle: true, minify: true, sourcemap: process.env.SOURCEMAP === '1', outdir: 'dist', entryNames: 'app', target: ['chrome110', 'edge110', 'firefox115'], loader: { '.jsx': 'jsx' }, define: { 'process.env.NODE_ENV': '"production"' } });
// Sourcemaps are ~4.3 MB against a 0.9 MB bundle and are debug-only; they
// previously shipped to every user. Build with SOURCEMAP=1 to emit them.
if (process.env.SOURCEMAP !== '1') {
  for (const f of ['dist/app.js.map', 'dist/app.css.map']) await rm(f, { force: true });
}
await copyFile('index.html', 'dist/index.html');
console.log('Steel Studio built in visualizer/dist. Launch with py -3 visualizer.py from the project folder.');
