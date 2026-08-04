import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
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

  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
      // Note: WebSocket rewrites don't work well in Next.js dev mode
      // Use direct ws://localhost:8000 connection in the app
    ];
  },
  // Re-enable StrictMode after fixing useWebSocket effect cleanup
  reactStrictMode: true,
};

export default nextConfig;
