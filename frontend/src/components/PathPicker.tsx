import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Folder, FolderOpen, Loader2 } from "lucide-react";
import { api, formatBytesAbs, type DirEntry, type Snapshot } from "../api";
import { toast } from "./Toast";

interface PathPickerProps {
  value: string;
  onChange: (path: string) => void;
  placeholder?: string;
  /** When true, empty means "use Settings default" - show placeholder. */
  allowEmpty?: boolean;
  className?: string;
}

export function PathPicker({ value, onChange, placeholder = "Select path…", allowEmpty = true, className = "" }: PathPickerProps) {
  const [open, setOpen] = useState(false);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [basePath, setBasePath] = useState<string>("/");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listSnapshots(5).then((s) => {
      setSnapshots(s);
      if (s.length > 0 && s[0].root_path) {
        setBasePath(s[0].root_path);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [open]);

  const handleSelect = (path: string) => {
    onChange(path);
    setOpen(false);
  };

  const snapId = snapshots[0]?.id ?? null;

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 w-full min-w-[200px] bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-left text-white font-mono hover:border-slate-600 transition-colors"
      >
        <Folder size={14} className="text-slate-500 shrink-0" />
        <span className="truncate flex-1">
          {value || (allowEmpty ? placeholder : basePath)}
        </span>
        {allowEmpty && value && (
          <span
            className="shrink-0 text-slate-500 hover:text-slate-400"
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
            title="Clear"
          >
            ×
          </span>
        )}
        <ChevronDown size={14} className={`shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 left-0 min-w-[280px] max-w-[400px] max-h-[320px] overflow-auto bg-slate-900 border border-slate-700 rounded-lg shadow-xl">
          {snapId == null ? (
            <div className="p-4 space-y-3">
              <p className="text-sm text-slate-500 text-center">
                No snapshots — type path or take a snapshot to browse.
              </p>
              <input
                type="text"
                placeholder="e.g. /home/ubuntu/downloads"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-white font-mono"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          ) : (
            <PathTree
              snapId={snapId}
              basePath={basePath}
              selectedPath={value}
              onSelect={handleSelect}
              allowEmpty={allowEmpty}
              onSelectEmpty={allowEmpty ? () => handleSelect("") : undefined}
            />
          )}
        </div>
      )}
    </div>
  );
}

interface PathTreeProps {
  snapId: number;
  basePath: string;
  selectedPath: string;
  onSelect: (path: string) => void;
  allowEmpty: boolean;
  onSelectEmpty?: () => void;
}

function PathTree({ snapId, basePath, selectedPath, onSelect, onSelectEmpty }: PathTreeProps) {
  return (
    <div className="py-2">
      {onSelectEmpty && (
        <button
          type="button"
          onClick={onSelectEmpty}
          className="w-full px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-800 hover:text-slate-300 transition-colors"
        >
          (Use Settings default)
        </button>
      )}
      <TreeNode
        snapId={snapId}
        path={basePath}
        depth={0}
        selectedPath={selectedPath}
        onSelect={onSelect}
      />
    </div>
  );
}

interface TreeNodeProps {
  snapId: number;
  path: string;
  depth: number;
  selectedPath: string;
  onSelect: (path: string) => void;
  sizeBytes?: number;
}

function TreeNode({ snapId, path, depth, selectedPath, onSelect, sizeBytes }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<DirEntry[] | null>(null);
  const [loading, setLoading] = useState(false);

  const loadChildren = useCallback(() => {
    if (children !== null) return;
    setLoading(true);
    api.drill(snapId, path)
      .then((c) => setChildren(c))
      .catch((err) => toast({ type: "error", text: `Load failed: ${err?.message ?? err}` }))
      .finally(() => setLoading(false));
  }, [snapId, path, children]);

  const hasChildren = children === null ? true : children.length > 0;
  const hasSubdirs = children === null ? true : children.some((c) => c.dir_count > 0);

  const toggleExpand = () => {
    if (!expanded) {
      loadChildren();
      setExpanded(true);
    } else {
      setExpanded(false);
    }
  };

  const name = path === "/" ? "/" : path.split("/").filter(Boolean).pop() || path;
  const isSelected = selectedPath === path;

  return (
    <div className="select-none">
      <div
        className={`flex items-center gap-1 px-3 py-1.5 cursor-pointer transition-colors group ${
          isSelected ? "bg-blue-600/20 text-blue-300" : "hover:bg-slate-800/80 text-slate-300"
        }`}
        style={{ paddingLeft: `${12 + depth * 16}px` }}
      >
        <button
          type="button"
          onClick={toggleExpand}
          className="p-0.5 -ml-0.5 rounded hover:bg-slate-700/50"
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin text-slate-500" />
          ) : hasSubdirs ? (
            expanded ? (
              <ChevronDown size={14} className="text-slate-500" />
            ) : (
              <ChevronRight size={14} className="text-slate-500" />
            )
          ) : (
            <span className="w-[14px] inline-block" />
          )}
        </button>
        <button
          type="button"
          onClick={() => onSelect(path)}
          className="flex-1 flex items-center gap-2 min-w-0 text-left"
        >
          {isSelected ? (
            <FolderOpen size={14} className="text-blue-400 shrink-0" />
          ) : (
            <Folder size={14} className="text-slate-500 shrink-0" />
          )}
          <span className="font-mono text-xs truncate">{name}</span>
          {sizeBytes != null && (
            <span className="text-[10px] text-slate-600 truncate ml-auto">
              {formatBytesAbs(sizeBytes)}
            </span>
          )}
        </button>
      </div>
      {expanded && children && hasChildren && (
        <div>
          {children.map((c) => (
            <TreeNode
              key={c.path}
              snapId={snapId}
              path={c.path}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              sizeBytes={c.total_bytes}
            />
          ))}
        </div>
      )}
    </div>
  );
}
