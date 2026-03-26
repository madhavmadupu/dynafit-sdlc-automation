"use client";

import { cn } from "@/lib/utils";

interface ConfidenceMeterProps {
  value: number; // 0-1
  showLabel?: boolean;
  className?: string;
}

export default function ConfidenceMeter({ value, showLabel = true, className }: ConfidenceMeterProps) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.85 ? "bg-emerald-400" :
    value >= 0.60 ? "bg-amber-400" :
    "bg-red-400";

  const textColor =
    value >= 0.85 ? "text-emerald-400" :
    value >= 0.60 ? "text-amber-400" :
    "text-red-400";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && <span className={cn("text-xs font-mono font-medium min-w-[36px] text-right", textColor)}>{pct}%</span>}
    </div>
  );
}
