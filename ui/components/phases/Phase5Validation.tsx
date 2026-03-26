"use client";

import { useState, useCallback } from "react";
import { useDynafitStore } from "@/store/useDynafitStore";
import { simulateValidation } from "@/lib/simulation";
import { api } from "@/lib/api";
import StatusBadge from "@/components/shared/StatusBadge";
import ConfidenceMeter from "@/components/shared/ConfidenceMeter";
import StatCard from "@/components/shared/StatCard";
import ErrorBanner from "@/components/shared/ErrorBanner";
import OverrideModal from "@/components/modals/OverrideModal";
import { cn } from "@/lib/utils";
import type { ClassificationResult } from "@/types";
import {
  CheckCircle, Loader2, Lock, ArrowRight, Download, Shield,
  AlertTriangle, FileText, Settings, ArrowDown, Play
} from "lucide-react";

interface Props {
  hasBackend: boolean;
  backendRunId: string | null;
}

export default function Phase5Validation({ hasBackend, backendRunId }: Props) {
  const { run, retryPhase } = useDynafitStore();
  const phase = run.phases.find((p) => p.key === "validation")!;
  const prevPhase = run.phases.find((p) => p.key === "classification")!;
  const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
  const isCompleted = phase.status === "completed" || phase.status === "warning";
  const isError = phase.status === "error";
  const canRun = prevPhase.status === "completed" || prevPhase.status === "warning";

  const [overrideItem, setOverrideItem] = useState<ClassificationResult | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const fitments = run.validatedFitments;
  // Pipeline paused for review: validation idle, classification done, and we have results
  const awaitingReview = phase.status === "idle" && canRun && backendRunId && fitments.length > 0;

  const { startPhase, completePhase } = useDynafitStore();

  const handleSubmitReview = useCallback(async () => {
    if (!backendRunId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      // Collect any overrides the user has made
      const decisions = fitments
        .filter((f) => f.consultantVerified)
        .map((f) => ({
          atom_id: f.requirementId,
          verdict: f.finalVerdict,
          reason: f.overrideReason || "Consultant reviewed",
          reviewed_by: f.overriddenBy || "consultant",
        }));

      startPhase("validation");

      const result = await api.submitReview(backendRunId, { decisions });

      // Fetch final results and complete validation
      const results = await api.getRunResults(backendRunId);
      if (results.classificationResults?.length) {
        completePhase("validation", {
          totalVerified: results.classificationResults.length,
          overrides: decisions.length,
          conflicts: 0,
          exportReady: "true",
        });
      } else {
        completePhase("validation", {
          totalVerified: fitments.length,
          overrides: decisions.length,
          conflicts: 0,
          exportReady: "true",
        });
      }
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Failed to submit review");
      // Revert validation phase back to idle
      useDynafitStore.getState().setPhaseStatus("validation", "idle");
    } finally {
      setSubmitting(false);
    }
  }, [backendRunId, fitments, startPhase, completePhase]);

  const handleExport = async () => {
    if (hasBackend && backendRunId) {
      // Download real fitment matrix from backend
      setExporting(true);
      try {
        const blob = await api.downloadFitmentMatrix(backendRunId);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "fitment_matrix.xlsx";
        a.click();
        URL.revokeObjectURL(url);
      } catch (e: unknown) {
        console.error("Export failed:", e);
        alert(e instanceof Error ? e.message : "Export failed — file may not be generated yet.");
      } finally {
        setExporting(false);
      }
    } else {
      // Fallback: generate a placeholder blob
      const blob = new Blob(["fitment_matrix_export"], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "fitment_matrix.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Phase 5 — Validation & Output Agent</h2>
        </div>
        <p className="text-sm text-slate-500 ml-4">
          Consistency checks, human review queue, and final fitment matrix generation.
        </p>
      </div>

      {isError && phase.errorMessage && (
        <ErrorBanner message={phase.errorMessage} onRetry={() => retryPhase("validation")} />
      )}

      {/* Processing */}
      {isActive && (
        <div className="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm font-medium text-brand-400">Validation Pipeline</span>
          </div>
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full progress-bar shimmer" style={{ width: `${phase.progress}%` }} />
          </div>
          <div className="flex justify-between mt-1">
            <span className="text-[10px] text-slate-600">{String(phase.stats?.step || "Initializing...")}</span>
            <span className="text-[10px] text-brand-400 font-mono">{phase.progress}%</span>
          </div>
        </div>
      )}

      {/* Awaiting Review — show review queue + submit button */}
      {awaitingReview && (
        <div className="space-y-4 animate-slide-up">
          {submitError && (
            <ErrorBanner message={submitError} onRetry={handleSubmitReview} />
          )}

          <div className="bg-amber-400/5 border border-amber-400/20 rounded-xl p-4 flex items-center gap-3">
            <Shield size={16} className="text-amber-400" />
            <div>
              <p className="text-xs font-medium text-amber-300">Awaiting Consultant Review</p>
              <p className="text-[10px] text-slate-500">
                Review the classification results below. Override any incorrect verdicts, then submit to run validation.
              </p>
            </div>
          </div>

          {/* Review queue table */}
          <div className="bg-surface-card border border-surface-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <Shield size={14} className="text-brand-400" />
                <span className="text-xs font-medium text-slate-300">Review Queue — {fitments.length} items</span>
              </div>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-hover">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">ID</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Requirement</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">Verdict</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-28">Confidence</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">Action</th>
                </tr>
              </thead>
              <tbody>
                {fitments.slice(0, 50).map((f) => {
                  const isLowConf = f.confidence < 0.65;
                  return (
                    <tr
                      key={f.requirementId}
                      className={cn(
                        "data-row border-b border-surface-border/50 last:border-0",
                        isLowConf && "border-l-2 border-l-amber-400/50"
                      )}
                    >
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{f.requirementId}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-300 max-w-xs truncate">{f.requirementText || f.rationale}</td>
                      <td className="px-4 py-2.5"><StatusBadge status={f.finalVerdict} /></td>
                      <td className="px-4 py-2.5"><ConfidenceMeter value={f.confidence} /></td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => {
                            setOverrideItem(f);
                            setModalOpen(true);
                          }}
                          className="px-2.5 py-1 rounded-md border border-brand-500/30 bg-brand-500/5 text-brand-300 text-[10px] hover:bg-brand-500/15 transition-colors"
                        >
                          Override
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Submit review button */}
          <button
            onClick={handleSubmitReview}
            disabled={submitting}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Running Validation...
              </>
            ) : (
              <>
                <Play size={16} />
                Submit Review & Run Validation
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      )}

      {/* Idle — no results yet */}
      {phase.status === "idle" && canRun && !awaitingReview && (
        <>
          <div className="bg-surface-card border border-surface-border rounded-xl p-5">
            <p className="text-xs text-slate-400 mb-3 font-medium">Validation Pipeline Steps</p>
            <div className="space-y-2">
              {[
                { icon: Settings, label: "Consistency Check", desc: "Dependency graph & country overrides" },
                { icon: Shield, label: "Human Review", desc: "Override queue with LangGraph interrupt" },
                { icon: FileText, label: "Report Generator", desc: "Excel builder with audit trail" },
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-3 py-1.5">
                  <div className="w-6 h-6 rounded-lg bg-surface border border-surface-border flex items-center justify-center">
                    <step.icon size={12} className="text-slate-500" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-slate-300">{step.label}</p>
                    <p className="text-[10px] text-slate-600">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {!backendRunId && (
            <button
              onClick={simulateValidation}
              className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
            >
              <CheckCircle size={16} />
              Run Validation
              <ArrowRight size={16} />
            </button>
          )}
          {backendRunId && (
            <div className="flex items-center justify-center gap-2 py-4 text-brand-400">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Pipeline is running — validation will begin after classification...</span>
            </div>
          )}
        </>
      )}

      {phase.status === "idle" && !canRun && (
        <div className="flex items-center justify-center gap-2 py-8 text-slate-600">
          <Lock size={16} />
          <span className="text-sm">Complete Phase 4 to unlock validation</span>
        </div>
      )}

      {/* Completed — human review queue */}
      {isCompleted && fitments.length > 0 && (
        <div className="space-y-4 animate-slide-up">
          {/* Stats */}
          <div className="grid grid-cols-4 gap-3">
            <StatCard label="Total Verified" value={phase.stats?.totalVerified || 0} icon={CheckCircle} color="brand" />
            <StatCard label="Overrides" value={phase.stats?.overrides || 0} icon={Shield} color="amber" />
            <StatCard label="Conflicts" value={phase.stats?.conflicts || 0} icon={AlertTriangle} color={Number(phase.stats?.conflicts) > 0 ? "red" : "slate"} />
            <StatCard label="Export Ready" value={phase.stats?.exportReady === "true" ? "Yes" : "No"} icon={Download} color="emerald" />
          </div>

          {/* Review queue table */}
          <div className="bg-surface-card border border-surface-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <Shield size={14} className="text-brand-400" />
                <span className="text-xs font-medium text-slate-300">Human Review Queue</span>
              </div>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="px-3 py-1.5 rounded-lg bg-emerald-400/10 border border-emerald-400/20 text-emerald-300 text-xs hover:bg-emerald-400/20 transition-colors flex items-center gap-1.5 disabled:opacity-50"
              >
                {exporting ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                Export Matrix
              </button>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-hover">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">ID</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Requirement</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">Verdict</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-28">Confidence</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-20">Status</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">Action</th>
                </tr>
              </thead>
              <tbody>
                {fitments.slice(0, 50).map((f) => {
                  const isLowConf = f.confidence < 0.65;
                  return (
                    <tr
                      key={f.requirementId}
                      className={cn(
                        "data-row border-b border-surface-border/50 last:border-0",
                        isLowConf && "border-l-2 border-l-amber-400/50"
                      )}
                    >
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{f.requirementId}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-300 max-w-xs truncate">{f.requirementText || f.rationale}</td>
                      <td className="px-4 py-2.5"><StatusBadge status={f.finalVerdict} /></td>
                      <td className="px-4 py-2.5"><ConfidenceMeter value={f.confidence} /></td>
                      <td className="px-4 py-2.5">
                        {f.consultantVerified ? (
                          <span className="badge bg-emerald-400/10 border-emerald-400/20 text-emerald-300">Verified</span>
                        ) : isLowConf ? (
                          <span className="badge bg-amber-400/10 border-amber-400/20 text-amber-300">Review</span>
                        ) : (
                          <span className="badge bg-slate-400/10 border-slate-400/20 text-slate-400">Pending</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => {
                            setOverrideItem(f);
                            setModalOpen(true);
                          }}
                          className="px-2.5 py-1 rounded-md border border-brand-500/30 bg-brand-500/5 text-brand-300 text-[10px] hover:bg-brand-500/15 transition-colors"
                        >
                          Override
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Downstream preview */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-emerald-400/5 border border-emerald-400/20 rounded-xl p-4 flex items-center gap-3">
              <ArrowRight size={16} className="text-emerald-400" />
              <div>
                <p className="text-xs font-medium text-emerald-300">FDD FOR FITS</p>
                <p className="text-[10px] text-slate-500">Functional Design Document for standard D365 features</p>
              </div>
            </div>
            <div className="bg-red-400/5 border border-red-400/20 rounded-xl p-4 flex items-center gap-3">
              <ArrowRight size={16} className="text-red-400" />
              <div>
                <p className="text-xs font-medium text-red-300">FDD FOR GAPS</p>
                <p className="text-[10px] text-slate-500">Technical Design Document for custom X++ development</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Override modal */}
      <OverrideModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setOverrideItem(null);
        }}
        item={overrideItem}
        hasBackend={hasBackend}
        backendRunId={backendRunId}
      />
    </div>
  );
}
