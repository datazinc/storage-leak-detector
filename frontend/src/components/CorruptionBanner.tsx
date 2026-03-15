import { useEffect, useState } from "react";
import { AlertTriangle, RotateCcw, RefreshCw } from "lucide-react";
import { api } from "../api";

interface CorruptionState {
  recovered: boolean;
  detail: string;
}

export function CorruptionBanner() {
  const [state, setState] = useState<CorruptionState | null>(null);

  useEffect(() => {
    const handler = (e: CustomEvent<CorruptionState>) => {
      setState(e.detail);
    };
    window.addEventListener("sldd:db-corrupted", handler as EventListener);
    return () => window.removeEventListener("sldd:db-corrupted", handler as EventListener);
  }, []);

  const doReset = async () => {
    try {
      await api.resetDb();
      window.dispatchEvent(new CustomEvent("sldd:db-reset"));
      setState(null);
      window.location.reload();
    } catch (err: unknown) {
      console.error("Reset failed:", err);
    }
  };

  const doRefresh = () => {
    setState(null);
    window.location.reload();
  };

  if (!state) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-amber-900/95 border-b border-amber-600 px-4 py-3 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <AlertTriangle size={20} className="text-amber-400 shrink-0" />
        <p className="text-sm text-amber-100 truncate">{state.detail}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {state.recovered ? (
          <button
            onClick={doRefresh}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded text-sm font-medium transition-colors"
            title="Reload the page (database was already wiped)"
          >
            <RefreshCw size={14} />
            Refresh page
          </button>
        ) : (
          <button
            onClick={doReset}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded text-sm font-medium transition-colors"
          >
            <RotateCcw size={14} />
            Reset Database
          </button>
        )}
      </div>
    </div>
  );
}
