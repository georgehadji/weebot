/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output for Docker: produces .next/standalone/ with server + assets
  output: 'standalone',

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
