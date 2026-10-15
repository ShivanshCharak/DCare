"use client";

import { FormEvent, useEffect, useState } from "react";

const API_TOKEN_KEY = "discharge-explainer-api-access-token";

export function ApiAccessToken() {
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const existing = window.sessionStorage.getItem(API_TOKEN_KEY) ?? "";
    setToken(existing);
    setSaved(Boolean(existing));
  }, []);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = token.trim();
    if (trimmed) {
      window.sessionStorage.setItem(API_TOKEN_KEY, trimmed);
      setToken(trimmed);
      setSaved(true);
    } else {
      window.sessionStorage.removeItem(API_TOKEN_KEY);
      setSaved(false);
    }
  }

  function clear() {
    window.sessionStorage.removeItem(API_TOKEN_KEY);
    setToken("");
    setSaved(false);
  }

  return (
    <div className="border-b border-slate-200 bg-slate-50">
      <form
        onSubmit={save}
        className="mx-auto flex max-w-7xl flex-wrap items-end gap-3 px-5 py-3 md:px-10"
      >
        <div className="min-w-64 flex-1">
          <label
            htmlFor="backend-access-token"
            className="mb-1 block text-xs font-semibold text-slate-700"
          >
            Backend access token (optional)
          </label>
          <input
            id="backend-access-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
              setSaved(false);
            }}
            placeholder="Only needed when API_ACCESS_TOKEN is configured"
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          className="rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white"
        >
          Save for this tab
        </button>
        {saved && (
          <button
            type="button"
            onClick={clear}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
          >
            Clear
          </button>
        )}
        <p className="basis-full text-xs text-slate-500">
          The token stays in this browser tab and is sent only to the configured backend.
        </p>
      </form>
    </div>
  );
}
