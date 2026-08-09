# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

````js
export default defineConfig([
  # Rebel Dot Support Frontend

  React 19 and Vite client for the semantic FAQ assistant. The browser uses only the typed API boundary in `src/api/client.ts`; authentication is held in an HttpOnly session cookie and never in Web Storage.

  ## Local Development

  Start FastAPI on `127.0.0.1:8000`, then run:

  ```bash
  npm ci
  npm run dev
````

Vite serves `http://127.0.0.1:5173` and proxies only `/auth`, `/ask-question`, `/admin`, and `/health` to FastAPI.

## Verification

Install the pinned Chromium binary once, then run the checks:

```bash
npx playwright install chromium
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
```

Vitest owns tests under `src/`. Playwright owns `e2e/` and runs the complete browser flow at desktop and mobile viewport sizes with deterministic API interception.

The production Docker build compiles `dist/` and copies it to `/app/static`, where FastAPI serves the same-origin application and API.
import reactX from 'eslint-plugin-react-x'
