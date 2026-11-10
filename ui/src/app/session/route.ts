// Saves or forgets the operator's API key. The key is checked against the agent API's /me
// first, then kept in an httpOnly cookie that the /api proxy turns into a bearer header, so it
// also reaches Server-Sent Events streams (EventSource cannot send headers).

import { KEY_COOKIE, upstreamBase } from "@/lib/upstream";

export const dynamic = "force-dynamic";

const MAX_AGE_S = 12 * 60 * 60;

function cookie(request: Request, value: string, maxAge: number): string {
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `${KEY_COOKIE}=${encodeURIComponent(value)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secure}`;
}

export async function POST(request: Request): Promise<Response> {
  const body: unknown = await request.json().catch(() => null);
  const key =
    body && typeof body === "object" && "key" in body && typeof body.key === "string"
      ? body.key.trim()
      : "";
  if (!key || key.length > 256) {
    return Response.json({ detail: "Enter an API key." }, { status: 400 });
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${upstreamBase()}/me`, {
      headers: { accept: "application/json", authorization: `Bearer ${key}` },
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: `The agent API is not reachable at ${upstreamBase()}. Is it running?` },
      { status: 502 },
    );
  }
  const me: unknown = await upstream.json().catch(() => null);
  if (upstream.status === 401) {
    return Response.json({ detail: "The agent API does not know this key." }, { status: 401 });
  }
  if (!upstream.ok) {
    return Response.json(me ?? { detail: "The key could not be checked." }, {
      status: upstream.status,
    });
  }
  return Response.json(me, { headers: { "set-cookie": cookie(request, key, MAX_AGE_S) } });
}

export async function DELETE(request: Request): Promise<Response> {
  return new Response(null, {
    status: 204,
    headers: { "set-cookie": cookie(request, "", 0) },
  });
}
