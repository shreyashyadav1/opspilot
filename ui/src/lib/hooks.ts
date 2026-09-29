"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import useSWR from "swr";

import { ApiError, api, eventsUrl } from "./api";
import { TERMINAL_STATUSES, type InvestigationDetail } from "./types";

export function useConfig() {
  return useSWR("config", api.config, { revalidateOnFocus: false, shouldRetryOnError: false });
}

export function useInvestigations() {
  return useSWR("investigations", api.investigations, { refreshInterval: 2500 });
}

export function useBenchmarks() {
  return useSWR("benchmarks", api.benchmarks, { revalidateOnFocus: false });
}

export function useBenchmark(runId: string) {
  return useSWR(["benchmark", runId], () => api.benchmark(runId), { revalidateOnFocus: false });
}

const POLL_MS = 2000;

/**
 * One investigation, kept current. Uses the API's Server-Sent Events stream and falls back to
 * polling when EventSource is unavailable or the stream cannot be opened.
 */
export function useInvestigation(investigationId: string) {
  const [data, setData] = useState<InvestigationDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [live, setLive] = useState(false);
  const done = useRef(false);

  const accept = useCallback((detail: InvestigationDetail) => {
    done.current = TERMINAL_STATUSES.has(detail.status);
    setData(detail);
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      accept(await api.investigation(investigationId));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc : new ApiError(0, String(exc)));
    }
  }, [accept, investigationId]);

  useEffect(() => {
    done.current = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = () => {
      void refresh();
      timer = setInterval(() => {
        if (done.current) {
          if (timer) clearInterval(timer);
          return;
        }
        void refresh();
      }, POLL_MS);
    };

    if (typeof EventSource === "undefined") {
      poll();
    } else {
      source = new EventSource(eventsUrl(investigationId));
      source.addEventListener("snapshot", (event) => {
        setLive(true);
        accept(JSON.parse((event as MessageEvent<string>).data) as InvestigationDetail);
      });
      source.addEventListener("end", () => {
        source?.close();
        setLive(false);
      });
      source.onerror = () => {
        setLive(false);
        // A refused stream (for example a 404) closes for good; transient drops reconnect.
        if (source?.readyState === EventSource.CLOSED && !done.current) {
          source = null;
          poll();
        }
      };
    }
    return () => {
      source?.close();
      if (timer) clearInterval(timer);
    };
  }, [accept, investigationId, refresh]);

  return { data, error, live, accept, refresh };
}

function subscribeToStorage(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/** A value from localStorage, for per-browser conveniences such as the reviewer name. */
export function useStoredValue(key: string, fallback: string) {
  const read = useCallback(() => {
    try {
      return window.localStorage.getItem(key);
    } catch {
      // Storage can be unavailable (private windows, blocked site data).
      return null;
    }
  }, [key]);
  const stored = useSyncExternalStore(subscribeToStorage, read, () => null);
  const [draft, setDraft] = useState<string | null>(null);
  const update = useCallback(
    (next: string) => {
      setDraft(next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // Not persisted; the value still applies to this page.
      }
    },
    [key],
  );
  return [draft ?? stored ?? fallback, update] as const;
}
