# Shadow APK Gateway

Universal APK endpoint extraction and gateway automation platform.

## Architecture

```
APK → [Ingest] → [Static Analysis] → [Dynamic Analysis] → [Merge] → [Gateway API]
        ↓              ↓                    ↓                 ↓           ↓
   IngestManifest  RawFindings         TraceRecords      ActionCatalog  OpenAPI
```

## Quick Start

### Installation

```bash
pip install -e ".[all]"
```

### Run Static Analysis

```bash
# Analyze an APK
python -m apps.extractor.src.cli analyze /path/to/app.apk --output ./output
```

### Start Gateway

```bash
# Start the API gateway
uvicorn apps.gateway.src.main:app --host 0.0.0.0 --port 8080

# Or with Docker
docker-compose up
```

### Review Actions

```bash
# List discovered actions
python -m apps.gateway.src.review_cli list-actions ./output/catalog.json

# Interactive review
python -m apps.gateway.src.review_cli review ./output/catalog.json --reviewer "analyst"

# Auto-approve high confidence
python -m apps.gateway.src.review_cli approve ./output/catalog.json --confidence-min 0.75

# View stats
python -m apps.gateway.src.review_cli stats ./output/catalog.json
```

## Project Structure

```
Shadow-APK-Gateway/
├── apps/
│   ├── extractor/     # APK ingestion + static parsers (M1)
│   ├── analyzer/      # Dynamic analysis: emulator, frida, capture (M2-M3)
│   └── gateway/       # REST API, executor, session mgmt (M5)
├── packages/
│   ├── core_schema/   # Pydantic models (shared data schemas)
│   ├── trace_model/   # Merger, scorer, inference engine (M4)
│   ├── openapi_gen/   # OpenAPI 3.1 spec generator (M5)
│   └── replay_engine/ # HAR replay + response differ (M6)
├── infra/
│   └── frida/         # Frida server download scripts
├── tests/             # Unit tests
├── Dockerfile
└── docker-compose.yml
```

## Milestones

| M  | Component              | Status |
|----|------------------------|--------|
| M1 | Static Extractor       | ✅     |
| M2 | Dynamic Analyzer       | ✅     |
| M3 | Trace Store + HAR      | ✅     |
| M4 | Merger + Scorer        | ✅     |
| M5 | Gateway + OpenAPI      | ✅     |
| M6 | Replay Engine          | ✅     |
| M7 | Orchestrator + CLI     | ✅     |

## API Endpoints

| Endpoint                                      | Method | Description                    |
|-----------------------------------------------|--------|--------------------------------|
| `/apps`                                       | GET    | List indexed apps              |
| `/apps/{id}`                                  | GET    | App metadata                   |
| `/apps/{id}/actions`                          | GET    | List discovered actions        |
| `/apps/{id}/actions/{aid}`                    | GET    | Action detail                  |
| `/apps/{id}/actions/{aid}`                    | PATCH  | Approve/annotate action        |
| `/apps/{id}/actions/{aid}/execute`            | POST   | Execute action                 |
| `/apps/{id}/spec.json`                        | GET    | OpenAPI JSON spec              |
| `/apps/{id}/spec.yaml`                        | GET    | OpenAPI YAML spec              |
| `/apps/{id}/sessions/start`                   | POST   | Bootstrap auth session         |
| `/jobs`                                       | POST   | Submit APK for analysis        |

## Running Tests

```bash
pytest tests/ -v
```
