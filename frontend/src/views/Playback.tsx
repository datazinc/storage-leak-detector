import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
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
import { Card, SeverityBadge } from "../components/Card";
import { DeletePathButton } from "../components/DeletePathButton";
import { PathInspectButton } from "../components/PathInspectButton";
import { ResizableTable } from "../components/ResizableTable";
import { PathPicker } from "../components/PathPicker";
import { toast } from "../components/Toast";

const GROWER_COLS = [
  { key: "rank", label: "#", defaultWidth: 36, minWidth: 30 },
  { key: "path", label: "Path", minWidth: 100 },
  { key: "growth", label: "Growth", defaultWidth: 90, minWidth: 65, align: "right" as const },
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
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      <h2 className="text-xl font-semibold text-white">Playback</h2>

      <Card>
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-xs text-slate-500 block mb-1">
              Path filter (optional)
            </label>
            <PathPicker
              value={pathFilter}
              onChange={setPathFilter}
              placeholder="All paths"
              allowEmpty={true}
              className="min-w-[220px]"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">From</label>
            <select
              className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white min-w-[220px]"
              value={rangeFrom ?? ""}
              onChange={(e) => setRangeFrom(Number(e.target.value) || null)}
            >
              <option value="">
                {snapshots.length === 0
                  ? "No snapshots — take one first"
                  : "Select snapshot"}
              </option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  #{s.id} — {new Date(s.timestamp).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">To</label>
            <select
              className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white min-w-[220px]"
              value={rangeTo ?? ""}
              onChange={(e) => setRangeTo(Number(e.target.value) || null)}
            >
              <option value="">
                {snapshots.length === 0
                  ? "No snapshots — take one first"
                  : "Select snapshot"}
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
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
          >
            {loading ? "Loading..." : "Load Frames"}
          </button>
        </div>
      </Card>

      {frames.length > 0 && (
        <>
          <Card>
            <div className="flex items-center gap-3 mb-4">
              <button
                onClick={() => setFrameIdx(Math.max(0, frameIdx - 1))}
                className="p-2 rounded hover:bg-slate-800 text-slate-400 transition-colors"
              >
                <SkipBack size={18} />
              </button>
              <button
                onClick={() => setPlaying(!playing)}
                className="p-2.5 rounded-full bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >
                {playing ? <Pause size={20} /> : <Play size={20} />}
              </button>
              <button
                onClick={() => {
                  setPlaying(false);
                  setFrameIdx(0);
                }}
                className="p-2 rounded hover:bg-slate-800 text-slate-400 transition-colors"
              >
                <Square size={18} />
              </button>
              <button
                onClick={() =>
                  setFrameIdx(Math.min(frames.length - 1, frameIdx + 1))
                }
                className="p-2 rounded hover:bg-slate-800 text-slate-400 transition-colors"
              >
                <SkipForward size={18} />
              </button>

              <div className="ml-4 flex items-center gap-2">
                <Gauge size={14} className="text-slate-500" />
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpeed(s)}
                    className={`px-2 py-1 text-xs rounded ${
                      speed === s
                        ? "bg-blue-600 text-white"
                        : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                    } transition-colors`}
                  >
                    {s}x
                  </button>
                ))}
              </div>

              <div className="ml-auto text-sm text-slate-400 font-mono">
                Frame {frameIdx + 1} / {frames.length}
              </div>
            </div>

            <input
              type="range"
              min={0}
              max={frames.length - 1}
              value={frameIdx}
              onChange={(e) => {
                setPlaying(false);
                setFrameIdx(Number(e.target.value));
              }}
              className="w-full accent-blue-500"
            />

            {frame && (
              <div className="flex gap-6 mt-3 text-xs text-slate-500">
                <span>
                  Snapshot #{frame.snapshot_id}
                </span>
                <span>
                  {new Date(frame.timestamp).toLocaleString()}
                </span>
                <span>
                  Elapsed: {(frame.elapsed_since_start_seconds / 60).toFixed(0)}m
                </span>
                <span>
                  Total: {formatBytesAbs(frame.total_bytes)}
                </span>
                <span className={frame.total_growth_bytes > 0 ? "text-red-400" : "text-green-400"}>
                  Growth: {formatBytes(frame.total_growth_bytes)}
                </span>
                {frame.anomalies.length > 0 && (
                  <span className="text-amber-400">
                    {frame.anomalies.length} anomalies
                  </span>
                )}
              </div>
            )}
          </Card>

          {frame && (
            <div className="grid grid-cols-3 gap-4">
              <Card className="col-span-2">
                <h3 className="text-sm font-semibold text-white mb-3">
                  Top Growers
                </h3>
                <ResizableTable columns={GROWER_COLS}>
                  <AnimatePresence mode="popLayout">
                    {frame.top_growers.slice(0, 15).map((g, i) => (
                      <motion.tr
                        key={g.path}
                        layout
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.3 }}
                        className="border-t border-slate-800"
                      >
                        <td className="py-2 pr-2 text-slate-600">{i + 1}</td>
                        <td className="py-2 pr-2 font-mono text-xs text-slate-300 truncate" title={g.path}>
                          {g.path}
                        </td>
                        <td
                          className={`py-2 pr-2 text-right font-mono ${
                            g.growth_bytes > 0
                              ? "text-red-400"
                              : g.growth_bytes < 0
                              ? "text-green-400"
                              : "text-slate-500"
                          }`}
                        >
                          {formatBytes(g.growth_bytes)}
                        </td>
                        <td className="py-2 text-right font-mono text-slate-500">
                          {g.growth_pct.toFixed(1)}%
                        </td>
                        <td className="py-2 pl-2 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <PathInspectButton path={g.path} />
                          <DeletePathButton path={g.path} />
                        </td>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </ResizableTable>
              </Card>

              <Card>
                <h3 className="text-sm font-semibold text-white mb-3">
                  Metadata
                </h3>
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-slate-500 text-xs">Snapshot</p>
                    <p className="font-mono text-white">#{frame.snapshot_id}</p>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs">Timestamp</p>
                    <p className="font-mono text-white">
                      {new Date(frame.timestamp).toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs">Total Size</p>
                    <p className="font-mono text-white">
                      {formatBytesAbs(frame.total_bytes)}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs">Growth This Frame</p>
                    <p className="font-mono text-red-400">
                      {formatBytes(frame.total_growth_bytes)}
                    </p>
                  </div>
                  {frame.anomalies.length > 0 && (
                    <div>
                      <p className="text-slate-500 text-xs mb-1">Anomalies</p>
                      {frame.anomalies.map((a, i) => (
                        <div
                          key={i}
                          className="flex items-center gap-2 py-1"
                        >
                          <SeverityBadge severity={a.severity} />
                          <span className="font-mono text-xs text-slate-400 truncate">
                            {a.path}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Card>
            </div>
          )}
        </>
      )}

      {frames.length === 0 && !loading && snapshots.length >= 2 && (
        <Card className="text-center py-12 text-slate-500">
          Select a range and click "Load Frames" to begin playback.
        </Card>
      )}

      {snapshots.length === 0 && (
        <Card className="text-center py-16 px-8">
          <div className="max-w-md mx-auto">
            <div className="p-4 rounded-full bg-slate-800 w-fit mx-auto mb-4">
              <Camera size={32} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">No snapshots yet</h3>
            <p className="text-slate-400 text-sm mb-6">
              Take at least 2 snapshots from the Dashboard to replay disk usage changes over time.
            </p>
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white font-medium transition-colors"
            >
              <LayoutDashboard size={16} />
              Go to Dashboard
            </Link>
          </div>
        </Card>
      )}

      {snapshots.length === 1 && (
        <Card className="text-center py-12 text-slate-500">
          <p className="mb-2">Need at least 2 snapshots for playback.</p>
          <p className="text-sm">Take another snapshot from the Dashboard to compare.</p>
        </Card>
      )}
    </div>
  );
}
