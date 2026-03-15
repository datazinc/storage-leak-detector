import { useRef, useCallback, type ReactNode, type ThHTMLAttributes } from "react";
import { clsx } from "clsx";

interface Column {
  key: string;
  label: string;
  minWidth?: number;
  defaultWidth?: number;
  align?: "left" | "right" | "center";
  className?: string;
}

interface Props {
  columns: Column[];
  children: ReactNode;
  className?: string;
}

export function ResizableTable({ columns, children, className }: Props) {
  const tableRef = useRef<HTMLTableElement>(null);

  const onMouseDown = useCallback(
    (colIdx: number, e: React.MouseEvent) => {
      e.preventDefault();
      const table = tableRef.current;
      if (!table) return;

      const th = table.querySelectorAll("thead th")[colIdx] as HTMLElement;
      if (!th) return;

      const startX = e.clientX;
      const startW = th.offsetWidth;
      const minW = columns[colIdx].minWidth ?? 40;

      const onMove = (ev: MouseEvent) => {
        const w = Math.max(minW, startW + ev.clientX - startX);
        th.style.width = `${w}px`;
        th.style.minWidth = `${w}px`;
      };

      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [columns],
  );

  return (
    <div className={clsx("min-w-0 w-full overflow-x-auto", className)}>
      <table ref={tableRef} className="w-full text-sm table-fixed" style={{ minWidth: 650 }}>
        <thead>
          <tr className="text-left text-slate-500 text-xs uppercase">
            {columns.map((col, i) => (
              <ResizableTh
                key={col.key}
                align={col.align}
                style={{
                  width: col.defaultWidth ? `${col.defaultWidth}px` : undefined,
                  minWidth: col.minWidth ? `${col.minWidth}px` : undefined,
                }}
                className={col.className}
                onResizeStart={(e) => onMouseDown(i, e)}
                isLast={i === columns.length - 1}
              >
                {col.label}
              </ResizableTh>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function ResizableTh({
  children,
  align,
  onResizeStart,
  isLast,
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & {
  align?: "left" | "right" | "center";
  onResizeStart: (e: React.MouseEvent) => void;
  isLast: boolean;
}) {
  return (
    <th
      {...rest}
      className={clsx(
        "pb-2 pr-2 relative select-none",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
      {!isLast && (
        <span
          onMouseDown={onResizeStart}
          className="absolute right-0 top-0 bottom-0 w-1 -mr-px cursor-col-resize bg-slate-600 hover:bg-slate-500 active:bg-blue-500/60 transition-colors"
        />
      )}
    </th>
  );
}
