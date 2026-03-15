import { useCallback, useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { ChevronRight, Folder, FolderOpen, Info, LayoutDashboard, Trash2, Loader2, AlertTriangle, ShieldOff, X } from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  formatBytes,
  formatBytesAbs,
  type DirEntry,
  type Snapshot,
  type DeletePreview as PreviewT,
} from "../api";
import { Card } from "../components/Card";
import { formatChartTime } from "../utils/formatChartTime";
import { PathInspectButton } from "../components/PathInspectButton";
import { toast } from "../components/Toast";

export function Explorer() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapId, setSnapId] = useState<number | null>(null);
  const [path, setPath] = useState<string>("");
  const [children, setChildren] = useState<DirEntry[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [selected, setSelected] = useState<DirEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const [deletePreview, setDeletePreview] = useState<PreviewT | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [blockedPaths, setBlockedPaths] = useState<string[]>([]);
  const [infoClosed, setInfoClosed] = useState(() => {
    try {
      return localStorage.getItem("sldd:explorer-info-closed") === "1";
    } catch {
      return false;
    }
  });

  const loadSnapshots = useCallback(() => {
    api.listSnapshots(200).then((s) => {
      setSnapshots(s);
      setChildren([]);
      setSelected(null);
      if (s.length > 0) {
        setSnapId(s[0].id ?? null);
        setPath(s[0].root_path);
      } else {
        setSnapId(null);
        setPath("");
      }
    }).catch((err) => toast({ type: "error", text: `Load failed: ${err?.message ?? err}` }));
  }, []);

  useEffect(() => { loadSnapshots(); }, [loadSnapshots]);

  useEffect(() => {
    window.addEventListener("sldd:db-reset", loadSnapshots);
    return () => window.removeEventListener("sldd:db-reset", loadSnapshots);
  }, [loadSnapshots]);

  useEffect(() => {
    if (snapId == null || !path) return;
    setLoading(true);
    api.drill(snapId, path).then((c) => {
      setChildren(c);
      setSelected(c.length > 0 ? c[0] : null);
    }).catch((err) => toast({ type: "error", text: `Drill failed: ${err?.message ?? err}` }))
      .finally(() => setLoading(false));
  }, [snapId, path]);

  useEffect(() => {
    if (!selected) {
      setHistory([]);
      return;
    }
    const scanDepth = snapshots.find((s) => s.id === snapId)?.scan_depth;
    api.pathHistory(selected.path, 50, scanDepth).then((h) => {
      const reversed = h.reverse();
      const timestamps = reversed.map((r) => r.timestamp);
      setHistory(
        reversed.map((r, i) => {
          const prev = i > 0 ? reversed[i - 1] : null;
          const delta = prev != null ? r.total_bytes - prev.total_bytes : undefined;
          return {
            time: formatChartTime(r.timestamp, timestamps),
            bytes: r.total_bytes,
            delta,
          };
        })
      );
    }).catch((err) => toast({ type: "error", text: `History failed: ${err?.message ?? err}` }));
  }, [selected, snapId, snapshots]);

  const doDeletePreview = async (path: string) => {
    setDeleting(true);
    setDeletePreview(null);
    setBlockedPaths([]);
    try {
      const p = await api.deletePreview([path]);
      if (p.blocked_paths.length > 0) {
        setBlockedPaths(p.blocked_paths);
      }
      setDeletePreview(p);
    } catch (err: any) {
      toast({ type: "error", text: `Preview failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  };

  const doDeleteExecute = async (paths: string[], force: boolean) => {
    setDeleting(true);
    try {
      const r = await api.deleteExecute(paths, false, force);
      if (r.succeeded.length > 0) {
        toast({ type: "success", text: `Deleted ${r.succeeded.length} items, freed ${formatBytesAbs(r.bytes_freed)}` });
        setSelected(null);
        setDeletePreview(null);
        setBlockedPaths([]);
        if (snapId != null && path) {
          api.drill(snapId, path).then(setChildren).catch(() => {});
        }
      }
      if (r.failed.length > 0) {
        toast({ type: "error", text: `${r.failed.length} failed` });
      }
    } catch (err: any) {
      toast({ type: "error", text: `Delete failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  };

  const breadcrumbs = (() => {
    if (!snapshots.length || !path) return [];
    const root = snapshots.find((s) => s.id === snapId)?.root_path ?? "/";
    const parts: { label: string; path: string }[] = [
      { label: root, path: root },
    ];
    if (path !== root) {
      const rel = path.slice(root.length).replace(/^\//, "");
      let accum = root;
      for (const p of rel.split("/")) {
        accum = accum.replace(/\/$/, "") + "/" + p;
        parts.push({ label: p, path: accum });
      }
    }
    return parts;
  })();

  if (snapshots.length === 0) {
    return (
      <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
        <h2 className="text-xl font-semibold text-white">Explorer</h2>
        <Card className="text-center py-16 px-8">
          <div className="max-w-md mx-auto">
            <div className="p-4 rounded-full bg-slate-800 w-fit mx-auto mb-4">
              <Folder size={32} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">No snapshots yet</h3>
            <p className="text-slate-400 text-sm mb-6">
              Take a snapshot from the Dashboard to browse directory sizes and drill into the filesystem.
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
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold text-white">Explorer</h2>
          {infoClosed && (
            <button
              onClick={() => {
                setInfoClosed(false);
                try {
                  localStorage.removeItem("sldd:explorer-info-closed");
                } catch { /* noop */ }
              }}
              className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors"
              title="Show explanation"
            >
              <Info size={14} />
            </button>
          )}
        </div>
        <select
          className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white min-w-[240px]"
          value={snapId ?? ""}
          onChange={(e) => {
            const id = Number(e.target.value);
            setSnapId(id);
            const s = snapshots.find((s) => s.id === id);
            if (s) setPath(s.root_path);
          }}
        >
          {snapshots.map((s) => (
            <option key={s.id} value={s.id}>
              #{s.id} — {new Date(s.timestamp).toLocaleString()}
            </option>
          ))}
        </select>
      </div>

      {!infoClosed && (
        <div className="rounded-lg bg-slate-800/50 border border-slate-700/50">
          <div className="p-3">
            <div className="flex items-start gap-2">
              <Info size={14} className="text-slate-500 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0 text-xs text-slate-400">
                <p className="font-medium text-slate-300">
                  Historical snapshot view — not live filesystem. Sizes and structure reflect the state when the snapshot was taken.
                </p>
              </div>
              <button
                onClick={() => {
                  setInfoClosed(true);
                  try {
                    localStorage.setItem("sldd:explorer-info-closed", "1");
                  } catch { /* noop */ }
                }}
                className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                title="Close"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center gap-1 text-sm text-slate-400 flex-wrap">
        {breadcrumbs.map((b, i) => (
          <span key={b.path} className="flex items-center gap-1">
            {i > 0 && <ChevronRight size={14} className="text-slate-600" />}
            <button
              onClick={() => setPath(b.path)}
              className="hover:text-blue-400 transition-colors font-mono text-xs"
            >
              {b.label}
            </button>
          </span>
        ))}
      </div>

      <div className="grid grid-cols-5 gap-4">
        <Card className="col-span-3 max-h-[600px] overflow-auto">
          {loading ? (
            <p className="text-slate-500 py-8 text-center">Loading...</p>
          ) : children.length === 0 ? (
            <p className="text-slate-500 py-8 text-center">
              No subdirectories
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 text-xs uppercase sticky top-0 bg-slate-900">
                  <th className="pb-2 pr-3">Name</th>
                  <th className="pb-2 pr-3 text-right">Size</th>
                  <th className="pb-2 pr-3 text-right">Files</th>
                  <th className="pb-2 text-right">Dirs</th>
                </tr>
              </thead>
              <tbody>
                {children.map((c) => {
                  const name = c.path.split("/").pop() || c.path;
                  const isSelected = selected?.path === c.path;
                  return (
                    <tr
                      key={c.path}
                      className={`border-t border-slate-800 cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-blue-600/10"
                          : "hover:bg-slate-800/50"
                      }`}
                      onClick={() => setSelected(c)}
                      onDoubleClick={() => {
                        if (c.dir_count > 0 || c.file_count > 0) {
                          setPath(c.path);
                        }
                      }}
                    >
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2">
                          {isSelected ? (
                            <FolderOpen size={14} className="text-blue-400 shrink-0" />
                          ) : (
                            <Folder size={14} className="text-slate-500 shrink-0" />
                          )}
                          <span className="font-mono text-xs text-slate-300 truncate">
                            {name}
                          </span>
                        </div>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono text-xs text-slate-400">
                        {formatBytesAbs(c.total_bytes)}
                      </td>
                      <td className="py-2 pr-3 text-right text-slate-500">
                        {c.file_count}
                      </td>
                      <td className="py-2 text-right text-slate-500">
                        {c.dir_count}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="col-span-2">
          {selected ? (
            <div className="space-y-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">Path</p>
                <p className="font-mono text-xs text-white break-all">
                  {selected.path}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <PathInspectButton path={selected.path} />
                <button
                  onClick={() => doDeletePreview(selected.path)}
                  disabled={deleting}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm bg-red-600/80 hover:bg-red-600 disabled:opacity-50 rounded-lg text-white transition-colors"
                >
                  {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                  Delete
                </button>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <p className="text-xs text-slate-500">Size</p>
                  <p className="font-mono text-white">
                    {formatBytesAbs(selected.total_bytes)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Files</p>
                  <p className="font-mono text-white">{selected.file_count}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Dirs</p>
                  <p className="font-mono text-white">{selected.dir_count}</p>
                </div>
              </div>
              {blockedPaths.length > 0 && (
                <div className="bg-amber-600/10 border border-amber-500/30 rounded-lg p-3 space-y-2">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-medium text-amber-300">Path blocked by safety rules</p>
                      <p className="text-[11px] text-slate-400 mt-1">Force delete if you&apos;re sure.</p>
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={() => { setBlockedPaths([]); setDeletePreview(null); }}
                          className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => doDeleteExecute([selected.path], true)}
                          disabled={deleting}
                          className="flex items-center gap-1 px-2 py-1 text-xs bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded"
                        >
                          {deleting ? <Loader2 size={12} className="animate-spin" /> : <ShieldOff size={12} />}
                          Force Delete
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {deletePreview && blockedPaths.length === 0 && (
                <div className="bg-red-600/10 border border-red-500/20 rounded-lg p-3 space-y-2">
                  <p className="text-xs text-red-400">
                    {deletePreview.total_files} files, {formatBytesAbs(deletePreview.total_bytes)} will be deleted.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setDeletePreview(null)}
                      className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => doDeleteExecute([selected!.path], false)}
                      disabled={deleting}
                      className="flex items-center gap-1 px-2 py-1 text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded"
                    >
                      {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      Confirm Delete
                    </button>
                  </div>
                </div>
              )}
              {history.length > 1 && (
                <div>
                  <p className="text-xs text-slate-500 mb-2">Size Over Time</p>
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={history}>
                      <XAxis
                        dataKey="time"
                        tick={{ fill: "#64748b", fontSize: 10 }}
                      />
                      <YAxis
                        tickFormatter={(v) => formatBytesAbs(v)}
                        tick={{ fill: "#64748b", fontSize: 10 }}
                        width={60}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#1a1d28",
                          border: "1px solid #334155",
                          borderRadius: 8,
                          fontSize: 11,
                        }}
                        content={({ active, payload, label }) => {
                          if (!active || !payload?.length) return null;
                          const p = payload[0]?.payload as { bytes: number; delta?: number };
                          const bytes = p?.bytes ?? payload[0]?.value;
                          const delta = p?.delta;
                          return (
                            <div className="px-3 py-2 space-y-1">
                              <p className="text-slate-300 font-medium">{label}</p>
                              <p className="font-mono text-white">{formatBytesAbs(Number(bytes))}</p>
                              {delta !== undefined && (
                                <p
                                  className={`font-mono text-xs ${
                                    delta > 0 ? "text-red-400" : delta < 0 ? "text-emerald-400" : "text-slate-500"
                                  }`}
                                >
                                  Change: {delta > 0 ? "+" : ""}{formatBytes(delta)} vs previous
                                </p>
                              )}
                            </div>
                          );
                        }}
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
                </div>
              )}
            </div>
          ) : (
            <p className="text-slate-500 text-sm text-center py-12">
              Click a directory to see details.
              <br />
              Double-click to navigate into it.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
