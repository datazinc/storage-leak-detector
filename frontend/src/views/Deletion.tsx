import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AlertTriangle, Trash2, Eye, History, ShieldOff, Loader2 } from "lucide-react";
import {
  api,
  formatBytesAbs,
  type Snapshot,
  type DeletePreview as PreviewT,
  type DeletionLog,
} from "../api";
import { Card } from "../components/Card";
import { DeleteConfirmModal } from "../components/DeleteConfirmModal";
import { toast } from "../components/Toast";
import { useAddToDeletion } from "../context/AddToDeletionContext";

type Tab = "files" | "snapshots" | "audit";

export function Deletion() {
  const [tab, setTab] = useState<Tab>("files");

  return (
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      <h2 className="text-xl font-semibold text-white">Deletion Manager</h2>

      <div className="flex gap-1 bg-slate-900 border border-slate-800 rounded-lg p-1 w-fit">
        {(
          [
            { key: "files", icon: Trash2, label: "Delete Files" },
            { key: "snapshots", icon: Eye, label: "Snapshots" },
            { key: "audit", icon: History, label: "Audit Log" },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === t.key
                ? "bg-slate-800 text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <t.icon size={14} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "files" && <FileDeleteTab />}
      {tab === "snapshots" && <SnapshotDeleteTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}

function FileDeleteTab() {
  const addToDeletion = useAddToDeletion();
  const location = useLocation();
  const [paths, setPaths] = useState("");

  const consumePending = addToDeletion?.consumePending;
  useEffect(() => {
    if (location.pathname !== "/deletion" || !consumePending) return;
    const pending = consumePending();
    if (pending.length > 0) {
      setPaths((prev) => {
        const existing = prev.split("\n").map((p) => p.trim()).filter(Boolean);
        const merged = [...new Set([...existing, ...pending])];
        return merged.join("\n");
      });
      toast({ type: "info", text: `Added ${pending.length} path(s) from Dashboard` });
    }
  }, [location.pathname, consumePending]);
  const [preview, setPreview] = useState<PreviewT | null>(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [forceMode, setForceMode] = useState(false);

  const pathList = paths
    .split("\n")
    .map((p) => p.trim())
    .filter(Boolean);

  const doPreview = async (force = false) => {
    setLoading(true);
    setResult(null);
    setForceMode(force);
    try {
      const p = await api.deletePreview(pathList, force);
      setPreview(p);
    } catch (err: any) {
      toast({ type: "error", text: `Preview failed: ${err?.message ?? err}` });
    } finally {
      setLoading(false);
    }
  };

  const doDelete = async () => {
    setLoading(true);
    try {
      const r = await api.deleteExecute(pathList, false, forceMode);
      setResult(r);
      setPreview(null);
      setDeleteModalOpen(false);
      setForceMode(false);
      if (r.succeeded.length > 0) {
        toast({ type: "success", text: `Deleted ${r.succeeded.length} items` });
      } else {
        toast({ type: "info", text: "No items were deleted" });
      }
    } catch (err: any) {
      toast({ type: "error", text: `Delete failed: ${err?.message ?? err}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-sm font-semibold text-white mb-2">
          Paths to Delete
        </h3>
        <p className="text-xs text-slate-500 mb-3">
          One path per line. These will be permanently deleted from disk.
        </p>
        <textarea
          className="w-full h-32 bg-slate-800 border border-slate-700 rounded-lg p-3 font-mono text-xs text-white resize-y"
          placeholder="/path/to/file-or-directory&#10;/another/path"
          value={paths}
          onChange={(e) => setPaths(e.target.value)}
        />
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => doPreview()}
            disabled={pathList.length === 0 || loading}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded-lg text-sm text-white transition-colors"
          >
            <Eye size={14} />
            Preview
          </button>
        </div>
      </Card>

      {preview && (
        <Card>
          <h3 className="text-sm font-semibold text-white mb-3">
            Deletion Preview
          </h3>

          {preview.blocked_paths.length > 0 && (
            <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg space-y-3">
              <div className="flex items-start gap-2">
                <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-amber-300 text-sm font-medium">
                    {preview.blocked_paths.length} path{preview.blocked_paths.length > 1 ? "s" : ""} blocked by safety rules
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    These paths are normally protected. You can re-preview with force to bypass.
                  </p>
                </div>
              </div>
              {preview.blocked_paths.map((p) => (
                <p key={p} className="font-mono text-xs text-amber-200/80 ml-6">
                  {p}
                </p>
              ))}
              {!forceMode && (
                <button
                  onClick={() => doPreview(true)}
                  disabled={loading}
                  className="ml-6 flex items-center gap-2 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded-lg text-xs text-white font-medium transition-colors"
                >
                  {loading ? <Loader2 size={13} className="animate-spin" /> : <ShieldOff size={13} />}
                  Re-preview with Force
                </button>
              )}
            </div>
          )}

          <table className="w-full text-sm mb-4">
            <thead>
              <tr className="text-left text-slate-500 text-xs uppercase">
                <th className="pb-2 pr-3">Path</th>
                <th className="pb-2 pr-3">Type</th>
                <th className="pb-2 pr-3 text-right">Size</th>
                <th className="pb-2 pr-3 text-right">Files</th>
                <th className="pb-2">Writable</th>
              </tr>
            </thead>
            <tbody>
              {preview.targets.map((t) => (
                <tr key={t.path} className="border-t border-slate-800">
                  <td className="py-2 pr-3 font-mono text-xs text-slate-300">
                    {t.path}
                  </td>
                  <td className="py-2 pr-3 text-slate-400">
                    {t.is_dir ? "Dir" : "File"}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-slate-400">
                    {formatBytesAbs(t.size_bytes)}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-400">
                    {t.file_count}
                  </td>
                  <td className="py-2">
                    <span
                      className={
                        t.writable ? "text-green-400" : "text-red-400"
                      }
                    >
                      {t.writable ? "Yes" : "No"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="flex items-center justify-between p-3 bg-slate-800 rounded-lg">
            <p className="text-sm text-slate-300">
              Total: <strong>{formatBytesAbs(preview.total_bytes)}</strong>{" "}
              across <strong>{preview.total_files}</strong> files.
            </p>
            <button
              onClick={() => setDeleteModalOpen(true)}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
            >
              <Trash2 size={14} />
              Delete
            </button>
          </div>
        </Card>
      )}

      <DeleteConfirmModal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        onConfirm={doDelete}
        paths={pathList}
        totalFiles={preview?.total_files ?? 0}
        totalBytes={preview?.total_bytes ?? 0}
        confirmLabel="Delete permanently"
        loading={loading}
      />

      {result && (
        <Card>
          <h3 className="text-sm font-semibold text-white mb-2">Result</h3>
          <p className="text-sm text-green-400">
            Deleted {result.succeeded.length} items, freed{" "}
            {formatBytesAbs(result.bytes_freed)}.
          </p>
          {result.failed.length > 0 && (
            <div className="mt-2">
              <p className="text-sm text-red-400">
                {result.failed.length} failed:
              </p>
              {result.failed.map(([p, err]: [string, string]) => (
                <p key={p} className="font-mono text-xs text-red-300">
                  {p}: {err}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function SnapshotDeleteTab() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [pruneN, setPruneN] = useState(10);

  const load = useCallback(() => {
    api.listSnapshots(500).then(setSnapshots).catch((err) =>
      toast({ type: "error", text: `Load snapshots failed: ${err?.message ?? err}` }),
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    window.addEventListener("sldd:db-reset", load);
    return () => window.removeEventListener("sldd:db-reset", load);
  }, [load]);

  const deleteSelected = async () => {
    try {
      for (const id of selected) {
        await api.deleteSnapshot(id);
      }
      toast({ type: "success", text: `Deleted ${selected.size} snapshot(s)` });
      setSelected(new Set());
      load();
    } catch (err: any) {
      toast({ type: "error", text: `Delete failed: ${err?.message ?? err}` });
    }
  };

  const prune = async () => {
    try {
      const r = await api.pruneSnapshots(pruneN);
      toast({ type: "success", text: `Pruned ${r.deleted} snapshot(s)` });
      load();
    } catch (err: any) {
      toast({ type: "error", text: `Prune failed: ${err?.message ?? err}` });
    }
  };

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Snapshots</h3>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Keep last</span>
            <input
              type="number"
              value={pruneN}
              onChange={(e) => setPruneN(Number(e.target.value))}
              className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-white"
              min={1}
            />
            <button
              onClick={prune}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs text-white transition-colors"
            >
              Prune
            </button>
            <button
              onClick={deleteSelected}
              disabled={selected.size === 0}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded text-xs text-white transition-colors"
            >
              Delete Selected ({selected.size})
            </button>
          </div>
        </div>

        <div className="max-h-[400px] overflow-auto">
          {snapshots.length === 0 ? (
            <div className="py-12 text-center text-slate-500">
              <p className="mb-1">No snapshots to delete</p>
              <p className="text-sm">Take snapshots from the Dashboard first.</p>
            </div>
          ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 text-xs uppercase sticky top-0 bg-slate-900">
                <th className="pb-2 pr-3 w-8"></th>
                <th className="pb-2 pr-3">ID</th>
                <th className="pb-2 pr-3">Timestamp</th>
                <th className="pb-2 pr-3">Root</th>
                <th className="pb-2">Label</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.map((s) => (
                <tr
                  key={s.id}
                  className="border-t border-slate-800 hover:bg-slate-800/50"
                >
                  <td className="py-2 pr-3">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id)}
                      onChange={() => toggle(s.id)}
                      className="accent-blue-500"
                    />
                  </td>
                  <td className="py-2 pr-3 font-mono text-slate-400">
                    {s.id}
                  </td>
                  <td className="py-2 pr-3 text-slate-300">
                    {new Date(s.timestamp).toLocaleString()}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-500">
                    {s.root_path}
                  </td>
                  <td className="py-2 text-slate-500">{s.label || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
        </div>
      </Card>
    </div>
  );
}

function AuditTab() {
  const [logs, setLogs] = useState<DeletionLog[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .deletionHistory(200)
      .then(setLogs)
      .catch((err) => {
        toast({ type: "error", text: `Audit log failed: ${err?.message ?? err}` });
        setLogs([]);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    window.addEventListener("sldd:db-reset", load);
    return () => window.removeEventListener("sldd:db-reset", load);
  }, [load]);

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white">
          Deletion Audit Log
        </h3>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-50 rounded transition-colors"
        >
          <History size={12} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>
      {loading ? (
        <p className="text-slate-500 text-sm py-8 text-center">Loading…</p>
      ) : logs.length === 0 ? (
        <p className="text-slate-500 text-sm py-8 text-center">
          No deletions recorded yet. Deletions from this app are logged here.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 text-xs uppercase">
              <th className="pb-2 pr-3">Time</th>
              <th className="pb-2 pr-3">Path</th>
              <th className="pb-2 pr-3">Type</th>
              <th className="pb-2 pr-3 text-right">Freed</th>
              <th className="pb-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.id} className="border-t border-slate-800">
                <td className="py-2 pr-3 text-slate-400">
                  {new Date(l.timestamp).toLocaleString()}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-slate-300 truncate max-w-[300px]">
                  {l.path}
                </td>
                <td className="py-2 pr-3 text-slate-500">
                  {l.was_dir ? "Dir" : "File"}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-slate-400">
                  {formatBytesAbs(l.bytes_freed)}
                </td>
                <td className="py-2">
                  {l.success ? (
                    <span className="text-green-400 text-xs">OK</span>
                  ) : (
                    <span className="text-red-400 text-xs" title={l.error ?? ""}>
                      Failed
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
