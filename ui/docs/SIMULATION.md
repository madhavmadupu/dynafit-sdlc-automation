# DYNAFIT — Simulation & API Integration Guide

## Overview

`lib/simulation.ts` contains a complete mock implementation of the 5-phase pipeline.
It uses `setTimeout` delays to simulate realistic processing times and populates
the Zustand store with generated mock data.

**Use this for development and demo. Replace with real API calls for production.**

---

## Mock Pipeline Flow

```
runFullPipeline()
  └── simulateIngestion()      ~2.5s  → generates 265 RequirementAtoms
  └── simulateRetrieval()      ~2.8s  → simulates RAG search
  └── simulateMatching()       ~2.0s  → generates MatchResults
  └── simulateClassification() ~3.5s  → generates ClassificationResults
  └── simulateValidation()     ~2.2s  → generates ValidatedFitments + RunStats
```

Total simulation time: ~13 seconds.

---

## How Each Simulator Works

### `simulateIngestion()`
1. Calls `store.startPhase("ingestion")` → status = "processing"
2. Updates status to "uploading" briefly
3. Increments progress in steps (15 → 35 → 55 → 75 → 90)
4. Updates `stats.step` at each checkpoint (shown in stepper detail bar)
5. Generates 265 `RequirementAtom` objects
6. Calls `store.setRequirementAtoms(atoms)`
7. Calls `store.completePhase("ingestion", { totalAtoms, modules, ambiguous, duplicates })`
8. If `ambiguous > 0`, calls `store.warnPhase("ingestion", message)` — status = "warning"

### `simulateRetrieval()`
Similar pattern. No actual data generation needed — just simulates progress.

### `simulateMatching()`
Changes status to "analyzing" mid-way (for visual differentiation).
Calculates routing breakdown: fastTrack / needsLLM / likelyGap.

### `simulateClassification()`
Runs 5 batch iterations, each updating progress by ~17%.
Generates `ClassificationResult[]` with realistic FIT/PARTIAL/GAP distribution:
- ~40% FIT
- ~35% PARTIAL_FIT
- ~25% GAP

### `simulateValidation()`
Generates `ValidatedFitment[]` from classification results.
Calculates final `RunStats`.
Sets `run.status = "completed"` at the end.

---

## Mock Data Generators

### `generateMockAtoms(count: number): RequirementAtom[]`
Creates realistic requirement atoms using:
- 15 sample requirement texts (rotated)
- Random modules from: AP, AR, GL, SCM, PO, FA, HR, PP, INV, TMS
- Random priorities: MUST, SHOULD, COULD
- 12% chance of isAmbiguous = true
- 6% chance of isDuplicate = true
- Completeness scores: 60–100 range

### `generateMockClassifications(atoms): ClassificationResult[]`
Maps each atom to a classification:
- FIT: confidence 0.85–0.99
- PARTIAL_FIT: confidence 0.60–0.84
- GAP: confidence 0.20–0.55
- Generic rationale strings per classification type

---

## Replacing with Real API

### Step 1: Create API route handlers

```
app/api/
├── phases/
│   ├── ingestion/
│   │   ├── route.ts        POST — start ingestion, returns job ID
│   │   └── [jobId]/
│   │       ├── status/route.ts   GET — poll progress
│   │       └── result/route.ts   GET — get final atoms
│   ├── retrieval/route.ts
│   ├── matching/route.ts
│   ├── classification/route.ts
│   └── validation/route.ts
```

### Step 2: Create real phase runner functions

Replace each `simulatePhaseX()` in `lib/simulation.ts` with:

```typescript
// lib/api/ingestion.ts
export async function runIngestionPhase(fileIds: string[]) {
  const store = useDynafitStore.getState();
  store.startPhase("ingestion");

  try {
    // 1. Start the job
    const { jobId } = await fetch("/api/phases/ingestion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fileIds }),
    }).then(r => r.json());

    // 2. Poll for progress (or use SSE/WebSocket)
    await pollJobProgress(jobId, "ingestion");

    // 3. Fetch result
    const result = await fetch(`/api/phases/ingestion/${jobId}/result`).then(r => r.json());

    // 4. Store data + complete phase
    store.setRequirementAtoms(result.atoms);
    store.completePhase("ingestion", result.stats);

    // 5. Handle warnings
    if (result.stats.ambiguous > 0) {
      store.warnPhase("ingestion", `${result.stats.ambiguous} requirements flagged as ambiguous`);
    }

  } catch (err) {
    store.failPhase("ingestion", err instanceof Error ? err.message : "Ingestion failed");
  }
}

async function pollJobProgress(jobId: string, phaseKey: PhaseKey) {
  const store = useDynafitStore.getState();

  while (true) {
    const status = await fetch(`/api/phases/${phaseKey}/${jobId}/status`).then(r => r.json());

    store.updatePhaseProgress(phaseKey, status.progress, { step: status.currentStep });

    if (status.done) break;
    if (status.error) throw new Error(status.error);

    await new Promise(r => setTimeout(r, 1000)); // poll every 1 second
  }
}
```

### Step 3: Use SSE for real-time streaming (recommended)

If the backend supports Server-Sent Events:

```typescript
async function streamPhaseProgress(phaseKey: PhaseKey, jobId: string) {
  const store = useDynafitStore.getState();

  return new Promise<void>((resolve, reject) => {
    const es = new EventSource(`/api/phases/${phaseKey}/${jobId}/stream`);

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);

      if (event.type === "progress") {
        store.updatePhaseProgress(phaseKey, event.progress, { step: event.step });
      }

      if (event.type === "complete") {
        es.close();
        resolve();
      }

      if (event.type === "error") {
        es.close();
        reject(new Error(event.message));
      }
    };

    es.onerror = () => {
      es.close();
      reject(new Error("Connection lost"));
    };
  });
}
```

---

## Error Scenarios to Handle in the UI

| Scenario | Phase | UI Behavior |
|---|---|---|
| File too large (> 50MB) | 1 | Show file-level error, allow removing file |
| Invalid file format | 1 | Show file-level error, allow retry |
| LLM extraction failed for row | 1 | Warning state, show count of failed rows |
| KB connection timeout | 2 | Error state with "Retry" button |
| No capabilities found | 2 | Warning — proceed but with 0 context |
| Embedding service down | 3 | Error state |
| All scores below threshold | 3 | Warning — all routed to LLM |
| LLM rate limit / timeout | 4 | Retry failed batch only |
| LLM parse error (bad JSON) | 4 | Show which batch failed, retry option |
| Conflict resolution failure | 5 | Warning — show unresolved conflicts |
| Export file generation error | 5 | Error on export button only |

---

## Pause / Resume Support

The store supports `pauseRun()` and `resumeRun()`. When integrated with real API:

```typescript
// On pause: send signal to backend
async function handlePause() {
  store.pauseRun();
  await fetch(`/api/runs/${runId}/pause`, { method: "POST" });
}

// On resume: continue from last checkpoint
async function handleResume() {
  store.resumeRun();
  // Backend resumes from LangGraph checkpoint
  const currentPhase = store.run.currentPhase;
  if (currentPhase) {
    await continuePhaseFrom(currentPhase);
  }
}
```

LangGraph on the backend handles checkpointing automatically — each completed step is saved and resumable.