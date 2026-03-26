"use client";

import { useDynafitStore } from "@/store/useDynafitStore";
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

  return (
    <div className="flex flex-col h-screen bg-surface">
      <Navbar />
      <PhaseStepper />
      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-6 py-8">
          {run.activePhaseIndex === -1 && <WelcomeScreen />}
          {run.activePhaseIndex === 0 && <Phase1Ingestion />}
          {run.activePhaseIndex === 1 && <Phase2Retrieval />}
          {run.activePhaseIndex === 2 && <Phase3Matching />}
          {run.activePhaseIndex === 3 && <Phase4Classification />}
          {run.activePhaseIndex === 4 && <Phase5Validation />}
        </div>
      </main>
    </div>
  );
}
