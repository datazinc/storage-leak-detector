import { Copy } from "lucide-react";
import { toast } from "./Toast";

interface Props {
  path: string;
  size?: "sm" | "md";
  className?: string;
}

export function CopyPathButton({ path, size = "sm", className = "" }: Props) {
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(path);
    toast({ type: "success", text: "Path copied" });
  };

  return (
    <button
      onClick={handleCopy}
      title="Copy path"
      className={`p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300 transition-colors shrink-0 ${className}`}
    >
      <Copy size={size === "sm" ? 12 : 14} />
    </button>
  );
}
