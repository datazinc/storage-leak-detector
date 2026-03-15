import { useCallback, useEffect, useRef, useState } from "react";
import {
  Copy,
  Trash2,
  Loader2,
  Search,
  Square,
  CheckSquare,
  Pause,
  Play,
  ChevronDown,
  ChevronRight,
  FileIcon,
  AlertTriangle,
  ShieldOff,
} from "lucide-react";
import {
  api,
  formatBytesAbs,
  type ScanJobStatus,
  type DuplicatesResult,
  type DuplicateGroup,
} from "../api";
import { useScanContext } from "../context/ScanContext";
import { Card, StatCard } from "../components/Card";
import { CopyPathButton } from "../components/CopyPathButton";
import { DeleteConfirmModal } from "../components/DeleteConfirmModal";
import { PathPicker } from "../components/PathPicker";
import { ScanProgress } from "../components/ScanProgress";
import { toast } from "../components/Toast";

export function Duplicates() {
  const { activeJobs, setActiveJob, isScanTypeActive, getActiveJob } = useScanContext();
  const [result, setResult] = useState<DuplicatesResult | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanJobStatus | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [minSize, setMinSize] = useState(1024 * 100); // 100 KB
  const [depth, setDepth] = useState(6);
  const [scanRoot, setScanRoot] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoStartedRef = useRef(false);
  const completionToastShownRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollJob = useCallback((jobId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.scanStatus(jobId);
        setScanStatus(s);
        if (s.done) {
          stopPolling();
          setActiveJob("duplicates", null);
          if (!s.error) {
            const r = await api.scanResult<DuplicatesResult>(jobId);
            setResult(r);
            setExpanded(new Set(r.groups.slice(0, 5).map((g) => g.hash)));
            if (!completionToastShownRef.current) {
              completionToastShownRef.current = true;
              toast({
                type: "success",
                text: `Found ${r.total_groups} duplicate groups (${r.total_wasted_human} wasted)`,
              });
            }
          }
        }
      } catch { /* polling */ }
    }, 600);
  }, [stopPolling, setActiveJob]);

  const scan = useCallback(async () => {
    if (isScanTypeActive("duplicates")) {
      toast({ type: "warning", text: "Duplicates scan already running." });
      return;
    }
    stopPolling();
    completionToastShownRef.current = false;
    setResult(null);
    setSelected(new Set());
    setExpanded(new Set());
    setPage(0);
    try {
      const job = await api.startDuplicatesScan(minSize, depth, scanRoot.trim() || undefined);
      setScanStatus(job);
      setActiveJob("duplicates", job.id);
      pollJob(job.id);
    } catch (err: any) {
      setActiveJob("duplicates", null);
      toast({ type: "error", text: `Scan failed: ${err?.message ?? err}` });
    }
  }, [minSize, depth, scanRoot, stopPolling, isScanTypeActive, setActiveJob, pollJob]);

  useEffect(() => {
    const jobId = getActiveJob("duplicates");
    if (jobId) {
      api.scanStatus(jobId).then((s) => {
        setScanStatus(s);
        if (!s.done) pollJob(jobId);
        else {
          setActiveJob("duplicates", null);
          if (!s.error) api.scanResult<DuplicatesResult>(jobId).then((r) => {
            setResult(r);
            setExpanded(new Set(r.groups.slice(0, 5).map((g) => g.hash)));
          });
        }
      }).catch(() => setActiveJob("duplicates", null));
    } else if (result === null && !autoStartedRef.current) {
      autoStartedRef.current = true;
      scan();
    }
    return stopPolling;
  }, [activeJobs.duplicates, pollJob, setActiveJob, stopPolling, scan, result]);

  const toggleExpand = (hash: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });
  };

  const toggleFile = (path: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const selectAllDuplicates = (group: DuplicateGroup) => {
    setSelected((prev) => {
      const next = new Set(prev);
      // Select all except the first (keep one original)
      group.files.slice(1).forEach((f) => next.add(f.path));
      return next;
    });
  };

  const selectAllGroups = () => {
    if (!result) return;
    const next = new Set<string>();
    for (const g of result.groups) {
      g.files.slice(1).forEach((f) => next.add(f.path));
    }
    setSelected(next);
  };

  const selectPageGroups = () => {
    if (!result) return;
    const start = page * pageSize;
    const pageGroups = result.groups.slice(start, start + pageSize);
    setSelected((prev) => {
      const next = new Set(prev);
      for (const g of pageGroups) {
        g.files.slice(1).forEach((f) => next.add(f.path));
      }
      return next;
    });
  };

  const deselectAll = () => setSelected(new Set());

  const [blockedPaths, setBlockedPaths] = useState<string[]>([]);
  const [pendingDeletePaths, setPendingDeletePaths] = useState<string[]>([]);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deletePreview, setDeletePreview] = useState<{ paths: string[]; totalFiles: number; totalBytes: number } | null>(null);

  const executeDelete = async (paths: string[], force: boolean) => {
    setDeleting(true);
    try {
      const r = await api.deleteExecute(paths, false, force);
      if (r.failed.length > 0) {
        toast({ type: "error", text: `${r.failed.length} failed: ${r.failed[0][1]}` });
      }
      if (r.succeeded.length > 0) {
        toast({ type: "success", text: `Deleted ${r.succeeded.length} files, freed ${formatBytesAbs(r.bytes_freed)}` });
      }
      setSelected(new Set());
      setBlockedPaths([]);
      setPendingDeletePaths([]);
      setDeleteModalOpen(false);
      setDeletePreview(null);
    } catch (err: any) {
      toast({ type: "error", text: `Delete failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  };

  const deleteSelected = async () => {
    if (selected.size === 0) return;
    const paths = [...selected];
    setDeleting(true);
    try {
      const preview = await api.deletePreview(paths);
      if (preview.blocked_paths.length > 0) {
        setBlockedPaths(preview.blocked_paths);
        setPendingDeletePaths(paths);
        setDeleting(false);
        return;
      }
      setDeletePreview({
        paths,
        totalFiles: preview.total_files,
        totalBytes: preview.total_bytes,
      });
      setDeleteModalOpen(true);
    } catch (err: any) {
      toast({ type: "error", text: `Preview failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  };

  const confirmDelete = async () => {
    if (!deletePreview) return;
    await executeDelete(deletePreview.paths, false);
  };

  const deleteGroupDuplicates = async (group: DuplicateGroup) => {
    const paths = group.files.slice(1).map((f) => f.path);
    if (paths.length === 0) return;
    setDeleting(true);
    try {
      const preview = await api.deletePreview(paths);
      if (preview.blocked_paths.length > 0) {
        setBlockedPaths(preview.blocked_paths);
        setPendingDeletePaths(paths);
        setDeleting(false);
        return;
      }
      setDeletePreview({
        paths,
        totalFiles: preview.total_files,
        totalBytes: preview.total_bytes,
      });
      setDeleteModalOpen(true);
    } catch (err: any) {
      toast({ type: "error", text: `Preview failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  };

  const scanInProgress = scanStatus != null && !scanStatus.done;

  const selectedBytes = result
    ? result.groups.flatMap((g) => g.files)
        .filter((f) => selected.has(f.path))
        .reduce((sum, f) => {
          const group = result.groups.find((g) => g.files.some((gf) => gf.path === f.path));
          return sum + (group?.size_bytes ?? 0);
        }, 0)
    : 0;

  return (
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Copy size={20} className="text-purple-400" />
          <h2 className="text-xl font-semibold text-white">Duplicate Files</h2>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <label>Scan root</label>
            <PathPicker
              value={scanRoot}
              onChange={setScanRoot}
              placeholder="Use Settings default"
              allowEmpty={true}
              className="min-w-[200px]"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <label>Min size</label>
            <select
              value={minSize}
              onChange={(e) => setMinSize(Number(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
            >
              <option value={1024}>1 KB</option>
              <option value={1024 * 10}>10 KB</option>
              <option value={1024 * 100}>100 KB</option>
              <option value={1024 * 1024}>1 MB</option>
              <option value={1024 * 1024 * 10}>10 MB</option>
              <option value={1024 * 1024 * 100}>100 MB</option>
            </select>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <label>Depth</label>
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
            >
              <option value={3}>3</option>
              <option value={4}>4</option>
              <option value={6}>6</option>
              <option value={8}>8</option>
              <option value={10}>10</option>
              <option value={15}>15</option>
            </select>
          </div>
          {result && result.groups.length > 0 && !scanInProgress && (
            <button
              onClick={selectAllGroups}
              title="Select all duplicate copies (keeps one original per group)"
              className="flex items-center gap-2 px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg text-white font-medium transition-colors"
            >
              <CheckSquare size={14} />
              Select all duplicates
            </button>
          )}
          <button
            onClick={scan}
            disabled={scanInProgress}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded-lg text-white font-medium transition-colors"
          >
            {scanInProgress ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            {scanInProgress ? "Scanning..." : "Find Duplicates"}
          </button>
          {scanInProgress && scanStatus?.id && (
            <>
              {scanStatus.paused ? (
                <button
                  onClick={() => api.scanResume(scanStatus.id).then(setScanStatus)}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 rounded-lg text-white font-medium transition-colors"
                >
                  <Play size={14} />
                  Resume
                </button>
              ) : (
                <button
                  onClick={() => api.scanPause(scanStatus.id).then(setScanStatus)}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 rounded-lg text-white font-medium transition-colors"
                >
                  <Pause size={14} />
                  Pause
                </button>
              )}
              <button
                onClick={() => api.scanStop(scanStatus.id)}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 hover:bg-red-500 rounded-lg text-white font-medium transition-colors"
              >
                <Square size={14} />
                Stop
              </button>
            </>
          )}
        </div>
      </div>

      {/* Live scan progress */}
      {scanStatus && !scanStatus.done && (
        <ScanProgress status={scanStatus} />
      )}

      {/* Stats */}
      {result && (
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            label="Duplicate Groups"
            value={String(result.total_groups)}
            color="text-purple-400"
          />
          <StatCard
            label="Duplicate Files"
            value={String(result.total_duplicate_files)}
          />
          <StatCard
            label="Wasted Space"
            value={result.total_wasted_human}
            color="text-red-400"
          />
          <StatCard
            label="Selected"
            value={selected.size > 0 ? `${selected.size} (${formatBytesAbs(selectedBytes)})` : "None"}
            color={selected.size > 0 ? "text-blue-400" : "text-slate-500"}
          />
        </div>
      )}

      {/* Action bar */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-red-600/10 border border-red-500/20 rounded-lg px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-sm text-red-400">
              {selected.size} file{selected.size > 1 ? "s" : ""} selected —{" "}
              <span className="font-mono font-semibold">{formatBytesAbs(selectedBytes)}</span>
            </span>
            <button onClick={deselectAll} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
              Clear
            </button>
          </div>
          <button
            onClick={deleteSelected}
            disabled={deleting}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
          >
            {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Delete Selected
          </button>
        </div>
      )}

      {/* Force-delete warning */}
      {blockedPaths.length > 0 && (
        <div className="bg-amber-600/10 border border-amber-500/30 rounded-lg p-4 space-y-3">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-amber-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-300">
                {blockedPaths.length} path{blockedPaths.length > 1 ? "s" : ""} blocked by safety rules
              </p>
              <p className="text-xs text-slate-400 mt-1">
                These paths are normally protected (system directories, home folder root, etc).
                You can force-delete if you&apos;re sure.
              </p>
              <div className="mt-2 space-y-1">
                {blockedPaths.map((p) => (
                  <p key={p} className="font-mono text-xs text-amber-200/80">{p}</p>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 ml-8">
            <button
              onClick={() => { setBlockedPaths([]); setPendingDeletePaths([]); }}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => executeDelete(pendingDeletePaths, true)}
              disabled={deleting}
              className="flex items-center gap-2 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded-lg text-xs text-white font-medium transition-colors"
            >
              {deleting ? <Loader2 size={13} className="animate-spin" /> : <ShieldOff size={13} />}
              Force Delete All ({pendingDeletePaths.length})
            </button>
          </div>
        </div>
      )}

      {/* Bulk actions & pagination */}
      {result && result.groups.length > 0 && (() => {
        const totalPages = Math.ceil(result.groups.length / pageSize) || 1;
        const start = page * pageSize;
        const end = Math.min(start + pageSize, result.groups.length);

        return (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3 text-xs">
            {!scanInProgress && (
              <>
                <button
                  onClick={selectAllGroups}
                  className="text-purple-400 hover:text-purple-300 transition-colors"
                >
                  Select all
                </button>
                <button
                  onClick={selectPageGroups}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                >
                  Select page
                </button>
              </>
            )}
            <span className="text-slate-700">|</span>
            <button
              onClick={() => setExpanded(new Set(result.groups.map((g) => g.hash)))}
              className="text-slate-500 hover:text-slate-300 transition-colors"
            >
              Expand all
            </button>
            <button
              onClick={() => setExpanded(new Set())}
              className="text-slate-500 hover:text-slate-300 transition-colors"
            >
              Collapse all
            </button>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span>
              Groups {start + 1}–{end} of {result.groups.length}
            </span>
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-0.5 rounded hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ←
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-2 py-0.5 rounded hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              →
            </button>
          </div>
        </div>
        );
      })()}

      {/* Empty state — no scan yet */}
      {!result && !scanInProgress && (
        <Card className="text-center py-16">
          <div className="max-w-md mx-auto">
            <div className="p-4 rounded-full bg-slate-800 w-fit mx-auto mb-4">
              <Search size={32} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">Find duplicate files</h3>
            <p className="text-slate-400 text-sm mb-6">
              Scan your filesystem to find files with identical content. Adjust min size and depth, then click Find Duplicates.
            </p>
            <button
              onClick={scan}
              disabled={scanInProgress}
              className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
            >
              <Search size={16} />
              {scanInProgress ? "Scanning..." : "Find Duplicates"}
            </button>
          </div>
        </Card>
      )}

      {result && result.groups.length === 0 && (
        <Card className="text-center py-16">
          <p className="text-slate-400">No duplicates found with the current settings.</p>
          <p className="text-slate-600 text-sm mt-1">Try lowering the minimum file size or increasing depth.</p>
        </Card>
      )}

      {result && (() => {
        const start = page * pageSize;
        const end = Math.min(start + pageSize, result.groups.length);
        const pageGroups = result.groups.slice(start, end);
        return pageGroups.map((group) => {
        const isOpen = expanded.has(group.hash);
        const groupSelectedCount = group.files.filter((f) => selected.has(f.path)).length;

        return (
          <Card key={group.hash} className="!p-0 overflow-hidden">
            {/* Group header */}
            <div className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors gap-3">
              <button
                onClick={() => toggleExpand(group.hash)}
                className="flex-1 flex items-center gap-3 text-left min-w-0"
              >
                {isOpen ? <ChevronDown size={14} className="text-slate-500 shrink-0" /> : <ChevronRight size={14} className="text-slate-500 shrink-0" />}
                {group.files[0]?.name && (
                  <span className="text-sm text-slate-300 truncate max-w-[200px] sm:max-w-[280px]" title={group.files[0].path}>
                    {group.files[0].name}
                  </span>
                )}
                <span className="text-sm font-medium text-white shrink-0">
                  {group.count} copies
                </span>
                <span className="text-xs text-slate-500 font-mono">
                  {group.size_human} each
                </span>
                <span className="text-xs bg-red-500/15 text-red-400 px-2 py-0.5 rounded-full font-medium">
                  {group.wasted_human} wasted
                </span>
                {groupSelectedCount > 0 && (
                  <span className="text-xs bg-blue-500/15 text-blue-400 px-2 py-0.5 rounded-full">
                    {groupSelectedCount} selected
                  </span>
                )}
              </button>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] text-slate-600 font-mono hidden sm:inline">
                  sha256:{group.hash}
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteGroupDuplicates(group); }}
                  disabled={deleting || group.count <= 1}
                  className="flex items-center gap-1.5 px-2 py-1 text-xs bg-red-600/80 hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed rounded text-white font-medium transition-colors"
                >
                  <Trash2 size={12} />
                  Delete duplicates
                </button>
              </div>
            </div>

            {/* Expanded file list */}
            {isOpen && (
              <div className="border-t border-slate-800">
                <div className="px-4 py-2 flex items-center justify-between bg-slate-900/50">
                  <span className="text-[11px] text-slate-600">
                    First file is the original (kept). Others are duplicates.
                  </span>
                  {!scanInProgress && (
                    <button
                      onClick={() => selectAllDuplicates(group)}
                      className="text-[11px] text-purple-400 hover:text-purple-300 transition-colors"
                    >
                      Select duplicates
                    </button>
                  )}
                </div>
                {group.files.map((f, idx) => {
                  const isOriginal = idx === 0;
                  const isSel = selected.has(f.path);
                  return (
                    <div
                      key={f.path}
                      className={`flex items-center gap-3 px-4 py-2 border-t border-slate-800/50 cursor-pointer transition-colors ${
                        isSel ? "bg-blue-600/10 hover:bg-blue-600/15" : "hover:bg-slate-800/30"
                      } ${isOriginal ? "opacity-70" : ""}`}
                      onClick={() => !isOriginal && toggleFile(f.path)}
                    >
                      {isOriginal ? (
                        <div className="w-4 h-4 flex items-center justify-center">
                          <div className="w-2 h-2 rounded-full bg-green-500" title="Original (kept)" />
                        </div>
                      ) : (
                        <input
                          type="checkbox"
                          checked={isSel}
                          onChange={() => toggleFile(f.path)}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                        />
                      )}
                      <FileIcon size={13} className={isOriginal ? "text-green-500" : "text-slate-500"} />
                      <span className="text-xs text-slate-300 truncate flex-1" title={f.path}>
                        {f.name}
                      </span>
                      <span className="text-[11px] text-slate-600 font-mono truncate max-w-[300px]" title={f.directory}>
                        {f.directory}
                      </span>
                      <CopyPathButton path={f.path} className="shrink-0" />
                      {f.mtime && (
                        <span className="text-[11px] text-slate-600 shrink-0">
                          {new Date(f.mtime).toLocaleDateString([], { month: "short", day: "numeric", year: "2-digit" })}
                        </span>
                      )}
                      {isOriginal && (
                        <span className="text-[10px] bg-green-500/15 text-green-400 px-1.5 py-0.5 rounded font-medium shrink-0">
                          keep
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        );
      });
    })()}

      <DeleteConfirmModal
        open={deleteModalOpen}
        onClose={() => { setDeleteModalOpen(false); setDeletePreview(null); }}
        onConfirm={confirmDelete}
        paths={deletePreview?.paths ?? []}
        totalFiles={deletePreview?.totalFiles ?? 0}
        totalBytes={deletePreview?.totalBytes ?? 0}
        confirmLabel="Delete duplicates"
        loading={deleting}
        keepOnePerGroup={true}
      />
    </div>
  );
}
