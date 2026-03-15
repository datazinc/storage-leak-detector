import { useCallback, useEffect, useState } from "react";
import { Trash2, Loader2, AlertTriangle, ShieldOff } from "lucide-react";
import { api, formatBytesAbs } from "../api";
import { toast } from "../components/Toast";

type Props = {
  path: string;
  onDeleted?: () => void;
  size?: "sm" | "md";
};

export function DeletePathButton({ path, onDeleted, size = "sm" }: Props) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [preview, setPreview] = useState<{ total_files: number; total_bytes: number } | null>(null);

  const fetchPreview = useCallback(async () => {
    setDeleting(true);
    setPreview(null);
    setBlocked(false);
    try {
      const p = await api.deletePreview([path]);
      if (p.blocked_paths.length > 0) {
        setBlocked(true);
      } else {
        setPreview({ total_files: p.total_files, total_bytes: p.total_bytes });
      }
    } catch (err: any) {
      toast({ type: "error", text: `Preview failed: ${err?.message ?? err}` });
    } finally {
      setDeleting(false);
    }
  }, [path]);

  useEffect(() => {
    if (open && !preview && !blocked) fetchPreview();
  }, [open, preview, blocked, fetchPreview]);

  const executeDelete = async (force: boolean) => {
    setDeleting(true);
    try {
      const r = await api.deleteExecute([path], false, force);
      if (r.succeeded.length > 0) {
        toast({ type: "success", text: `Deleted ${r.succeeded.length} items, freed ${formatBytesAbs(r.bytes_freed)}` });
        setOpen(false);
        setPreview(null);
        setBlocked(false);
        onDeleted?.();
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

  const btnClass = size === "sm"
    ? "p-1.5 rounded hover:bg-red-600/20 text-slate-500 hover:text-red-400 transition-colors"
    : "px-2 py-1 text-xs rounded bg-red-600/80 hover:bg-red-600 text-white transition-colors";

  return (
    <>
      <button
        onClick={() => {
          setPreview(null);
          setBlocked(false);
          setOpen(true);
        }}
        className={btnClass}
        title="Delete path"
      >
        <Trash2 size={size === "sm" ? 14 : 12} />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setOpen(false)}>
          <div
            className="bg-slate-900 border border-slate-700 rounded-xl p-5 w-[400px] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-white mb-2">Delete path?</h3>
            <p className="font-mono text-xs text-slate-400 break-all mb-4">{path}</p>
            {blocked ? (
              <div className="space-y-3">
                <p className="text-sm text-amber-400 flex items-center gap-2">
                  <AlertTriangle size={16} /> Path blocked by safety rules
                </p>
                <p className="text-xs text-slate-500">Force delete if you&apos;re sure.</p>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setOpen(false)} className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                  <button onClick={() => executeDelete(true)} disabled={deleting} className="flex items-center gap-2 px-3 py-1.5 text-sm bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded-lg">
                    {deleting ? <Loader2 size={14} className="animate-spin" /> : <ShieldOff size={14} />}
                    Force Delete
                  </button>
                </div>
              </div>
            ) : preview ? (
              <div className="space-y-3">
                <p className="text-sm text-slate-300">
                  {preview.total_files} files, {formatBytesAbs(preview.total_bytes)} will be permanently deleted.
                </p>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setOpen(false)} className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                  <button onClick={() => executeDelete(false)} disabled={deleting} className="flex items-center gap-2 px-3 py-1.5 text-sm bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg">
                    {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    Delete
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-slate-500">
                <Loader2 size={16} className="animate-spin" />
                <span className="text-sm">Loading preview...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
