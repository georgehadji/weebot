// The /api proxy forwards to a backend that trusts loopback callers. Without a check, any
// web page the user visits could POST to http://localhost:3000/api/... and ride that trust
// (cross-site request forgery). This is the Fetch Metadata "resource isolation" policy:
// a state-changing request must come from this origin.

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function isForeignMutation(
  method: string,
  headers: Pick<Headers, "get">,
  requestHost: string,
): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) return false;

  const site = headers.get("sec-fetch-site");
  if (site) return site !== "same-origin";

  // No Fetch Metadata (old browser or a non-browser client): fall back to Origin.
  const origin = headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host !== requestHost;
  } catch {
    return true;
  }
}
