"use client";

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  DynafitRun,
  PhaseKey,
  PhaseMetadata,
  PhaseStatus,
  UploadedFile,
  RequirementAtom,
  ClassificationResult,
  ValidatedFitment,
  RunStats,
  FitmentClass,
} from "@/types";

const INITIAL_PHASES: PhaseMetadata[] = [
  {
    id: 1,
    key: "ingestion",
    label: "Ingestion Agent",
    shortLabel: "Ingestion",
    description: "Parse & atomize requirement documents",
    icon: "FileText",
    status: "idle",
    progress: 0,
  },
  {
    id: 2,
    key: "retrieval",
    label: "Knowledge Retrieval Agent",
    shortLabel: "Retrieval",
    description: "RAG search across D365 knowledge bases",
    icon: "Database",
    status: "idle",
    progress: 0,
  },
  {
    id: 3,
    key: "matching",
    label: "Semantic Matching Agent",
    shortLabel: "Matching",
    description: "Compute semantic match scores",
    icon: "Zap",
    status: "idle",
    progress: 0,
  },
  {
    id: 4,
    key: "classification",
    label: "Classification Agent",
    shortLabel: "Classification",
    description: "LLM reasoning for FIT / PARTIAL / GAP",
    icon: "Brain",
    status: "idle",
    progress: 0,
  },
  {
    id: 5,
    key: "validation",
    label: "Validation & Output Agent",
    shortLabel: "Validation",
    description: "Consistency checks & human review",
    icon: "CheckCircle",
    status: "idle",
    progress: 0,
  },
];

function createInitialRun(): DynafitRun {
  return {
    id: `run-${Date.now()}`,
    createdAt: new Date(),
    status: "idle",
    currentPhase: null,
    activePhaseIndex: -1,
    phases: INITIAL_PHASES.map((p) => ({ ...p })),
    uploadedFiles: [],
    requirementAtoms: [],
    retrievalContexts: [],
    matchResults: [],
    classificationResults: [],
    validatedFitments: [],
  };
}

interface DynafitStore {
  run: DynafitRun;
  sidebarCollapsed: boolean;

  // Backend connection
  hasBackend: boolean;
  backendRunId: string | null;
  setHasBackend: (v: boolean) => void;
  setBackendRunId: (id: string | null) => void;

  // Navigation
  goToPhase: (index: number) => void;
  canNavigateTo: (index: number) => boolean;

  // File Upload
  addFiles: (files: UploadedFile[]) => void;
  updateFileProgress: (id: string, progress: number, status?: UploadedFile["status"]) => void;
  removeFile: (id: string) => void;
  setFileError: (id: string, message: string) => void;

  // Phase Control
  startPhase: (key: PhaseKey) => void;
  updatePhaseProgress: (key: PhaseKey, progress: number, stats?: Record<string, number | string>) => void;
  completePhase: (key: PhaseKey, stats?: Record<string, number | string>) => void;
  failPhase: (key: PhaseKey, message: string) => void;
  warnPhase: (key: PhaseKey, message: string) => void;
  retryPhase: (key: PhaseKey) => void;
  setPhaseStatus: (key: PhaseKey, status: PhaseStatus) => void;

  // Run Control
  startRun: () => void;
  pauseRun: () => void;
  resumeRun: () => void;
  resetRun: () => void;
  setRunError: (message: string) => void;

  // Data Setters
  setRequirementAtoms: (atoms: RequirementAtom[]) => void;
  setClassificationResults: (results: ClassificationResult[]) => void;
  setValidatedFitments: (fitments: ValidatedFitment[]) => void;
  overrideClassification: (
    requirementId: string,
    classification: FitmentClass,
    reason: string,
    consultant: string
  ) => void;
  setRunStats: (stats: RunStats) => void;

  // UI
  toggleSidebar: () => void;
}

