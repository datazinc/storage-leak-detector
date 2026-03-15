const BASE = "/api";

type ConnectionListener = (connected: boolean) => void;
const _connListeners = new Set<ConnectionListener>();
let _lastConnected = true;

export function onConnectionChange(fn: ConnectionListener) {
  _connListeners.add(fn);
  return () => { _connListeners.delete(fn); };
}

function _setConnected(v: boolean) {
  if (v !== _lastConnected) {
    _lastConnected = v;
    _connListeners.forEach((fn) => fn(v));
  }
}

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch {
    _setConnected(false);
    throw new Error(`Network error: backend unreachable (${path})`);
  }
  _setConnected(true);
  if (!r.ok) {
    const body = await r.text();
    let msg: string;
    try {
      const json = JSON.parse(body) as Record<string, unknown>;
      msg = (json.error ?? json.detail ?? body) as string;
      if (json.error === "database_corrupted") {
        window.dispatchEvent(new CustomEvent("sldd:db-corrupted", {
          detail: { recovered: json.recovered === true, detail: String(json.detail ?? msg) },
        }));
      } else if (String(msg).toLowerCase().includes("malformed")) {
        window.dispatchEvent(new CustomEvent("sldd:db-corrupted", {
          detail: { recovered: false, detail: msg },
        }));
      }
    } catch {
      msg = body || `Request failed (${r.status})`;
      if (msg.toLowerCase().includes("malformed")) {
        window.dispatchEvent(new CustomEvent("sldd:db-corrupted", {
          detail: { recovered: false, detail: msg },
        }));
      }
    }
    throw new Error(msg);
  }
  return r.json();
}

export interface Snapshot {
  id: number;
  timestamp: string;
  root_path: string;
  label: string;
}

export interface DirEntry {
  path: string;
  total_bytes: number;
  file_count: number;
  dir_count: number;
  depth: number;
  error: string | null;
}

export interface DirDiff {
  path: string;
  bytes_before: number;
  bytes_after: number;
  growth_bytes: number;
  growth_pct: number;
  files_before: number;
  files_after: number;
  files_delta: number;
  depth: number;
}

export interface Anomaly {
  path: string;
  severity: "info" | "warning" | "critical";
  rule: string;
  message: string;
  growth_bytes: number;
  growth_rate_bytes_per_hour: number;
  attributed_path: string;
}

export interface ReportData {
  generated_at: string;
  snapshot_old: Snapshot;
  snapshot_new: Snapshot;
  elapsed_seconds: number;
  total_growth_bytes: number;
  total_growth_human: string;
  anomalies: Array<{
    path: string;
    severity: string;
    rule: string;
    message: string;
    growth_bytes: number;
    growth_rate_bytes_per_hour: number;
    growth_human: string;
    rate_human: string;
    attributed_path: string;
    sldd_db_bytes?: number;
    sldd_db_human?: string;
  }>;
  top_growers: Array<{
    path: string;
    bytes_before: number;
    bytes_after: number;
    growth_bytes: number;
    growth_pct: number;
    growth_human: string;
    rate_human: string;
    rate_bytes_per_hour: number;
    files_before: number;
    files_after: number;
    files_delta: number;
    depth: number;
  }>;
  top_shrinkers?: Array<{
    path: string;
    bytes_before: number;
    bytes_after: number;
    growth_bytes: number;
    growth_pct: number;
    growth_human: string;
    rate_human: string;
    rate_bytes_per_hour: number;
    files_before: number;
    files_after: number;
    files_delta: number;
    depth: number;
  }>;
  _meta?: { depth: number; matching_snapshots: number };
}

export interface PlaybackFrame {
  frame_index: number;
  snapshot_id: number;
  timestamp: string;
  elapsed_since_start_seconds: number;
  top_growers: DirDiff[];
  anomalies: Anomaly[];
  total_bytes: number;
  total_growth_bytes: number;
}

export interface LargeFile {
  path: string;
  size_bytes: number;
  size_human: string;
  directory: string;
  name: string;
  mtime: string | null;
}

export interface ScanJobStatus {
  id: string;
  kind: string;
  phase: string;
  current_path: string;
  dirs_scanned: number;
  files_checked: number;
  detail: string;
  done: boolean;
  error: string | null;
  elapsed_seconds: number;
}

export interface DuplicateFile {
  path: string;
  name: string;
  directory: string;
  mtime: string | null;
}

export interface DuplicateGroup {
  hash: string;
  size_bytes: number;
  size_human: string;
  count: number;
  wasted_bytes: number;
  wasted_human: string;
  files: DuplicateFile[];
}

export interface DuplicatesResult {
  groups: DuplicateGroup[];
  total_groups: number;
  total_duplicate_files: number;
  total_wasted_bytes: number;
  total_wasted_human: string;
}

export interface DeleteTarget {
  path: string;
  exists: boolean;
  is_dir: boolean;
  size_bytes: number;
  file_count: number;
  writable: boolean;
  error: string | null;
}

