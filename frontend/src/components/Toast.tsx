import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, CheckCircle, XCircle, X, WifiOff } from "lucide-react";

export interface ToastMessage {
  id: string;
  type: "error" | "warning" | "success" | "info";
  text: string;
  timeout?: number;
}

let _pushToast: ((msg: Omit<ToastMessage, "id">) => void) | null = null;

export function toast(msg: Omit<ToastMessage, "id">) {
  _pushToast?.(msg);
}

const ICONS = {
  error: XCircle,
  warning: AlertTriangle,
  success: CheckCircle,
  info: AlertTriangle,
};
const COLORS = {
  error: "bg-red-900/80 border-red-700 text-red-200",
  warning: "bg-amber-900/80 border-amber-700 text-amber-200",
  success: "bg-green-900/80 border-green-700 text-green-200",
  info: "bg-blue-900/80 border-blue-700 text-blue-200",
};

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const push = useCallback((msg: Omit<ToastMessage, "id">) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => {
      if (prev.length > 4) return [...prev.slice(-4), { ...msg, id }];
      return [...prev, { ...msg, id }];
    });
    const ms = msg.timeout ?? (msg.type === "error" ? 8000 : 4000);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), ms);
  }, []);

  useEffect(() => {
    _pushToast = push;
    return () => { _pushToast = null; };
  }, [push]);

  if (!toasts.length) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map((t) => {
        const Icon = ICONS[t.type];
        return (
          <div
            key={t.id}
            className={`flex items-start gap-2 px-4 py-3 rounded-lg border backdrop-blur-sm text-sm shadow-lg animate-slide-in ${COLORS[t.type]}`}
          >
            <Icon size={16} className="mt-0.5 shrink-0" />
            <span className="flex-1">{t.text}</span>
            <button
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
              className="shrink-0 opacity-60 hover:opacity-100"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function ConnectionBanner({ connected }: { connected: boolean }) {
  if (connected) return null;
  return (
    <div className="bg-red-900/60 border-b border-red-800 px-4 py-2 flex items-center gap-2 text-red-200 text-sm">
      <WifiOff size={14} />
      <span>Backend unavailable — retrying automatically...</span>
    </div>
  );
}
