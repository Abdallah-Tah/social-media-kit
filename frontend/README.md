# smkit React Frontend

Phase L: React SPA migration for the smkit dashboard.

## Stack

- Vite + React + TypeScript
- TanStack Router (file-based routing)
- TanStack Query (data fetching)
- Tailwind CSS v4 (dark mode first)

Note: Tailwind v4 is CSS-first and does not require a `tailwind.config.js` file.
The theme is defined in `src/index.css` using `@theme`.

- shadcn/ui-style base components
- Recharts (charts)
- React Hook Form (forms)
- Zustand (state)
- Sonner (toasts)
- Vitest + React Testing Library + jsdom (testing)

## Development

```bash
cd frontend
npm ci
npm run dev
```

The Vite dev server proxies `/api` requests to the Python dashboard at `http://127.0.0.1:8801`. Make sure the backend is running:

```bash
smkit dashboard --host 127.0.0.1 --port 8801
```

Then open http://localhost:5173.

## Build

```bash
cd frontend
npm ci
npm run build
```

Output goes to `frontend/dist/`.

## Production dashboard

Build the React assets first, then run the Python dashboard on localhost:

```bash
cd frontend
npm ci
npm run build
smkit dashboard --host 127.0.0.1 --port 8801
```

The Python backend serves `frontend/dist` directly and falls back to
`frontend/dist/index.html` for React routes. Keep Cloudflare pointed at
`127.0.0.1:8801`; do not expose a public Vite development server.

If `frontend/dist` is missing, the backend returns a setup message with the
commands above instead of crashing.

## Architecture

- `src/routes/` — TanStack Router file-based routes
- `src/components/` — reusable UI components
- `src/api/client.ts` — API abstraction layer over existing `/api/*` endpoints
- `src/components/app-shell.tsx` — shared sidebar + top bar layout
- `src/pages/` — page-level composite components (to be populated)

## Migration plan

This is the incremental Phase L scaffold. The existing HTML dashboards remain functional until the React frontend reaches feature parity. Backend logic is unchanged; only the presentation layer is replaced.
