"use client";

import { createContext, useContext, type ReactNode } from "react";

interface TracesContextValue {
  isReady: boolean;
  canSeeTeamData: boolean;
}

const TracesContext = createContext<TracesContextValue | null>(null);

export function useTracesContext() {
  const ctx = useContext(TracesContext);
  if (!ctx) {
    throw new Error("useTracesContext must be used within TracesProvider");
  }
  return ctx;
}

export function TracesProvider({ children }: { children: ReactNode }) {
  return (
    <TracesContext.Provider
      value={{
        isReady: true,
        canSeeTeamData: true,
      }}
    >
      {children}
    </TracesContext.Provider>
  );
}
