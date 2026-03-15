import { createContext, useCallback, useContext, useState } from "react";

export type ScanType = "biggest" | "duplicates" | null;

type ScanJobType = "biggest" | "duplicates";

type ActiveJobs = Record<ScanJobType, string | null>;

type ScanContextValue = {
  activeJobs: ActiveJobs;
  setActiveJob: (type: ScanJobType, jobId: string | null) => void;
  isScanTypeActive: (type: ScanJobType) => boolean;
  getActiveJob: (type: ScanJobType) => string | null;
};

const ScanContext = createContext<ScanContextValue | null>(null);

export function ScanProvider({ children }: { children: React.ReactNode }) {
  const [activeJobs, setActiveJobsState] = useState<ActiveJobs>({
    biggest: null,
    duplicates: null,
  });

  const setActiveJob = useCallback((type: ScanJobType, jobId: string | null) => {
    setActiveJobsState((prev) => ({ ...prev, [type]: jobId }));
  }, []);

  const isScanTypeActive = useCallback(
    (type: ScanJobType) => activeJobs[type] !== null,
    [activeJobs]
  );

  const getActiveJob = useCallback(
    (type: ScanJobType) => activeJobs[type],
    [activeJobs]
  );

  return (
    <ScanContext.Provider value={{ activeJobs, setActiveJob, isScanTypeActive, getActiveJob }}>
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
