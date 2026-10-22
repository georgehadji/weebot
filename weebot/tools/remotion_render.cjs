// Fixed Remotion renderer for Weebot's remotion_video tool (weebot/tools/remotion_video.py).
// Reads one JSON request on stdin:
//   {host, entry, action: "compositions"|"render"|"still", composition, props, codec, output, frame}
// The Remotion packages live in the host folder, not in the agent's project, so
// webpack is told to resolve modules from there too.
'use strict';

const path = require('path');

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (data += chunk));
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

async function main() {
  const req = JSON.parse(await readStdin());
  const hostModules = path.join(req.host, 'node_modules');
  const load = (name) => require(path.join(hostModules, name));
  const { bundle } = load('@remotion/bundler');
  const { getCompositions, selectComposition, renderMedia, renderStill } =
    load('@remotion/renderer');
  const inputProps = req.props || {};

  const serveUrl = await bundle({
    entryPoint: req.entry,
    webpackOverride: (config) => ({
      ...config,
      resolve: {
        ...config.resolve,
        modules: [...((config.resolve && config.resolve.modules) || ['node_modules']), hostModules],
      },
    }),
  });

  if (req.action === 'compositions') {
    const all = await getCompositions(serveUrl, { inputProps });
    const brief = all.map(({ id, width, height, fps, durationInFrames }) => ({
      id, width, height, fps, durationInFrames,
    }));
    process.stdout.write(JSON.stringify(brief));
    return;
  }

  const composition = await selectComposition({ serveUrl, id: req.composition, inputProps });
  if (req.action === 'still') {
    await renderStill({ composition, serveUrl, output: req.output, inputProps, frame: req.frame || 0 });
  } else {
    await renderMedia({
      composition, serveUrl, codec: req.codec, outputLocation: req.output, inputProps,
    });
  }
  process.stdout.write(JSON.stringify({ output: req.output, composition: composition.id }));
}

main().catch((err) => {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(1);
});
