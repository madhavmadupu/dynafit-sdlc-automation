"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
import { usePhaseRunner } from "@/hooks/usePhaseRunner";
import Navbar from "@/components/layout/Navbar";
import PhaseStepper from "@/components/layout/PhaseStepper";
import WelcomeScreen from "@/components/WelcomeScreen";
import Phase1Ingestion from "@/components/phases/Phase1Ingestion";
import Phase2Retrieval from "@/components/phases/Phase2Retrieval";
import Phase3Matching from "@/components/phases/Phase3Matching";
import Phase4Classification from "@/components/phases/Phase4Classification";
import Phase5Validation from "@/components/phases/Phase5Validation";

export default function DashboardPage() {
  const { run } = useDynafitStore();
  // Initialize the phase runner — connects to backend, manages SSE
  const runner = usePhaseRunner();

  return (
    <div className="flex flex-col h-screen bg-surface">
      <Navbar />
      <PhaseStepper />
      <main className="flex-1 overflow-auto">
        <div className="w-full px-6 py-8">
          {run.activePhaseIndex === -1 && <WelcomeScreen />}
          {run.activePhaseIndex === 0 && (
            <Phase1Ingestion runIngestion={runner.runIngestion} hasBackend={runner.hasBackend} />
          )}
          {run.activePhaseIndex === 1 && (
            <Phase2Retrieval runRetrieval={runner.runRetrieval} hasBackend={runner.hasBackend} backendRunId={runner.backendRunId} />
          )}
          {run.activePhaseIndex === 2 && (
            <Phase3Matching runMatching={runner.runMatching} hasBackend={runner.hasBackend} backendRunId={runner.backendRunId} />
          )}
          {run.activePhaseIndex === 3 && (
            <Phase4Classification runClassification={runner.runClassification} hasBackend={runner.hasBackend} backendRunId={runner.backendRunId} />
          )}
          {run.activePhaseIndex === 4 && (
            <Phase5Validation hasBackend={runner.hasBackend} backendRunId={runner.backendRunId} />
          )}
        </div>
      </main>
    </div>
  );
}
