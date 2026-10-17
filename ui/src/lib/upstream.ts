// Server-side helpers shared by the route handlers that talk to the agent API.

/** The cookie holding the operator's API key. httpOnly, so page scripts never see the key. */
export const KEY_COOKIE = "opspilot_key";

export function upstreamBase(): string {
  return (process.env.OPSPILOT_API_URL ?? "http://127.0.0.1:8180").replace(/\/+$/, "");
}

/** The API key from the request's cookie, if one was saved with POST /session. */
export function keyFrom(request: Request): string | null {
  const cookies = request.headers.get("cookie") ?? "";
  for (const part of cookies.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === KEY_COOKIE && rest.length) {
      try {
        return decodeURIComponent(rest.join("=")) || null;
      } catch {
        return null;
      }
    }
  }
  return null;
}
