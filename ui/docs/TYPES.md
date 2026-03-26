# DYNAFIT — TypeScript Types Reference

**File:** `types/index.ts`

All types used across the application. Import from `@/types`.

---

## Core Enums / Union Types

```typescript
// Phase execution status
type PhaseStatus =
  | "idle"         // Not started
  | "pending"      // Queued
  | "uploading"    // File upload in progress (Phase 1)
  | "processing"   // Agent actively running
  | "analyzing"    // Deep computation (Phase 3)
  | "completed"    // Done successfully
  | "warning"      // Done with non-blocking issues
  | "error"        // Failed
  | "skipped";     // Bypassed

// Fitment classification output
type FitmentClass = "FIT" | "PARTIAL_FIT" | "GAP";

// Confidence tier (from Phase 3 routing)
type ConfidenceTier = "HIGH" | "MED" | "LOW";

// Phase identifier keys
type PhaseKey =
  | "ingestion"
  | "retrieval"
  | "matching"
  | "classification"
  | "validation";
```

---

## Phase 1 Output: `RequirementAtom`

```typescript
interface RequirementAtom {
  id: string;             // "req-0001"
  text: string;           // Full requirement text
  module: string;         // "AP" | "AR" | "GL" | "SCM" | "PO" | "FA" | "HR" | "PP" | "INV" | "TMS"
  priority: "MUST" | "SHOULD" | "COULD" | "WONT";   // MoSCoW
  country?: string;       // "US" | "DE" | "IN" | "GB" | "FR" (optional localization)
  completenessScore: number;  // 0–100 (how complete/unambiguous the req is)
  isAmbiguous: boolean;   // flagged by ambiguity detector
  isDuplicate: boolean;   // flagged by deduplicator
  sourceFile: string;     // "requirements_wave1.xlsx"
  sourceRow?: number;     // row number in source document
}
```

---

## Phase 2 Output: `RetrievalContext`

```typescript
interface D365Capability {
  id: string;
  title: string;
  module: string;
  description: string;
  msLearnUrl?: string;
  confidenceSignal: number;   // 0–1
}

interface PriorFitment {
  wave: string;               // "Wave 1" | "Wave 2"
  country: string;
  classification: FitmentClass;
  confidence: number;
}

interface RetrievalContext {
  requirementId: string;
  topCapabilities: D365Capability[];    // top-5 after reranking
  priorFitments: PriorFitment[];        // historical decisions
  msLearnRefs: string[];                // doc chunk references
}
```

---

## Phase 3 Output: `MatchResult`

```typescript
interface MatchResult {
  requirementId: string;
  cosineScore: number;               // raw cosine similarity (0–1)
  confidenceTier: ConfidenceTier;    // HIGH / MED / LOW
  compositeScore: number;            // weighted composite (0–1)
  topCandidates: D365Capability[];
  routeDecision: "FAST_TRACK" | "LLM_REASON" | "LIKELY_GAP";
  // FAST_TRACK  = score > 0.85 + historical precedent
  // LLM_REASON  = score 0.60–0.85
  // LIKELY_GAP  = score < 0.60
}
```

---

## Phase 4 Output: `ClassificationResult`

```typescript
interface ClassificationResult {
  requirementId: string;
  classification: FitmentClass;       // FIT | PARTIAL_FIT | GAP
  confidence: number;                 // 0–1
  rationale: string;                  // LLM explanation
  d365Feature?: string;               // "AP > Vendor invoices > Invoice matching"
  d365Module?: string;                // "AP"
  configNotes?: string;               // For PARTIAL_FIT: what config is needed
  gapDescription?: string;            // For GAP: what is missing
  caveats?: string[];                 // Additional notes
  overriddenBy?: string;              // consultant email (if overridden)
  overrideReason?: string;            // why they overrode
}
```

---

## Phase 5 Output: `ValidatedFitment`

```typescript
// Extends ClassificationResult with validation fields
interface ValidatedFitment extends ClassificationResult {
  consultantVerified: boolean;
  conflictFlags: string[];            // e.g., ["Dependency conflict with req-0034"]
  countryOverride?: string;           // Country-specific rule applied
  finalVerdict: FitmentClass;         // May differ from classification if overridden
}
```

---

## Supporting Types

### `UploadedFile`
```typescript
interface UploadedFile {
  id: string;
  name: string;
  size: number;                       // bytes
  type: string;                       // MIME type
  status: "queued" | "uploading" | "parsed" | "error";
  progress: number;                   // 0–100
  errorMessage?: string;
}
```

### `PhaseMetadata`
```typescript
interface PhaseMetadata {
  id: number;                         // 1–5
  key: PhaseKey;
  label: string;                      // "Ingestion Agent"
  shortLabel: string;                 // "Ingestion"
  description: string;
  icon: string;                       // Lucide icon name
  status: PhaseStatus;
  progress: number;                   // 0–100
  startedAt?: Date;
  completedAt?: Date;
  errorMessage?: string;
  warningMessage?: string;
  stats?: Record<string, number | string>;
}
```

### `RunStats` (final summary)
```typescript
interface RunStats {
  totalRequirements: number;
  fit: number;
  partialFit: number;
  gap: number;
  flagged: number;                    // low confidence / conflict flags
  processingTimeMs: number;
}
```

### `DynafitRun`
```typescript
interface DynafitRun {
  id: string;
  createdAt: Date;
  status: "idle" | "running" | "completed" | "error" | "paused";
  currentPhase: PhaseKey | null;
  activePhaseIndex: number;           // -1 = no phase selected
  phases: PhaseMetadata[];            // always exactly 5 elements
  uploadedFiles: UploadedFile[];
  requirementAtoms: RequirementAtom[];
  retrievalContexts: RetrievalContext[];
  matchResults: MatchResult[];
  classificationResults: ClassificationResult[];
  validatedFitments: ValidatedFitment[];
  stats?: RunStats;
  errorMessage?: string;
}
```

---

## Utility Type Helpers

```typescript
// Check if a phase status means the phase is currently running
function isActiveStatus(status: PhaseStatus): boolean {
  return ["uploading", "processing", "analyzing", "pending"].includes(status);
}

// Check if navigation to a phase index is allowed
function canNavigateTo(phases: PhaseMetadata[], index: number, activeIndex: number): boolean {
  if (index < 0 || index >= phases.length) return false;
  const target = phases[index];
  if (target.status === "completed" || target.status === "warning") return true;
  if (index === activeIndex) return true;
  if (index > 0 && phases[index - 1]?.status === "completed") return true;
  if (index === 0) return true;
  return false;
}
```