"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import StatCard from "@/components/shared/StatCard";
import ErrorBanner from "@/components/shared/ErrorBanner";
import { cn } from "@/lib/utils";
import {
  Zap, Loader2, Lock, ArrowRight, CheckCheck,
  TrendingUp, Brain, AlertTriangle, Target
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell } from "recharts";

const THRESHOLD_ZONES = [
  { label: "GAP", range: "< 0.60", color: "bg-red-400", textColor: "text-red-400", width: "60%" },
  { label: "LLM Review", range: "0.60 – 0.85", color: "bg-amber-400", textColor: "text-amber-400", width: "25%" },
  { label: "FIT", range: "> 0.85", color: "bg-emerald-400", textColor: "text-emerald-400", width: "15%" },
];

interface Props {
  runMatching: () => Promise<void>;
  hasBackend: boolean;
  backendRunId: string | null;
}

export default function Phase3Matching({ runMatching, hasBackend, backendRunId }: Props) {
  const { run, retryPhase } = useDynafitStore();
  const phase = run.phases.find((p) => p.key === "matching")!;
  const prevPhase = run.phases.find((p) => p.key === "retrieval")!;
  const isActive = ["processing", "uploading", "analyzing"].includes(phase.status);
  const isCompleted = phase.status === "completed" || phase.status === "warning";
  const isError = phase.status === "error";
  const canRun = prevPhase.status === "completed" || prevPhase.status === "warning";

  // Generate distribution chart data
  const chartData = isCompleted && phase.stats ? [
    { name: "0.0-0.2", count: Math.floor(Number(phase.stats.likelyGap || 0) * 0.2), fill: "#F87171" },
    { name: "0.2-0.4", count: Math.floor(Number(phase.stats.likelyGap || 0) * 0.35), fill: "#F87171" },
    { name: "0.4-0.6", count: Math.floor(Number(phase.stats.likelyGap || 0) * 0.45), fill: "#F87171" },
    { name: "0.6-0.7", count: Math.floor(Number(phase.stats.needsLLM || 0) * 0.45), fill: "#FBBF24" },
    { name: "0.7-0.8", count: Math.floor(Number(phase.stats.needsLLM || 0) * 0.35), fill: "#FBBF24" },
    { name: "0.8-0.85", count: Math.floor(Number(phase.stats.needsLLM || 0) * 0.2), fill: "#FBBF24" },
    { name: "0.85-0.9", count: Math.floor(Number(phase.stats.fastTrack || 0) * 0.4), fill: "#34D399" },
    { name: "0.9-1.0", count: Math.floor(Number(phase.stats.fastTrack || 0) * 0.6), fill: "#34D399" },
  ] : [];

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Phase 3 — Semantic Matching Agent</h2>
        </div>
        <p className="text-sm text-slate-500 ml-4">
          Computes match scores between requirements and D365 capabilities, then routes based on confidence.
        </p>
      </div>

      {isError && phase.errorMessage && (
        <ErrorBanner message={phase.errorMessage} onRetry={() => retryPhase("matching")} />
      )}

      {/* Confidence threshold bar */}
      <div className="bg-surface-card border border-surface-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Target size={14} className="text-slate-400" />
          <span className="text-xs font-medium text-slate-300">Confidence Thresholds</span>
        </div>
        <div className="flex h-6 rounded-lg overflow-hidden">
          <div className="bg-red-400/20 flex items-center justify-center" style={{ width: "60%" }}>
            <span className="text-[10px] font-medium text-red-400">GAP &lt; 0.60</span>
          </div>
          <div className="bg-amber-400/20 flex items-center justify-center" style={{ width: "25%" }}>
            <span className="text-[10px] font-medium text-amber-400">LLM 0.60–0.85</span>
          </div>
          <div className="bg-emerald-400/20 flex items-center justify-center" style={{ width: "15%" }}>
            <span className="text-[10px] font-medium text-emerald-400">FIT &gt; 0.85</span>
          </div>
        </div>
      </div>

      {/* Processing state */}
      {isActive && (
        <div className="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm font-medium text-brand-400">Computing Semantic Scores</span>
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

      {/* Idle run button */}
      {phase.status === "idle" && canRun && !backendRunId && (
        <button
          onClick={runMatching}
          className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
        >
          <Zap size={16} />
          Run Semantic Matching
          <ArrowRight size={16} />
        </button>
      )}

      {phase.status === "idle" && canRun && backendRunId && (
        <div className="flex items-center justify-center gap-2 py-8 text-brand-400">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">Backend pipeline is running this phase automatically...</span>
        </div>
      )}

      {phase.status === "idle" && !canRun && (
        <div className="flex items-center justify-center gap-2 py-8 text-slate-600">
          <Lock size={16} />
          <span className="text-sm">Complete Phase 2 to unlock matching</span>
        </div>
      )}

      {/* Completion - results */}
      {isCompleted && phase.stats && (
        <div className="space-y-4 animate-slide-up">
          {/* Score distribution chart */}
          <div className="bg-surface-card border border-surface-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1.5 h-4 bg-brand-500 rounded-full" />
              <span className="text-sm font-medium text-white">Score Distribution</span>
            </div>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} barCategoryGap="15%">
                  <XAxis dataKey="name" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "#1E1E2A" }} tickLine={false} />
                  <YAxis tick={{ fill: "#64748B", fontSize: 10 }} axisLine={{ stroke: "#1E1E2A" }} tickLine={false} />
                  <RechartsTooltip
                    contentStyle={{ background: "#16161E", border: "1px solid #1E1E2A", borderRadius: "8px", fontSize: "12px" }}
                    labelStyle={{ color: "#94A3B8" }}
                    itemStyle={{ color: "#E2E8F0" }}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Routing breakdown cards */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-emerald-400/5 border border-emerald-400/20 rounded-xl p-4 text-center">
              <CheckCheck size={18} className="text-emerald-400 mx-auto mb-2" />
              <p className="text-xl font-bold text-emerald-400">{phase.stats.fastTrack}</p>
              <p className="text-xs text-emerald-300/70">Fast-track FIT</p>
              <p className="text-[10px] text-slate-600 mt-1">Score &gt; 0.85</p>
            </div>
            <div className="bg-amber-400/5 border border-amber-400/20 rounded-xl p-4 text-center">
              <Brain size={18} className="text-amber-400 mx-auto mb-2" />
              <p className="text-xl font-bold text-amber-400">{phase.stats.needsLLM}</p>
              <p className="text-xs text-amber-300/70">Needs LLM</p>
              <p className="text-[10px] text-slate-600 mt-1">Score 0.60 – 0.85</p>
            </div>
            <div className="bg-red-400/5 border border-red-400/20 rounded-xl p-4 text-center">
              <AlertTriangle size={18} className="text-red-400 mx-auto mb-2" />
              <p className="text-xl font-bold text-red-400">{phase.stats.likelyGap}</p>
              <p className="text-xs text-red-300/70">Likely GAP</p>
              <p className="text-[10px] text-slate-600 mt-1">Score &lt; 0.60</p>
            </div>
          </div>

          <StatCard label="Avg Composite Score" value={phase.stats.avgScore || "0"} icon={TrendingUp} color="brand" />

          <button
            onClick={() => useDynafitStore.getState().goToPhase(3)}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30 flex items-center justify-center gap-2"
          >
            Proceed to Classification
            <ArrowRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
