"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import { cn } from "@/lib/utils";
import { Pause, Play, Download, RotateCcw } from "lucide-react";

export default function Navbar() {
  const { run, pauseRun, resumeRun, resetRun } = useDynafitStore();
  const isRunning = run.status === "running";
  const isPaused = run.status === "paused";
  const isCompleted = run.status === "completed";

  return (
    <nav className="h-14 bg-surface-card border-b border-surface-border px-6 flex items-center justify-between shrink-0 z-50">
      {/* Left: Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
          <span className="text-white font-bold text-sm">D</span>
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-bold text-white tracking-tight leading-none">DYNAFIT</span>
          <span className="text-[10px] text-slate-500 leading-none mt-0.5">D365 F&O Pipeline</span>
        </div>
      </div>

      {/* Center: Status */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="relative w-2 h-2">
            <div
              className={cn(
                "w-2 h-2 rounded-full",
                isRunning && "bg-brand-400 animate-pulse-slow",
                isPaused && "bg-amber-400",
                isCompleted && "bg-emerald-400",
                run.status === "error" && "bg-red-400",
                run.status === "idle" && "bg-slate-600"
              )}
            />
            {isRunning && (
              <div className="absolute inset-0 rounded-full bg-brand-400 animate-ping opacity-30" />
            )}
          </div>
          <span className="text-xs text-slate-400 capitalize">{run.status}</span>
        </div>

        {run.currentPhase && (
          <>
            <div className="h-4 w-px bg-surface-border" />
            <span className="text-xs text-slate-500">
              Phase: <span className="text-slate-300 capitalize">{run.currentPhase}</span>
            </span>
          </>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {(isRunning || isPaused) && (
          <button
            onClick={isPaused ? resumeRun : pauseRun}
            className="px-3 py-1.5 rounded-lg border border-surface-border text-slate-400 text-xs hover:bg-surface-hover hover:text-slate-300 transition-colors flex items-center gap-1.5"
          >
            {isPaused ? <Play size={12} /> : <Pause size={12} />}
            {isPaused ? "Resume" : "Pause"}
          </button>
        )}

        {isCompleted && (
          <button
            onClick={() => {
              // Mock export
              const blob = new Blob(["fitment_matrix"], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "fitment_matrix.xlsx";
              a.click();
              URL.revokeObjectURL(url);
            }}
            className="px-3 py-1.5 rounded-lg bg-emerald-400/10 border border-emerald-400/20 text-emerald-300 text-xs hover:bg-emerald-400/20 transition-colors flex items-center gap-1.5"
          >
            <Download size={12} />
            Export Matrix
          </button>
        )}

        <button
          onClick={resetRun}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-slate-300 hover:bg-surface-hover transition-colors"
          title="Reset pipeline"
        >
          <RotateCcw size={14} />
        </button>
      </div>
    </nav>
  );
}
