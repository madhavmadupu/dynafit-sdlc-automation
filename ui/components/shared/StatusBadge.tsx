"use client";

import { cn } from "@/lib/utils";
import type { FitmentClass, PhaseStatus } from "@/types";
import { CheckCheck, XCircle, AlertTriangle, Loader2, Clock, Info } from "lucide-react";

interface StatusBadgeProps {
  status: FitmentClass | PhaseStatus;
  size?: "sm" | "md";
  showIcon?: boolean;
}

const fitmentConfig: Record<FitmentClass, { bg: string; border: string; text: string; label: string }> = {
  FIT: { bg: "bg-emerald-400/10", border: "border-emerald-400/20", text: "text-emerald-300", label: "FIT" },
  PARTIAL_FIT: { bg: "bg-amber-400/10", border: "border-amber-400/20", text: "text-amber-300", label: "PARTIAL FIT" },
  GAP: { bg: "bg-red-400/10", border: "border-red-400/20", text: "text-red-300", label: "GAP" },
};

const phaseStatusConfig: Record<string, { bg: string; border: string; text: string; label: string; icon?: React.ReactNode }> = {
  idle: { bg: "bg-slate-400/10", border: "border-slate-400/20", text: "text-slate-400", label: "Idle", icon: <Clock size={11} /> },
  pending: { bg: "bg-slate-400/10", border: "border-slate-400/20", text: "text-slate-400", label: "Pending", icon: <Clock size={11} /> },
  uploading: { bg: "bg-brand-400/10", border: "border-brand-400/20", text: "text-brand-400", label: "Uploading", icon: <Loader2 size={11} className="animate-spin" /> },
  processing: { bg: "bg-brand-400/10", border: "border-brand-400/20", text: "text-brand-400", label: "Processing", icon: <Loader2 size={11} className="animate-spin" /> },
  analyzing: { bg: "bg-brand-400/10", border: "border-brand-400/20", text: "text-brand-400", label: "Analyzing", icon: <Loader2 size={11} className="animate-spin" /> },
  completed: { bg: "bg-emerald-400/10", border: "border-emerald-400/20", text: "text-emerald-300", label: "Completed", icon: <CheckCheck size={11} /> },
  warning: { bg: "bg-amber-400/10", border: "border-amber-400/20", text: "text-amber-300", label: "Warning", icon: <AlertTriangle size={11} /> },
  error: { bg: "bg-red-400/10", border: "border-red-400/20", text: "text-red-300", label: "Error", icon: <XCircle size={11} /> },
  skipped: { bg: "bg-slate-400/10", border: "border-slate-400/20", text: "text-slate-500", label: "Skipped", icon: <Info size={11} /> },
};

export default function StatusBadge({ status, size = "sm", showIcon = true }: StatusBadgeProps) {
  const isFitment = status === "FIT" || status === "PARTIAL_FIT" || status === "GAP";
  const config = isFitment
    ? fitmentConfig[status as FitmentClass]
    : phaseStatusConfig[status] || phaseStatusConfig.idle;
  const icon = isFitment ? null : phaseStatusConfig[status]?.icon;

  return (
    <span
      className={cn(
        "badge",
        config.bg,
        config.border,
        config.text,
        size === "md" && "px-3 py-1 text-xs"
      )}
    >
      {showIcon && icon}
      {config.label}
    </span>
  );
}
