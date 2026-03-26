"use client";

import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
}

export default function EmptyState({ icon: Icon = Inbox, title, description, className, children }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 text-center animate-fade-in", className)}>
      <div className="w-14 h-14 rounded-2xl bg-surface-hover border border-surface-border flex items-center justify-center mb-4">
        <Icon size={24} className="text-slate-500" />
      </div>
      <h3 className="text-sm font-semibold text-slate-300 mb-1">{title}</h3>
      {description && <p className="text-xs text-slate-500 max-w-sm">{description}</p>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
