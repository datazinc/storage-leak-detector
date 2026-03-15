import { FolderSearch, FileCheck, Hash, Loader2, CheckCircle, XCircle } from "lucide-react";
import type { ScanJobStatus } from "../api";

const PHASE_CONFIG: Record<string, { icon: typeof Loader2; label: string; color: string }> = {
  starting: { icon: Loader2, label: "Starting scan...", color: "text-blue-400" },
  walking: { icon: FolderSearch, label: "Walking file system", color: "text-blue-400" },
  sizing: { icon: FolderSearch, label: "Collecting file sizes", color: "text-blue-400" },
  sorting: { icon: FileCheck, label: "Sorting results", color: "text-emerald-400" },
  partial_hash: { icon: Hash, label: "Partial hashing (4KB)", color: "text-amber-400" },
  full_hash: { icon: Hash, label: "Full hashing", color: "text-orange-400" },
  building_results: { icon: FileCheck, label: "Building results", color: "text-emerald-400" },
  done: { icon: CheckCircle, label: "Complete", color: "text-green-400" },
  error: { icon: XCircle, label: "Failed", color: "text-red-400" },
};

interface Props {
  status: ScanJobStatus;
}

export function ScanProgress({ status }: Props) {
  const cfg = PHASE_CONFIG[status.phase] ?? PHASE_CONFIG.starting;
  const Icon = cfg.icon;
  const spinning = !status.done;

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
      {/* Phase header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Icon
            size={16}
            className={`${cfg.color} ${spinning ? "animate-pulse" : ""}`}
          />
          <span className={`text-sm font-medium ${cfg.color}`}>{cfg.label}</span>
        </div>
        <span className="text-xs text-slate-500 font-mono">
          {status.elapsed_seconds.toFixed(1)}s
        </span>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-5 text-xs text-slate-400">
        <span>
          Dirs: <span className="text-white font-mono">{status.dirs_scanned.toLocaleString()}</span>
        </span>
        <span>
          Files: <span className="text-white font-mono">{status.files_checked.toLocaleString()}</span>
        </span>
        {status.detail && (
          <span className="text-slate-500">
            {status.detail}
          </span>
        )}
      </div>

      {/* Current path */}
      {status.current_path && !status.done && (
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse shrink-0" />
          <span
            className="text-[11px] text-slate-500 font-mono truncate"
            title={status.current_path}
          >
            {status.current_path}
          </span>
        </div>
      )}

      {/* Error */}
      {status.error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded-lg px-3 py-2">
          {status.error}
        </div>
      )}
    </div>
  );
}
