import { useCallback, useEffect, useRef, useState } from "react";
import {
  Trash2,
  Loader2,
  FileSearch,
  HardDrive,
  CheckSquare,
  Square,
  Pause,
  Play,
  AlertTriangle,
  ShieldOff,
} from "lucide-react";
import { api, formatBytesAbs, type LargeFile, type ScanJobStatus } from "../api";
import { useScanContext } from "../context/ScanContext";
import { Card, StatCard } from "../components/Card";
import { DeleteConfirmModal } from "../components/DeleteConfirmModal";
import { CopyPathButton } from "../components/CopyPathButton";
import { PathPicker } from "../components/PathPicker";
import { ResizableTable } from "../components/ResizableTable";
import { ScanProgress } from "../components/ScanProgress";
import { toast } from "../components/Toast";

const FILE_COLS = [
  { key: "sel", label: "", defaultWidth: 36, minWidth: 32 },
  { key: "rank", label: "#", defaultWidth: 36, minWidth: 30 },
  { key: "name", label: "File Name", minWidth: 120 },
  { key: "size", label: "Size", defaultWidth: 90, minWidth: 70, align: "right" as const },
  { key: "dir", label: "Directory", minWidth: 140 },
  { key: "mtime", label: "Modified", defaultWidth: 120, minWidth: 90 },
  { key: "copy", label: "", defaultWidth: 36, minWidth: 32 },
];

