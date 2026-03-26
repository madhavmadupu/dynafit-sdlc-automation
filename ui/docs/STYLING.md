# DYNAFIT — Styling & Design System Reference

## Theme: Dark / Industrial

The UI uses a deep dark theme inspired by developer tooling and data pipelines.
No light mode support required. Background: near-black (#0F0F14).

---

## Color Tokens

### Surfaces (custom Tailwind colors)
```
bg-surface          #0F0F14   Page background
bg-surface-card     #16161E   Cards, panels, sidebars
bg-surface-border   #1E1E2A   Used as border color
bg-surface-hover    #1C1C28   Hover state background
```

### Brand (Indigo)
```
brand-400  #818CF8   Light brand — icons, links, secondary
brand-500  #6366F1   Primary brand — buttons, active states
brand-600  #4F46E5   Dark brand — pressed states
brand-700  #4338CA   Glow base
brand-900  #312E81   Glow shadow color
```

### Semantic / Status
```
Completed / FIT:     text-emerald-400  #34D399
                     bg-emerald-400/10
                     border-emerald-400/20

Partial / Warning:   text-amber-400    #FBBF24
                     bg-amber-400/10
                     border-amber-400/20

Error / GAP:         text-red-400      #F87171
                     bg-red-400/10
                     border-red-400/20

Processing (brand):  text-brand-400    #818CF8
                     bg-brand-400/10
                     border-brand-400/20

Muted text:          text-slate-500    #64748B
Secondary text:      text-slate-400    #94A3B8
Primary text:        text-slate-200    #E2E8F0
White:               text-white        #FFFFFF
```

---

## Typography Scale

```
text-xs      12px   Labels, metadata, captions
text-[11px]  11px   Badge text, tiny labels
text-[10px]  10px   Sub-labels, stat card units
text-sm      14px   Body text, descriptions
text-base    16px   Normal content (rarely used)
text-lg      18px   Section titles
text-xl      20px   Page titles
text-2xl     24px   Stat numbers
```

Font weight:
- 400: body, descriptions
- 500: labels, button text
- 600: headings
- 700: large stat numbers

---

## Common Utility Classes

### Cards / Panels
```html
<!-- Standard card -->
<div class="bg-surface-card border border-surface-border rounded-xl p-5">

<!-- Hoverable card -->
<div class="bg-surface-card border border-surface-border rounded-xl p-5 card-lift cursor-pointer">

<!-- Colored state card (e.g. error) -->
<div class="bg-red-400/5 border border-red-400/20 rounded-xl p-5">

<!-- Active/glow card -->
<div class="bg-surface-card border border-brand-500/30 rounded-xl p-5 phase-glow">
```

### Badges
```html
<!-- FIT badge -->
<span class="badge bg-emerald-400/10 border-emerald-400/20 text-emerald-300">FIT</span>

<!-- PARTIAL FIT badge -->
<span class="badge bg-amber-400/10 border-amber-400/20 text-amber-300">PARTIAL FIT</span>

<!-- GAP badge -->
<span class="badge bg-red-400/10 border-red-400/20 text-red-300">GAP</span>

<!-- Processing badge -->
<span class="badge bg-brand-400/10 border-brand-400/20 text-brand-300">Processing</span>
```

### Buttons
```html
<!-- Primary CTA -->
<button class="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-medium text-sm transition-all shadow-lg shadow-brand-900/30">
  Run Agent →
</button>

<!-- Secondary -->
<button class="px-4 py-2 rounded-lg border border-surface-border text-slate-400 text-sm hover:bg-surface-hover hover:text-slate-300 transition-colors">
  Cancel
</button>

<!-- Danger / destructive -->
<button class="px-3 py-1.5 rounded-md border border-red-400/20 bg-red-400/5 text-red-300 text-xs hover:bg-red-400/10 transition-colors">
  Retry
</button>

<!-- Icon button -->
<button class="w-8 h-8 flex items-center justify-center rounded-md text-slate-500 hover:text-slate-300 hover:bg-surface-hover transition-colors">
  <Settings size={15} />
</button>
```

### Progress Bars
```html
<!-- Standard progress bar -->
<div class="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
  <div class="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full transition-all duration-300"
       style={{ width: `${progress}%` }} />
</div>

<!-- Thicker progress bar -->
<div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
  <div class="h-full bg-brand-500 rounded-full progress-bar shimmer"
       style={{ width: `${progress}%` }} />
</div>
```

### Dividers
```html
<!-- Horizontal section divider -->
<div class="h-px bg-surface-border my-4" />

<!-- Vertical divider in flex row -->
<div class="h-5 w-px bg-surface-border" />
```

### Grid Layouts
```html
<!-- 4-column stats grid -->
<div class="grid grid-cols-4 gap-3">

<!-- Responsive 3-column -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

<!-- 2-column 60/40 split -->
<div class="grid grid-cols-5 gap-6">
  <div class="col-span-3"> {/* main content */} </div>
  <div class="col-span-2"> {/* sidebar */} </div>
</div>
```

---

## Animation Classes

From `globals.css` + Tailwind config:

```
animate-fade-in      Fade in from opacity-0 (enter component)
animate-slide-up     Slide up + fade in (cards entering)
animate-spin         Standard spinner
animate-spin-slow    2s slow spinner
animate-pulse-slow   3s slow pulse (status dots)
animate-shimmer      Shimmer sweep (progress bars, skeletons)
log-item             Slides in from left (log entries)
```

### Phase glow (active phase card)
```css
.phase-glow {
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.15);
}
```

### Pulse ring (active status dot)
Applied via CSS `::after` pseudo-element for animated expanding ring:
```html
<div class="relative w-2 h-2">
  <div class="w-2 h-2 rounded-full bg-brand-400 animate-pulse-slow" />
  <!-- ring added by CSS .pulse-ring class -->
</div>
```

---

## Icon Usage

Use **Lucide React** icons throughout. Standard sizes:
- 12px: inline text icons
- 14px: compact UI icons
- 15–16px: standard buttons
- 18–20px: section icons
- 22–24px: feature/empty state icons

Import: `import { FileText, Database, Zap, Brain, CheckCircle } from "lucide-react";`

Phase icons mapping:
```
Phase 1 (Ingestion):      FileText
Phase 2 (Retrieval):      Database
Phase 3 (Matching):       Zap
Phase 4 (Classification): Brain
Phase 5 (Validation):     CheckCircle
```

Status icons:
```
completed:  CheckCheck
error:      XCircle
warning:    AlertTriangle
processing: Loader2 (with animate-spin)
info:       Info
```

---

## Data Table Pattern

Used in Phase 4 results:

```html
<div class="rounded-xl border border-surface-border overflow-hidden">
  <table class="w-full text-sm">
    <thead>
      <tr class="border-b border-surface-border bg-surface-hover">
        <th class="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">ID</th>
        <th class="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Requirement</th>
        ...
      </tr>
    </thead>
    <tbody>
      <tr class="data-row border-b border-surface-border/50 last:border-0">
        <td class="px-4 py-3 font-mono text-xs text-slate-500">REQ-0001</td>
        <td class="px-4 py-3 text-slate-300 max-w-xs truncate">System must support...</td>
        ...
      </tr>
    </tbody>
  </table>
</div>
```

---

## Phase Section Header Pattern

Used at the top of each phase panel:

```html
<div class="flex items-center gap-2 mb-1">
  <div class="w-1.5 h-4 bg-brand-500 rounded-full" />
  <h2 class="text-base font-semibold text-white">Phase 1 — Ingestion Agent</h2>
</div>
<p class="text-sm text-slate-500 ml-4">
  Upload requirement documents. The agent will parse, atomize...
</p>
```

---

## Responsive Breakpoints

The dashboard is designed for 1280px+ (laptop/desktop). Minimal mobile support needed.

```
sm:   640px+   Show phase short labels in stepper
md:   768px+   Show sidebar
lg:   1024px+  Full layout with stats sidebar
xl:   1280px+  Optimal layout
2xl:  1536px+  max-w-screen-2xl container
```

---

## Shadcn/ui Components to Use

Install and use these shadcn components:
- `Dialog` — Override modal (Phase 5)
- `Tooltip` — Hover hints on stepper phases
- `Progress` — Alternative progress bars
- `Badge` — Status badges (or use custom .badge class)
- `Separator` — Dividers
- `ScrollArea` — Log stream, results table
- `Select` — Module/classification filter dropdowns
- `Input` — Search bar in Phase 4
- `Textarea` — Override reason in modal
- `Button` — Standardized button component

Install shadcn: `npx shadcn-ui@latest init`
Add components: `npx shadcn-ui@latest add dialog tooltip progress badge`