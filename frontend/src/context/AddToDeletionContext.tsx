import { createContext, useCallback, useContext, useMemo, useState } from "react";

interface AddToDeletionContextValue {
  pendingPaths: string[];
  addPath: (path: string) => void;
  addPaths: (paths: string[]) => void;
  consumePending: () => string[];
}

const AddToDeletionContext = createContext<AddToDeletionContextValue | null>(null);

export function AddToDeletionProvider({ children }: { children: React.ReactNode }) {
  const [pendingPaths, setPendingPaths] = useState<string[]>([]);

  const addPath = useCallback((path: string) => {
    setPendingPaths((prev) => (prev.includes(path) ? prev : [...prev, path]));
  }, []);

  const addPaths = useCallback((paths: string[]) => {
    setPendingPaths((prev) => {
      const next = new Set(prev);
      paths.forEach((p) => next.add(p));
      return [...next];
    });
  }, []);

  const consumePending = useCallback(() => {
    let out: string[] = [];
    setPendingPaths((prev) => {
      out = [...prev];
      return out.length ? [] : prev;
    });
    return out;
  }, []);

  const value = useMemo(
    () => ({ pendingPaths, addPath, addPaths, consumePending }),
    [pendingPaths, addPath, addPaths, consumePending],
  );
  return (
    <AddToDeletionContext.Provider value={value}>
      {children}
    </AddToDeletionContext.Provider>
  );
}

export function useAddToDeletion() {
  const ctx = useContext(AddToDeletionContext);
  if (!ctx) return null;
  return ctx;
}