export function BiggestFiles() {
  const { activeJobs, setActiveJob, isScanTypeActive, getActiveJob } = useScanContext();
  const [files, setFiles] = useState<LargeFile[]>([]);
  const [scanStatus, setScanStatus] = useState<ScanJobStatus | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [limit, setLimit] = useState(500);
  const [depth, setDepth] = useState(6);
  const [scanRoot, setScanRoot] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoStartedRef = useRef(false);

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
          setActiveJob("biggest", null);
          if (!s.error) {
            const result = await api.scanResult<LargeFile[]>(jobId);
            setFiles(result);
            toast({
              type: "success",
              text: `Found ${result.length} files (${s.dirs_scanned.toLocaleString()} dirs, ${s.elapsed_seconds.toFixed(1)}s)`,
            });
          }
        }
      } catch { /* polling error, ignore */ }
    }, 500);
  }, [stopPolling, setActiveJob]);

  const scan = useCallback(async () => {
    if (isScanTypeActive("biggest")) {
      toast({ type: "warning", text: "Biggest Files scan already running." });
      return;
    }
    stopPolling();
    setFiles([]);
    setSelected(new Set());
    setPage(0);
    try {
      const job = await api.startLargestScan(limit, depth, scanRoot.trim() || undefined);
      setScanStatus(job);
      setActiveJob("biggest", job.id);
      pollJob(job.id);
    } catch (err: any) {
      setActiveJob("biggest", null);
      toast({ type: "error", text: `Scan failed: ${err?.message ?? err}` });
    }
  }, [limit, depth, scanRoot, stopPolling, isScanTypeActive, setActiveJob, pollJob]);

  useEffect(() => {
    const jobId = getActiveJob("biggest");
    if (jobId) {
      api.scanStatus(jobId).then((s) => {
        setScanStatus(s);
        if (!s.done) pollJob(jobId);
        else {
          setActiveJob("biggest", null);
          if (!s.error) api.scanResult<LargeFile[]>(jobId).then(setFiles);
        }
      }).catch(() => setActiveJob("biggest", null));
    } else if (files.length === 0 && !autoStartedRef.current) {
      autoStartedRef.current = true;
      scan();
    }
    return stopPolling;
  }, [activeJobs.biggest, pollJob, setActiveJob, stopPolling, scan, files.length]);

  const toggle = (path: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === files.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(files.map((f) => f.path)));
    }
  };

  const [blockedPaths, setBlockedPaths] = useState<string[]>([]);
  const [pendingDeletePaths, setPendingDeletePaths] = useState<string[]>([]);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deletePreview, setDeletePreview] = useState<{ paths: string[]; totalFiles: number; totalBytes: number } | null>(null);

  const executeDelete = async (paths: string[], force: boolean) => {
    setDeleting(true);
    try {
      const result = await api.deleteExecute(paths, false, force);
      if (result.failed.length > 0) {
        toast({ type: "error", text: `${result.failed.length} failed: ${result.failed[0][1]}` });
      }
      if (result.succeeded.length > 0) {
        toast({
          type: "success",
          text: `Deleted ${result.succeeded.length} files, freed ${formatBytesAbs(result.bytes_freed)}`,
        });
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

  const scanInProgress = scanStatus != null && !scanStatus.done;
  const selectedTotal = files
    .filter((f) => selected.has(f.path))
    .reduce((sum, f) => sum + f.size_bytes, 0);
  const totalSize = files.reduce((sum, f) => sum + f.size_bytes, 0);

  return (
    <div className="p-6 space-y-5 max-w-[1400px] min-w-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HardDrive size={20} className="text-blue-400" />
          <h2 className="text-xl font-semibold text-white">Biggest Files</h2>
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
            <label>Top</label>
            <select
              value={limit}
              onChange={(e) => { setLimit(Number(e.target.value)); setPage(0); }}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
            >
              <option value={100}>100</option>
              <option value={500}>500</option>
              <option value={1000}>1,000</option>
              <option value={2000}>2,000</option>
              <option value={5000}>5,000</option>
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
          <button
            onClick={scan}
            disabled={scanInProgress}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-white font-medium transition-colors"
          >
            {scanInProgress ? <Loader2 size={14} className="animate-spin" /> : <FileSearch size={14} />}
            {scanInProgress ? "Scanning..." : "Scan"}
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
      {files.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          <StatCard label="Files Found" value={String(files.length)} />
          <StatCard label="Combined Size" value={formatBytesAbs(totalSize)} color="text-amber-400" />
          <StatCard label="Largest File" value={files[0]?.size_human ?? "—"} sub={files[0]?.name ?? ""} color="text-red-400" />
          <StatCard
            label="Selected"
            value={selected.size > 0 ? `${selected.size} (${formatBytesAbs(selectedTotal)})` : "None"}
            color={selected.size > 0 ? "text-blue-400" : "text-slate-500"}
          />
        </div>
      )}

      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-red-600/10 border border-red-500/20 rounded-lg px-4 py-3">
          <span className="text-sm text-red-400">
            {selected.size} file{selected.size > 1 ? "s" : ""} selected —{" "}
            <span className="font-mono font-semibold">{formatBytesAbs(selectedTotal)}</span> will be freed
          </span>
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

      {files.length === 0 && !scanInProgress && (
        <Card className="text-center py-16">
          <div className="max-w-md mx-auto">
            <div className="p-4 rounded-full bg-slate-800 w-fit mx-auto mb-4">
              <FileSearch size={32} className="text-slate-500" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">Find largest files</h3>
            <p className="text-slate-400 text-sm mb-6">
              Scan your filesystem to discover the biggest files by size. Adjust depth and limit, then click Scan.
            </p>
            <button
              onClick={scan}
              disabled={scanInProgress}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
            >
              <FileSearch size={16} />
              {scanInProgress ? "Scanning..." : "Start Scan"}
            </button>
          </div>
        </Card>
      )}

      {files.length > 0 && (() => {
        const totalPages = Math.ceil(files.length / pageSize) || 1;
        const start = page * pageSize;
        const end = Math.min(start + pageSize, files.length);
        const pageFiles = files.slice(start, end);
        const pageSelected = new Set(pageFiles.map((f) => f.path).filter((p) => selected.has(p)));
        const allOnPageSelected = pageFiles.length > 0 && pageSelected.size === pageFiles.length;

        return (
        <Card>
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 className="text-sm font-semibold text-white">
              Files by Size <span className="text-slate-500 font-normal ml-1">(largest first)</span>
            </h3>
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (allOnPageSelected) {
                      pageFiles.forEach((f) => next.delete(f.path));
                    } else {
                      pageFiles.forEach((f) => next.add(f.path));
                    }
                    return next;
                  });
                }}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                {allOnPageSelected ? <CheckSquare size={13} /> : <Square size={13} />}
                {allOnPageSelected ? "Deselect page" : "Select page"}
              </button>
              <button
                onClick={toggleAll}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                {selected.size === files.length ? <CheckSquare size={13} /> : <Square size={13} />}
                {selected.size === files.length ? "Deselect all" : "Select all"}
              </button>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                </select>
                <span>
                  {start + 1}–{end} of {files.length}
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
          </div>
          <ResizableTable columns={FILE_COLS}>
            {pageFiles.map((f, i) => (
              <tr
                key={f.path}
                className={`border-t border-slate-800 cursor-pointer transition-colors ${
                  selected.has(f.path) ? "bg-blue-600/10 hover:bg-blue-600/20" : "hover:bg-slate-800/50"
                }`}
                onClick={() => toggle(f.path)}
              >
                <td className="py-2 pr-1 text-center" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(f.path)} onChange={() => toggle(f.path)}
                    className="rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-0 focus:ring-offset-0 cursor-pointer" />
                </td>
                <td className="py-2 pr-2 text-slate-600 text-xs font-mono">{start + i + 1}</td>
                <td className="py-2 pr-2 text-sm text-slate-200 truncate max-w-[300px]" title={f.path}>{f.name}</td>
                <td className="py-2 pr-2 text-right font-mono text-sm text-amber-400 font-medium whitespace-nowrap">{f.size_human}</td>
                <td className="py-2 pr-2 font-mono text-xs text-slate-500 truncate max-w-[300px]" title={f.directory}>{f.directory}</td>
                <td className="py-2 pr-2 text-xs text-slate-500 whitespace-nowrap">
                  {f.mtime ? new Date(f.mtime).toLocaleString([], { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                </td>
                <td className="py-1.5 pl-2">
                  <CopyPathButton path={f.path} />
                </td>
              </tr>
            ))}
          </ResizableTable>
        </Card>
        );
      })()}

      <DeleteConfirmModal
        open={deleteModalOpen}
        onClose={() => { setDeleteModalOpen(false); setDeletePreview(null); }}
        onConfirm={confirmDelete}
        paths={deletePreview?.paths ?? []}
        totalFiles={deletePreview?.totalFiles ?? 0}
        totalBytes={deletePreview?.totalBytes ?? 0}
        confirmLabel="Delete permanently"
        loading={deleting}
      />
    </div>
  );
}
