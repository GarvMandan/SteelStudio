import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
await build({ entryPoints: ['src/main.jsx'], bundle: true, minify: true, sourcemap: true, outdir: 'dist', entryNames: 'app', target: ['chrome110', 'edge110', 'firefox115'], loader: { '.jsx': 'jsx' }, define: { 'process.env.NODE_ENV': '"production"' } });
await copyFile('index.html', 'dist/index.html');
console.log('Steel Studio built in visualizer/dist. Launch with py -3 visualizer.py from the project folder.');