export interface DeletePreview {
  targets: DeleteTarget[];
  total_bytes: number;
  total_files: number;
  all_writable: boolean;
  blocked_paths: string[];
}

export interface DeleteResult {
  succeeded: string[];
  failed: [string, string][];
  bytes_freed: number;
  dry_run: boolean;
}

export interface DeletionLog {
  id: number;
  timestamp: string;
  path: string;
  bytes_freed: number;
  was_dir: boolean;
  success: boolean;
  error: string | null;
}

export interface DbInfo {
  path: string;
  size_bytes: number;
  snapshot_count: number;
}

export interface ScanProgress {
  current_path: string;
  dirs_scanned: number;
}

export interface WatchStatus {
  running: boolean;
  interval_seconds: number;
  scanning: boolean;
  scans_completed: number;
  last_scan_at: string | null;
  next_scan_at: string | null;
  last_error: string | null;
  last_plan: any;
  progress?: ScanProgress;
}

export interface WatchEvent {
  seq: number;
  time: string;
  kind: string;
  detail: string;
}

export interface AdaptiveStats {
  scan_number: number;
  baseline_snapshot_id: number | null;
  total_tracked_paths: number;
  active_paths: number;
  stable_paths: number;
  focus_paths: number;
  total_entries: number;
}

export interface AdaptivePlan {
  strategy: string;
  scan_depth: number | null;
  focus_paths: string[];
  skip_paths: string[];
  scan_number: number;
  reason: string;
}

export interface CompactResult {
  entries_removed: number;
  bytes_saved_estimate: number;
  paths_collapsed: number;
  snapshots_pruned: number;
}

export interface TrackedPath {
  path: string;
  status: string;
  last_bytes: number;
  last_file_count: number;
  depth: number;
  consecutive_stable: number;
  last_growth_bytes: number;
  updated_at: string;
}

export interface ProcessIOInfo {
  pid: number;
  process_name: string;
  read_bytes: number;
  write_bytes: number;
  open_files_under_path: number;
  cmdline?: string | null;
  username?: string | null;
}

export interface PathIOOffender {
  pid: number;
  process_name: string;
  write_bytes: number;
  cmdline?: string | null;
  username?: string | null;
}

export interface PathIOHistoryEntry {
  timestamp: string;
  pid: number;
  process_name: string;
  read_bytes_delta: number;
  write_bytes_delta: number;
}

export interface PathIOWatchStatus {
  path: string;
  started_at: string;
  duration_minutes: number;
  sample_interval_sec: number;
}

export interface PathIOSummary {
  path: string;
  last_timestamp: string;
  sample_count: number;
}

