"use client";

import { useState, useMemo } from "react";
import { useDynafitStore } from "@/store/useDynafitStore";
import { simulateClassification } from "@/lib/simulation";
import StatusBadge from "@/components/shared/StatusBadge";
import ConfidenceMeter from "@/components/shared/ConfidenceMeter";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { cn } from "@/lib/utils";
import {
  Brain, Loader2, Lock, ArrowRight, Search, ChevronDown, ChevronUp,
  Filter, ArrowDown
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { FitmentClass } from "@/types";

const MODULES_ALL = ["All", "AP", "AR", "GL", "SCM", "PO", "FA", "HR", "PP", "INV", "TMS"];
const CLASSIFICATIONS: (FitmentClass | "ALL")[] = ["ALL", "FIT", "PARTIAL_FIT", "GAP"];
const PAGE_SIZE = 25;

export default function Phase4Classification() {
  const { run, retryPhase } = useDynafitStore();
  const phase = run.phases.find((p) => p.key === "classification")!;
  const prevPhase = run.phases.find((p) => p.key === "matching")!;
  const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
  const isCompleted = phase.status === "completed" || phase.status === "warning";
  const isError = phase.status === "error";
  const canRun = prevPhase.status === "completed" || prevPhase.status === "warning";

  const [search, setSearch] = useState("");
  const [moduleFilter, setModuleFilter] = useState("All");
  const [classFilter, setClassFilter] = useState<FitmentClass | "ALL">("ALL");
  const [page, setPage] = useState(0);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const results = run.classificationResults;

  const filtered = useMemo(() => {
    return results.filter((r) => {
      if (search && !r.requirementId.toLowerCase().includes(search.toLowerCase()) && !r.requirementText?.toLowerCase().includes(search.toLowerCase())) return false;
      if (moduleFilter !== "All" && r.d365Module !== moduleFilter) return false;
      if (classFilter !== "ALL" && r.classification !== classFilter) return false;
      return true;
    });
  }, [results, search, moduleFilter, classFilter]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const fitCount = results.filter((r) => r.classification === "FIT").length;
  const partialCount = results.filter((r) => r.classification === "PARTIAL_FIT").length;
  const gapCount = results.filter((r) => r.classification === "GAP").length;
  const total = results.length || 1;

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Phase 4 — Classification Agent</h2>
        </div>
        <p className="text-sm text-slate-500 ml-4">
          LLM chain-of-thought reasoning to classify each requirement as FIT, PARTIAL FIT, or GAP.
        </p>
      </div>

      {isError && phase.errorMessage && (
        <ErrorBanner message={phase.errorMessage} onRetry={() => retryPhase("classification")} />
      )}

      {/* Processing state */}
      {isActive && (
        <div className="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm font-medium text-brand-400">LLM Reasoning in Progress</span>
          </div>
          {phase.stats?.batch && (
            <p className="text-xs text-slate-400 mb-2">Batch {String(phase.stats.batch)}</p>
          )}
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full progress-bar shimmer" style={{ width: `${phase.progress}%` }} />
          </div>
          <div className="flex justify-between mt-1">
            <span className="text-[10px] text-slate-600">{String(phase.stats?.step || "Initializing...")}</span>
            <span className="text-[10px] text-brand-400 font-mono">{phase.progress}%</span>
          </div>
        </div>
      )}

      {/* Idle states */}
      {phase.status === "idle" && canRun && (
        <>
          {/* CoT preview */}
          <div className="bg-surface-card border border-surface-border rounded-xl p-5">
            <p className="text-xs text-slate-400 mb-3 font-medium">Chain-of-Thought Reasoning Steps</p>
            <div className="space-y-2">
              {[
                "1. Does a matching D365 feature exist?",
                "2. Does it fully cover the requirement?",
                "3. What is the gap between D365 and the requirement?",
                "4. Does historical evidence support this?",
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-slate-500">
                  <div className="w-5 h-5 rounded-full bg-surface border border-surface-border flex items-center justify-center text-[10px] text-slate-600 shrink-0">
                    {i + 1}
                  </div>
                  {step.slice(3)}
                </div>
              ))}
            </div>
          </div>
          <button
            onClick={simulateClassification}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
          >
            <Brain size={16} />
            Run Classification Agent
            <ArrowRight size={16} />
          </button>
        </>
      )}

      {phase.status === "idle" && !canRun && (
        <div className="flex items-center justify-center gap-2 py-8 text-slate-600">
          <Lock size={16} />
          <span className="text-sm">Complete Phase 3 to unlock classification</span>
        </div>
      )}

      {/* Completion — results */}
      {isCompleted && results.length > 0 && (
        <div className="space-y-4 animate-slide-up">
          {/* Summary bar */}
          <div className="flex items-center gap-3 bg-surface-card border border-surface-border rounded-xl p-4">
            <div className="flex items-center gap-2 flex-1">
              <div className="h-8 rounded-lg bg-emerald-400/15 border border-emerald-400/20 flex items-center px-3 gap-1.5">
                <div className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-xs font-medium text-emerald-300">FIT {fitCount}</span>
                <span className="text-[10px] text-emerald-400/60">({Math.round(fitCount / total * 100)}%)</span>
              </div>
              <div className="h-8 rounded-lg bg-amber-400/15 border border-amber-400/20 flex items-center px-3 gap-1.5">
                <div className="w-2 h-2 rounded-full bg-amber-400" />
                <span className="text-xs font-medium text-amber-300">PARTIAL {partialCount}</span>
                <span className="text-[10px] text-amber-400/60">({Math.round(partialCount / total * 100)}%)</span>
              </div>
              <div className="h-8 rounded-lg bg-red-400/15 border border-red-400/20 flex items-center px-3 gap-1.5">
                <div className="w-2 h-2 rounded-full bg-red-400" />
                <span className="text-xs font-medium text-red-300">GAP {gapCount}</span>
                <span className="text-[10px] text-red-400/60">({Math.round(gapCount / total * 100)}%)</span>
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <Input
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(0); }}
                placeholder="Search requirements..."
                className="pl-9 bg-surface border-surface-border text-slate-300 placeholder:text-slate-600 h-9 text-sm"
              />
            </div>
            <Select value={moduleFilter} onValueChange={(v) => { setModuleFilter(v); setPage(0); }}>
              <SelectTrigger className="w-32 bg-surface border-surface-border text-slate-300 h-9 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-surface-border">
                {MODULES_ALL.map((m) => (
                  <SelectItem key={m} value={m} className="text-slate-300 text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex items-center gap-1">
              {CLASSIFICATIONS.map((c) => (
                <button
                  key={c}
                  onClick={() => { setClassFilter(c); setPage(0); }}
                  className={cn(
                    "px-2.5 py-1.5 rounded-md text-[11px] font-medium border transition-all",
                    classFilter === c
                      ? c === "FIT" ? "bg-emerald-400/15 border-emerald-400/30 text-emerald-300" :
                        c === "PARTIAL_FIT" ? "bg-amber-400/15 border-amber-400/30 text-amber-300" :
                        c === "GAP" ? "bg-red-400/15 border-red-400/30 text-red-300" :
                        "bg-brand-400/15 border-brand-400/30 text-brand-300"
                      : "bg-surface border-surface-border text-slate-500 hover:text-slate-300"
                  )}
                >
                  {c === "ALL" ? "All" : c.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Results table */}
          <div className="rounded-xl border border-surface-border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-surface-hover">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-24">ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Requirement</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-16">Module</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-28">Classification</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-28">Confidence</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8"></th>
                </tr>
              </thead>
              <tbody>
                {paged.map((r) => (
                  <> 
                    <tr
                      key={r.requirementId}
                      onClick={() => setExpandedRow(expandedRow === r.requirementId ? null : r.requirementId)}
                      className="data-row border-b border-surface-border/50 last:border-0 cursor-pointer"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{r.requirementId}</td>
                      <td className="px-4 py-3 text-slate-300 max-w-xs truncate text-xs">{r.requirementText || r.rationale}</td>
                      <td className="px-4 py-3">
                        <span className="badge bg-surface border-surface-border text-slate-400">{r.d365Module || "—"}</span>
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={r.classification} /></td>
                      <td className="px-4 py-3"><ConfidenceMeter value={r.confidence} /></td>
                      <td className="px-4 py-3">
                        {expandedRow === r.requirementId ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
                      </td>
                    </tr>
                    {expandedRow === r.requirementId && (
                      <tr key={`${r.requirementId}-expand`} className="bg-surface">
                        <td colSpan={6} className="px-6 py-4 border-b border-surface-border/50">
                          <div className="grid grid-cols-2 gap-4 text-xs">
                            <div>
                              <p className="text-slate-500 font-medium mb-1">Rationale</p>
                              <p className="text-slate-300">{r.rationale}</p>
                            </div>
                            <div className="space-y-2">
                              {r.d365Feature && (
                                <div>
                                  <p className="text-slate-500 font-medium mb-0.5">D365 Feature</p>
                                  <p className="text-slate-300">{r.d365Feature}</p>
                                </div>
                              )}
                              {r.configNotes && (
                                <div>
                                  <p className="text-slate-500 font-medium mb-0.5">Config Notes</p>
                                  <p className="text-amber-300/80">{r.configNotes}</p>
                                </div>
                              )}
                              {r.gapDescription && (
                                <div>
                                  <p className="text-slate-500 font-medium mb-0.5">Gap Description</p>
                                  <p className="text-red-300/80">{r.gapDescription}</p>
                                </div>
                              )}
                              {r.overriddenBy && (
                                <div>
                                  <p className="text-slate-500 font-medium mb-0.5">Overridden By</p>
                                  <p className="text-brand-300">{r.overriddenBy} — {r.overrideReason}</p>
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-3 py-1.5 rounded-md border border-surface-border text-slate-400 hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Prev
              </button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const p = page < 3 ? i : page - 2 + i;
                if (p >= totalPages) return null;
                return (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={cn(
                      "w-8 h-8 rounded-md text-xs transition-colors",
                      p === page ? "bg-brand-600 text-white" : "border border-surface-border text-slate-400 hover:bg-surface-hover"
                    )}
                  >
                    {p + 1}
                  </button>
                );
              })}
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1.5 rounded-md border border-surface-border text-slate-400 hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          </div>

          <button
            onClick={() => useDynafitStore.getState().goToPhase(4)}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
          >
            Proceed to Validation
            <ArrowRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
