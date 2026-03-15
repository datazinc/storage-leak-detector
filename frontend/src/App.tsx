import { Component, useCallback, useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import {
  LayoutDashboard,
  Play,
  FolderTree,
  HardDrive,
  Copy,
  Trash2,
  Settings,
  Database,
  RotateCcw,
  AlertTriangle,
  Activity,
} from "lucide-react";
import { Dashboard } from "./views/Dashboard";
import { Playback } from "./views/Playback";
import { Explorer } from "./views/Explorer";
import { BiggestFiles } from "./views/BiggestFiles";
import { Duplicates } from "./views/Duplicates";
import { Deletion } from "./views/Deletion";
import { ProcessIO } from "./views/ProcessIO";
import { SettingsView } from "./views/Settings";
import { ToastContainer, ConnectionBanner, AdminBanner, AdminSuggestionBanner, toast } from "./components/Toast";
import { CorruptionBanner } from "./components/CorruptionBanner";
import { api, onConnectionChange } from "./api";
import { ScanProvider } from "./context/ScanContext";
import { AddToDeletionProvider } from "./context/AddToDeletionContext";

class RouteErrorBoundary extends Component<
  { children: React.ReactNode; path: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[sldd:nav] RouteErrorBoundary caught:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-6 text-red-400">
          <p className="font-medium">Something went wrong on this page.</p>
          <p className="text-sm text-slate-500 mt-1 font-mono">{this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/playback", icon: Play, label: "Playback" },
  { to: "/explorer", icon: FolderTree, label: "Explorer" },
  { to: "/biggest", icon: HardDrive, label: "Biggest Files" },
  { to: "/duplicates", icon: Copy, label: "Duplicates" },
  { to: "/deletion", icon: Trash2, label: "Deletion" },
  { to: "/process-io", icon: Activity, label: "Process I/O" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function DbFooter() {
  const [size, setSize] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [resetting, setResetting] = useState(false);

  const fetchSize = useCallback(async () => {
    try {
      const r = await api.dbSizeLive();
      setSize(r.total_human);
    } catch { /* noop */ }
  }, []);

  useEffect(() => {
    fetchSize();
    const id = setInterval(fetchSize, 15000);
    return () => clearInterval(id);
  }, [fetchSize]);

  useEffect(() => {
    if (!showConfirm) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowConfirm(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [showConfirm]);

  const doReset = async () => {
    setResetting(true);
    try {
      await api.resetDb();
      toast({ type: "success", text: "Database reset — all snapshot data cleared" });
      setShowConfirm(false);
      fetchSize();
      window.dispatchEvent(new CustomEvent("sldd:db-reset"));
    } catch (err: any) {
      toast({ type: "error", text: `Reset failed: ${err?.message ?? err}` });
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="px-4 py-3 border-t border-slate-800">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <Database size={11} />
          <span>DB: <span className="text-slate-400 font-mono">{size ?? "..."}</span></span>
        </div>
        <button
          onClick={() => setShowConfirm(true)}
          className="text-[11px] text-slate-600 hover:text-red-400 transition-colors flex items-center gap-1"
          title="Reset database"
        >
          <RotateCcw size={10} />
          Reset
        </button>
      </div>

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 w-[400px] shadow-2xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-full bg-red-500/10">
                <AlertTriangle size={20} className="text-red-400" />
              </div>
              <h3 className="text-base font-semibold text-white">Reset Database?</h3>
            </div>
            <p className="text-sm text-slate-400 mb-1">
              This will <span className="text-red-400 font-medium">permanently delete</span> all
              snapshot history, anomaly data, and tracking state.
            </p>
            <p className="text-xs text-slate-500 mb-4">
              The database currently uses <span className="font-mono text-slate-300">{size ?? "..."}</span>.
              This space will be freed.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={doReset}
                disabled={resetting}
                className="px-4 py-2 text-sm text-white bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg font-medium transition-colors"
              >
                {resetting ? "Resetting..." : "Delete All Data"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="text-[10px] text-slate-700 mt-1">v0.1.0</div>
    </div>
  );
}

function MainContent() {
  return (
    <main className="flex-1 overflow-auto">
      <Routes>
        <Route path="/" element={<RouteErrorBoundary path="/"><Dashboard /></RouteErrorBoundary>} />
        <Route path="/playback" element={<RouteErrorBoundary path="/playback"><Playback /></RouteErrorBoundary>} />
        <Route path="/explorer" element={<RouteErrorBoundary path="/explorer"><Explorer /></RouteErrorBoundary>} />
        <Route path="/biggest" element={<RouteErrorBoundary path="/biggest"><BiggestFiles /></RouteErrorBoundary>} />
        <Route path="/duplicates" element={<RouteErrorBoundary path="/duplicates"><Duplicates /></RouteErrorBoundary>} />
        <Route path="/deletion" element={<RouteErrorBoundary path="/deletion"><Deletion /></RouteErrorBoundary>} />
        <Route path="/process-io" element={<RouteErrorBoundary path="/process-io"><ProcessIO /></RouteErrorBoundary>} />
        <Route path="/settings" element={<RouteErrorBoundary path="/settings"><SettingsView /></RouteErrorBoundary>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </main>
  );
}

const ADMIN_HINT_CLOSED_KEY = "sldd:admin-hint-closed";

export default function App() {
  const [connected, setConnected] = useState(true);
  const [runningAsRoot, setRunningAsRoot] = useState(false);
  const [canRestartAsUser, setCanRestartAsUser] = useState(false);
  const [restartingAsUser, setRestartingAsUser] = useState(false);
  const [isWindows, setIsWindows] = useState(false);
  const [canRestartAsAdmin, setCanRestartAsAdmin] = useState(false);
  const [restartingAsAdmin, setRestartingAsAdmin] = useState(false);
  const [adminHintClosed, setAdminHintClosed] = useState(() =>
    typeof localStorage !== "undefined" && localStorage.getItem(ADMIN_HINT_CLOSED_KEY) === "1"
  );

  useEffect(() => {
    api.runningAsRoot().then((r) => setRunningAsRoot(r.running_as_root)).catch(() => {});
  }, []);

  useEffect(() => {
    if (runningAsRoot) {
      api.canRestartAsRegularUser().then((r) => {
        setCanRestartAsUser(r.can_restart);
        setIsWindows(r.reason === "Windows");
      }).catch(() => {});
      setCanRestartAsAdmin(false);
    } else {
      setCanRestartAsUser(false);
      api.canRestartAsAdministrator().then((r) => setCanRestartAsAdmin(r.can_restart)).catch(() => {});
    }
  }, [runningAsRoot]);

  const handleRestartAsUser = useCallback(async () => {
    setRestartingAsUser(true);
    try {
      const res = await api.restartAsRegularUser();
      toast({ type: "success", text: "Restarting as regular user…" });
      const newUrl = res?.url;
      const delay = 4000; // server starts after ~3s
      if (newUrl) {
        setTimeout(() => (window.location.href = newUrl), delay);
      } else {
        setTimeout(() => window.location.reload(), delay);
      }
    } catch (err: any) {
      toast({
        type: "error",
        text: `${err?.message ?? "Restart failed"}. Close the app and run sldd web as a regular user.`,
        timeout: 8000,
      });
      setRestartingAsUser(false);
    }
  }, []);

  const handleRestartAsAdmin = useCallback(async () => {
    setRestartingAsAdmin(true);
    try {
      const res = await api.restartAsAdministrator();
      toast({ type: "success", text: "Restarting with administrator privileges…" });
      const newUrl = res?.url;
      const delay = 4000;
      if (newUrl) {
        setTimeout(() => (window.location.href = newUrl), delay);
      } else {
        setTimeout(() => window.location.reload(), delay);
      }
    } catch (err: any) {
      toast({
        type: "error",
        text: `${err?.message ?? "Restart failed"}. Run sldd web as administrator manually.`,
        timeout: 8000,
      });
      setRestartingAsAdmin(false);
    }
  }, []);

  const closeAdminHint = useCallback(() => {
    setAdminHintClosed(true);
    localStorage.setItem(ADMIN_HINT_CLOSED_KEY, "1");
  }, []);

  useEffect(() => {
    const unsub = onConnectionChange(setConnected);

    const handler = (e: PromiseRejectionEvent) => {
      e.preventDefault();
      const msg = e.reason?.message ?? String(e.reason);
      if (msg.includes("Network error") || msg.includes("ECONNREFUSED")) {
        return;
      }
      toast({ type: "error", text: msg });
    };
    window.addEventListener("unhandledrejection", handler);
    return () => {
      unsub();
      window.removeEventListener("unhandledrejection", handler);
    };
  }, []);

  return (
    <ScanProvider>
    <AddToDeletionProvider>
    <BrowserRouter>
      <ToastContainer />
      <CorruptionBanner />
      <div className="flex flex-col h-screen overflow-hidden">
        {!isWindows && (
          <AdminBanner
            runningAsRoot={runningAsRoot}
            canRestart={canRestartAsUser}
            onRestartAsUser={handleRestartAsUser}
            restarting={restartingAsUser}
          />
        )}
        <AdminSuggestionBanner
          runningAsRoot={runningAsRoot}
          closed={adminHintClosed}
          onClose={closeAdminHint}
          canRestartAsAdmin={canRestartAsAdmin}
          onRestartAsAdmin={handleRestartAsAdmin}
          restartingAsAdmin={restartingAsAdmin}
        />
        <ConnectionBanner connected={connected} />
        <div className="flex flex-1 overflow-hidden">
          <aside className="w-56 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
            <div className="px-5 py-5 border-b border-slate-800">
              <h1 className="text-lg font-bold tracking-tight text-white">
                sldd
              </h1>
              <p className="text-[11px] text-slate-500 mt-0.5">
                Storage Leak Diff Detector
              </p>
            </div>
            <nav className="flex-1 py-3 px-3 space-y-0.5">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                      isActive
                        ? "bg-blue-600/20 text-blue-400"
                        : "text-slate-400 hover:text-white hover:bg-slate-800"
                    }`
                  }
                >
                  <n.icon size={18} />
                  {n.label}
                </NavLink>
              ))}
            </nav>
            <DbFooter />
          </aside>

          <MainContent />
        </div>
      </div>
    </BrowserRouter>
    </AddToDeletionProvider>
    </ScanProvider>
  );
}
