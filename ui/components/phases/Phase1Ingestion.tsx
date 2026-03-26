"use client";

import { useState, useRef, useCallback } from "react";
import { useDynafitStore } from "@/store/useDynafitStore";
import { simulateIngestion } from "@/lib/simulation";
import StatCard from "@/components/shared/StatCard";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { cn } from "@/lib/utils";
import {
  FileText, Upload, X, AlertTriangle, Loader2, CheckCheck,
  FileSpreadsheet, FileType, Atom, Layers, Copy, ShieldAlert, ArrowRight
} from "lucide-react";
import type { UploadedFile } from "@/types";

const ACCEPTED = [".xlsx", ".xls", ".docx", ".doc", ".txt", ".csv"];

const PIPELINE_STEPS = [
  { label: "Doc Parser", desc: "Format detection & table extraction" },
  { label: "Req Extractor", desc: "LLM atomizer & intent classifier" },
  { label: "Normalizer", desc: "Deduplication & term alignment" },
  { label: "Validator", desc: "Schema validation & completeness" },
];

export default function Phase1Ingestion() {
  const { run, addFiles, removeFile, updateFileProgress, startPhase, retryPhase } = useDynafitStore();
  const phase = run.phases.find((p) => p.key === "ingestion")!;
  const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
  const isCompleted = phase.status === "completed" || phase.status === "warning";
  const isError = phase.status === "error";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = useCallback((fileList: FileList) => {
    const newFiles: UploadedFile[] = Array.from(fileList).map((f) => ({
      id: `file-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      name: f.name,
      size: f.size,
      type: f.type,
      status: "queued" as const,
      progress: 0,
    }));
    addFiles(newFiles);
  }, [addFiles]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleRunIngestion = async () => {
    // Simulate file uploads first
    for (const f of run.uploadedFiles) {
      updateFileProgress(f.id, 50, "uploading");
      await new Promise((r) => setTimeout(r, 200));
      updateFileProgress(f.id, 100, "parsed");
    }
    await simulateIngestion();
  };

  const currentPipelineStep = phase.stats?.step
    ? PIPELINE_STEPS.findIndex((s) => String(phase.stats?.step).toLowerCase().includes(s.label.toLowerCase().split(" ")[0]))
    : -1;

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Phase 1 — Ingestion Agent</h2>
        </div>
        <p className="text-sm text-slate-500 ml-4">
          Upload requirement documents. The agent will parse, atomize, normalize, and validate each requirement.
        </p>
      </div>

      {/* Error state */}
      {isError && phase.errorMessage && (
        <ErrorBanner message={phase.errorMessage} onRetry={() => retryPhase("ingestion")} />
      )}

      {/* Warning banner */}
      {phase.status === "warning" && phase.warningMessage && (
        <div className="bg-amber-400/5 border border-amber-400/20 rounded-xl p-4 flex items-start gap-3 animate-fade-in">
          <AlertTriangle size={18} className="text-amber-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-300">Ambiguous requirements detected</p>
            <p className="text-xs text-amber-400/80 mt-1">{phase.warningMessage}</p>
          </div>
        </div>
      )}

      {/* File upload zone (shown when idle or has files) */}
      {!isActive && !isCompleted && (
        <>
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
              isDragging
                ? "border-brand-500 bg-brand-500/5"
                : "border-surface-border hover:border-brand-500/30 hover:bg-surface-card"
            )}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED.join(",")}
              onChange={(e) => e.target.files && handleFiles(e.target.files)}
              className="hidden"
            />
            <Upload size={24} className={cn("mx-auto mb-3", isDragging ? "text-brand-400" : "text-slate-500")} />
            <p className="text-sm font-medium text-slate-300 mb-1">Drop files here or click to browse</p>
            <p className="text-xs text-slate-600">
              Accepted: {ACCEPTED.join(", ")}
            </p>
          </div>

          {/* File list */}
          {run.uploadedFiles.length > 0 && (
            <div className="space-y-2">
              {run.uploadedFiles.map((f) => (
                <div key={f.id} className="flex items-center gap-3 bg-surface-card border border-surface-border rounded-lg p-3">
                  <FileSpreadsheet size={16} className="text-brand-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300 truncate">{f.name}</p>
                    <p className="text-[10px] text-slate-600">{(f.size / 1024).toFixed(1)} KB</p>
                    {f.status === "uploading" && (
                      <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden mt-1">
                        <div className="h-full bg-brand-500 rounded-full transition-all duration-300" style={{ width: `${f.progress}%` }} />
                      </div>
                    )}
                    {f.status === "error" && (
                      <p className="text-[10px] text-red-400 mt-0.5">{f.errorMessage || "Upload failed"}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {f.status === "parsed" && <CheckCheck size={14} className="text-emerald-400" />}
                    {f.status === "error" && <AlertTriangle size={14} className="text-red-400" />}
                    <button onClick={() => removeFile(f.id)} className="text-slate-600 hover:text-slate-400 transition-colors">
                      <X size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Run button */}
          {run.uploadedFiles.length > 0 && !isError && (
            <button
              onClick={handleRunIngestion}
              className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
            >
              <Atom size={16} />
              Run Ingestion Agent
              <ArrowRight size={16} />
            </button>
          )}
        </>
      )}

      {/* Processing pipeline animation */}
      {isActive && (
        <div className="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm font-medium text-brand-400">Processing Pipeline</span>
          </div>

          <div className="grid grid-cols-4 gap-3">
            {PIPELINE_STEPS.map((step, i) => {
              const isStepActive = i === currentPipelineStep || (currentPipelineStep === -1 && i === 0);
              const isStepDone = i < currentPipelineStep;
              return (
                <div
                  key={i}
                  className={cn(
                    "rounded-lg p-3 border text-center transition-all duration-300",
                    isStepActive ? "bg-brand-500/10 border-brand-500/30" :
                    isStepDone ? "bg-emerald-400/5 border-emerald-400/20" :
                    "bg-surface border-surface-border"
                  )}
                >
                  <div className="flex items-center justify-center mb-2">
                    {isStepActive ? <Loader2 size={14} className="text-brand-400 animate-spin" /> :
                     isStepDone ? <CheckCheck size={14} className="text-emerald-400" /> :
                     <div className="w-3.5 h-3.5 rounded-full bg-slate-700" />}
                  </div>
                  <p className={cn("text-xs font-medium", isStepActive ? "text-brand-400" : isStepDone ? "text-emerald-300" : "text-slate-500")}>
                    {step.label}
                  </p>
                  <p className="text-[10px] text-slate-600 mt-0.5">{step.desc}</p>
                </div>
              );
            })}
          </div>

          {/* Progress bar */}
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

      {/* Completion stats */}
      {isCompleted && phase.stats && (
        <div className="space-y-4 animate-slide-up">
          <div className="grid grid-cols-4 gap-3">
            <StatCard label="Total Atoms" value={phase.stats.totalAtoms || 0} icon={Atom} color="brand" />
            <StatCard label="Modules" value={phase.stats.modules || 0} icon={Layers} color="emerald" />
            <StatCard label="Ambiguous" value={phase.stats.ambiguous || 0} icon={ShieldAlert} color={Number(phase.stats.ambiguous) > 0 ? "amber" : "slate"} />
            <StatCard label="Duplicates" value={phase.stats.duplicates || 0} icon={Copy} color="slate" />
          </div>

          {/* Proceed button */}
          <button
            onClick={() => useDynafitStore.getState().goToPhase(1)}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
          >
            Proceed to Retrieval
            <ArrowRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
