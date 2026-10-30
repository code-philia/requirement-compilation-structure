# Web Application Template

A full-stack TypeScript application using React, Vite, Express, and SQLite
(`better-sqlite3`). Node.js 22.12 or newer, npm, and Bash are required.

## Structure

```text
frontend/                 React UI; builds into frontend/dist/
backend/
  src/
    server.ts             Server entry point and database initialization
    app.ts                Express app, API routes, and frontend serving
    api/                  Business API registration
    db/                   SQLite connection, initialization, and SQL tables
  scripts/                Build and backend test helpers
  dist/                   Compiled backend (generated)
package.json              npm workspace configuration and shared commands
deploy.sh                 Dependency installation, build, and server startup
```

## Start the Application

Run from the application root:

```bash
bash deploy.sh
```

The script installs dependencies for both workspaces, builds the frontend and
backend, and starts the server in the
foreground. It does not run tests. Startup errors stop the script.

The server initializes the database, serves the built frontend and `/api/`
routes on the same port, and exposes `/api/health`.

Optional environment variables:

```bash
PORT=3000 DATABASE_URL=./data/app.db bash deploy.sh
```

- `PORT`: HTTP port; defaults to `3000`. The ARC-Bench Runner supplies this value.
- `DATABASE_URL`: SQLite file path, despite its name; defaults to
  `backend/data/app.db`. Relative paths resolve from the backend workspace.
  Use an absolute path to select a fixed location, or `:memory:` for temporary data.

The current ARC-Bench agent Runner detects the root `deploy.sh` and invokes it
automatically. Keep this file at the application root when copying the template.

## Development

```bash
npm install --include=dev --include=optional
npm run dev:backend
# In another terminal:
npm run dev:frontend
```

The Vite development server proxies `/api` requests to backend port `3000`.
If you change the backend port during development, update
`frontend/vite.config.ts` accordingly.
