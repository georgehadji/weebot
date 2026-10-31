import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The browser tests build into their own directory so they never clobber a running `next dev`.
  distDir: process.env.NEXT_DIST_DIR || '.next',

  // Standalone output for Docker: produces .next/standalone/ with server + assets
  output: 'standalone',

  // Pin the workspace root to weebot-ui. The repo root carries its own
  // package.json/package-lock.json (unrelated @openrouter deps), so Turbopack
  // otherwise infers the repo root as the workspace root and resolves
  // node_modules from there — breaking imports like "tw-animate-css" that are
  // installed under weebot-ui/node_modules.
  turbopack: {
    root: __dirname,
  },

  // No `rewrites()` for /api: a rewrite runs before the dynamic route handler in
  // src/app/api/[[...path]]/route.ts, which would skip its cross-site and Host checks and
  // ignore BACKEND_URL. That handler is the one proxy. WebSockets do not go through it: the
  // app connects straight to ws://localhost:8000.
  // Re-enable StrictMode after fixing useWebSocket effect cleanup
  reactStrictMode: true,
};

export default nextConfig;
