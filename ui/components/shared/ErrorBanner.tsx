"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="bg-red-400/5 border border-red-400/20 rounded-xl p-4 animate-fade-in">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="text-red-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-red-300">Something went wrong</p>
          <p className="text-xs text-red-400/80 mt-1">{message}</p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-3 py-1.5 rounded-md border border-red-400/20 bg-red-400/5 text-red-300 text-xs hover:bg-red-400/10 transition-colors flex items-center gap-1.5 shrink-0"
          >
            <RotateCcw size={12} />
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
