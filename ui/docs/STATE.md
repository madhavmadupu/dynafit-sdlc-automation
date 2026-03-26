# DYNAFIT — State Management Reference

## Store: `useDynafitStore`
**File:** `store/useDynafitStore.ts`

Single Zustand store for all application state. Uses `devtools` middleware for Redux DevTools support.

---

## State Shape

```typescript
interface DynafitStore {
  // ─── Run State ───────────────────────────────────────────
  run: DynafitRun;           // The current pipeline run
  sidebarCollapsed: boolean;

  // ─── Navigation ──────────────────────────────────────────
  goToPhase: (index: number) => void;
  canNavigateTo: (index: number) => boolean;

  // ─── File Upload ─────────────────────────────────────────
  addFiles: (files: UploadedFile[]) => void;
  updateFileProgress: (id: string, progress: number, status?: UploadedFile["status"]) => void;
  removeFile: (id: string) => void;
  setFileError: (id: string, message: string) => void;

  // ─── Phase Control ───────────────────────────────────────
  startPhase: (key: PhaseKey) => void;
  updatePhaseProgress: (key: PhaseKey, progress: number, stats?: Record<string, number | string>) => void;
  completePhase: (key: PhaseKey, stats?: Record<string, number | string>) => void;
  failPhase: (key: PhaseKey, message: string) => void;
  warnPhase: (key: PhaseKey, message: string) => void;
  retryPhase: (key: PhaseKey) => void;
  setPhaseStatus: (key: PhaseKey, status: PhaseStatus) => void;

  // ─── Run Control ─────────────────────────────────────────
  startRun: () => void;
  pauseRun: () => void;
  resumeRun: () => void;
  resetRun: () => void;
  setRunError: (message: string) => void;

  // ─── Data Setters ────────────────────────────────────────
  setRequirementAtoms: (atoms: RequirementAtom[]) => void;
  setClassificationResults: (results: ClassificationResult[]) => void;
  setValidatedFitments: (fitments: ValidatedFitment[]) => void;
  overrideClassification: (requirementId: string, classification: FitmentClass, reason: string, consultant: string) => void;
  setRunStats: (stats: RunStats) => void;

  // ─── UI ──────────────────────────────────────────────────
  toggleSidebar: () => void;
}
```

---

## `DynafitRun` Shape

```typescript
interface DynafitRun {
  id: string;                           // "run-1718900000000"
  createdAt: Date;
  status: "idle" | "running" | "completed" | "error" | "paused";
  currentPhase: PhaseKey | null;         // which phase is currently executing
  activePhaseIndex: number;              // which phase panel is displayed (-1 = none)
  phases: PhaseMetadata[];               // array of 5 phase objects
  uploadedFiles: UploadedFile[];
  requirementAtoms: RequirementAtom[];   // populated after Phase 1
  retrievalContexts: RetrievalContext[]; // populated after Phase 2
  matchResults: MatchResult[];           // populated after Phase 3
  classificationResults: ClassificationResult[]; // populated after Phase 4
  validatedFitments: ValidatedFitment[]; // populated after Phase 5
  stats?: RunStats;                      // final summary stats
  errorMessage?: string;
}
```

---

## `PhaseMetadata` Shape

```typescript
interface PhaseMetadata {
  id: 1 | 2 | 3 | 4 | 5;
  key: "ingestion" | "retrieval" | "matching" | "classification" | "validation";
  label: string;       // "Ingestion Agent"
  shortLabel: string;  // "Ingestion"
  description: string;
  icon: string;        // Lucide icon name string
  status: PhaseStatus;
  progress: number;    // 0–100
  startedAt?: Date;
  completedAt?: Date;
  errorMessage?: string;
  warningMessage?: string;
  stats?: Record<string, number | string>; // phase-specific output stats
}
```

---

## Phase Keys

```typescript
type PhaseKey =
  | "ingestion"        // Phase 1
  | "retrieval"        // Phase 2
  | "matching"         // Phase 3
  | "classification"   // Phase 4
  | "validation";      // Phase 5
```

---

## Usage Patterns

### Reading phase state in a component

```typescript
const { run } = useDynafitStore();
const phase = run.phases.find(p => p.key === "ingestion")!;
const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
const isCompleted = phase.status === "completed" || phase.status === "warning";
```

### Triggering a phase from a component

```typescript
const { startPhase, updatePhaseProgress, completePhase, failPhase } = useDynafitStore();

async function runIngestion() {
  startPhase("ingestion");                                    // sets status = "processing"
  updatePhaseProgress("ingestion", 25, { step: "Parsing..." });
  updatePhaseProgress("ingestion", 75, { step: "Validating..." });
  // on success:
  completePhase("ingestion", { totalAtoms: 265, modules: 10 });
  // on failure:
  failPhase("ingestion", "Failed to parse document: invalid format");
}
```

### Checking navigation permission

```typescript
const { canNavigateTo, goToPhase } = useDynafitStore();

// In PhaseStepper
<button
  onClick={() => goToPhase(i)}
  disabled={!canNavigateTo(i)}
>
```

### Override a classification (Phase 5)

```typescript
const { overrideClassification } = useDynafitStore();

overrideClassification(
  "req-0042",           // requirementId
  "FIT",                // new classification
  "Standard D365 covers this fully per wave 2 validation.",  // reason
  "consultant@acme.com" // consultant identifier
);
```

---

## Simulation vs Real API

The file `lib/simulation.ts` contains mock implementations of each phase.
To connect to the real backend, replace each `simulatePhaseX()` function with a real API call that:

1. Calls `startPhase(key)` before the request
2. Polls or streams progress, calling `updatePhaseProgress(key, %)` 
3. Calls `completePhase(key, stats)` on success
4. Calls `failPhase(key, message)` on error

### Example real API integration pattern

```typescript
// lib/api.ts
export async function runIngestionPhase(files: UploadedFile[]) {
  const store = useDynafitStore.getState();
  store.startPhase("ingestion");

  try {
    // POST to backend
    const response = await fetch("/api/phases/ingestion", {
      method: "POST",
      body: JSON.stringify({ fileIds: files.map(f => f.id) }),
    });

    // Stream SSE progress updates
    const reader = response.body!.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const event = JSON.parse(new TextDecoder().decode(value));
      store.updatePhaseProgress("ingestion", event.progress, { step: event.step });
    }

    // Get final result
    const result = await fetch("/api/phases/ingestion/result").then(r => r.json());
    store.setRequirementAtoms(result.atoms);
    store.completePhase("ingestion", result.stats);

  } catch (err) {
    store.failPhase("ingestion", err instanceof Error ? err.message : "Unknown error");
  }
}
```

---

## Initial Phase Configuration

```typescript
const INITIAL_PHASES: PhaseMetadata[] = [
  { id: 1, key: "ingestion",       label: "Ingestion Agent",            shortLabel: "Ingestion",       icon: "FileText",    ... },
  { id: 2, key: "retrieval",       label: "Knowledge Retrieval Agent",  shortLabel: "Retrieval",       icon: "Database",    ... },
  { id: 3, key: "matching",        label: "Semantic Matching Agent",    shortLabel: "Matching",        icon: "Zap",         ... },
  { id: 4, key: "classification",  label: "Classification Agent",       shortLabel: "Classification",  icon: "Brain",       ... },
  { id: 5, key: "validation",      label: "Validation & Output Agent",  shortLabel: "Validation",      icon: "CheckCircle", ... },
];
```