# DYNAFIT — Build Task List

Ordered list of everything that needs to be built. Work top-to-bottom.
Check off tasks as you complete them.

---

## ✅ Setup (already done)

- [x] `package.json` — dependencies configured
- [x] `tsconfig.json`
- [x] `tailwind.config.js` — custom colors: surface, brand
- [x] `postcss.config.js`
- [x] `app/globals.css` — base styles + custom utilities
- [x] `types/index.ts` — all TypeScript interfaces
- [x] `store/useDynafitStore.ts` — Zustand store
- [x] `lib/utils.ts` — cn(), formatters, color helpers
- [x] `lib/simulation.ts` — mock pipeline runner
- [x] `components/phases/Phase1Ingestion.tsx` — Phase 1 panel

---

## 🔴 Priority 1 — Core Shell

### 1.1 Root layout + pages
- [ ] `app/layout.tsx` — Root layout with Geist font, dark body
- [ ] `app/page.tsx` — Redirect to `/dashboard`
- [ ] `app/dashboard/page.tsx` — Main dashboard page (client component)

### 1.2 Layout components
- [ ] `components/layout/Navbar.tsx` — Top nav bar
- [ ] `components/layout/PhaseStepper.tsx` — Phase progress bar + step chips

### 1.3 Dashboard page structure
The dashboard page should render:
```tsx
// app/dashboard/page.tsx
"use client";
export default function DashboardPage() {
  const { run } = useDynafitStore();
  const activePhase = run.phases[run.activePhaseIndex];

  return (
    <div className="flex flex-col h-screen">
      <Navbar />
      <PhaseStepper />
      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-6 py-8">
          {/* Render the active phase panel */}
          {run.activePhaseIndex === 0 && <Phase1Ingestion />}
          {run.activePhaseIndex === 1 && <Phase2Retrieval />}
          {run.activePhaseIndex === 2 && <Phase3Matching />}
          {run.activePhaseIndex === 3 && <Phase4Classification />}
          {run.activePhaseIndex === 4 && <Phase5Validation />}
          
          {/* Default idle state when no phase selected */}
          {run.activePhaseIndex === -1 && <WelcomeScreen />}
        </div>
      </main>
    </div>
  );
}
```

---

## 🟠 Priority 2 — Phase Panels

### 2.1 Phase 1 - Ingestion (already scaffolded)
- [ ] Finalize `components/phases/Phase1Ingestion.tsx`
  - [ ] Drag-and-drop file upload zone
  - [ ] Per-file progress rows
  - [ ] Processing pipeline animation (4 steps)
  - [ ] Completion stats cards
  - [ ] Warning banner for ambiguous requirements
  - [ ] Error state + retry button
  - [ ] Run button (calls `simulateIngestion()`)

### 2.2 Phase 2 - Knowledge Retrieval
- [ ] `components/phases/Phase2Retrieval.tsx`
  - [ ] 3 knowledge source cards (D365 KB, MS Learn, Historical Fitments)
  - [ ] Idle: locked state with "Waiting for Phase 1" message
  - [ ] Processing: animated retrieval counters per source
  - [ ] 5-step pipeline visualization
  - [ ] Completion stats
  - [ ] Run button (calls `simulateRetrieval()`)

### 2.3 Phase 3 - Semantic Matching
- [ ] `components/phases/Phase3Matching.tsx`
  - [ ] Confidence threshold bar (visual 0.0–1.0 with zones)
  - [ ] Idle: locked state
  - [ ] Analyzing: live score distribution chart updating
  - [ ] Routing breakdown (Fast-track / LLM / GAP) with counts
  - [ ] Completion: Recharts bar chart of score distribution
  - [ ] Run button (calls `simulateMatching()`)

### 2.4 Phase 4 - Classification (most complex)
- [ ] `components/phases/Phase4Classification.tsx`
  - [ ] Idle: chain-of-thought reasoning preview
  - [ ] Processing: batch progress (batch N/5), running totals per class
  - [ ] Completion:
    - [ ] Summary bar: FIT N (X%) | PARTIAL FIT N (X%) | GAP N (X%)
    - [ ] Searchable + filterable results table
    - [ ] Expandable row with full rationale
    - [ ] Pagination (25 per page)
    - [ ] Module filter dropdown
    - [ ] Classification filter chips
  - [ ] Run button (calls `simulateClassification()`)