export const useDynafitStore = create<DynafitStore>()(
  devtools(
    (set, get) => ({
      run: createInitialRun(),
      sidebarCollapsed: false,
      hasBackend: false,
      backendRunId: null,

      setHasBackend: (v) =>
        set({ hasBackend: v }, false, "setHasBackend"),

      setBackendRunId: (id) => {
        // Persist to localStorage so we can reconnect after page refresh
        if (typeof window !== "undefined") {
          if (id) {
            localStorage.setItem("dynafit_run_id", id);
          } else {
            localStorage.removeItem("dynafit_run_id");
          }
        }
        set({ backendRunId: id }, false, "setBackendRunId");
      },

      // ─── Navigation ──────────────────────────────────────────
      goToPhase: (index: number) => {
        if (get().canNavigateTo(index)) {
          set(
            (s) => ({ run: { ...s.run, activePhaseIndex: index } }),
            false,
            "goToPhase"
          );
        }
      },

      canNavigateTo: (index: number) => {
        const { run } = get();
        if (index < 0 || index >= run.phases.length) return false;
        const target = run.phases[index];
        if (target.status === "completed" || target.status === "warning") return true;
        if (index === run.activePhaseIndex) return true;
        if (
          index > 0 &&
          (run.phases[index - 1]?.status === "completed" ||
            run.phases[index - 1]?.status === "warning")
        )
          return true;
        if (index === 0) return true;
        return false;
      },

      // ─── File Upload ─────────────────────────────────────────
      addFiles: (files) =>
        set(
          (s) => ({
            run: { ...s.run, uploadedFiles: [...s.run.uploadedFiles, ...files] },
          }),
          false,
          "addFiles"
        ),

      updateFileProgress: (id, progress, status) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              uploadedFiles: s.run.uploadedFiles.map((f) =>
                f.id === id
                  ? { ...f, progress, ...(status ? { status } : {}) }
                  : f
              ),
            },
          }),
          false,
          "updateFileProgress"
        ),

      removeFile: (id) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              uploadedFiles: s.run.uploadedFiles.filter((f) => f.id !== id),
            },
          }),
          false,
          "removeFile"
        ),

      setFileError: (id, message) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              uploadedFiles: s.run.uploadedFiles.map((f) =>
                f.id === id ? { ...f, status: "error" as const, errorMessage: message } : f
              ),
            },
          }),
          false,
          "setFileError"
        ),

      // ─── Phase Control ───────────────────────────────────────
      startPhase: (key) =>
        set(
          (s) => {
            const phaseIndex = s.run.phases.findIndex((p) => p.key === key);
            return {
              run: {
                ...s.run,
                status: "running",
                currentPhase: key,
                activePhaseIndex: phaseIndex,
                phases: s.run.phases.map((p) =>
                  p.key === key
                    ? { ...p, status: "processing" as const, progress: 0, startedAt: new Date(), errorMessage: undefined, warningMessage: undefined }
                    : p
                ),
              },
            };
          },
          false,
          "startPhase"
        ),

      updatePhaseProgress: (key, progress, stats) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              phases: s.run.phases.map((p) =>
                p.key === key
                  ? { ...p, progress, ...(stats ? { stats: { ...p.stats, ...stats } } : {}) }
                  : p
              ),
            },
          }),
          false,
          "updatePhaseProgress"
        ),

      completePhase: (key, stats) =>
        set(
          (s) => {
            const phaseIndex = s.run.phases.findIndex((p) => p.key === key);
            const nextIndex = phaseIndex + 1;
            const allDone = nextIndex >= s.run.phases.length;
            return {
              run: {
                ...s.run,
                status: allDone ? "completed" : s.run.status,
                currentPhase: allDone ? null : s.run.currentPhase,
                phases: s.run.phases.map((p) =>
                  p.key === key
                    ? {
                        ...p,
                        status: "completed" as const,
                        progress: 100,
                        completedAt: new Date(),
                        ...(stats ? { stats: { ...p.stats, ...stats } } : {}),
                      }
                    : p
                ),
              },
            };
          },
          false,
          "completePhase"
        ),

      failPhase: (key, message) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              status: "error",
              phases: s.run.phases.map((p) =>
                p.key === key
                  ? { ...p, status: "error" as const, errorMessage: message }
                  : p
              ),
            },
          }),
          false,
          "failPhase"
        ),

      warnPhase: (key, message) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              phases: s.run.phases.map((p) =>
                p.key === key
                  ? { ...p, status: "warning" as const, warningMessage: message }
                  : p
              ),
            },
          }),
          false,
          "warnPhase"
        ),

      retryPhase: (key) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              status: "running",
              errorMessage: undefined,
              phases: s.run.phases.map((p) =>
                p.key === key
                  ? { ...p, status: "idle" as const, errorMessage: undefined, progress: 0 }
                  : p
              ),
            },
          }),
          false,
          "retryPhase"
        ),

      setPhaseStatus: (key, status) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              phases: s.run.phases.map((p) =>
                p.key === key ? { ...p, status } : p
              ),
            },
          }),
          false,
          "setPhaseStatus"
        ),

      // ─── Run Control ─────────────────────────────────────────
      startRun: () =>
        set(
          (s) => ({
            run: {
              ...s.run,
              status: "running",
              activePhaseIndex: 0,
            },
          }),
          false,
          "startRun"
        ),

      pauseRun: () =>
        set(
          (s) => ({ run: { ...s.run, status: "paused" } }),
          false,
          "pauseRun"
        ),

      resumeRun: () =>
        set(
          (s) => ({ run: { ...s.run, status: "running" } }),
          false,
          "resumeRun"
        ),

      resetRun: () =>
        set({ run: createInitialRun(), backendRunId: null }, false, "resetRun"),

      setRunError: (message) =>
        set(
          (s) => ({
            run: { ...s.run, status: "error", errorMessage: message },
          }),
          false,
          "setRunError"
        ),

      // ─── Data Setters ────────────────────────────────────────
      setRequirementAtoms: (atoms) =>
        set(
          (s) => ({ run: { ...s.run, requirementAtoms: atoms } }),
          false,
          "setRequirementAtoms"
        ),

      setClassificationResults: (results) =>
        set(
          (s) => ({ run: { ...s.run, classificationResults: results } }),
          false,
          "setClassificationResults"
        ),

      setValidatedFitments: (fitments) =>
        set(
          (s) => ({ run: { ...s.run, validatedFitments: fitments } }),
          false,
          "setValidatedFitments"
        ),

      overrideClassification: (requirementId, classification, reason, consultant) =>
        set(
          (s) => ({
            run: {
              ...s.run,
              classificationResults: s.run.classificationResults.map((r) =>
                r.requirementId === requirementId
                  ? { ...r, classification, overriddenBy: consultant, overrideReason: reason }
                  : r
              ),
              validatedFitments: s.run.validatedFitments.map((v) =>
                v.requirementId === requirementId
                  ? {
                      ...v,
                      classification,
                      finalVerdict: classification,
                      overriddenBy: consultant,
                      overrideReason: reason,
                      consultantVerified: true,
                    }
                  : v
              ),
            },
          }),
          false,
          "overrideClassification"
        ),

      setRunStats: (stats) =>
        set(
          (s) => ({ run: { ...s.run, stats } }),
          false,
          "setRunStats"
        ),

      // ─── UI ──────────────────────────────────────────────────
      toggleSidebar: () =>
        set(
          (s) => ({ sidebarCollapsed: !s.sidebarCollapsed }),
          false,
          "toggleSidebar"
        ),
    }),
    { name: "DynafitStore" }
  )
);
