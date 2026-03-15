import { useEffect, useState } from "react";
import { Save, Database, Loader2, Zap, RotateCcw, Archive, Target, Pause as PauseIcon, Activity } from "lucide-react";
import { api, formatBytesAbs, type DbInfo, type AdaptiveStats, type TrackedPath } from "../api";
import { Card } from "../components/Card";
import { PathPicker } from "../components/PathPicker";
import { toast } from "../components/Toast";

export function SettingsView() {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [dbInfo, setDbInfo] = useState<DbInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [vacuuming, setVacuuming] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings({
        "scan.root": "/",
        "scan.excludes": "/proc,/sys,/dev,/run",
        "scan.max_depth": "",
        "scan.follow_symlinks": "false",
        "scan.cross_devices": "false",
        "scan.skip_unchanged_minutes": "",
        "detect.abs_threshold_mb": "500",
        "detect.growth_rate_mb_per_hour": "200",
        "detect.relative_threshold_pct": "100",
        "detect.stddev_factor": "2.0",
        "detect.min_size_mb": "10",
        "watch.interval_seconds": "600",
        "watch.max_snapshots_kept": "144",
        "replay.focus_path": "",
        ...s,
      });
    }).catch((err) => toast({ type: "error", text: `Settings load failed: ${err?.message ?? err}` }));
    api.dbInfo().then(setDbInfo).catch((err) =>
      toast({ type: "error", text: `DB info failed: ${err?.message ?? err}` }),
    );
  }, []);

  const update = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.saveSettings(settings);
      setSaved(true);
      toast({ type: "success", text: "Settings saved" });
    } catch (err: any) {
      toast({ type: "error", text: `Save failed: ${err?.message ?? err}` });
    } finally {
      setSaving(false);
    }
  };

  const doVacuum = async () => {
    setVacuuming(true);
    try {
      await api.vacuum();
      const info = await api.dbInfo();
      setDbInfo(info);
      toast({ type: "success", text: "Database compacted" });
    } catch (err: any) {
      toast({ type: "error", text: `Vacuum failed: ${err?.message ?? err}` });
    } finally {
      setVacuuming(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[900px] min-w-0">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Settings</h2>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm text-white font-medium transition-colors"
        >
          {saving ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Save size={14} />
          )}
          {saved ? "Saved!" : "Save Settings"}
        </button>
      </div>

      <Card>
        <h3 className="text-sm font-semibold text-white mb-4">
          Scan Configuration
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Root Path</label>
            <PathPicker
              value={settings["scan.root"] ?? "/"}
              onChange={(v) => update("scan.root", v)}
              placeholder="/"
              allowEmpty={false}
            />
            <p className="text-[11px] text-slate-600 mt-1">
              Used for watch, snapshots, Duplicates, Biggest Files.
            </p>
          </div>
          <Field
            label="Exclude Paths (comma-separated)"
            value={settings["scan.excludes"] ?? ""}
            onChange={(v) => update("scan.excludes", v)}
          />
          <Field
            label="Max Depth (blank = unlimited)"
            value={settings["scan.max_depth"] ?? ""}
            onChange={(v) => update("scan.max_depth", v)}
            type="number"
          />
          <Toggle
            label="Follow Symlinks"
            value={settings["scan.follow_symlinks"] === "true"}
            onChange={(v) =>
              update("scan.follow_symlinks", v ? "true" : "false")
            }
          />
          <Toggle
            label="Cross Device Boundaries"
            value={settings["scan.cross_devices"] === "true"}
            onChange={(v) =>
              update("scan.cross_devices", v ? "true" : "false")
            }
          />
          <Field
            label="Skip Unchanged (minutes, blank = off)"
            value={settings["scan.skip_unchanged_minutes"] ?? ""}
            onChange={(v) => update("scan.skip_unchanged_minutes", v)}
            type="number"
            hint="Skip directories whose mtime hasn't changed within this many minutes."
          />
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-white mb-4">
          Detection Thresholds
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <Field
            label="Absolute Growth Threshold (MB)"
            value={settings["detect.abs_threshold_mb"] ?? "500"}
            onChange={(v) => update("detect.abs_threshold_mb", v)}
            type="number"
          />
          <Field
            label="Growth Rate Threshold (MB/hour)"
            value={settings["detect.growth_rate_mb_per_hour"] ?? "200"}
            onChange={(v) => update("detect.growth_rate_mb_per_hour", v)}
            type="number"
          />
          <Field
            label="Relative Growth Threshold (%)"
            value={settings["detect.relative_threshold_pct"] ?? "100"}
            onChange={(v) => update("detect.relative_threshold_pct", v)}
            type="number"
          />
          <Field
            label="Statistical Deviation Factor (sigma)"
            value={settings["detect.stddev_factor"] ?? "2.0"}
            onChange={(v) => update("detect.stddev_factor", v)}
            type="number"
          />
          <Field
            label="Minimum Directory Size (MB)"
            value={settings["detect.min_size_mb"] ?? "10"}
            onChange={(v) => update("detect.min_size_mb", v)}
            type="number"
          />
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-white mb-4">Replay & Focus</h3>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Replay path filter (optional)</label>
            <PathPicker
              value={settings["replay.focus_path"] ?? ""}
              onChange={(v) => update("replay.focus_path", v)}
              placeholder="All paths"
              allowEmpty={true}
            />
            <p className="text-[11px] text-slate-600 mt-1">
              Default path filter for Playback.
            </p>
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-white mb-1">Watch Mode</h3>
        <p className="text-xs text-slate-500 mb-4">
          Background monitoring: scans at the interval below, compares snapshots, and flags abnormal growth. Use when your disk fills up over time and you need to find the culprit.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <Field
            label="Scan Interval (seconds)"
            value={settings["watch.interval_seconds"] ?? "600"}
            onChange={(v) => update("watch.interval_seconds", v)}
            type="number"
          />
          <Field
            label="Max Snapshots to Keep"
            value={settings["watch.max_snapshots_kept"] ?? "144"}
            onChange={(v) => update("watch.max_snapshots_kept", v)}
            type="number"
          />
        </div>
      </Card>

      <AdaptiveSection settings={settings} update={update} />

      <Card>
        <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Database size={16} />
          Database
        </h3>
        {dbInfo ? (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <p className="text-xs text-slate-500">Path</p>
                <p className="font-mono text-white text-xs break-all">
                  {dbInfo.path}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Size</p>
                <p className="font-mono text-white">
                  {formatBytesAbs(dbInfo.size_bytes)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Snapshots</p>
                <p className="font-mono text-white">{dbInfo.snapshot_count}</p>
              </div>
            </div>
            <button
              onClick={doVacuum}
              disabled={vacuuming}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded text-xs text-white transition-colors"
            >
              {vacuuming ? <Loader2 size={12} className="animate-spin" /> : <Database size={12} />}
              {vacuuming ? "Compacting..." : "Compact Database"}
            </button>
          </div>
        ) : (
          <p className="text-slate-500">Loading...</p>
        )}
      </Card>
    </div>
  );
}

function AdaptiveSection({
  settings,
  update,
}: {
  settings: Record<string, string>;
  update: (key: string, value: string) => void;
}) {
  const [stats, setStats] = useState<AdaptiveStats | null>(null);
  const [paths, setPaths] = useState<TrackedPath[]>([]);
  const [pathFilter, setPathFilter] = useState<string>("all");
  const [compacting, setCompacting] = useState(false);

  const loadStats = () => {
    api.adaptiveStats().then(setStats).catch(() => {});
    api.adaptivePaths(pathFilter === "all" ? undefined : pathFilter, 100)
      .then(setPaths).catch(() => {});
  };

  useEffect(() => { loadStats(); }, [pathFilter]);

  const doCompact = async () => {
    setCompacting(true);
    try {
      const r = await api.adaptiveCompact();
      toast({
        type: "success",
        text: `Compacted: ${r.entries_removed} entries removed, ${r.paths_collapsed} subtrees collapsed`,
      });
      loadStats();
    } catch (err: any) {
      toast({ type: "error", text: `Compact failed: ${err?.message ?? err}` });
    } finally {
      setCompacting(false);
    }
  };

  const doReset = async () => {
    try {
      await api.adaptiveReset();
      toast({ type: "success", text: "Adaptive tracking reset" });
      loadStats();
    } catch (err: any) {
      toast({ type: "error", text: `Reset failed: ${err?.message ?? err}` });
    }
  };

  const STATUS_ICONS: Record<string, typeof Activity> = {
    focus: Target,
    stable: PauseIcon,
    active: Activity,
  };
  const STATUS_COLORS: Record<string, string> = {
    focus: "text-red-400",
    stable: "text-green-400",
    active: "text-slate-400",
  };

  return (
    <Card>
      <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        <Zap size={16} />
        Adaptive Scanning
      </h3>
      <p className="text-xs text-slate-500 mb-4">
        Start shallow, focus on what changes, discard the rest.
        In <strong>auto</strong> mode, the scanner begins at a shallow depth and
        progressively drills deeper only into directories that are growing.
        Stable paths are compacted out of the database to save space.
      </p>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Mode</label>
          <select
            value={settings["adaptive.mode"] ?? "auto"}
            onChange={(e) => update("adaptive.mode", e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
          >
            <option value="auto">Auto (recommended)</option>
            <option value="full">Full (scan everything)</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
        <Field
          label="Initial Depth"
          value={settings["adaptive.initial_depth"] ?? "3"}
          onChange={(v) => update("adaptive.initial_depth", v)}
          type="number"
          hint="Depth for discovery scans. Lower = faster + less storage."
        />
        <Field
          label="Stability Threshold (scans)"
          value={settings["adaptive.stability_scans"] ?? "3"}
          onChange={(v) => update("adaptive.stability_scans", v)}
          type="number"
          hint="How many unchanged scans before marking a path stable."
        />
        <Field
          label="Retain Snapshots"
          value={settings["adaptive.retain_snapshots"] ?? "5"}
          onChange={(v) => update("adaptive.retain_snapshots", v)}
          type="number"
          hint="Number of recent snapshots to keep."
        />
        <Field
          label="Rediscovery Interval"
          value={settings["adaptive.rediscovery_every"] ?? "10"}
          onChange={(v) => update("adaptive.rediscovery_every", v)}
          type="number"
          hint="Full discovery scan every N scans."
        />
        <Toggle
          label="Auto-compact"
          value={(settings["adaptive.auto_compact"] ?? "true") === "true"}
          onChange={(v) => update("adaptive.auto_compact", v ? "true" : "false")}
        />
      </div>

      {stats && (
        <div className="bg-slate-800/50 rounded-lg p-4 mb-4">
          <div className="grid grid-cols-4 gap-3 text-sm mb-3">
            <div>
              <p className="text-xs text-slate-500">Scan #</p>
              <p className="font-mono text-white">{stats.scan_number}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Tracked Paths</p>
              <p className="font-mono text-white">{stats.total_tracked_paths}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">DB Entries</p>
              <p className="font-mono text-white">{stats.total_entries.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Baseline</p>
              <p className="font-mono text-white">
                {stats.baseline_snapshot_id ? `#${stats.baseline_snapshot_id}` : "—"}
              </p>
            </div>
          </div>

          <div className="flex gap-4 text-xs mb-3">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
              Focus: {stats.focus_paths}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
              Stable: {stats.stable_paths}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block" />
              Active: {stats.active_paths}
            </span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={doCompact}
              disabled={compacting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded text-xs text-white transition-colors"
            >
              {compacting ? <Loader2 size={12} className="animate-spin" /> : <Archive size={12} />}
              {compacting ? "Compacting..." : "Compact Now"}
            </button>
            <button
              onClick={doReset}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs text-white transition-colors"
            >
              <RotateCcw size={12} />
              Reset Tracking
            </button>
            <button
              onClick={loadStats}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs text-white transition-colors"
            >
              Refresh
            </button>
          </div>
        </div>
      )}

      {stats && stats.total_tracked_paths > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <p className="text-xs text-slate-500">Tracked Paths</p>
            <select
              value={pathFilter}
              onChange={(e) => setPathFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white"
            >
              <option value="all">All</option>
              <option value="focus">Focus (growing)</option>
              <option value="stable">Stable</option>
              <option value="active">Active</option>
            </select>
          </div>
          <div className="max-h-[250px] overflow-auto rounded border border-slate-800">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 uppercase sticky top-0 bg-slate-900">
                  <th className="pb-1 px-2 pt-1">Status</th>
                  <th className="pb-1 px-2 pt-1">Path</th>
                  <th className="pb-1 px-2 pt-1 text-right">Size</th>
                  <th className="pb-1 px-2 pt-1 text-right">Stable #</th>
                </tr>
              </thead>
              <tbody>
                {paths.map((p) => {
                  const Icon = STATUS_ICONS[p.status] || Activity;
                  const color = STATUS_COLORS[p.status] || "text-slate-400";
                  return (
                    <tr key={p.path} className="border-t border-slate-800/50">
                      <td className={`py-1 px-2 ${color}`}>
                        <Icon size={12} className="inline mr-1" />
                        {p.status}
                      </td>
                      <td className="py-1 px-2 font-mono text-slate-300 truncate max-w-[300px]" title={p.path}>
                        {p.path}
                      </td>
                      <td className="py-1 px-2 text-right font-mono text-slate-400">
                        {formatBytesAbs(p.last_bytes)}
                      </td>
                      <td className="py-1 px-2 text-right font-mono text-slate-500">
                        {p.consecutive_stable}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
}) {
  return (
    <div>
      <label className="text-xs text-slate-400 block mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
      />
      {hint && <p className="text-[11px] text-slate-600 mt-1">{hint}</p>}
    </div>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-xs text-slate-400">{label}</label>
      <button
        onClick={() => onChange(!value)}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          value ? "bg-blue-600" : "bg-slate-700"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            value ? "translate-x-5" : ""
          }`}
        />
      </button>
    </div>
  );
}
