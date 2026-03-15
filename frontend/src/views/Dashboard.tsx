import { useCallback, useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";
import {
  RefreshCw,
  Camera,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import {
  api,
  formatBytes,
  formatBytesAbs,
  type Snapshot,
  type ReportData,
  type PathIOOffender,
} from "../api";
import { Card, StatCard, SeverityBadge } from "../components/Card";
import { DeletePathButton } from "../components/DeletePathButton";
import { PathInspectButton } from "../components/PathInspectButton";
import { ResizableTable } from "../components/ResizableTable";
import { DepthFilter, filterByDepth, type DepthMode } from "../components/DepthFilter";
import { toast } from "../components/Toast";
import { WatchPanel } from "../components/WatchPanel";

const ANOMALY_COLS = [
  { key: "sev", label: "Sev", defaultWidth: 60, minWidth: 50 },
  { key: "path", label: "Path", minWidth: 120 },
  { key: "rules", label: "Rules", defaultWidth: 140, minWidth: 80 },
  { key: "growth", label: "Growth", defaultWidth: 85, minWidth: 65, align: "right" as const },
  { key: "rate", label: "Rate", defaultWidth: 85, minWidth: 65, align: "right" as const },
  { key: "cause", label: "Cause", minWidth: 100 },
  { key: "offender", label: "Process", defaultWidth: 110, minWidth: 80 },
  { key: "actions", label: "", defaultWidth: 44, minWidth: 40 },
];

const GROWER_COLS = [
  { key: "rank", label: "#", defaultWidth: 32, minWidth: 28 },
  { key: "path", label: "Path", minWidth: 100 },
  { key: "growth", label: "Growth", defaultWidth: 85, minWidth: 60, align: "right" as const },
  { key: "rate", label: "Rate/h", defaultWidth: 85, minWidth: 60, align: "right" as const },
  { key: "size", label: "Size", defaultWidth: 85, minWidth: 60, align: "right" as const },
  { key: "pct", label: "%", defaultWidth: 50, minWidth: 40, align: "right" as const },
  { key: "files", label: "Files", defaultWidth: 55, minWidth: 40, align: "right" as const },
  { key: "offender", label: "Process", defaultWidth: 100, minWidth: 80 },
  { key: "actions", label: "", defaultWidth: 44, minWidth: 40 },
];

const RULE_LABELS: Record<string, { label: string; color: string }> = {
  abs_threshold: { label: "Abs", color: "bg-red-500/20 text-red-400" },
  growth_rate: { label: "Rate", color: "bg-orange-500/20 text-orange-400" },
  relative_growth: { label: "Rel", color: "bg-amber-500/20 text-amber-400" },
  statistical: { label: "Stats", color: "bg-purple-500/20 text-purple-400" },
};

function RuleBadges({ rules }: { rules: string }) {
  return (
    <div className="flex gap-1 flex-wrap">
      {rules.split(", ").map((r) => {
        const info = RULE_LABELS[r] ?? { label: r, color: "bg-slate-700 text-slate-400" };
        return (
          <span key={r} className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${info.color}`}>
            {info.label}
          </span>
        );
      })}
    </div>
  );
}

export function Dashboard() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [report, setReport] = useState<ReportData | null>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [taking, setTaking] = useState(false);
  const [depthMode, setDepthMode] = useState<DepthMode>("all");
  const [depthVal, setDepthVal] = useState(2);

  const [chartOpen, setChartOpen] = useState(true);
  const [oneShotWatch, setOneShotWatch] = useState(false);
  const [watchRunning, setWatchRunning] = useState(false);
  const [compareDepth, setCompareDepth] = useState<number | null>(null);
  const [depths, setDepths] = useState<Array<{ depth: number; count: number }>>([]);
  const [offenders, setOffenders] = useState<Record<string, PathIOOffender | null>>({});

  const load = useCallback(async () => {
    setLoading(true);
    let snaps: Snapshot[] = [];
    try {
      const [snapsRes, depthsRes] = await Promise.all([
        api.listSnapshots(100),
        api.snapshotDepths().catch(() => []),
      ]);
      snaps = snapsRes;
      setSnapshots(snaps);
      setDepths(depthsRes);
      if (snaps.length >= 2) {
        let r: ReportData | null = null;
        if (compareDepth != null && depthsRes.some((d) => d.depth === compareDepth && d.count >= 2)) {
          try {
            r = await api.getReport(undefined, undefined, 20, compareDepth);
          } catch {
            /* fall through */
          }
        }
        if (!r) {
          try {
            r = await api.getReport(snaps[1].id, snaps[0].id);
          } catch {
            const best = depthsRes.reduce((a, b) => (a.count >= b.count ? a : b), depthsRes[0]);
            if (best && best.count >= 2) {
              r = await api.getReport(undefined, undefined, 20, best.depth);
              setCompareDepth(best.depth);
            } else {
              try {
                r = await api.getReport(snaps[snaps.length - 1].id, snaps[0].id);
              } catch {
                /* no report */
              }
            }
          }
        }
        setReport(r ?? null);
        if (r?.anomalies?.length || r?.top_growers?.length) {
          const anomalyPaths = r.anomalies?.map((a) => a.attributed_path) ?? [];
          const growerPaths = (r.top_growers ?? []).slice(0, 15).map((g) => g.path);
          const paths = [...new Set([...anomalyPaths, ...growerPaths])];
          api.pathIoOffenders(paths).then(setOffenders).catch(() => {});
        } else {
          setOffenders({});
        }
      } else {
        setReport(null);
        setOffenders({});
      }
      if (snaps.length > 0) {
        const rootPath = snaps[0].root_path;
        const hist = await api.pathHistory(rootPath, 100);
        setTimeline(
          hist.reverse().map((h) => ({
            time: new Date(h.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            }),
            bytes: h.total_bytes,
          }))
        );
      }
    } catch (err: any) {
      if (!err?.message?.includes("Network error")) {
        toast({ type: "error", text: `Load failed: ${err?.message ?? err}` });
      }
    }
    setLoading(false);
    if (oneShotWatch && snaps.length > 0) {
      setOneShotWatch(false);
      setWatchRunning(false);
      api.watchStop().catch(() => {});
    }
  }, [oneShotWatch, compareDepth]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (compareDepth != null && snapshots.length >= 2) {
      load();
    }
  }, [compareDepth]);

  useEffect(() => {
    if (snapshots.length === 0) {
      api.watchStatus().then((s) => setWatchRunning(s?.running ?? false)).catch(() => {});
    }
  }, [snapshots.length]);

  useEffect(() => {
    const onWatchChanged = () => {
      api.watchStatus().then((s) => setWatchRunning(s?.running ?? false)).catch(() => {});
    };
    window.addEventListener("sldd:watch-changed", onWatchChanged);
    return () => window.removeEventListener("sldd:watch-changed", onWatchChanged);
  }, []);

  useEffect(() => {
    const onReset = () => load();
    window.addEventListener("sldd:db-reset", onReset);
    return () => window.removeEventListener("sldd:db-reset", onReset);
  }, [load]);

  const takeSnap = async () => {
    if (snapshots.length === 0) {
      setTaking(true);
      try {
        await api.watchStart(300, true);
        setOneShotWatch(true);
        window.dispatchEvent(new CustomEvent("sldd:watch-changed"));
        toast({ type: "info", text: "Scanning filesystem… Watch panel shows live progress." });
      } catch (err: any) {
        toast({ type: "error", text: `Start failed: ${err?.message ?? err}` });
      } finally {
        setTaking(false);
      }
      return;
    }
    setTaking(true);
    try {
      await api.createSnapshot("");
      toast({ type: "success", text: "Snapshot captured" });
      await load();
    } catch (err: any) {
      toast({ type: "error", text: `Snapshot failed: ${err?.message ?? err}` });
    } finally {
      setTaking(false);
    }
  };

  const maxDepth = Math.max(
    ...(report?.top_growers.map((g) => g.depth) ?? [0]),
    ...(report?.anomalies.map((a) => (a.path.match(/\//g) || []).length) ?? [0]),
  );

  const filteredGrowers = filterByDepth(report?.top_growers ?? [], depthMode, depthVal);
  const filteredShrinkers = filterByDepth(report?.top_shrinkers ?? [], depthMode, depthVal);
  const filteredAnomalies = report
    ? filterByDepth(
        report.anomalies.map((a) => ({ ...a, depth: (a.path.match(/\//g) || []).length })),
        depthMode,
        depthVal,
      )
    : [];

  const growthData = filteredGrowers.slice(0, 10).map((g) => ({
    path: g.path.split("/").pop() || g.path,
    fullPath: g.path,
    growth: g.growth_bytes,
  }));

  return (
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Dashboard</h2>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <button
            onClick={takeSnap}
            disabled={taking}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-white font-medium transition-colors"
          >
            <Camera size={14} />
            {taking ? "Scanning..." : "Take Snapshot"}
          </button>
        </div>
      </div>

      <WatchPanel onNewData={load} />

      {loading ? (
        <div className="text-slate-500 py-20 text-center">Loading...</div>
      ) : snapshots.length === 0 ? (
        <Card className="text-center py-16 px-8">
          <div className="max-w-md mx-auto">
            <div className="p-4 rounded-full bg-slate-800 w-fit mx-auto mb-4">
              <Camera size={32} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">No snapshots yet</h3>
            <p className="text-slate-400 text-sm mb-6">
              {watchRunning
                ? "Watch panel above shows live scan progress. First snapshot will appear when done."
                : "Take your first snapshot to start tracking disk usage and detecting growth anomalies."}
            </p>
            {!watchRunning && (
              <button
                onClick={takeSnap}
                disabled={taking}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
              >
                <Camera size={16} />
                {taking ? "Starting…" : "Take First Snapshot"}
              </button>
            )}
          </div>
        </Card>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-4 gap-4">
            <StatCard
              label="Snapshots"
              value={String(snapshots.length)}
              sub={`Latest: ${new Date(snapshots[0].timestamp).toLocaleString()}`}
            />
            <StatCard
              label="Change"
              value={report ? formatBytes(report.total_growth_bytes) : "—"}
              sub={report ? `over ${(report.elapsed_seconds / 3600).toFixed(1)}h` : ""}
              color={
                report && report.total_growth_bytes > 0
                  ? "text-red-400"
                  : report && report.total_growth_bytes < 0
                  ? "text-green-400"
                  : "text-slate-400"
              }
            />
            <StatCard
              label="Anomalies"
              value={String(filteredAnomalies.length)}
              color={
                filteredAnomalies.length > 0
                  ? "text-amber-400"
                  : "text-green-400"
              }
            />
            <StatCard
              label="Root Path"
              value={snapshots[0]?.root_path ?? "—"}
              color="text-slate-300"
            />
          </div>

          {/* Compare depth + Depth filter */}
          {report && (
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-500">Compare at depth</span>
                  <select
                    value={compareDepth ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setCompareDepth(v ? Number(v) : null);
                    }}
                    className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-white"
                  >
                    <option value="">Auto</option>
                    {depths.map((d) => (
                      <option key={d.depth} value={d.depth}>
                        {d.depth} ({d.count} snapshots)
                      </option>
                    ))}
                  </select>
                </div>
                {report._meta && (
                  <span className="text-xs text-slate-500">
                    {report._meta.matching_snapshots} at depth {report._meta.depth}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-500">
                  Showing depth {depthMode === "all" ? "0–" + maxDepth : depthVal}
                </span>
                <DepthFilter
                  mode={depthMode}
                  depth={depthVal}
                  maxAvailable={maxDepth}
                  onModeChange={setDepthMode}
                  onDepthChange={setDepthVal}
                />
              </div>
            </div>
          )}

          {/* Anomalies — grouped by path */}
          {filteredAnomalies.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-white mb-3">
                Anomalies
                <span className="text-slate-500 font-normal ml-2">
                  ({filteredAnomalies.length} paths)
                </span>
              </h3>
              <ResizableTable columns={ANOMALY_COLS}>
                {filteredAnomalies.map((a, i) => (
                  <tr
                    key={i}
                    className="border-t border-slate-800 hover:bg-slate-800/50"
                  >
                    <td className="py-2 pr-2">
                      <SeverityBadge severity={a.severity} />
                    </td>
                    <td className="py-2 pr-2 font-mono text-xs text-slate-300 truncate" title={a.path}>
                      {a.path}
                    </td>
                    <td className="py-2 pr-2">
                      <RuleBadges rules={a.rule} />
                    </td>
                    <td
                      className={`py-2 pr-2 text-right font-mono ${
                        a.growth_bytes < 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {a.growth_human}
                    </td>
                    <td className="py-2 pr-2 text-right font-mono text-slate-400">
                      {a.rate_human}
                    </td>
                    <td className="py-2 pr-2 font-mono text-xs text-slate-500 truncate" title={a.attributed_path}>
                      {a.attributed_path !== a.path
                        ? a.attributed_path
                        : "—"}
                    </td>
                    <td className="py-2 pr-2" title={offenders[a.attributed_path]?.cmdline ?? undefined}>
                      <div className="flex flex-col gap-0.5">
                        {a.sldd_db_bytes && a.sldd_db_bytes > 0 && (
                          <span className="text-xs text-blue-400 font-medium" title="This tool's database contributed to growth">
                            sldd (this tool) +{a.sldd_db_human ?? ""}
                          </span>
                        )}
                        {offenders[a.attributed_path] ? (
                          <span className="text-xs text-amber-300 font-medium truncate block max-w-[140px]">
                            {offenders[a.attributed_path]!.process_name}
                            {offenders[a.attributed_path]!.username
                              ? ` (@${offenders[a.attributed_path]!.username})`
                              : ""}
                          </span>
                        ) : !a.sldd_db_bytes || a.sldd_db_bytes <= 0 ? (
                          <span className="text-slate-600">—</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="py-1.5 pl-2 flex items-center gap-1">
                      <PathInspectButton path={a.path} />
                      <DeletePathButton path={a.path} onDeleted={load} />
                    </td>
                  </tr>
                ))}
              </ResizableTable>
            </Card>
          )}

          {/* Top Growers — table + inline mini chart */}
          <Card>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">
                Top Growing Directories
                <span className="text-slate-500 font-normal ml-2">
                  ({filteredGrowers.length})
                </span>
              </h3>
              <button
                onClick={() => setChartOpen(!chartOpen)}
                className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors"
              >
                {chartOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {chartOpen ? "Hide chart" : "Show chart"}
              </button>
            </div>

            {chartOpen && growthData.length > 0 && (
              <div className="mb-4 border border-slate-800 rounded-lg p-3 bg-slate-950/50">
                <ResponsiveContainer width="100%" height={Math.min(growthData.length * 28 + 40, 320)}>
                  <BarChart
                    data={growthData}
                    layout="vertical"
                    margin={{ left: 10, right: 20 }}
                  >
                    <XAxis
                      type="number"
                      tickFormatter={(v) => formatBytesAbs(v)}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                    />
                    <YAxis
                      type="category"
                      dataKey="path"
                      width={120}
                      tick={{ fill: "#94a3b8", fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#1a1d28",
                        border: "1px solid #334155",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      formatter={(v: any) => formatBytes(Number(v))}
                      labelFormatter={(_, payload) =>
                        payload?.[0]?.payload?.fullPath ?? ""
                      }
                    />
                    <Bar dataKey="growth" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            <ResizableTable columns={GROWER_COLS}>
              {filteredGrowers.map((g, i) => (
                <tr
                  key={g.path}
                  className="border-t border-slate-800 hover:bg-slate-800/50"
                >
                  <td className="py-1.5 pr-2 text-slate-600 text-xs">{i + 1}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs text-slate-300 truncate" title={g.path}>
                    {g.path}
                  </td>
                  <td
                    className={`py-1.5 pr-2 text-right font-mono text-xs ${
                      g.growth_bytes > 100 * 1024 * 1024
                        ? "text-red-400 font-semibold"
                        : g.growth_bytes > 0
                        ? "text-red-400"
                        : g.growth_bytes < 0
                        ? "text-green-400"
                        : "text-slate-500"
                    }`}
                  >
                    {g.growth_human}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-400">
                    {g.rate_human}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-400">
                    {formatBytesAbs(g.bytes_after)}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-500">
                    {g.growth_pct.toFixed(1)}%
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-500">
                    {g.files_delta > 0 ? "+" : ""}{g.files_delta}
                  </td>
                  <td className="py-1.5 pr-2" title={offenders[g.path]?.cmdline ?? undefined}>
                    {offenders[g.path] ? (
                      <span className="text-xs text-amber-300 font-medium truncate block max-w-[120px]">
                        {offenders[g.path]!.process_name}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-1.5 pl-2 flex items-center gap-1">
                    <PathInspectButton path={g.path} />
                    <DeletePathButton path={g.path} onDeleted={load} />
                  </td>
                </tr>
              ))}
            </ResizableTable>
          </Card>

          {/* Top Shrinking Directories */}
          {filteredShrinkers.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-white mb-3">
                Top Shrinking Directories
                <span className="text-slate-500 font-normal ml-2">
                  ({filteredShrinkers.length})
                </span>
              </h3>
              <ResizableTable columns={GROWER_COLS}>
                {filteredShrinkers.map((g, i) => (
                  <tr
                    key={g.path}
                    className="border-t border-slate-800 hover:bg-slate-800/50"
                  >
                    <td className="py-1.5 pr-2 text-slate-600 text-xs">{i + 1}</td>
                    <td className="py-1.5 pr-2 font-mono text-xs text-slate-300 truncate" title={g.path}>
                      {g.path}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-xs text-green-400">
                      {g.growth_human}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-400">
                      {g.rate_human}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-400">
                      {formatBytesAbs(g.bytes_after)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-500">
                      {g.growth_pct.toFixed(1)}%
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-xs text-slate-500">
                      {g.files_delta > 0 ? "+" : ""}{g.files_delta}
                    </td>
                    <td className="py-1.5 pr-2">
                      <span className="text-slate-600">—</span>
                    </td>
                    <td className="py-1.5 pl-2 flex items-center gap-1">
                      <PathInspectButton path={g.path} />
                      <DeletePathButton path={g.path} onDeleted={load} />
                    </td>
                  </tr>
                ))}
              </ResizableTable>
            </Card>
          )}

          {/* Disk Usage Over Time */}
          {timeline.length > 1 && (
            <Card>
              <h3 className="text-sm font-semibold text-white mb-3">
                Disk Usage Over Time
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={timeline}>
                  <XAxis
                    dataKey="time"
                    tick={{ fill: "#64748b", fontSize: 11 }}
                  />
                  <YAxis
                    tickFormatter={(v) => formatBytesAbs(v)}
                    tick={{ fill: "#64748b", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#1a1d28",
                      border: "1px solid #334155",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v: any) => formatBytesAbs(Number(v))}
                  />
                  <Area
                    type="monotone"
                    dataKey="bytes"
                    stroke="#3b82f6"
                    fill="#3b82f6"
                    fillOpacity={0.15}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Card>
          )}

        </>
      )}
    </div>
  );
}
