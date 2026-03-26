"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import { FileText, Database, Zap, Brain, CheckCircle, ArrowRight, Sparkles } from "lucide-react";

const PHASES = [
  { icon: FileText, label: "Ingestion", desc: "Parse & atomize requirements", color: "text-blue-400" },
  { icon: Database, label: "Retrieval", desc: "RAG search D365 knowledge", color: "text-teal-400" },
  { icon: Zap, label: "Matching", desc: "Semantic scoring & routing", color: "text-purple-400" },
  { icon: Brain, label: "Classification", desc: "LLM reasoning for FIT/GAP", color: "text-amber-400" },
  { icon: CheckCircle, label: "Validation", desc: "Human review & export", color: "text-emerald-400" },
];

export default function WelcomeScreen() {
  const { goToPhase, startRun } = useDynafitStore();

  const handleStart = () => {
    startRun();
    goToPhase(0);
  };

  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <div className="text-center mb-10">
        <div className="flex items-center justify-center mb-4">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-lg shadow-brand-900/40">
            <Sparkles size={28} className="text-white" />
          </div>
        </div>
        <h1 className="text-2xl font-bold text-white mb-2">DYNAFIT Pipeline</h1>
        <p className="text-sm text-slate-500 max-w-md mx-auto">
          AI-powered fitment analysis for D365 Finance & Operations.
          Upload requirement documents and let the 5-agent pipeline classify every requirement as FIT, PARTIAL FIT, or GAP.
        </p>
      </div>

      {/* Pipeline overview */}
      <div className="bg-surface-card border border-surface-border rounded-2xl p-6 mb-8">
        <div className="flex items-center gap-2 mb-5">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Pipeline Phases</h2>
        </div>

        <div className="space-y-3">
          {PHASES.map((phase, i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="w-8 h-8 rounded-lg bg-surface border border-surface-border flex items-center justify-center shrink-0">
                <phase.icon size={16} className={phase.color} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-slate-600">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-sm font-medium text-slate-200">{phase.label}</span>
                </div>
                <p className="text-xs text-slate-500">{phase.desc}</p>
              </div>
              {i < PHASES.length - 1 && (
                <ArrowRight size={14} className="text-surface-border shrink-0" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Start button */}
      <button
        onClick={handleStart}
        className="w-full py-3.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
      >
        <Sparkles size={16} />
        Start New Run
        <ArrowRight size={16} />
      </button>
    </div>
  );
}
