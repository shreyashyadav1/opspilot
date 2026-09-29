import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { SWRConfig } from "swr";
import { vi } from "vitest";

/** Render with a fresh SWR cache, so tests never share fetched data. */
export function renderWithSWR(ui: ReactElement) {
  return render(
    <SWRConfig
      value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}
    >
      {ui}
    </SWRConfig>,
  );
}

type Handler = (init: RequestInit | undefined) => [number, unknown];

/** Stub fetch for `/api/...` paths. Unknown paths answer 404. Returns the mock for assertions. */
export function mockApi(routes: Record<string, Handler | [number, unknown]>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const key = `${init?.method ?? "GET"} ${url}`;
    const route = routes[key] ?? routes[url];
    const [status, body] =
      route === undefined
        ? [404, { detail: `no mock for ${key}` }]
        : typeof route === "function"
          ? route(init)
          : route;
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
