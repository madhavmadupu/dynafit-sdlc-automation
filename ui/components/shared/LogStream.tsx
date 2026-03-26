"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { Terminal } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";

interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  level?: "info" | "warn" | "error" | "success";
}

interface LogStreamProps {
  entries: LogEntry[];
  maxHeight?: string;
  className?: string;
}

const levelColors = {
  info: "text-brand-400",
  warn: "text-amber-400",
  error: "text-red-400",
  success: "text-emerald-400",
};

const levelBadges = {
  info: "text-brand-400/60",
  warn: "text-amber-400/60",
  error: "text-red-400/60",
  success: "text-emerald-400/60",
};

export default function LogStream({ entries, maxHeight = "300px", className }: LogStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  return (
    <div className={cn("bg-surface border border-surface-border rounded-xl overflow-hidden", className)}>
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-surface-border bg-surface-card">
        <Terminal size={14} className="text-slate-500" />
        <span className="text-xs font-medium text-slate-400">Pipeline Logs</span>
        <span className="text-[10px] text-slate-600 ml-auto">{entries.length} entries</span>
      </div>
      <ScrollArea style={{ maxHeight }}>
        <div className="p-3 space-y-0.5 font-mono text-[11px]">
          {entries.length === 0 && (
            <p className="text-slate-600 text-center py-4">Waiting for pipeline output...</p>
          )}
          {entries.map((entry) => (
            <div key={entry.id} className="log-item flex gap-2 py-0.5">
              <span className="text-slate-600 shrink-0">{entry.timestamp}</span>
              <span className={cn("shrink-0 uppercase w-12", levelBadges[entry.level || "info"])}>
                [{entry.level || "info"}]
              </span>
              <span className={cn(levelColors[entry.level || "info"])}>{entry.message}</span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
