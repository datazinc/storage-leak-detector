import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, Clock, AlertTriangle, Copy, FolderOpen, Info } from "lucide-react";
import { api, formatBytesAbs, type ProcessIOInfo, type PathIOHistoryEntry, type PathIOWatchStatus } from "../api";
import { ResizableTable } from "./ResizableTable";
import { toast } from "../components/Toast";

const PATH_INSPECT_COLS = [
  { key: "process", label: "Process", minWidth: 120 },
  { key: "pid", label: "PID", defaultWidth: 60, minWidth: 45, align: "right" as const },
  { key: "read", label: "Read", defaultWidth: 75, minWidth: 55, align: "right" as const },
  { key: "write", label: "Write", defaultWidth: 75, minWidth: 55, align: "right" as const },
  { key: "open", label: "Open", defaultWidth: 55, minWidth: 45, align: "right" as const },
  { key: "actions", label: "", defaultWidth: 44, minWidth: 40 },
];
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

type Props = {
  path: string;
  size?: "sm" | "md";
};

export function PathInspectButton({ path, size = "sm" }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [processes, setProcesses] = useState<ProcessIOInfo[] | null>(null);
  const [history, setHistory] = useState<PathIOHistoryEntry[] | null>(null);
  const [watchStatus, setWatchStatus] = useState<PathIOWatchStatus | null>(null);
  const [watching, setWatching] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [procs, hist, watches] = await Promise.all([
        api.pathIoNow(path),
        api.pathIoHistory(path, 100).catch(() => []),
        api.pathIoWatchStatus(),
      ]);
      setProcesses(procs);
      setHistory(hist);
      const w = watches.find((x) => x.path === path);
      setWatchStatus(w ?? null);
    } catch (err: unknown) {
      if (!silent) toast({ type: "error", text: `Inspect failed: ${(err as Error)?.message ?? err}` });
    } finally {
      if (!silent) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (open) load(false);
  }, [open, load]);

  useEffect(() => {
    if (!open || !watchStatus) return;
    const id = setInterval(() => load(true), 5000);
    return () => clearInterval(id);
  }, [open, watchStatus, load]);

  const startWatch = async (minutes: number) => {
    setWatching(true);
    try {
      await api.pathIoWatchStart(path, minutes);
      toast({ type: "success", text: `Watching for ${minutes} min` });
      load(true);
    } catch (err: unknown) {
      toast({ type: "error", text: `Watch failed: ${(err as Error)?.message ?? err}` });
    } finally {
      setWatching(false);
    }
  };

  const stopWatch = async () => {
    try {
      await api.pathIoWatchStop(path);
      toast({ type: "success", text: "Stopped watching" });
      load(true);
    } catch (err: unknown) {
      toast({ type: "error", text: `Stop failed: ${(err as Error)?.message ?? err}` });
    }
  };

  const btnClass = size === "sm"
    ? "p-1.5 rounded hover:bg-blue-600/20 text-slate-500 hover:text-blue-400 transition-colors"
    : "px-2 py-1 text-xs rounded bg-blue-600/80 hover:bg-blue-600 text-white transition-colors";

  type ChartBucket = { time: string; ts: string; [k: string]: string | number };
  const chartBuckets: Record<string, ChartBucket> = history
    ? history
        .filter((h) => h.write_bytes_delta > 0)
        .reduce((acc, h) => {
          const key = h.timestamp.slice(0, 19);
          if (!acc[key]) acc[key] = { time: new Date(h.timestamp).toLocaleTimeString(), ts: h.timestamp };
          const label = `${h.process_name} (${h.pid})`;
          acc[key][label] = ((acc[key][label] as number) || 0) + h.write_bytes_delta;
          return acc;
        }, {} as Record<string, ChartBucket>)
    : {};
  const chartData = Object.values(chartBuckets).sort(
    (a, b) => new Date(a.ts as string).getTime() - new Date(b.ts as string).getTime()
  );
  const chartSeries = chartData.length > 0
    ? Array.from(new Set(chartData.flatMap((d) => Object.keys(d).filter((k) => k !== "time" && k !== "ts"))))
    : [];

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={btnClass}
        title="Inspect process I/O"
      >
        <Activity size={size === "sm" ? 14 : 12} />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-slate-900 border border-slate-700 rounded-xl p-5 w-[520px] max-h-[85vh] overflow-auto shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-white mb-2 flex items-center gap-2">
              <Activity size={18} />
              Process I/O
            </h3>
            <div className="flex items-center gap-2 mb-4">
              <p className="font-mono text-xs text-slate-400 truncate flex-1 min-w-0" title={path}>{path}</p>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(path);
                  toast({ type: "success", text: "Path copied" });
                }}
                className="p-1.5 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                title="Copy path"
              >
                <Copy size={14} />
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.pathOpen(path);
                    toast({ type: "success", text: "Opened in file manager" });
                  } catch (e) {
                    toast({ type: "error", text: (e as Error)?.message ?? "Failed to open" });
                  }
                }}
                className="p-1.5 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                title="Open in file manager"
              >
                <FolderOpen size={14} />
              </button>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-slate-500 py-8">
                <Loader2 size={20} className="animate-spin" />
                <span>Loading...</span>
              </div>
            ) : (
              <div className="space-y-4">
                {watchStatus && (
                  <div className="flex items-center justify-between p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                    <span className="text-sm text-amber-300 flex items-center gap-2">
                      <Clock size={14} />
                      Watching for {watchStatus.duration_minutes} min
                    </span>
                    <button
                      onClick={stopWatch}
                      className="px-2 py-1 text-xs bg-amber-600 hover:bg-amber-500 rounded"
                    >
                      Stop
                    </button>
                  </div>
                )}

                <div>
                  <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">
                    Processes using this path
                  </h4>
                  {processes && processes.length > 0 ? (
                    <>
                      {processes.every((p) => p.read_bytes === 0 && p.write_bytes === 0) && (
                        <div className="flex items-start gap-2 p-2.5 mb-2 rounded-lg bg-slate-800/50 border border-slate-700 text-xs text-slate-400">
                          <Info size={14} className="shrink-0 mt-0.5" />
                          <span>
                            On macOS, per-process I/O often reports 0. The &quot;Open&quot; count is still accurate.
                          </span>
                        </div>
                      )}
                      <div className="border border-slate-800 rounded-lg overflow-hidden">
                        <ResizableTable columns={PATH_INSPECT_COLS}>
                          {processes.map((p, idx) => (
                            <tr key={p.pid} className="border-t border-slate-800">
                              <td className="py-2 pr-2">
                                <div className="flex items-center gap-2 min-w-0">
                                  {idx === 0 && p.write_bytes > 0 && (
                                    <span
                                      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-300 shrink-0"
                                      title="Primary process (highest write activity)"
                                    >
                                      <AlertTriangle size={10} />
                                      Primary
                                    </span>
                                  )}
                                  <span
                                    className="font-mono text-slate-300 truncate"
                                    title={p.cmdline ?? (p.username ? `User: ${p.username}` : undefined)}
                                  >
                                    {p.process_name}
                                    {p.username ? (
                                      <span className="text-slate-500 font-normal ml-1">@{p.username}</span>
                                    ) : null}
                                  </span>
                                </div>
                              </td>
                              <td className="py-2 pr-2 text-right text-slate-500">{p.pid}</td>
                              <td className="py-2 pr-2 text-right font-mono text-slate-400">
                                {formatBytesAbs(p.read_bytes)}
                              </td>
                              <td className="py-2 pr-2 text-right font-mono text-slate-400">
                                {formatBytesAbs(p.write_bytes)}
                              </td>
                              <td className="py-2 pr-2 text-right text-slate-500">{p.open_files_under_path}</td>
                              <td className="py-1.5 pl-2">
                                <button
                                  onClick={() => {
                                    navigator.clipboard.writeText(String(p.pid));
                                    toast({ type: "success", text: "PID copied" });
                                  }}
                                  className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors"
                                  title="Copy PID"
                                >
                                  <Copy size={12} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </ResizableTable>
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-slate-500">No processes have files open under this path.</p>
                  )}
                </div>

                {history && history.length > 1 && (
                  <div>
                    <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">
                      Write activity over time
                    </h4>
                    <div className="h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={Object.values(chartData)}>
                          <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
                          <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => formatBytesAbs(v)} />
                          <Tooltip formatter={(v) => formatBytesAbs(Number(v ?? 0))} />
                          {chartSeries.slice(0, 5).map((s, i) => (
                            <Area
                              key={s}
                              type="monotone"
                              dataKey={s}
                              stackId="1"
                              stroke={`hsl(${200 + i * 40}, 70%, 50%)`}
                              fill={`hsl(${200 + i * 40}, 70%, 50%)`}
                              fillOpacity={0.4}
                            />
                          ))}
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                <div className="flex gap-2 pt-2">
                  {!watchStatus && (
                    <>
                      <button
                        onClick={() => startWatch(10)}
                        disabled={watching}
                        className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg"
                      >
                        {watching ? "Starting..." : "Watch 10 min"}
                      </button>
                      <button
                        onClick={() => startWatch(30)}
                        disabled={watching}
                        className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded-lg"
                      >
                        Watch 30 min
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => setOpen(false)}
                    className="ml-auto px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
