# NBA Edge Dashboard

A Next.js 15 (app router) experience for exploring NBA betting edges with player prop transparency, +EV tracking, and a same-game parlay composer powered by TanStack Query.

## Getting started

```bash
npm install
npm run dev
```

By default the UI boots in **mock mode** using JSON fixtures inside `__mocks__/`. Provide a REST backend by setting `NEXT_PUBLIC_API_BASE_URL` in your environment.

## Key features

- Dark theme UI (#0B0F14) with accent #06B6D4 and EV status pills
- Dedicated routes: `/games`, `/games/[id]`, `/props`, `/tickets`, `/about-model`
- Components for games, props, odds, EV tables, distribution charts, and a transparent Why Drawer
- SGP composer that respects joint probability straight from `/simulations/run`
- Tailwind CSS styling with loading skeletons, toast-driven error handling, and URL-synced filters
- Chart visualizations via `react-chartjs-2`
