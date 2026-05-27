import type { RunStatus } from "../api/types";

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    queued: "badge-slate",
    running: "badge-yellow",
    passed: "badge-green",
    failed: "badge-red",
    errored: "badge-red",
    cancelled: "badge-slate",
  };
  return <span className={map[status]}>{status}</span>;
}

export function formatRelative(iso: string): string {
  const ts = new Date(iso).getTime();
  const diffMs = Date.now() - ts;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const min = Math.floor(seconds / 60);
  const rem = seconds - min * 60;
  return `${min}m ${rem.toFixed(0)}s`;
}
