import { AlertTriangle, Loader2, X } from "lucide-react";
import { formatBytesAbs } from "../api";

interface DeleteConfirmModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  paths: string[];
  totalFiles: number;
  totalBytes: number;
  confirmLabel?: string;
  loading?: boolean;
}

export function DeleteConfirmModal({
  open,
  onClose,
  onConfirm,
  paths,
  totalFiles,
  totalBytes,
  confirmLabel = "Delete permanently",
  loading = false,
}: DeleteConfirmModalProps) {
  if (!open) return null;

  const maxPathsShown = 10;
  const hasMore = paths.length > maxPathsShown;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-md w-full max-h-[85vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <AlertTriangle size={18} className="text-amber-400" />
            Confirm deletion
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-4 py-4 space-y-4 overflow-auto flex-1">
          <div className="bg-red-600/10 border border-red-500/20 rounded-lg p-3">
            <p className="text-sm font-medium text-red-400">
              This action cannot be undone.
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Files will be permanently removed from disk. There is no recycle bin.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs text-slate-500">Files to delete</p>
              <p className="font-mono text-white">{totalFiles.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Space to free</p>
              <p className="font-mono text-amber-400 font-medium">
                {formatBytesAbs(totalBytes)}
              </p>
            </div>
          </div>

          {paths.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 mb-2">
                Paths {hasMore ? `(showing first ${maxPathsShown} of ${paths.length})` : ""}
              </p>
              <div className="max-h-[160px] overflow-auto rounded border border-slate-800 bg-slate-950/50 p-2 font-mono text-xs text-slate-400 space-y-1">
                {paths.slice(0, maxPathsShown).map((p) => (
                  <div key={p} className="truncate" title={p}>
                    {p}
                  </div>
                ))}
                {hasMore && (
                  <div className="text-slate-600 pt-1">
                    … and {paths.length - maxPathsShown} more
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-slate-800 bg-slate-900/80">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg text-white font-medium transition-colors flex items-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Deleting…
              </>
            ) : (
              confirmLabel
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
