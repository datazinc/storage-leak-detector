import { useCallback, useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { api, type PathIOSummary } from "../api";
import { Card } from "../components/Card";
import { PathInspectButton } from "../components/PathInspectButton";
import { ResizableTable } from "../components/ResizableTable";
import { toast } from "../components/Toast";

const PROCESS_IO_COLS = [
  { key: "path", label: "Path", minWidth: 150 },
  { key: "last", label: "Last sample", defaultWidth: 110, minWidth: 90 },
  { key: "samples", label: "Samples", defaultWidth: 80, minWidth: 60, align: "right" as const },
  { key: "actions", label: "", defaultWidth: 48, minWidth: 40 },
];

export function ProcessIO() {
  const [summary, setSummary] = useState<PathIOSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.pathIoSummary(50);
      setSummary(data);
    } catch (err: unknown) {
      toast({
        type: "error",
        text: `Load failed: ${(err as Error)?.message ?? err}`,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffM = Math.floor(diffMs / 60000);
      if (diffM < 1) return "just now";
      if (diffM < 60) return `${diffM}m ago`;
      const diffH = Math.floor(diffM / 60);
      if (diffH < 24) return `${diffH}h ago`;
      return d.toLocaleDateString();
    } catch {
      return ts;
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1400px] min-w-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-600/20">
            <Activity size={24} className="text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">Process I/O</h1>
            <p className="text-sm text-slate-500">
              Paths with I/O samples — inspect which processes are writing
            </p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 text-sm text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-50 rounded-lg transition-colors"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <Card>
        {loading ? (
          <div className="py-12 text-center text-slate-500">Loading...</div>
        ) : summary.length === 0 ? (
          <div className="py-12 text-center text-slate-500">
            <Activity size={32} className="mx-auto mb-3 opacity-50" />
            <p>No I/O samples yet.</p>
            <p className="text-xs mt-1">
              Use Inspect on paths in Dashboard or Playback to collect data, or
              run a watch scan.
            </p>
          </div>
        ) : (
          <ResizableTable columns={PROCESS_IO_COLS}>
            {summary.map((s) => (
              <tr
                key={s.path}
                className="border-t border-slate-800 hover:bg-slate-800/50"
              >
                <td className="py-2 pr-2 font-mono text-xs text-slate-300 truncate" title={s.path}>
                  {s.path}
                </td>
                <td className="py-2 pr-2 text-slate-400">
                  {formatTime(s.last_timestamp)}
                </td>
                <td className="py-2 pr-2 text-right text-slate-400">
                  {s.sample_count.toLocaleString()}
                </td>
                <td className="py-1.5 pl-2">
                  <PathInspectButton path={s.path} />
                </td>
              </tr>
            ))}
          </ResizableTable>
        )}
      </Card>
    </div>
  );
}
