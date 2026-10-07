/**
 * Bundles the drill viewer (three.js + src/) into swimform/web/viewer/.
 *
 *   cd drill3d && npm ci && npm run build
 *
 * The built files are committed, so running swimform needs no Node. Rebuild only after editing
 * src/. Scripts and styles are separate files (not inlined) so the page's content-security policy
 * can stay strict: no inline script, no inline style.
 */
import {build} from 'esbuild';
import {mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '../swimform/web/viewer');
mkdirSync(out, {recursive: true});

// Offline fallback: NODE_PATH=/path/to/node_modules node build.mjs
const nodePaths = (process.env.NODE_PATH ?? '').split(':').filter(Boolean);

await build({
  entryPoints: [join(here, 'src/main.ts')],
  outfile: join(out, 'viewer.js'),
  bundle: true,
  minify: true,
  format: 'iife',
  target: 'safari15',
  legalComments: 'eof', // keeps three.js's MIT notice in the bundle
  nodePaths,
});

writeFileSync(
  join(out, 'viewer.css'),
  `html,body{margin:0;height:100%;overflow:hidden;background:#f3f3f3;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}
#scene{display:block;width:100%;height:100%;touch-action:none;outline:none}
#hud{position:fixed;left:8px;top:8px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;font:12px -apple-system,system-ui,sans-serif;color:#1a1a1a}
#hud button{font:inherit;padding:3px 8px;border:1px solid #c9c9c9;border-radius:6px;background:#fff;color:inherit;cursor:pointer}
`,
);

writeFileSync(
  join(out, 'viewer.html'),
  `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>3D drill demonstration</title>
<link rel="stylesheet" href="viewer.css">
</head>
<body>
<canvas id="scene" role="img" aria-label="A 3D swimmer performing the drill"></canvas>
<script src="viewer.js"></script>
</body>
</html>
`,
);

console.log('drill3d viewer built into swimform/web/viewer');
