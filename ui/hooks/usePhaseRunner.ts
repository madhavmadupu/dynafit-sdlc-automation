"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import {
  simulateIngestion,
  simulateRetrieval,
  simulateMatching,
  simulateClassification,
  simulateValidation,
} from "@/lib/simulation";
import type { PhaseKey } from "@/types";

export function usePhaseRunner() {
  const [hasBackend, setHasBackend] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    api.checkBackendHealth().then(setHasBackend);
  }, []);

  const simulators: Record<PhaseKey, () => Promise<void>> = {
    ingestion: simulateIngestion,
    retrieval: simulateRetrieval,
    matching: simulateMatching,
    classification: simulateClassification,
    validation: simulateValidation,
  };

  const runPhase = useCallback(
    async (phaseKey: PhaseKey) => {
      setIsRunning(true);
      try {
        if (hasBackend) {
          // Real API mode - would call api.startPhaseWithStream etc.
          // For now, fall through to simulation
          await simulators[phaseKey]();
        } else {
          await simulators[phaseKey]();
        }
      } finally {
        setIsRunning(false);
      }
    },
    [hasBackend]
  );

  return {
    hasBackend,
    isRunning,
    runPhase,
    runIngestion: () => runPhase("ingestion"),
    runRetrieval: () => runPhase("retrieval"),
    runMatching: () => runPhase("matching"),
    runClassification: () => runPhase("classification"),
    runValidation: () => runPhase("validation"),
  };
}
