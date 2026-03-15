import { useCallback, useEffect, useRef, useState } from "react";
import {
  Play,
  Pause,
  Square,
  SkipBack,
  SkipForward,
  Gauge,
  Camera,
  LayoutDashboard,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  formatBytes,
  formatBytesAbs,
  type Snapshot,
  type PlaybackFrame,
} from "../api";
import { SeverityBadge } from "../components/Card";
import { DeletePathButton } from "../components/DeletePathButton";
import { PathInspectButton } from "../components/PathInspectButton";
import { ResizableTable } from "../components/ResizableTable";
import { PathPicker } from "../components/PathPicker";
import { toast } from "../components/Toast";

const GROWER_COLS = [
  { key: "rank", label: "#", defaultWidth: 36, minWidth: 30 },
  { key: "path", label: "Path", defaultWidth: 160, minWidth: 80 },
  { key: "growth", label: "Change", defaultWidth: 90, minWidth: 65, align: "right" as const },
  { key: "pct", label: "%", defaultWidth: 55, minWidth: 40, align: "right" as const },
  { key: "actions", label: "", defaultWidth: 70, minWidth: 55 },
];

const SPEEDS = [0.25, 0.5, 1, 2, 5, 10];
const BASE_INTERVAL_MS = 1500;

export function Playback() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [frames, setFrames] = useState<PlaybackFrame[]>([]);
  const [frameIdx, setFrameIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loading, setLoading] = useState(false);
  const [rangeFrom, setRangeFrom] = useState<number | null>(null);
  const [rangeTo, setRangeTo] = useState<number | null>(null);
  const [pathFilter, setPathFilter] = useState<string>("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadSnapshots = useCallback(() => {
    api.listSnapshots(1000).then((s) => {
      const sorted = [...s].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
      setSnapshots(sorted);
      setFrames([]);
      setFrameIdx(0);
      if (sorted.length >= 2) {
        // Most recent 5 frames = last 6 snapshots (6 snapshots → 5 diffs)
        const n = Math.min(6, sorted.length);
        const fromIdx = sorted.length - n;
        setRangeFrom(sorted[fromIdx].id ?? null);
        setRangeTo(sorted[sorted.length - 1].id ?? null);
      } else {
        setRangeFrom(null);
        setRangeTo(null);
      }
    }).catch((err) => toast({ type: "error", text: `Failed to load snapshots: ${err?.message ?? err}` }));
  }, []);

  useEffect(() => { loadSnapshots(); }, [loadSnapshots]);

  useEffect(() => {
    window.addEventListener("sldd:db-reset", loadSnapshots);
    return () => window.removeEventListener("sldd:db-reset", loadSnapshots);
  }, [loadSnapshots]);

  const loadFrames = useCallback(async () => {
    if (rangeFrom == null || rangeTo == null) return;
    setLoading(true);
    setPlaying(false);
    setFrameIdx(0);
    try {
      const f = await api.playbackFrames(
        rangeFrom,
        rangeTo,
        20,
        pathFilter.trim() || undefined,
      );
      setFrames(f);
    } catch (err: any) {
      toast({ type: "error", text: `Playback failed: ${err?.message ?? err}` });
    } finally {
      setLoading(false);
    }
  }, [rangeFrom, rangeTo, pathFilter]);

  // Auto-load most recent 5 frames when user navigates to Playback
  useEffect(() => {
    if (rangeFrom != null && rangeTo != null && snapshots.length >= 2) {
      loadFrames();
    }
  }, [rangeFrom, rangeTo, snapshots.length, loadFrames]);

  const tick = useCallback(() => {
    setFrameIdx((prev) => {
      if (prev >= frames.length - 1) {
        setPlaying(false);
        return prev;
      }
      return prev + 1;
    });
  }, [frames.length]);

  useEffect(() => {
    if (playing) {
      timerRef.current = setInterval(tick, BASE_INTERVAL_MS / speed);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing, speed, tick]);

  const frame = frames[frameIdx] ?? null;

  return (
    <div className="p-6 space-y-6 max-w-[1400px] min-w-0">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold tracking-tight text-white">Playback</h2>
        <p className="text-sm text-slate-500">Replay disk usage changes over time</p>
      </div>

      {/* Range selector — compact inline */}
      <div className="flex flex-wrap items-end gap-4 p-4 rounded-xl bg-slate-900/80 border border-slate-800/80">
        <div className="flex-1 min-w-[200px]">
          <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block mb-2">
            Path filter
          </label>
          <PathPicker
            value={pathFilter}
            onChange={setPathFilter}
            placeholder="All paths"
            allowEmpty={true}
            className="min-w-full bg-slate-800/60 border-slate-700/80 rounded-lg"
          />
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block mb-2">From</label>
            <select
              className="bg-slate-800/60 border border-slate-700/80 rounded-lg px-3 py-2.5 text-sm text-white min-w-[200px] focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 outline-none transition-all"
              value={rangeFrom ?? ""}
              onChange={(e) => setRangeFrom(Number(e.target.value) || null)}
            >
              <option value="">
                {snapshots.length === 0 ? "No snapshots" : "Select snapshot"}
              </option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  #{s.id} — {new Date(s.timestamp).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block mb-2">To</label>
            <select
              className="bg-slate-800/60 border border-slate-700/80 rounded-lg px-3 py-2.5 text-sm text-white min-w-[200px] focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 outline-none transition-all"
              value={rangeTo ?? ""}
              onChange={(e) => setRangeTo(Number(e.target.value) || null)}
            >
              <option value="">
                {snapshots.length === 0 ? "No snapshots" : "Select snapshot"}
              </option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  #{s.id} — {new Date(s.timestamp).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={loadFrames}
            disabled={loading || snapshots.length < 2}
            className="px-5 py-2.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-all hover:shadow-lg hover:shadow-blue-500/20"
          >
            {loading ? "Loading…" : "Load Frames"}
          </button>
        </div>
      </div>

      {frames.length > 0 && (
        <>
          {/* Transport + timeline */}
          <div className="rounded-xl bg-slate-900/80 border border-slate-800/80 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <div className="flex items-center rounded-lg bg-slate-800/60 p-1 border border-slate-700/60">
                <button
                  onClick={() => setFrameIdx(Math.max(0, frameIdx - 1))}
                  className="p-2 rounded-md hover:bg-slate-700/80 text-slate-400 hover:text-white transition-colors"
                  title="Previous frame"
                >
                  <SkipBack size={18} />
                </button>
                <button
                  onClick={() => setPlaying(!playing)}
                  className="p-2.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-all mx-0.5"
                  title={playing ? "Pause" : "Play"}
                >
                  {playing ? <Pause size={20} /> : <Play size={20} />}
                </button>
                <button
                  onClick={() => { setPlaying(false); setFrameIdx(0); }}
                  className="p-2 rounded-md hover:bg-slate-700/80 text-slate-400 hover:text-white transition-colors"
                  title="Reset"
                >
                  <Square size={16} />
                </button>
                <button
                  onClick={() => setFrameIdx(Math.min(frames.length - 1, frameIdx + 1))}
                  className="p-2 rounded-md hover:bg-slate-700/80 text-slate-400 hover:text-white transition-colors"
                  title="Next frame"
                >
                  <SkipForward size={18} />
                </button>
              </div>

              <div className="flex items-center gap-1.5 ml-2 px-2 py-1 rounded-md bg-slate-800/40 border border-slate-700/40">
                <Gauge size={13} className="text-slate-500" />
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpeed(s)}
                    className={`px-2.5 py-1 text-xs font-medium rounded ${
                      speed === s
                        ? "bg-blue-600 text-white"
                        : "text-slate-400 hover:text-white hover:bg-slate-700/60"
                    } transition-colors`}
                  >
                    {s}×
                  </button>
                ))}
              </div>

              <div className="ml-auto text-sm font-mono text-slate-400 tabular-nums">
                {frameIdx + 1} / {frames.length}
              </div>
            </div>

            <div className="relative space-y-1">
              {/* Tick marks at each frame position */}
              {frames.length > 1 && (
                <div className="relative h-2 w-full pointer-events-none" aria-hidden>
                  {frames.map((_, i) => (
                    <div
                      key={i}
                      className="absolute w-px h-2 bg-slate-600"
                      style={{
                        left: `${(i / Math.max(1, frames.length - 1)) * 100}%`,
                        top: 0,
                        transform: "translateX(-50%)",
                      }}
                    />
                  ))}
                </div>
              )}
              <input
                type="range"
                min={0}
                max={Math.max(0, frames.length - 1)}
                value={frameIdx}
                onChange={(e) => {
                  setPlaying(false);
                  setFrameIdx(Number(e.target.value));
                }}
                className="playback-slider w-full h-4 cursor-pointer"
              />
            </div>

            {frame && (
              <div className="flex flex-wrap gap-2 pt-1">
                <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-slate-800/60 text-xs font-mono text-slate-400">
                  #{frame.snapshot_id}
                </span>
                <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-slate-800/60 text-xs text-slate-400">
                  {new Date(frame.timestamp).toLocaleString()}
                </span>
                <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-slate-800/60 text-xs text-slate-400">
                  {(frame.elapsed_since_start_seconds / 60).toFixed(0)}m elapsed
                </span>
                <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-slate-800/60 text-xs font-mono text-slate-300">
                  {formatBytesAbs(frame.total_bytes)}
                </span>
                <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium ${
                  frame.total_growth_bytes > 0 ? "bg-red-500/15 text-red-400" : "bg-emerald-500/15 text-emerald-400"
                }`}>
                  {formatBytes(frame.total_growth_bytes)}
                </span>
                {frame.anomalies.length > 0 && (
                  <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-amber-500/15 text-amber-400 text-xs font-medium">
                    {frame.anomalies.length} anomalies
                  </span>
                )}
              </div>
            )}
          </div>

          {frame && (
            <div className="grid grid-cols-3 gap-5">
              <div className="col-span-2 rounded-xl bg-slate-900/80 border border-slate-800/80 overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-800/80">
                  <h3 className="text-sm font-semibold text-white">Top Growers</h3>
                </div>
                <ResizableTable columns={GROWER_COLS}>
                  {frame.top_growers.slice(0, 15).map((g, i) => (
                    <tr key={g.path} className="border-t border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                      <td className="py-2.5 pr-3 text-slate-500 text-sm">{i + 1}</td>
                      <td className="py-2.5 pr-3 font-mono text-sm text-slate-300 truncate" title={g.path}>
                        {g.path}
                      </td>
                      <td
                        className={`py-2.5 pr-3 text-right font-mono text-sm ${
                          g.growth_bytes > 0 ? "text-red-400" : g.growth_bytes < 0 ? "text-emerald-400" : "text-slate-500"
                        }`}
                      >
                        {formatBytes(g.growth_bytes)}
                      </td>
                      <td className="py-2.5 pr-3 text-right font-mono text-slate-500 text-sm">
                        {g.growth_pct.toFixed(1)}%
                      </td>
                      <td className="py-2.5 pl-3 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <PathInspectButton path={g.path} />
                        <DeletePathButton path={g.path} />
                      </td>
                    </tr>
                  ))}
                </ResizableTable>
              </div>

              <div className="rounded-xl bg-slate-900/80 border border-slate-800/80 p-5">
                <h3 className="text-sm font-semibold text-white mb-4">Frame Details</h3>
                <div className="space-y-4">
                  <div className="p-3 rounded-lg bg-slate-800/40">
                    <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1">Snapshot</p>
                    <p className="font-mono text-white">#{frame.snapshot_id}</p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-800/40">
                    <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1">Timestamp</p>
                    <p className="text-sm text-slate-200">
                      {new Date(frame.timestamp).toLocaleString()}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-800/40">
                    <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1">Total Size</p>
                    <p className="font-mono text-lg text-white">
                      {formatBytesAbs(frame.total_bytes)}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-800/40">
                    <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1">Change</p>
                    <p className={`font-mono text-lg font-medium ${frame.total_growth_bytes > 0 ? "text-red-400" : "text-emerald-400"}`}>
                      {formatBytes(frame.total_growth_bytes)}
                    </p>
                  </div>
                  {frame.anomalies.length > 0 && (
                    <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
                      <p className="text-[11px] font-medium text-amber-400 uppercase tracking-wider mb-2">
                        {frame.anomalies.length} Anomalies
                      </p>
                      <div className="space-y-1.5 max-h-32 overflow-auto">
                        {frame.anomalies.map((a, i) => (
                          <div key={i} className="flex items-center gap-2">
                            <SeverityBadge severity={a.severity} />
                            <span className="font-mono text-xs text-slate-400 truncate flex-1 min-w-0">
                              {a.path}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {frames.length === 0 && !loading && snapshots.length >= 2 && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/60 border-dashed py-16 text-center">
          <p className="text-slate-500 mb-1">Select a range and click Load Frames to begin</p>
          <p className="text-slate-600 text-sm">Compare snapshots over time</p>
        </div>
      )}

      {snapshots.length === 0 && (
        <div className="rounded-xl bg-slate-900/80 border border-slate-800/80 py-20 px-8 text-center">
          <div className="max-w-sm mx-auto">
            <div className="w-16 h-16 rounded-2xl bg-slate-800/80 flex items-center justify-center mx-auto mb-5">
              <Camera size={28} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">No snapshots yet</h3>
            <p className="text-slate-400 text-sm mb-6 leading-relaxed">
              Take at least 2 snapshots from the Dashboard to replay disk usage changes over time.
            </p>
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-all hover:shadow-lg hover:shadow-blue-500/20"
            >
              <LayoutDashboard size={16} />
              Go to Dashboard
            </Link>
          </div>
        </div>
      )}

      {snapshots.length === 1 && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/60 py-12 text-center">
          <p className="text-slate-500 mb-1">Need at least 2 snapshots for playback</p>
          <p className="text-slate-600 text-sm">Take another snapshot from the Dashboard to compare</p>
        </div>
      )}
    </div>
  );
}
