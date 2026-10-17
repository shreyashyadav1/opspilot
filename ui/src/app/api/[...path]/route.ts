// Proxies /api/* to the agent API, so the browser only ever talks to this origin: no CORS, and
// the upstream address is a runtime setting (OPSPILOT_API_URL) rather than a build-time one.
// Server-Sent Events pass through as a stream. A key saved with POST /session (an httpOnly
// cookie) is sent upstream as a bearer header; cookies themselves are never forwarded.

import { keyFrom, upstreamBase } from "@/lib/upstream";

export const dynamic = "force-dynamic";

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "last-event-id"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "cache-control", "retry-after"];

async function proxy(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params;
  if (path.some((segment) => segment === "." || segment === ".." || segment === "")) {
    return Response.json({ detail: "Invalid API path." }, { status: 400 });
  }
  const base = upstreamBase();
  const url = new URL(request.url);
  const target = `${base}/${path.map(encodeURIComponent).join("/")}${url.search}`;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const key = keyFrom(request);
  if (key) headers.set("authorization", `Bearer ${key}`);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch {
    return Response.json(
      { detail: `The agent API is not reachable at ${base}. Is it running?` },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  if (upstream.headers.get("content-type")?.startsWith("text/event-stream")) {
    // no-transform keeps response compression from buffering the stream.
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as DELETE, proxy as GET, proxy as POST };
