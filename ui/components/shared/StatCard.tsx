"use client";

import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  color?: "brand" | "emerald" | "amber" | "red" | "slate";
  className?: string;
}

const colorMap = {
  brand: "text-brand-400",
  emerald: "text-emerald-400",
  amber: "text-amber-400",
  red: "text-red-400",
  slate: "text-slate-400",
};

export default function StatCard({ label, value, icon: Icon, color = "brand", className }: StatCardProps) {
  return (
    <div className={cn("bg-surface-card border border-surface-border rounded-xl p-4 animate-fade-in", className)}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">{label}</span>
        {Icon && <Icon size={16} className={cn("opacity-60", colorMap[color])} />}
      </div>
      <div className={cn("text-2xl font-bold", colorMap[color])}>{value}</div>
    </div>
  );
}
