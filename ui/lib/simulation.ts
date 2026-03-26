"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import type { RequirementAtom, ClassificationResult, ValidatedFitment, FitmentClass } from "@/types";

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

const MODULES = ["AP", "AR", "GL", "SCM", "PO", "FA", "HR", "PP", "INV", "TMS"];
const PRIORITIES: RequirementAtom["priority"][] = ["MUST", "SHOULD", "COULD"];

const SAMPLE_TEXTS = [
  "System must support three-way matching for vendor invoices with configurable tolerance thresholds",
  "Automated bank reconciliation with AI-assisted matching for GL transactions",
  "Multi-currency support for intercompany transactions across subsidiaries",
  "Real-time inventory tracking with warehouse management integration",
  "Automated purchase order approval workflow with configurable thresholds",
  "Fixed asset depreciation calculation supporting multiple methods (SL, DB, SYD)",
  "Employee expense report submission with receipt OCR and auto-categorization",
  "Production planning with BOM explosion and capacity scheduling",
  "Vendor payment batch processing with early payment discount optimization",
  "Sales order to invoice automation with delivery tolerance checks",
  "Budget control framework with encumbrance and pre-encumbrance tracking",
  "Customer credit management with automated hold/release workflows",
  "Tax engine integration for multi-jurisdiction compliance (GST, VAT, Sales Tax)",
  "Procurement category hierarchy with approval policies per category",
  "Quality management with inspection plans and non-conformance tracking",
];

const RATIONALES: Record<FitmentClass, string[]> = {
  FIT: [
    "D365 F&O natively supports this requirement through the standard module configuration without any customization.",
    "This capability is available out-of-the-box in D365 and aligns with documented best practices.",
    "Standard D365 functionality fully covers this business requirement across all specified scenarios.",
  ],
  PARTIAL_FIT: [
    "D365 partially covers this requirement but needs additional parameter configuration for the custom tolerance thresholds.",
    "Core functionality exists in D365 but requires ISV solution or minor extension for full coverage.",
    "D365 supports the base scenario, but edge cases require Power Automate workflow customization.",
  ],
  GAP: [
    "No standard D365 feature addresses this requirement. Custom X++ development is needed.",
    "This requirement goes beyond D365's standard capabilities and requires a custom extension module.",
    "D365 does not support this specific business process. Development of a custom solution is recommended.",
  ],
};

function generateMockAtoms(count: number): RequirementAtom[] {
  return Array.from({ length: count }, (_, i) => {
    const isAmbiguous = Math.random() < 0.12;
    const isDuplicate = Math.random() < 0.06;
    return {
      id: `req-${String(i + 1).padStart(4, "0")}`,
      text: SAMPLE_TEXTS[i % SAMPLE_TEXTS.length],
      module: MODULES[Math.floor(Math.random() * MODULES.length)],
      priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
      completenessScore: 60 + Math.floor(Math.random() * 41),
      isAmbiguous,
      isDuplicate,
      sourceFile: `requirements_wave${Math.ceil(Math.random() * 3)}.xlsx`,
      sourceRow: i + 2,
    };
  });
}

function generateMockClassifications(atoms: RequirementAtom[]): ClassificationResult[] {
  return atoms.map((atom) => {
    const rand = Math.random();
    let classification: FitmentClass;
    let confidence: number;

    if (rand < 0.4) {
      classification = "FIT";
      confidence = 0.85 + Math.random() * 0.14;
    } else if (rand < 0.75) {
      classification = "PARTIAL_FIT";
      confidence = 0.60 + Math.random() * 0.24;
    } else {
      classification = "GAP";
      confidence = 0.20 + Math.random() * 0.35;
    }

    const rationales = RATIONALES[classification];
    return {
      requirementId: atom.id,
      requirementText: atom.text,
      classification,
      confidence: Math.round(confidence * 100) / 100,
      rationale: rationales[Math.floor(Math.random() * rationales.length)],
      d365Feature: classification !== "GAP" ? `${atom.module} > Auto-configured feature` : undefined,
      d365Module: atom.module,
      configNotes: classification === "PARTIAL_FIT" ? "Configure matching policy in module parameters." : undefined,
      gapDescription: classification === "GAP" ? "Custom X++ development required for this scenario." : undefined,
      caveats: Math.random() > 0.7 ? ["Review with functional consultant", "Verify in sandbox environment"] : undefined,
    };
  });
}

// ─── Simulation Functions ──────────────────────────────────────

export async function simulateIngestion() {
  const store = useDynafitStore.getState();
  store.startPhase("ingestion");

  await delay(300);
  store.setPhaseStatus("ingestion", "uploading");
  store.updatePhaseProgress("ingestion", 15, { step: "Uploading documents..." });

  await delay(500);
  store.setPhaseStatus("ingestion", "processing");
  store.updatePhaseProgress("ingestion", 35, { step: "Parsing document formats..." });

  await delay(500);
  store.updatePhaseProgress("ingestion", 55, { step: "Extracting requirements..." });

  await delay(500);
  store.updatePhaseProgress("ingestion", 75, { step: "Normalizing language..." });

  await delay(400);
  store.updatePhaseProgress("ingestion", 90, { step: "Validating atoms..." });

  const atoms = generateMockAtoms(265);
  store.setRequirementAtoms(atoms);

  const ambiguous = atoms.filter((a) => a.isAmbiguous).length;
  const duplicates = atoms.filter((a) => a.isDuplicate).length;
  const modules = new Set(atoms.map((a) => a.module)).size;

  await delay(300);
  store.completePhase("ingestion", {
    totalAtoms: atoms.length,
    modules,
    ambiguous,
    duplicates,
  });

  if (ambiguous > 0) {
    store.warnPhase("ingestion", `${ambiguous} requirements flagged as ambiguous – review recommended`);
  }
}

