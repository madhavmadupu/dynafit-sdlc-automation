"use client";

import { useState } from "react";
import { useDynafitStore } from "@/store/useDynafitStore";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import StatusBadge from "@/components/shared/StatusBadge";
import ConfidenceMeter from "@/components/shared/ConfidenceMeter";
import type { ClassificationResult, FitmentClass } from "@/types";
import { cn } from "@/lib/utils";
import { Shield, ArrowRight, Loader2 } from "lucide-react";

interface OverrideModalProps {
  open: boolean;
  onClose: () => void;
  item: ClassificationResult | null;
}

export default function OverrideModal({ open, onClose, item }: OverrideModalProps) {
  const { overrideClassification } = useDynafitStore();
  const [newVerdict, setNewVerdict] = useState<FitmentClass | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (!item || !newVerdict || !reason.trim()) return;

    setSubmitting(true);
    try {
      // Update local store only — backend submission happens in bulk via handleSubmitReview
      overrideClassification(item.requirementId, newVerdict, reason.trim(), "consultant@company.com");

      setNewVerdict(null);
      setReason("");
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setNewVerdict(null);
    setReason("");
    onClose();
  };

  if (!item) return null;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="bg-surface-card border-surface-border max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-white">
            <Shield size={18} className="text-brand-400" />
            Override Classification
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Requirement info */}
          <div className="bg-surface border border-surface-border rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono text-slate-500">{item.requirementId}</span>
              <StatusBadge status={item.classification} />
            </div>
            <p className="text-sm text-slate-300 line-clamp-2">{item.requirementText || item.rationale}</p>
            <div className="mt-2">
              <ConfidenceMeter value={item.confidence} />
            </div>
          </div>

          {/* Current rationale */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-1 block">AI Rationale</label>
            <p className="text-xs text-slate-500 bg-surface rounded-lg p-3 border border-surface-border">
              {item.rationale}
            </p>
          </div>

          {/* New verdict selection */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-2 block">New Verdict</label>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs text-slate-500">
                <StatusBadge status={item.classification} size="md" />
                <ArrowRight size={14} className="text-slate-600 mx-1" />
              </div>
              {(["FIT", "PARTIAL_FIT", "GAP"] as FitmentClass[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setNewVerdict(v)}
                  className={cn(
                    "px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                    newVerdict === v
                      ? v === "FIT"
                        ? "bg-emerald-400/15 border-emerald-400/40 text-emerald-300"
                        : v === "PARTIAL_FIT"
                        ? "bg-amber-400/15 border-amber-400/40 text-amber-300"
                        : "bg-red-400/15 border-red-400/40 text-red-300"
                      : "bg-surface border-surface-border text-slate-500 hover:text-slate-300 hover:bg-surface-hover"
                  )}
                >
                  {v.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Reason */}
          <div>
            <label className="text-xs font-medium text-slate-400 mb-1 block">
              Reason <span className="text-red-400">*</span>
            </label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why you're overriding this classification..."
              className="bg-surface border-surface-border text-slate-300 placeholder:text-slate-600 min-h-[80px] text-sm"
            />
          </div>
        </div>

        <DialogFooter className="gap-2">
          <button
            onClick={handleClose}
            className="px-4 py-2 rounded-lg border border-surface-border text-slate-400 text-sm hover:bg-surface-hover hover:text-slate-300 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!newVerdict || !reason.trim() || submitting}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2",
              newVerdict && reason.trim() && !submitting
                ? "bg-brand-600 hover:bg-brand-500 text-white shadow-lg shadow-brand-900/30"
                : "bg-surface-hover text-slate-600 cursor-not-allowed"
            )}
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            Confirm Override
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
