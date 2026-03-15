import { Layers } from "lucide-react";

export type DepthMode = "all" | "min" | "max" | "exact";

interface Props {
  mode: DepthMode;
  depth: number;
  maxAvailable: number;
  onModeChange: (m: DepthMode) => void;
  onDepthChange: (d: number) => void;
}

export function DepthFilter({ mode, depth, maxAvailable, onModeChange, onDepthChange }: Props) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <Layers size={13} className="text-slate-500" />
      <select
        value={mode}
        onChange={(e) => onModeChange(e.target.value as DepthMode)}
        className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300"
      >
        <option value="all">All depths</option>
        <option value="min">Depth &ge; </option>
        <option value="max">Depth &le; </option>
        <option value="exact">Depth = </option>
      </select>
      {mode !== "all" && (
        <input
          type="range"
          min={0}
          max={Math.max(maxAvailable, 1)}
          value={depth}
          onChange={(e) => onDepthChange(Number(e.target.value))}
          className="w-24 accent-blue-500"
        />
      )}
      {mode !== "all" && (
        <span className="text-slate-400 font-mono w-6 text-center">{depth}</span>
      )}
    </div>
  );
}

export function filterByDepth<T extends { depth: number }>(
  items: T[],
  mode: DepthMode,
  depth: number,
): T[] {
  if (mode === "all") return items;
  if (mode === "min") return items.filter((i) => i.depth >= depth);
  if (mode === "max") return items.filter((i) => i.depth <= depth);
  return items.filter((i) => i.depth === depth);
}
