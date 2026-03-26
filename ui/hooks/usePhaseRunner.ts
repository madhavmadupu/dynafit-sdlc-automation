"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useDynafitStore } from "@/store/useDynafitStore";
import {
  simulateIngestion,
  simulateRetrieval,
  simulateMatching,
  simulateClassification,
  simulateValidation,
} from "@/lib/simulation";
import type { PhaseKey, ValidatedFitment } from "@/types";

const PHASE_ORDER: PhaseKey[] = [
  "ingestion",
  "retrieval",
  "matching",
  "classification",
  "validation",
];

export function usePhaseRunner() {
  const {
    hasBackend,
    backendRunId,
    setHasBackend,
    setBackendRunId,
    startPhase,
    completePhase,
    failPhase,
    setRunError,
    setRequirementAtoms,
    setClassificationResults,
    setValidatedFitments,
    setRunStats,
    goToPhase,
  } = useDynafitStore();

  const [isRunning, setIsRunning] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Check backend health on mount
  useEffect(() => {
    api.checkBackendHealth().then((ok) => {
      setHasBackend(ok);
    });
  }, [setHasBackend]);

  // Fetch results from backend and populate the store
  const fetchAndPopulateResults = useCallback(
    async (runId: string) => {
      try {
        const results = await api.getRunResults(runId);

        if (results.atoms?.length) {
          setRequirementAtoms(results.atoms);
        }

        if (results.classificationResults?.length) {
          setClassificationResults(results.classificationResults);

          // Generate validated fitments from classifications
          const validated: ValidatedFitment[] =
            results.classificationResults.map((c: any) => ({
              ...c,
              consultantVerified: false,
              conflictFlags: [],
              finalVerdict: c.classification,
            }));
          setValidatedFitments(validated);

          // Compute run stats
          const fit = validated.filter(
            (v) => v.finalVerdict === "FIT"
          ).length;
          const partial = validated.filter(
            (v) => v.finalVerdict === "PARTIAL_FIT"
          ).length;
          const gap = validated.filter(
            (v) => v.finalVerdict === "GAP"
          ).length;
          const flagged = validated.filter(
            (v) =>
              v.confidence < 0.65 || v.conflictFlags.length > 0
          ).length;

          setRunStats({
            totalRequirements: validated.length,
            fit,
            partialFit: partial,
            gap,
            flagged,
            processingTimeMs: 0,
          });
        }
      } catch (e) {
        console.error("Failed to fetch pipeline results:", e);
      }
    },
    [setRequirementAtoms, setClassificationResults, setValidatedFitments, setRunStats]
  );

  // Connect to SSE stream when we have a backend run ID
  const connectStream = useCallback(
    (runId: string) => {
      // Close existing connection
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const es = api.connectToStream(runId, {
        onState: async (state) => {
          // Process initial state snapshot — mark already-completed phases
          if (state.phases) {
            for (const phase of PHASE_ORDER) {
              const phaseState = state.phases[phase];
              if (phaseState?.status === "completed") {
                completePhase(phase, phaseState.stats || {});
              } else if (phaseState?.status === "processing") {
                startPhase(phase);
              }
            }
          }

          // If pipeline already finished, fetch results and populate store
          // but stay on Phase 1 so user can review each phase's stats
          if (state.status === "AWAITING_REVIEW" || state.status === "COMPLETED") {
            await fetchAndPopulateResults(runId);
            const store = useDynafitStore.getState();
            const validated = store.run.validatedFitments;
            if (validated.length > 0) {
              completePhase("validation", {
                totalVerified: validated.length,
                overrides: 0,
                conflicts: validated.filter((v) => v.conflictFlags.length > 0).length,
                exportReady: "true",
              });
            }
            setIsRunning(false);
            // Stay on Phase 1 — user navigates manually via "Proceed" buttons
            goToPhase(0);
          } else if (state.status === "RUNNING") {
            // Pipeline is still running — find the active phase
            const processingIdx = PHASE_ORDER.findIndex(
              (p) => state.phases?.[p]?.status === "processing"
            );
            if (processingIdx >= 0) {
              goToPhase(processingIdx);
            }
          }
        },

        onPhaseStart: (phase) => {
          startPhase(phase as PhaseKey);
        },

        onPhaseComplete: (phase, stats) => {
          completePhase(phase as PhaseKey, stats);
        },

        onPipelinePaused: async () => {
          await fetchAndPopulateResults(runId);
          setIsRunning(false);
          // Navigate to Phase 1 so the user can review each phase's stats
          goToPhase(0);
        },

        onPipelineComplete: async () => {
          await fetchAndPopulateResults(runId);
          setIsRunning(false);
          // Navigate to Phase 1 so the user can review each phase's results
          goToPhase(0);
        },

        onPipelineError: (message) => {
          setRunError(message);
          setIsRunning(false);
        },
      });

      eventSourceRef.current = es;
    },
    [
      startPhase,
      completePhase,
      goToPhase,
      fetchAndPopulateResults,
      setRunError,
    ]
  );

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // ── Phase Runners ─────────────────────────────────────────────────────

  const simulators: Record<PhaseKey, () => Promise<void>> = {
    ingestion: simulateIngestion,
    retrieval: simulateRetrieval,
    matching: simulateMatching,
    classification: simulateClassification,
    validation: simulateValidation,
  };

  /**
   * Start the pipeline with real file upload (backend mode)
   * or fall back to simulation.
   */
  const runIngestion = useCallback(
    async (files?: File[]) => {
      setIsRunning(true);
      try {
        if (hasBackend && files && files.length > 0) {
          // Real backend: upload files → start pipeline → connect SSE
          startPhase("ingestion");
          try {
            const result = await api.createRun(files);
            setBackendRunId(result.run_id);
            connectStream(result.run_id);
            return;
          } catch (e: any) {
            // Backend call failed — fall back to simulation gracefully
            console.warn("Backend upload failed, falling back to simulation:", e.message);
            setHasBackend(false);
          }
        }
        // Simulation fallback
        await simulateIngestion();
        setIsRunning(false);
      } catch (e: any) {
        failPhase("ingestion", e.message || "Failed to start pipeline");
        setIsRunning(false);
      }
    },
    [hasBackend, startPhase, setBackendRunId, setHasBackend, connectStream, failPhase]
  );

  /**
   * Run a specific phase. When backend is connected and pipeline is running,
   * this is a no-op (phases auto-advance via SSE). Falls back to simulation.
   */
  const runPhase = useCallback(
    async (phaseKey: PhaseKey) => {
      if (backendRunId && hasBackend) {
        // Backend is handling this phase automatically — no-op
        return;
      }
      setIsRunning(true);
      try {
        await simulators[phaseKey]();
      } finally {
        setIsRunning(false);
      }
    },
    [hasBackend, backendRunId]
  );

  return {
    hasBackend,
    backendRunId,
    isRunning,
    runPhase,
    runIngestion,
    runRetrieval: () => runPhase("retrieval"),
    runMatching: () => runPhase("matching"),
    runClassification: () => runPhase("classification"),
    runValidation: () => runPhase("validation"),
  };
}
