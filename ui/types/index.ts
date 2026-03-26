// ─── Phase execution status ────────────────────────────────────
export type PhaseStatus =
  | "idle"
  | "pending"
  | "uploading"
  | "processing"
  | "analyzing"
  | "completed"
  | "warning"
  | "error"
  | "skipped";

// ─── Fitment classification output ─────────────────────────────
export type FitmentClass = "FIT" | "PARTIAL_FIT" | "GAP";

// ─── Confidence tier (from Phase 3 routing) ────────────────────
export type ConfidenceTier = "HIGH" | "MED" | "LOW";

// ─── Phase identifier keys ─────────────────────────────────────
export type PhaseKey =
  | "ingestion"
  | "retrieval"
  | "matching"
  | "classification"
  | "validation";

// ─── Phase 1 Output ────────────────────────────────────────────
export interface RequirementAtom {
  id: string;
  text: string;
  module: string;
  priority: "MUST" | "SHOULD" | "COULD" | "WONT";
  country?: string;
  completenessScore: number;
  isAmbiguous: boolean;
  isDuplicate: boolean;
  sourceFile: string;
  sourceRow?: number;
}

// ─── Phase 2 Output ────────────────────────────────────────────
export interface D365Capability {
  id: string;
  title: string;
  module: string;
  description: string;
  msLearnUrl?: string;
  confidenceSignal: number;
}

export interface PriorFitment {
  wave: string;
  country: string;
  classification: FitmentClass;
  confidence: number;
}

export interface RetrievalContext {
  requirementId: string;
  topCapabilities: D365Capability[];
  priorFitments: PriorFitment[];
  msLearnRefs: string[];
}

// ─── Phase 3 Output ────────────────────────────────────────────
export interface MatchResult {
  requirementId: string;
  cosineScore: number;
  confidenceTier: ConfidenceTier;
  compositeScore: number;
  topCandidates: D365Capability[];
  routeDecision: "FAST_TRACK" | "LLM_REASON" | "LIKELY_GAP";
}

// ─── Phase 4 Output ────────────────────────────────────────────
export interface ClassificationResult {
  requirementId: string;
  requirementText?: string;
  classification: FitmentClass;
  confidence: number;
  rationale: string;
  d365Feature?: string;
  d365Module?: string;
  configNotes?: string;
  gapDescription?: string;
  caveats?: string[];
  overriddenBy?: string;
  overrideReason?: string;
}

// ─── Phase 5 Output ────────────────────────────────────────────
export interface ValidatedFitment extends ClassificationResult {
  consultantVerified: boolean;
  conflictFlags: string[];
  countryOverride?: string;
  finalVerdict: FitmentClass;
}

// ─── Supporting Types ──────────────────────────────────────────
export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  status: "queued" | "uploading" | "parsed" | "error";
  progress: number;
  errorMessage?: string;
}

export interface PhaseMetadata {
  id: number;
  key: PhaseKey;
  label: string;
  shortLabel: string;
  description: string;
  icon: string;
  status: PhaseStatus;
  progress: number;
  startedAt?: Date;
  completedAt?: Date;
  errorMessage?: string;
  warningMessage?: string;
  stats?: Record<string, number | string>;
}

export interface RunStats {
  totalRequirements: number;
  fit: number;
  partialFit: number;
  gap: number;
  flagged: number;
  processingTimeMs: number;
}

export interface DynafitRun {
  id: string;
  createdAt: Date;
  status: "idle" | "running" | "completed" | "error" | "paused";
  currentPhase: PhaseKey | null;
  activePhaseIndex: number;
  phases: PhaseMetadata[];
  uploadedFiles: UploadedFile[];
  requirementAtoms: RequirementAtom[];
  retrievalContexts: RetrievalContext[];
  matchResults: MatchResult[];
  classificationResults: ClassificationResult[];
  validatedFitments: ValidatedFitment[];
  stats?: RunStats;
  errorMessage?: string;
}

// ─── Utility helpers ───────────────────────────────────────────
export function isActiveStatus(status: PhaseStatus): boolean {
  return ["uploading", "processing", "analyzing", "pending"].includes(status);
}

export function canNavigateToPhase(
  phases: PhaseMetadata[],
  index: number,
  activeIndex: number
): boolean {
  if (index < 0 || index >= phases.length) return false;
  const target = phases[index];
  if (target.status === "completed" || target.status === "warning") return true;
  if (index === activeIndex) return true;
  if (index > 0 && (phases[index - 1]?.status === "completed" || phases[index - 1]?.status === "warning")) return true;
  if (index === 0) return true;
  return false;
}
