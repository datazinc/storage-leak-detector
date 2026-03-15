import { createContext, useCallback, useContext, useState } from "react";

export type ScanType = "biggest" | "duplicates" | null;

type ActiveJob = { type: ScanType; jobId: string };

type ScanContextValue = {
  activeJob: ActiveJob | null;
  setActiveJob: (job: ActiveJob | null) => void;
  isOtherScanning: (type: ScanType) => boolean;
};

const ScanContext = createContext<ScanContextValue | null>(null);

export function ScanProvider({ children }: { children: React.ReactNode }) {
  const [activeJob, setActiveJobState] = useState<ActiveJob | null>(null);

  const setActiveJob = useCallback((job: ActiveJob | null) => {
    setActiveJobState(job);
  }, []);

  const isOtherScanning = useCallback(
    (type: ScanType) => activeJob !== null && activeJob.type !== type,
    [activeJob]
  );

  return (
    <ScanContext.Provider value={{ activeJob, setActiveJob, isOtherScanning }}>
      {children}
    </ScanContext.Provider>
  );
}

export function useScanContext() {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScanContext must be used within ScanProvider");
  return ctx;
}

export function useScanContextOptional() {
  return useContext(ScanContext);
}
