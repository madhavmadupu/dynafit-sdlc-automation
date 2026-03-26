"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import { simulateRetrieval } from "@/lib/simulation";
import StatCard from "@/components/shared/StatCard";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { cn } from "@/lib/utils";
import {
  Database, BookOpen, History, Loader2, CheckCheck,
  ArrowRight, Lock, Search, Layers, BarChart3
} from "lucide-react";

const KNOWLEDGE_SOURCES = [
  { icon: Database, label: "D365 Capability KB", desc: "Qdrant vector store + BM25", color: "text-teal-400", bg: "bg-teal-400/5", border: "border-teal-400/20" },
  { icon: BookOpen, label: "MS Learn Corpus", desc: "Module documentation index", color: "text-blue-400", bg: "bg-blue-400/5", border: "border-blue-400/20" },
  { icon: History, label: "Historical Fitments", desc: "Prior wave decisions (pgvector)", color: "text-purple-400", bg: "bg-purple-400/5", border: "border-purple-400/20" },
];

const PIPELINE_STEPS = [
  { label: "Query Builder", desc: "Build embeddings & filters" },
  { label: "Parallel Retrieval", desc: "Search all 3 sources" },
  { label: "RRF Fusion", desc: "Reciprocal rank fusion" },
  { label: "Cross-Encoder", desc: "MiniLM reranking" },
  { label: "Context Assembly", desc: "Merge results" },
];

export default function Phase2Retrieval() {
  const { run, retryPhase } = useDynafitStore();
  const phase = run.phases.find((p) => p.key === "retrieval")!;
  const prevPhase = run.phases.find((p) => p.key === "ingestion")!;
  const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
  const isCompleted = phase.status === "completed" || phase.status === "warning";
  const isError = phase.status === "error";
  const canRun = prevPhase.status === "completed" || prevPhase.status === "warning";

  const currentStep = phase.stats?.step
    ? PIPELINE_STEPS.findIndex((s) => String(phase.stats?.step).toLowerCase().includes(s.label.toLowerCase().split(" ")[0]))
    : -1;

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Phase 2 — Knowledge Retrieval Agent</h2>
        </div>
        <p className="text-sm text-slate-500 ml-4">
          RAG search across D365 knowledge bases to find matching capabilities for each requirement atom.
        </p>
      </div>

      {isError && phase.errorMessage && (
        <ErrorBanner message={phase.errorMessage} onRetry={() => retryPhase("retrieval")} />
      )}

      {/* Knowledge source cards */}
      <div className="grid grid-cols-3 gap-3">
        {KNOWLEDGE_SOURCES.map((src, i) => (
          <div
            key={i}
            className={cn(
              "rounded-xl p-4 border transition-all",
              isActive ? `${src.bg} ${src.border}` :
              isCompleted ? `${src.bg} ${src.border}` :
              "bg-surface-card border-surface-border"
            )}
          >
            <div className="flex items-center gap-2 mb-2">
              <src.icon size={16} className={cn(isActive || isCompleted ? src.color : "text-slate-500")} />
              <span className={cn("text-xs font-medium", isActive || isCompleted ? "text-slate-200" : "text-slate-500")}>
                {src.label}
              </span>
            </div>
            <p className="text-[10px] text-slate-500">{src.desc}</p>
            {isActive && (
              <div className="flex items-center gap-1.5 mt-2">
                <Loader2 size={10} className={cn("animate-spin", src.color)} />
                <span className={cn("text-[10px]", src.color)}>Searching...</span>
              </div>
            )}
            {isCompleted && (
              <div className="flex items-center gap-1.5 mt-2">
                <CheckCheck size={10} className={src.color} />
                <span className={cn("text-[10px]", src.color)}>Complete</span>
              </div>
            )}
            {!isActive && !isCompleted && (
              <div className="flex items-center gap-1.5 mt-2">
                <Lock size={10} className="text-slate-600" />
                <span className="text-[10px] text-slate-600">Waiting</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Processing pipeline */}
      {isActive && (
        <div className="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm font-medium text-brand-400">Retrieval Pipeline</span>
          </div>

          <div className="flex items-center gap-1">
            {PIPELINE_STEPS.map((step, i) => {
              const isStepActive = i === currentStep || (currentStep === -1 && i === 0);
              const isStepDone = i < currentStep;
              return (
                <div key={i} className="flex items-center flex-1">
                  <div className={cn(
                    "rounded-lg p-2 border text-center flex-1 transition-all",
                    isStepActive ? "bg-brand-500/10 border-brand-500/30" :
                    isStepDone ? "bg-emerald-400/5 border-emerald-400/20" :
                    "bg-surface border-surface-border"
                  )}>
                    <div className="flex items-center justify-center mb-1">
                      {isStepActive ? <Loader2 size={12} className="text-brand-400 animate-spin" /> :
                       isStepDone ? <CheckCheck size={12} className="text-emerald-400" /> :
                       <div className="w-2.5 h-2.5 rounded-full bg-slate-700" />}
                    </div>
                    <p className={cn("text-[10px] font-medium", isStepActive ? "text-brand-400" : isStepDone ? "text-emerald-300" : "text-slate-600")}>
                      {step.label}
                    </p>
                  </div>
                  {i < PIPELINE_STEPS.length - 1 && <ArrowRight size={10} className="text-slate-700 mx-0.5 shrink-0" />}
                </div>
              );
            })}
          </div>

          <div className="mt-4">
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full progress-bar shimmer" style={{ width: `${phase.progress}%` }} />
            </div>
            <div className="flex justify-between mt-1">
              <span className="text-[10px] text-slate-600">{String(phase.stats?.step || "Initializing...")}</span>
              <span className="text-[10px] text-brand-400 font-mono">{phase.progress}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Idle — run button */}
      {phase.status === "idle" && canRun && (
        <button
          onClick={simulateRetrieval}
          className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
        >
          <Search size={16} />
          Run Knowledge Retrieval
          <ArrowRight size={16} />
        </button>
      )}

      {phase.status === "idle" && !canRun && (
        <div className="flex items-center justify-center gap-2 py-8 text-slate-600">
          <Lock size={16} />
          <span className="text-sm">Complete Phase 1 to unlock retrieval</span>
        </div>
      )}

      {/* Completion stats */}
      {isCompleted && phase.stats && (
        <div className="space-y-4 animate-slide-up">
          <div className="grid grid-cols-4 gap-3">
            <StatCard label="Capabilities" value={phase.stats.capabilitiesRetrieved || 0} icon={Layers} color="brand" />
            <StatCard label="MS Learn Refs" value={phase.stats.msLearnRefs || 0} icon={BookOpen} color="emerald" />
            <StatCard label="Historical" value={phase.stats.historicalMatches || 0} icon={History} color="amber" />
            <StatCard label="Avg Confidence" value={phase.stats.avgConfidence || "0"} icon={BarChart3} color="brand" />
          </div>

          <button
            onClick={() => useDynafitStore.getState().goToPhase(2)}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
          >
            Proceed to Matching
            <ArrowRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
