# CompetitorScope

CompetitorScope is a website-monitoring proof of concept. The Flask service
owns the API, discovery, monitoring, snapshot, and change-detection logic.
The Django service renders the browser UI and calls Flask over HTTP.

The current scope is website monitoring only. Social-media monitoring is
deferred to roadmap Step 5.

## Prerequisites

- Python 3.11 or newer
- A MongoDB database, typically MongoDB Atlas for the live PoC data
- Either an OpenAI/OpenRouter configuration for discovery fallback classification
  or a separately running Open-Jev service; an OpenAI key is still used for
  optional narrative enrichment
- Chromium for Playwright’s browser-fetch fallback

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

The Playwright browser is only used when the normal HTTP fetch cannot obtain a
usable HTML response, but installing it is recommended for a complete local
setup.

## Environment configuration

Create a local, ignored `.env` file or export these variables in your shell.
Never commit credentials. The Flask database connection reads its MongoDB
settings from the process environment; the OpenAI provider also supports the
local `.env` file through `python-dotenv`.

```dotenv
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>/<options>
MONGODB_DATABASE=competitor_monitoring

# OPENAI_API_KEY is also accepted for compatibility.
OPENAI_KEY=<your-openai-api-key>
OPENAI_MODEL=<model-name>

# Optional discovery provider: openai (default), openrouter, or open-jev
DISCOVERY_CLASSIFIER_PROVIDER=openai
# Open-Jev is an external HTTP service; Flask does not install its model stack.
# OPEN_JEV_ENDPOINT=http://127.0.0.1:8791/v1/systemone
# OPEN_JEV_MODEL=open-jev
# OPEN_JEV_TIMEOUT_SECONDS=30
# DISCOVERY_JEV_MIN_CONFIDENCE=0.75

APP_USER_ID=default-user
DJANGO_SECRET_KEY=<local-development-secret>
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

FLASK_API_BASE_URL=http://127.0.0.1:5000/api
FLASK_API_TIMEOUT_SECONDS=60
```

Load the file before starting Flask so `MONGODB_URI` is available:

```bash
set -a
source .env
set +a
```

`MONGODB_DB_NAME` is supported as a legacy alias for `MONGODB_DATABASE`. If no
database name is supplied, the backend falls back to
`competitor_monitoring`. `DJANGO_SECRET_KEY` and the Django development
defaults are suitable only for local development.

## Run the backend and frontend

Run the services in two terminals from the repository root. Activate the
virtual environment and load `.env` in each terminal, or export the variables
once in a parent shell.

### Terminal 1: Flask API

```bash
source .venv/bin/activate
set -a; source .env; set +a
python -m flask --app backend.flask.app:create_app run \
  --host 127.0.0.1 \
  --port 5000
```

The API is available at `http://127.0.0.1:5000/api`. For example:

```bash
curl http://127.0.0.1:5000/api/companies
```

On startup, the application factory connects to MongoDB, creates required
indexes, and idempotently ensures the two demo company records exist:
Marketing Eye and The Athletes Foot.

### Terminal 2: Django UI

```bash
source .venv/bin/activate
set -a; source .env; set +a
python frontend/django/manage.py runserver 127.0.0.1:8000
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in a browser. The Django
frontend uses `FLASK_API_BASE_URL` to reach the Flask service; start Flask
first and make sure this value points to the same host and port.

## UI flow

The UI is company-scoped through the company selector:

1. Select Marketing Eye to view Lyfe Marketing.
2. Open the competitor detail page and review or activate discovered candidates.
3. Open the changes feed to review detected changes.
4. Switch to The Athletes Foot to view JD Sports AU without Marketing Eye data.
5. Repeat the discovery and monitoring flow for JD Sports.

JD Sports discovery can take up to approximately 12 minutes. For a live demo,
run that discovery before the session. Marketing Eye/Lyfe discovery normally
completes in seconds. See [docs/PoC_story.md](docs/PoC_story.md) for the full
narrative and known limitations.

## Project structure

```text
backend/flask/
├── app.py                    # Flask application factory and service wiring
├── companies/                # Company identity routes, service, repository
├── competitors/              # Competitor CRUD and company scoping
├── discovery/                # Robots, sitemaps, links, classification, runs
├── website_monitoring/       # Fetch, normalize, monitor, and process changes
├── snapshot/                 # Snapshot metadata and local content storage
├── change_detection/         # Change/event reads and persistence boundary
├── scheduler/                # Per-target scheduling service
└── database/                 # Shared Mongo connection and repository helpers

frontend/django/
├── manage.py                 # Django command-line entry point
├── config/                   # Settings, URL configuration, WSGI entry point
├── monitoring/               # Django views, URLs, and the single Flask client
├── templates/                # Base page templates and reusable partials
└── static/                   # PoC CSS and JavaScript

docs/                         # Specification, architecture, roadmap, API contract
design/                       # Claude Design visual reference and design tokens
storage/snapshots/            # Local compressed snapshot content
tests/                        # Unit, API, frontend, and opt-in live verifications
```

The layering rules are intentional:

- Django views call Flask only through `frontend/django/monitoring/api_client/`.
- Flask routes delegate to services, and services delegate to repositories.
- MongoDB access belongs in repositories.
- Snapshot files are handled by `snapshot/storage.py`.

The frozen Django↔Flask endpoint shapes are documented in
[docs/api-contract.md](docs/api-contract.md).

## Tests

Run the default test suite from the repository root:

```bash
source .venv/bin/activate
python -m pytest -q
```

The live verification scripts are opt-in and require network access, MongoDB
credentials, and (where applicable) an OpenAI key. They refuse to run unless
their specific opt-in variable is set. For example:

```bash
set -a
source .env
set +a
export MONGODB_DATABASE=competitors_monitoring_test
export RUN_LIVE_HTTP=1
python -u tests/live_http_api_verification.py
```

The test database name should be separate from any production or demo database.
The branch-integrity audit can be run with:

```bash
python scripts/check_unmerged_branches.py
```

## Important development notes

- This PoC has no authentication boundary; the company selector is a demo
  scoping mechanism, not a security boundary.
- Keep API contract changes deliberate and update
  [docs/api-contract.md](docs/api-contract.md) when the Flask surface changes.
- Do not place API keys, MongoDB URIs, or other credentials in source files,
  logs, screenshots, or commits.
- Production has no simulation endpoint or simulation-only verification tooling.
  The legacy `is_simulated` field remains readable for historical records, but
  production code does not create simulated snapshots or changes.
