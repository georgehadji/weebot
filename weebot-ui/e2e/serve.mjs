// Builds the app into its own directory (so a running `next dev` is left alone) and serves it.
// Used by playwright.config.ts; run by hand with `node e2e/serve.mjs` to debug the same server.
import { execFileSync, spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const next = require.resolve("next/dist/bin/next");
const port = process.env.E2E_PORT || "3100";
const env = { ...process.env, NEXT_DIST_DIR: ".next-e2e" };

execFileSync(process.execPath, [next, "build"], { stdio: "inherit", env });

const server = spawn(process.execPath, [next, "start", "-H", "127.0.0.1", "-p", port], { stdio: "inherit", env });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
