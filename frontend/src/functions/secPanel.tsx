/** Shared bits of the Phase 6 panels (FA, FIL, OWN, HDS): envelope loading and the title line. The error line is `panelStatus.tsx`. */
import type { ReactNode } from "react";
import type { Envelope } from "../net/types";
import { EnvStatus } from "./panelStatus";

// The shared envelope loader lives in useEnvelope.ts; re-exported here so the SEC panels keep one import line.
export { useEnvelope } from "./useEnvelope";

/** Title line: name, then the shared status tail (source, age/STALE, fallback, `extra`, LOADING) and the panel's key hints. */
export function Header({ title, env, loading, extra, keys }: { title: ReactNode; env: Envelope<unknown> | null; loading: boolean; extra?: ReactNode; keys: string }) {
  return (
    <div className="line">
      <span className="acc">{title}</span>
      <EnvStatus env={env} loading={loading} extra={extra} />
      <span className="dim legend"> · {keys}</span>
    </div>
  );
}

export function openUrl(url: string): void {
  // SEC pages open on sec.gov in a new tab; nothing is scraped or shown here.
  window.open(url, "_blank", "noopener,noreferrer");
}
