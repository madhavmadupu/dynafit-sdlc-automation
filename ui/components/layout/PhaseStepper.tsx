"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import { cn } from "@/lib/utils";
import { FileText, Database, Zap, Brain, CheckCircle, Loader2, CheckCheck, XCircle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const PHASE_ICONS: Record<string, React.ElementType> = {
  FileText,
  Database,
  Zap,
  Brain,
  CheckCircle,
};

export default function PhaseStepper() {
  const { run, goToPhase, canNavigateTo } = useDynafitStore();

  return (
    <div className="bg-surface-card border-b border-surface-border px-6 py-3 shrink-0">
      {/* Step chips + connectors */}
      <div className="flex items-center justify-center gap-0 max-w-3xl mx-auto">
        {run.phases.map((phase, i) => {
          const Icon = PHASE_ICONS[phase.icon] || FileText;
          const isActive = phase.status === "processing" || phase.status === "uploading" || phase.status === "analyzing";
          const isCompleted = phase.status === "completed" || phase.status === "warning";
          const isError = phase.status === "error";
          const canNav = canNavigateTo(i);
          const isCurrent = i === run.activePhaseIndex;

          return (
            <div key={phase.key} className="flex items-center">
              {/* Connector line before (not on first) */}
              {i > 0 && (
                <div className="w-8 sm:w-12 lg:w-16 h-0.5 mx-0.5">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      isCompleted || run.phases[i - 1]?.status === "completed" || run.phases[i - 1]?.status === "warning"
                        ? "bg-emerald-400/40"
                        : isActive
                        ? "bg-brand-400/30 shimmer"
                        : "bg-surface-border"
                    )}
                  />
                </div>
              )}

              {/* Step chip */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => canNav && goToPhase(i)}
                    disabled={!canNav}
                    className={cn(
                      "relative flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium transition-all duration-300",
                      isCurrent && "bg-brand-500/15 border border-brand-500/30 text-brand-400 phase-glow",
                      isCompleted && !isCurrent && "bg-emerald-400/10 border border-emerald-400/20 text-emerald-300",
                      isError && "bg-red-400/10 border border-red-400/20 text-red-300",
                      !isCurrent && !isCompleted && !isError && !isActive && "bg-surface-hover border border-surface-border text-slate-500",
                      isActive && !isCurrent && "bg-brand-400/10 border border-brand-400/20 text-brand-400",
                      canNav ? "cursor-pointer hover:scale-105" : "cursor-default opacity-70"
                    )}
                  >
                    <div className="w-5 h-5 flex items-center justify-center">
                      {isActive ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : isCompleted ? (
                        <CheckCheck size={14} />
                      ) : isError ? (
                        <XCircle size={14} />
                      ) : (
                        <Icon size={14} />
                      )}
                    </div>
                    <span className="hidden sm:inline">{phase.shortLabel}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="bg-surface-card border-surface-border text-slate-300">
                  <p className="font-medium">{phase.label}</p>
                  <p className="text-xs text-slate-500">{phase.description}</p>
                </TooltipContent>
              </Tooltip>
            </div>
          );
        })}
      </div>

      {/* Detail bar */}
      {run.activePhaseIndex >= 0 && (
        <div className="mt-2 flex items-center justify-center gap-3 text-xs text-slate-500 max-w-3xl mx-auto">
          {run.phases[run.activePhaseIndex] && (
            <>
              <span className="text-slate-400 font-medium">{run.phases[run.activePhaseIndex].label}</span>
              <div className="h-3 w-px bg-surface-border" />
              {run.phases[run.activePhaseIndex].progress > 0 && (
                <>
                  <div className="w-32 h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full transition-all duration-300"
                      style={{ width: `${run.phases[run.activePhaseIndex].progress}%` }}
                    />
                  </div>
                  <span className="text-brand-400 font-mono">{run.phases[run.activePhaseIndex].progress}%</span>
                </>
              )}
              {run.phases[run.activePhaseIndex].stats?.step && (
                <span className="text-slate-500 truncate max-w-[200px]">
                  {String(run.phases[run.activePhaseIndex].stats?.step)}
                </span>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