### 2.5 Phase 5 - Validation
- [ ] `components/phases/Phase5Validation.tsx`
  - [ ] 3-step pipeline preview
  - [ ] Processing: consistency check animation
  - [ ] Review queue table (all fitments, sortable)
  - [ ] Override button per row
  - [ ] Override modal (`OverrideModal`)
  - [ ] Completion: final stats + export button
  - [ ] Run button (calls `simulateValidation()`)

---

## 🟡 Priority 3 — Shared Components

- [ ] `components/shared/StatusBadge.tsx` — FIT/PARTIAL/GAP/phase status badges
- [ ] `components/shared/ConfidenceMeter.tsx` — Thin colored progress bar
- [ ] `components/shared/StatCard.tsx` — Metric card with number + label
- [ ] `components/shared/LogStream.tsx` — Terminal-style log feed
- [ ] `components/shared/ErrorBanner.tsx` — Error panel with retry
- [ ] `components/shared/EmptyState.tsx` — Placeholder for locked phases
- [ ] `components/shared/ProgressRing.tsx` — SVG circular progress
- [ ] `components/shared/PhaseCard.tsx` — Card wrapper for phase content

---

## 🟡 Priority 4 — Modals

- [ ] `components/modals/OverrideModal.tsx`
  - [ ] Uses shadcn Dialog
  - [ ] Shows: req ID, text, module, AI verdict + confidence
  - [ ] Shows: full rationale text
  - [ ] New verdict selector (3 buttons: FIT / PARTIAL FIT / GAP)
  - [ ] Reason textarea (required)
  - [ ] Confirm button disabled until reason is filled
  - [ ] On confirm: calls `store.overrideClassification()`

---

## 🟢 Priority 5 — Welcome Screen

- [ ] `components/WelcomeScreen.tsx`
  - [ ] Shown when `activePhaseIndex === -1`
  - [ ] Large logo/branding
  - [ ] Pipeline overview (5 phases with descriptions)
  - [ ] "Start New Run →" button → sets `activePhaseIndex = 0`
  - [ ] Recent runs list (from localStorage or mock)

---

## 🟢 Priority 6 — Hooks

- [ ] `hooks/usePhaseRunner.ts`
  ```typescript
  // Returns functions to run each phase + loading state
  const { runIngestion, runRetrieval, runMatching, runClassification, runValidation, isRunning } = usePhaseRunner();
  ```

- [ ] `hooks/usePolling.ts`
  ```typescript
  // Polls a URL at interval, stops when done
  const { data, error } = usePolling(url, intervalMs, shouldPoll);
  ```

---

## 🔵 Priority 7 — Advanced Features

- [ ] Run stats summary panel (below the main content)
  - Donut chart: FIT / PARTIAL / GAP breakdown
  - Processing time
  - Phase timings

- [ ] Export functionality
  - `lib/export.ts` — generates mock Excel blob
  - Download button in Phase 5 and Navbar

- [ ] Keyboard shortcuts
  - `1-5`: Navigate to phase 1-5 (if accessible)
  - `R`: Run current phase
  - `Esc`: Close modal

- [ ] Audit trail expandable section in Phase 5

---

## File Creation Order (recommended for AI IDE)

Build in this order to avoid import errors:

1. `types/index.ts` ✅
2. `store/useDynafitStore.ts` ✅
3. `lib/utils.ts` ✅
4. `lib/simulation.ts` ✅
5. `app/globals.css` ✅
6. `app/layout.tsx`
7. `app/page.tsx`
8. `components/shared/StatusBadge.tsx`
9. `components/shared/StatCard.tsx`
10. `components/shared/ConfidenceMeter.tsx`
11. `components/shared/ErrorBanner.tsx`
12. `components/shared/EmptyState.tsx`
13. `components/shared/LogStream.tsx`
14. `components/layout/Navbar.tsx`
15. `components/layout/PhaseStepper.tsx`
16. `components/phases/Phase1Ingestion.tsx` ✅
17. `components/phases/Phase2Retrieval.tsx`
18. `components/phases/Phase3Matching.tsx`
19. `components/phases/Phase4Classification.tsx`
20. `components/phases/Phase5Validation.tsx`
21. `components/modals/OverrideModal.tsx`
22. `app/dashboard/page.tsx`