// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { DELETE, POST } from "@/app/session/route";

import { keyFrom } from "./upstream";

const withCookie = (cookie: string) => new Request("http://dash/api/me", { headers: { cookie } });

describe("keyFrom", () => {
  it("reads the key cookie and ignores the others", () => {
    expect(keyFrom(withCookie("theme=dark; opspilot_key=ops_a%3Db; x=1"))).toBe("ops_a=b");
    expect(keyFrom(withCookie("theme=dark"))).toBeNull();
    expect(keyFrom(new Request("http://dash/"))).toBeNull();
    expect(keyFrom(withCookie("opspilot_key=%E0%A4%A"))).toBeNull();
  });
});

describe("/session", () => {
  const signIn = (key: unknown, url = "http://dash/session") =>
    POST(new Request(url, { method: "POST", body: JSON.stringify({ key }) }));

  it("checks the key with the agent API, then keeps it in an httpOnly cookie", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ name: "alice", role: "approver", authenticated: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const response = await signIn(" ops_alice-key ", "https://dash/session");
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ name: "alice" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/me$/);
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer ops_alice-key");
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("opspilot_key=ops_alice-key");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Strict");
    expect(cookie).toContain("Secure");
  });

  it("refuses an unknown or empty key without setting a cookie", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "Unknown API key." }, { status: 401 })),
    );
    const unknown = await signIn("wrong");
    expect(unknown.status).toBe(401);
    expect(unknown.headers.get("set-cookie")).toBeNull();
    expect((await signIn("")).status).toBe(400);
    expect((await signIn(42)).status).toBe(400);
  });

  it("forgets the key on sign-out", async () => {
    const response = await DELETE(new Request("http://dash/session", { method: "DELETE" }));
    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });
});
