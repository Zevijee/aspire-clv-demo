# Optional legacy setup without Docker

The default setup is [Docker-managed frontend, API and PostgreSQL](docker.md). Use this page only when deliberately maintaining the older native workflow. None of these host installations are required for the Docker setup.

This optional workflow needs host Python, Node.js and a separately accessible PostgreSQL instance.

1. Copy the root `.env.example` to `.env` if needed. Configure `DATABASE_URL` and `CORS_ORIGINS` for the existing database and local frontend.
2. From `backend`, prepare the Python environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e .
   ```

3. From `frontend`, install frontend dependencies:

   ```powershell
   npm install
   ```

4. Apply schema upgrades and populate/adopt data only when needed, following the [refactor handoff](backend-refactor-status.md) and [seeding reference](../backend/seeding/README.md). These are separate explicit operations.
5. From the repository root, start the native services:

   ```powershell
   python run_app.py
   ```

The frontend uses `http://localhost:5173`; the API defaults to `http://localhost:8000`.

## Native launcher

- The launcher prefers `backend/.venv`, then `.venv`, then its own Python interpreter.
- Services write to the launcher terminal. Ctrl+C stops their process trees. On Windows, a job object ties descendant processes to the launcher lifetime.
- The backend supervisor watches the backend packages, dependency configuration and root `.env`; source edits restart the API worker.
- `python run_app.py --check` inspects imports, configuration and ports without starting servers. It does not inspect report coverage.
- `--backend-port` and `--frontend-port` override local ports. The launcher supplies the frontend API URL.
- Startup does not install dependencies, apply migrations, seed data or schedule tasks.

For standalone frontend scripts, see [frontend/README.md](../frontend/README.md).
