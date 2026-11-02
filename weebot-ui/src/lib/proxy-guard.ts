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

// DNS rebinding: a hostile page can make its own domain resolve to 127.0.0.1. The browser then
// treats http://evil.test:3000 as same origin, so isForeignMutation lets it through, and the
// backend we forward to trusts loopback. The Host header gives the page away.
//
// The rule applies only when the backend is local: in a container the UI reaches the API over
// the network bridge, which the API does not trust as loopback, and users arrive by a LAN name.

const LOCAL_NAMES = new Set(["localhost", "127.0.0.1", "::1"]);
const BAD_HOST_CHARS = /[@/?#\s\\]/;

/** The lower-cased host of a Host header or configured name, without port; null if malformed. */
function hostName(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.trim();
  if (!text || BAD_HOST_CHARS.test(text)) return null;
  let host: string;
  if (text.startsWith("[")) {
    const end = text.indexOf("]");
    if (end === -1) return null;
    const rest = text.slice(end + 1);
    if (rest && !/^:\d+$/.test(rest)) return null;
    host = text.slice(1, end);
  } else if ((text.match(/:/g) ?? []).length > 1) {
    return null;
  } else if (text.includes(":")) {
    const [name, port] = text.split(":");
    if (!/^\d+$/.test(port)) return null;
    host = name;
  } else {
    host = text;
  }
  return host.toLowerCase() || null;
}

function backendIsLocal(backendUrl: string): boolean {
  try {
    return LOCAL_NAMES.has(hostName(new URL(backendUrl).host) ?? "");
  } catch {
    return false;
  }
}

/** True when the proxy must refuse: a local backend, and a Host that is not the operator's. */
export function isUntrustedHost(
  hostHeader: string | null | undefined,
  backendUrl: string,
  extraAllowed: string,
): boolean {
  if (!backendIsLocal(backendUrl)) return false;
  const host = hostName(hostHeader);
  if (host === null) return true;
  if (LOCAL_NAMES.has(host)) return false;
  const extra = extraAllowed
    .split(",")
    .map((entry) => hostName(entry))
    .filter((entry): entry is string => entry !== null);
  return !extra.includes(host);
}