export const api = {
  listSnapshots: (limit = 50, depth?: number) =>
    request<Snapshot[]>(`/snapshots?limit=${limit}${depth != null ? `&depth=${depth}` : ""}`),
  snapshotDepths: () =>
    request<Array<{ depth: number; count: number }>>("/snapshots/depths"),
  createSnapshot: (label = "") =>
    request<Snapshot>("/snapshots", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),
  deleteSnapshot: (id: number) =>
    request<{ ok: boolean }>(`/snapshots/${id}`, { method: "DELETE" }),
  pruneSnapshots: (keep: number) =>
    request<{ deleted: number }>("/snapshots/prune", {
      method: "POST",
      body: JSON.stringify({ keep }),
    }),
  getReport: (oldId?: number, newId?: number, topN = 20, depth?: number) =>
    request<ReportData>(
      depth != null
        ? `/report?depth=${depth}&top_n=${topN}`
        : `/report?old=${oldId}&new=${newId}&top_n=${topN}`,
    ),
  diffLatest: () => request<any>("/diff/latest"),
  drill: (snapId: number, path: string) =>
    request<DirEntry[]>(`/drill/${snapId}?path=${encodeURIComponent(path)}`),
  pathHistory: (path: string, limit = 50) =>
    request<Array<{ snapshot_id: number; timestamp: string; total_bytes: number; file_count: number }>>(
      `/history?path=${encodeURIComponent(path)}&limit=${limit}`
    ),
  topDirs: (snapId: number, limit = 20) =>
    request<DirEntry[]>(`/top/${snapId}?limit=${limit}`),
  playbackFrames: (from: number, to: number, topN = 20, pathFilter?: string) => {
    const params = new URLSearchParams({ from: String(from), to: String(to), top_n: String(topN) });
    if (pathFilter?.trim()) params.set("path", pathFilter.trim());
    return request<PlaybackFrame[]>(`/playback/frames?${params}`);
  },
  playbackPathTimeline: (path: string, from: number, to: number) =>
    request<Array<{ snapshot_id: number; timestamp: string; total_bytes: number; file_count: number }>>(
      `/playback/path-timeline?path=${encodeURIComponent(path)}&from=${from}&to=${to}`
    ),
  deletePreview: (paths: string[], force = false) =>
    request<DeletePreview>("/delete/preview", {
      method: "POST",
      body: JSON.stringify({ paths, force }),
    }),
  deleteExecute: (paths: string[], dryRun = false, force = false) =>
    request<DeleteResult>("/delete/execute", {
      method: "POST",
      body: JSON.stringify({ paths, confirm: true, dry_run: dryRun, force }),
    }),
  deletionHistory: (limit = 100) =>
    request<DeletionLog[]>(`/delete/history?limit=${limit}`),
  getSettings: () => request<Record<string, string>>("/settings"),
  saveSettings: (settings: Record<string, string>) =>
    request<{ ok: boolean }>("/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    }),
  dbInfo: () => request<DbInfo>("/db-info"),
  vacuum: () => request<{ ok: boolean }>("/db/vacuum", { method: "POST" }),

  watchStatus: () => request<WatchStatus>("/watch/status"),
  watchStart: (intervalSeconds = 300, oneShot = false) =>
    request<WatchStatus>("/watch/start", {
      method: "POST",
      body: JSON.stringify({
        interval_seconds: intervalSeconds,
        one_shot: oneShot,
      }),
    }),
  watchStop: () =>
    request<WatchStatus>("/watch/stop", { method: "POST" }),
  watchEvents: (after = 0) =>
    request<WatchEvent[]>(`/watch/events?after=${after}`),
  watchReport: () => request<ReportData>("/watch/report"),

  largestFiles: (limit = 50) =>
    request<LargeFile[]>(`/files/largest?limit=${limit}`),

  startLargestScan: (limit = 100, maxDepth = 6, root?: string) => {
    const params = new URLSearchParams({ limit: String(limit), max_depth: String(maxDepth) });
    if (root?.trim()) params.set("root", root.trim());
    return request<ScanJobStatus>(`/scan/largest?${params}`, { method: "POST" });
  },
  startDuplicatesScan: (minSize = 1024, maxDepth = 6, root?: string) => {
    const params = new URLSearchParams({ min_size: String(minSize), max_depth: String(maxDepth) });
    if (root?.trim()) params.set("root", root.trim());
    return request<ScanJobStatus>(`/scan/duplicates?${params}`, { method: "POST" });
  },
  scanStatus: (jobId: string) =>
    request<ScanJobStatus>(`/scan/${jobId}/status`),
  scanStop: (jobId: string) =>
    request<ScanJobStatus>(`/scan/${jobId}/stop`, { method: "POST" }),
  scanResult: <T = any>(jobId: string) =>
    request<T>(`/scan/${jobId}/result`),

  dbSizeLive: () => request<{ total_bytes: number; total_human: string }>("/db/size"),
  resetDb: () => request<{ ok: boolean }>("/db/reset", { method: "POST" }),

  adaptiveStats: () => request<AdaptiveStats>("/adaptive/stats"),
  adaptivePlan: () => request<AdaptivePlan>("/adaptive/plan"),
  adaptiveCompact: () => request<CompactResult>("/adaptive/compact", { method: "POST" }),
  adaptiveReset: () => request<{ ok: boolean }>("/adaptive/reset", { method: "POST" }),
  adaptivePaths: (status?: string, limit = 200) =>
    request<TrackedPath[]>(
      `/adaptive/paths?limit=${limit}${status ? `&status=${status}` : ""}`,
    ),

  pathIoNow: (path: string) =>
    request<ProcessIOInfo[]>(`/path/io?path=${encodeURIComponent(path)}`),
  pathIoOffenders: (paths: string[]) =>
    request<Record<string, PathIOOffender | null>>("/path/io/offenders", {
      method: "POST",
      body: JSON.stringify({ paths }),
    }),
  pathIoHistory: (path: string, limit = 100) =>
    request<PathIOHistoryEntry[]>(
      `/path/io/history?path=${encodeURIComponent(path)}&limit=${limit}`
    ),
  pathIoWatchStart: (path: string, durationMinutes = 10, sampleIntervalSec = 60) =>
    request<{ ok: boolean }>("/path/io/watch", {
      method: "POST",
      body: JSON.stringify({
        path,
        duration_minutes: durationMinutes,
        sample_interval_sec: sampleIntervalSec,
      }),
    }),
  pathIoWatchStop: (path: string) =>
    request<{ ok: boolean }>(
      `/path/io/watch?path=${encodeURIComponent(path)}`,
      { method: "DELETE" }
    ),
  pathIoWatchStatus: () =>
    request<PathIOWatchStatus[]>("/path/io/watch"),
  pathIoSummary: (limit = 50) =>
    request<PathIOSummary[]>(`/path/io/summary?limit=${limit}`),
  pathOpen: (path: string) =>
    request<{ ok: boolean }>("/path/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
};

export function formatBytes(n: number): string {
  const sign = n < 0 ? "-" : n > 0 ? "+" : "";
  const abs = Math.abs(n);
  if (abs >= 1024 ** 3) return `${sign}${(abs / 1024 ** 3).toFixed(2)} GB`;
  if (abs >= 1024 ** 2) return `${sign}${(abs / 1024 ** 2).toFixed(1)} MB`;
  if (abs >= 1024) return `${sign}${(abs / 1024).toFixed(1)} KB`;
  return `${sign}${abs} B`;
}

export function formatBytesAbs(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}