export async function simulateRetrieval() {
  const store = useDynafitStore.getState();
  store.startPhase("retrieval");

  await delay(400);
  store.updatePhaseProgress("retrieval", 15, { step: "Building query embeddings..." });

  await delay(500);
  store.updatePhaseProgress("retrieval", 35, { step: "Searching D365 Capability KB..." });

  await delay(500);
  store.updatePhaseProgress("retrieval", 55, { step: "Searching MS Learn corpus..." });

  await delay(500);
  store.updatePhaseProgress("retrieval", 75, { step: "Running RRF fusion..." });

  await delay(400);
  store.updatePhaseProgress("retrieval", 90, { step: "Cross-encoder reranking..." });

  await delay(300);
  const atomCount = store.run.requirementAtoms.length;
  store.completePhase("retrieval", {
    capabilitiesRetrieved: atomCount * 5,
    msLearnRefs: Math.floor(atomCount * 2.3),
    historicalMatches: Math.floor(atomCount * 0.8),
    avgConfidence: "0.76",
  });
}

export async function simulateMatching() {
  const store = useDynafitStore.getState();
  store.startPhase("matching");

  await delay(400);
  store.updatePhaseProgress("matching", 20, { step: "Computing cosine similarities..." });

  await delay(500);
  store.setPhaseStatus("matching", "analyzing");
  store.updatePhaseProgress("matching", 50, { step: "Scoring confidence tiers..." });

  await delay(500);
  store.updatePhaseProgress("matching", 75, { step: "Ranking candidates..." });

  await delay(400);
  store.updatePhaseProgress("matching", 90, { step: "Finalizing route decisions..." });

  const atomCount = store.run.requirementAtoms.length;
  const fastTrack = Math.floor(atomCount * 0.35);
  const needsLLM = Math.floor(atomCount * 0.40);
  const likelyGap = atomCount - fastTrack - needsLLM;

  await delay(300);
  store.completePhase("matching", {
    fastTrack,
    needsLLM,
    likelyGap,
    avgScore: "0.72",
  });
}

export async function simulateClassification() {
  const store = useDynafitStore.getState();
  store.startPhase("classification");

  const totalBatches = 5;
  for (let batch = 1; batch <= totalBatches; batch++) {
    await delay(600);
    const progress = Math.round((batch / totalBatches) * 90);
    store.updatePhaseProgress("classification", progress, {
      step: `Processing batch ${batch}/${totalBatches}...`,
      batch: `${batch}/${totalBatches}`,
    });
  }

  const atoms = store.run.requirementAtoms;
  const results = generateMockClassifications(atoms);
  store.setClassificationResults(results);

  const fit = results.filter((r) => r.classification === "FIT").length;
  const partial = results.filter((r) => r.classification === "PARTIAL_FIT").length;
  const gap = results.filter((r) => r.classification === "GAP").length;

  await delay(300);
  store.completePhase("classification", {
    fit,
    partialFit: partial,
    gap,
    avgConfidence: (results.reduce((s, r) => s + r.confidence, 0) / results.length).toFixed(2),
    lowConfidence: results.filter((r) => r.confidence < 0.65).length,
  });
}

export async function simulateValidation() {
  const store = useDynafitStore.getState();
  store.startPhase("validation");

  await delay(400);
  store.updatePhaseProgress("validation", 20, { step: "Running consistency checks..." });

  await delay(500);
  store.updatePhaseProgress("validation", 45, { step: "Checking dependency graph..." });

  await delay(500);
  store.updatePhaseProgress("validation", 65, { step: "Applying country overrides..." });

  await delay(400);
  store.updatePhaseProgress("validation", 85, { step: "Building review queue..." });

  const classifications = store.run.classificationResults;
  const validated: ValidatedFitment[] = classifications.map((c) => ({
    ...c,
    consultantVerified: false,
    conflictFlags: Math.random() > 0.9 ? [`Dependency conflict with ${c.requirementId}`] : [],
    finalVerdict: c.classification,
  }));

  store.setValidatedFitments(validated);

  const fit = validated.filter((v) => v.finalVerdict === "FIT").length;
  const partial = validated.filter((v) => v.finalVerdict === "PARTIAL_FIT").length;
  const gap = validated.filter((v) => v.finalVerdict === "GAP").length;
  const flagged = validated.filter((v) => v.confidence < 0.65 || v.conflictFlags.length > 0).length;

  store.setRunStats({
    totalRequirements: validated.length,
    fit,
    partialFit: partial,
    gap,
    flagged,
    processingTimeMs: Date.now() - store.run.createdAt.getTime(),
  });

  await delay(300);
  store.completePhase("validation", {
    totalVerified: validated.length,
    overrides: 0,
    conflicts: validated.filter((v) => v.conflictFlags.length > 0).length,
    exportReady: "true",
  });
}

export async function runFullPipeline() {
  await simulateIngestion();
  await simulateRetrieval();
  await simulateMatching();
  await simulateClassification();
  await simulateValidation();
}
