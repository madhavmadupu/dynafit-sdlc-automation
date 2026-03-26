# DYNAFIT — Requirement Fitment Engine UI

## Overview

DYNAFIT is a Next.js dashboard that provides a visual interface for the DYNAFIT backend pipeline — an AI multi-agent system that automates fitment analysis of business requirements against standard Microsoft Dynamics 365 Finance & Operations (D365 F&O) capabilities.

The UI walks users through **5 sequential phases**, each corresponding to an autonomous backend agent, with real-time status tracking, error handling, and result visualization.

---

## Tech Stack

| Layer            | Technology              |
| ---------------- | ----------------------- |
| Framework        | Next.js 14 (App Router) |
| Language         | TypeScript (strict)     |
| Styling          | Tailwind CSS            |
| Components       | shadcn/ui               |
| State Management | Zustand (with devtools) |
| Animations       | Framer Motion           |
| Icons            | Lucide React            |
| Charts           | Recharts                |
| Font             | Geist (next/font)       |

---

## Project Structure

```
dynafit/
├── app/
│   ├── globals.css              # Global styles + Tailwind base
│   ├── layout.tsx               # Root layout (dark theme)
│   ├── page.tsx                 # Redirects to /dashboard
│   └── dashboard/
│       └── page.tsx             # Main dashboard page
├── components/
│   ├── layout/
│   │   ├── Navbar.tsx           # Top nav: logo, run controls, export
│   │   ├── PhaseStepper.tsx     # Phase progress bar (top of dashboard)
│   │   └── Sidebar.tsx          # Optional collapsible sidebar
│   ├── phases/
│   │   ├── Phase1Ingestion.tsx  # File upload + ingestion agent UI
│   │   ├── Phase2Retrieval.tsx  # RAG knowledge retrieval UI
│   │   ├── Phase3Matching.tsx   # Semantic matching + confidence scores
│   │   ├── Phase4Classification.tsx  # LLM classification results table
│   │   └── Phase5Validation.tsx # Human review + fitment matrix export
│   ├── shared/
│   │   ├── PhaseCard.tsx        # Reusable phase status card wrapper
│   │   ├── StatusBadge.tsx      # FIT / PARTIAL FIT / GAP badge
│   │   ├── ConfidenceMeter.tsx  # Visual confidence score bar
│   │   ├── StatCard.tsx         # Metric summary card
│   │   ├── ProgressRing.tsx     # Circular progress indicator
│   │   ├── LogStream.tsx        # Live processing log feed
│   │   ├── ErrorBanner.tsx      # Error state with retry action
│   │   └── EmptyState.tsx       # Empty/idle state placeholder
│   └── modals/
│       └── OverrideModal.tsx    # Consultant classification override dialog
├── store/
│   └── useDynafitStore.ts       # Zustand store — all app state
├── types/
│   └── index.ts                 # All TypeScript interfaces
├── lib/
│   ├── utils.ts                 # cn(), formatters, color helpers
│   └── simulation.ts            # Mock pipeline simulator (replace with real API)
├── hooks/
│   ├── usePhaseRunner.ts        # Hook to trigger individual phase runs
│   └── usePolling.ts            # Hook to poll phase status from backend
└── public/
    └── logo.svg
```

---

## Color Palette (Dark Theme)

```css
/* Base surfaces */
--surface: #0f0f14 /* page background */ --surface-card: #16161e
  /* card / panel background */ --surface-border: #1e1e2a /* border color */
  --surface-hover: #1c1c28 /* hover state */ /* Brand (indigo) */
  --brand-400: #818cf8 --brand-500: #6366f1 --brand-600: #4f46e5
  /* Status colors */ --fit: #34d399 /* emerald-400 */ --partial: #fbbf24
  /* amber-400 */ --gap: #f87171 /* red-400 */ --error: #f87171
  --warning: #fbbf24 --info: #818cf8;
```

---

## Running the Project

```bash
npm install
npm run dev        # http://localhost:3000
npm run build
npm run lint
```
