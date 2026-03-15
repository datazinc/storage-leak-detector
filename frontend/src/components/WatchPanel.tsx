import { useCallback, useEffect, useRef, useState } from "react";
import {
  Play,
  Square,
  Radio,
  AlertTriangle,
  CheckCircle,
  Clock,
  Loader2,
  Zap,
  FolderSearch,
  Timer,
} from "lucide-react";
import { api, type WatchStatus, type WatchEvent } from "../api";
import { toast } from "./Toast";

interface Props {
  onNewData: () => void;
}

function useCountdown(targetIso: string | null | undefined): string {
  const [text, setText] = useState("");
  useEffect(() => {
    if (!targetIso) {
      setText("");
      return;
    }
    const tick = () => {
      const diff = Math.max(0, Math.floor((new Date(targetIso).getTime() - Date.now()) / 1000));
      if (diff <= 0) {
        setText("now");
      } else {
        const m = Math.floor(diff / 60);
        const s = diff % 60;
        setText(m > 0 ? `${m}m ${s}s` : `${s}s`);
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetIso]);
  return text;
}

export function WatchPanel({ onNewData }: Props) {
  const [status, setStatus] = useState<WatchStatus | null>(null);
  const [events, setEvents] = useState<WatchEvent[]>([]);
  const [interval, setInterval_] = useState(300);
  const [starting, setStarting] = useState(false);
  const lastSeq = useRef(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const countdown = useCountdown(
    status?.running && !status.scanning ? status.next_scan_at : null
  );

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.watchStatus();
      setStatus(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const evts = await api.watchEvents(lastSeq.current);
      if (evts.length > 0) {
        lastSeq.current = evts[evts.length - 1].seq;
        setEvents((prev) => [...prev, ...evts].slice(-50));
        const hasScan = evts.some((e) => e.kind === "scan_complete");
        if (hasScan) onNewData();
      }
    } catch { /* noop */ }
  }, [onNewData]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    const onReset = () => {
      setEvents([]);
      lastSeq.current = 0;
      fetchStatus();
    };
    const onWatchChanged = () => fetchStatus();
    window.addEventListener("sldd:db-reset", onReset);
    window.addEventListener("sldd:watch-changed", onWatchChanged);
    return () => {
      window.removeEventListener("sldd:db-reset", onReset);
      window.removeEventListener("sldd:watch-changed", onWatchChanged);
    };
  }, [fetchStatus]);

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (status?.running) {
      const ms = status.scanning ? 800 : 3000;
      pollRef.current = setInterval(() => {
        fetchStatus();
        fetchEvents();
      }, ms);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status?.running, status?.scanning, fetchStatus, fetchEvents]);

  const doStart = async () => {
    setStarting(true);
    try {
      const s = await api.watchStart(interval);
      setStatus(s);
      toast({ type: "success", text: `Watch started (every ${interval}s)` });
    } catch (err: any) {
      toast({ type: "error", text: `Start failed: ${err?.message ?? err}` });
    } finally {
      setStarting(false);
    }
  };

  const doStop = async () => {
    try {
      const s = await api.watchStop();
      setStatus(s);
      toast({ type: "info", text: "Watch stopped" });
    } catch (err: any) {
      toast({ type: "error", text: `Stop failed: ${err?.message ?? err}` });
    }
  };

  const isRunning = status?.running ?? false;
  const progress = status?.progress;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isRunning ? (
            <Radio size={14} className="text-green-400 animate-pulse" />
          ) : (
            <Radio size={14} className="text-slate-600" />
          )}
          <span className="text-sm font-semibold text-white">Watch Mode</span>
          {isRunning && (
            <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded-full">
              Active
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {!isRunning && (
            <>
              <div className="flex items-center gap-1.5">
                <Clock size={12} className="text-slate-500" />
                <select
                  value={interval}
                  onChange={(e) => setInterval_(Number(e.target.value))}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                >
                  <option value={60}>1 min</option>
                  <option value={120}>2 min</option>
                  <option value={300}>5 min</option>
                  <option value={600}>10 min</option>
                  <option value={900}>15 min</option>
                  <option value={1800}>30 min</option>
                </select>
              </div>
              <button
                onClick={doStart}
                disabled={starting}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-lg text-xs text-white font-medium transition-colors"
              >
                {starting ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Play size={12} />
                )}
                Start Watching
              </button>
            </>
          )}
          {isRunning && (
            <button
              onClick={doStop}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-500 rounded-lg text-xs text-white font-medium transition-colors"
            >
              <Square size={12} />
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Live scan progress */}
      {isRunning && status?.scanning && progress && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 mb-3">
          <div className="flex items-center gap-2 mb-1">
            <FolderSearch size={13} className="text-blue-400 animate-pulse shrink-0" />
            <span className="text-xs text-blue-400 font-medium">Scanning file system...</span>
            <span className="text-xs text-slate-500 ml-auto font-mono">
              {progress.dirs_scanned.toLocaleString()} dirs
            </span>
          </div>
          <div className="text-[11px] text-slate-500 font-mono truncate pl-5" title={progress.current_path}>
            {progress.current_path}
          </div>
        </div>
      )}

      {/* Idle status bar */}
      {isRunning && !status?.scanning && status && (
        <div className="flex items-center gap-4 text-xs text-slate-400 mb-3">
          <span>
            Scans: <span className="text-white font-mono">{status.scans_completed}</span>
          </span>
          {status.last_scan_at && (
            <span>
              Last: <span className="text-white font-mono">
                {new Date(status.last_scan_at).toLocaleTimeString()}
              </span>
            </span>
          )}
          {countdown && (
            <span className="flex items-center gap-1">
              <Timer size={10} className="text-slate-500" />
              Next in: <span className="text-white font-mono">{countdown}</span>
            </span>
          )}
          {status.last_error && (
            <span className="text-red-400 truncate max-w-[200px]" title={status.last_error}>
              Error: {status.last_error}
            </span>
          )}
        </div>
      )}

      {/* Event log */}
      {events.length > 0 && (
        <div className="max-h-[140px] overflow-auto border-t border-slate-800 pt-2 mt-1 space-y-1">
          {[...events].reverse().slice(0, 20).map((e) => (
            <div key={e.seq} className="flex items-start gap-2 text-xs">
              <EventIcon kind={e.kind} />
              <span className="text-slate-500 font-mono shrink-0">
                {new Date(e.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className={`truncate ${eventColor(e.kind)}`}>
                {e.detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function eventColor(kind: string): string {
  switch (kind) {
    case "anomaly_detected": return "text-amber-400";
    case "scan_error": return "text-red-400";
    case "scan_complete": return "text-slate-300";
    case "compacted": return "text-blue-400";
    case "watch_started": return "text-green-400";
    case "watch_stopped": return "text-slate-500";
    default: return "text-slate-400";
  }
}

function EventIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "anomaly_detected":
      return <AlertTriangle size={12} className="text-amber-400 mt-0.5 shrink-0" />;
    case "scan_error":
      return <AlertTriangle size={12} className="text-red-400 mt-0.5 shrink-0" />;
    case "scan_complete":
      return <CheckCircle size={12} className="text-green-400 mt-0.5 shrink-0" />;
    case "compacted":
      return <Zap size={12} className="text-blue-400 mt-0.5 shrink-0" />;
    case "watch_started":
      return <Play size={12} className="text-green-400 mt-0.5 shrink-0" />;
    case "watch_stopped":
      return <Square size={12} className="text-slate-500 mt-0.5 shrink-0" />;
    default:
      return <Radio size={12} className="text-slate-500 mt-0.5 shrink-0" />;
  }
}
