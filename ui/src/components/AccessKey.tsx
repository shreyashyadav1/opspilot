"use client";

import { KeyRound } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";

import { ApiError, api } from "@/lib/api";
import { useMe } from "@/lib/hooks";

import { Button, uiStyles } from "./ui";
import styles from "./AppHeader.module.css";

/**
 * Who is signed in, when the agent API uses keys. Shows a key field when the API answers 401 or
 * lets a caller without a key in with a lower role, the key's name and role once one is saved,
 * and nothing when the API runs open.
 */
export function AccessKey() {
  const ids = useId();
  const { data: me, error } = useMe();
  const { mutate } = useSWRConfig();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // Every cached response was fetched as the previous caller; fetch them all again.
  const refreshAll = () => mutate(() => true);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.signIn(key);
      setKey("");
      await refreshAll();
    } catch (exc) {
      setProblem(exc instanceof ApiError ? exc.message : "The key could not be checked.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await api.signOut();
    await refreshAll();
  }

  if (me?.authenticated) {
    return (
      <div className={styles.access}>
        <KeyRound size={16} aria-hidden="true" className={styles.accessIcon} />
        <span>
          <span className={styles.accessName}>{me.name}</span>{" "}
          <span className={styles.accessRole}>{me.role}</span>
        </span>
        <Button variant="quiet" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    );
  }
  const keyWanted =
    (error instanceof ApiError && error.status === 401) ||
    (me?.authenticated === false && me.keys_enabled === true);
  if (!keyWanted) return null;
  return (
    <form className={styles.access} onSubmit={(event) => void signIn(event)}>
      <label htmlFor={`${ids}-key`} className={styles.accessLabel}>
        API key
      </label>
      <input
        id={`${ids}-key`}
        name="key"
        type="password"
        className={`${uiStyles.input} ${styles.accessInput}`}
        value={key}
        maxLength={256}
        autoComplete="off"
        spellCheck={false}
        required
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? `${ids}-problem` : undefined}
        onChange={(event) => setKey(event.target.value)}
      />
      <Button type="submit" variant="secondary" disabled={busy || !key.trim()}>
        {busy ? "Checking…" : "Sign in"}
      </Button>
      {problem ? (
        <p id={`${ids}-problem`} role="alert" className={styles.accessProblem}>
          {problem}
        </p>
      ) : null}
    </form>
  );
}
