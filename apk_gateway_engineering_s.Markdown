Engineering Specification — v1.0

# Universal APK-to-Gateway  
Engineering Specification

Concrete repo layout, data schemas, milestone task breakdown, and AI agent prompt templates for building a pipeline that extracts Android app API endpoints statically and dynamically, then exposes them through a normalized, executable gateway.

**Agent target:** Claude Code / Google Antigravity **Stack:** Python · Android · Frida · OpenAPI 3.1 **Date:** April 2026

## Table of Contents

1.  [Overview and System Goal](#overview)
2.  [Architecture — Five-Layer Design](#architecture)
3.  [Repository Layout](#repo)
4.  [Core Data Schemas](#schemas)
    1.  [ActionObject schema](#action-schema)
    2.  [TraceRecord schema](#trace-schema)
    3.  [OpenAPI generation contract](#openapi-gen)
5.  [Milestone Breakdown and Task Specs](#milestones)
    1.  [M1 — Static Extractor Library](#m1)
    2.  [M2 — Emulator Launcher and Frida Hooks](#m2)
    3.  [M3 — Trace Schema and Storage](#m3)
    4.  [M4 — Merger and Action Inference](#m4)
    5.  [M5 — OpenAPI Export and Gateway Scaffolding](#m5)
    6.  [M6 — Replay Engine and Session Manager](#m6)
    7.  [M7 — Review CLI and Approval Workflow](#m7)
6.  [AI Agent Prompt Templates](#agent-prompts)
7.  [Validation and Test Matrix](#validation)
8.  [Practical Constraints and Risk Register](#constraints)
9.  [Infrastructure and CI Pipeline](#infra)
10.  [Recommended MVP Scope](#mvp)
11.  [References](#refs)

## 1\. Overview and System Goal

This specification translates the blueprint for a universal APK endpoint extraction and gateway system into actionable engineering tasks. The target audience is a code-generation AI agent — such as Claude Code or Google Antigravity — operating in a mono-repo under human supervision. Each milestone in this document is sized to be completable in a single focused agent session, with a clear pass/fail test that prevents the session from advancing to the next milestone on broken foundations.

The system solves a specific problem: an Android APK is a closed binary. Its network behavior is not documented. A developer or researcher who needs to drive that behavior programmatically must either reverse-engineer the binary by hand or build tooling that does it systematically. This pipeline does the latter at scale.

**What "universal" means here:** the pipeline must handle apps that use Retrofit, OkHttp, raw `HttpURLConnection`, WebView with bridged JavaScript, native HTTP (via NDK), and dynamically assembled requests. It will not achieve 100% coverage of every app, because obfuscation, certificate pinning, dynamic class loading, and hardware attestation create hard limits. Universality means the system handles the common cases automatically and routes the hard cases to human review, rather than silently failing.

### Deliverable summary

Layer

Deliverable

Success criterion

Static extractor

`packages/core-schema` + `apps/extractor`

Extracts >90% of endpoints from test APK set with known ground truth

Dynamic capture

`apps/analyzer` + `infra/frida`

Captures runtime requests from at least 3 reference apps with mitmproxy validation

Merge engine

`packages/trace-model`

Produces merged ActionObject list with confidence scores; no duplicate actions

OpenAPI export

`packages/openapi-gen`

Output validates against OpenAPI 3.1 spec validator

Gateway

`apps/gateway`

Can execute any confirmed action object end-to-end with session state

Replay engine

`packages/replay-engine`

Replays captured HAR and detects response divergence >5% with alert

## 2\. Architecture — Five-Layer Design

The system is composed of five independently deployable layers. Each layer has a single well-defined input and output contract. The contracts are JSON-schema-validated at runtime so that a broken upstream layer fails loudly rather than silently poisoning downstream results.

#### Layer 1 — Ingestion

-   Accepts APK file, an APK download URL, or a directory of pre-decompiled smali
-   Runs `apktool d` or equivalent to unpack
-   Emits an `IngestManifest` JSON listing all extracted file paths, package name, version, min/target SDK, declared permissions, and activity/service/receiver/provider list
-   Stores output in a content-addressable directory keyed by SHA-256 of the APK

#### Layer 2 — Static Analysis

-   Reads from an `IngestManifest`
-   Runs modular parsers: smali Retrofit annotation scanner, OkHttp builder scanner, WebView interface extractor, JS asset scanner, deep link extractor
-   Emits a list of `RawStaticFinding` objects with source file, line, extracted value, and parser name
-   Never modifies input; always read-only

#### Layer 3 — Dynamic Analysis

-   Reads from an `IngestManifest`
-   Launches emulator, installs APK, starts Frida server, runs app, traverses UI, captures requests
-   Emits a list of `TraceRecord` objects — one per observed network request — with full request/response metadata and correlated UI context
-   Exports optional HAR file and PCAP for manual inspection

#### Layer 4 — Normalization

-   Reads `RawStaticFinding` list and `TraceRecord` list
-   Merges equivalent observations into `ActionObject` instances
-   Infers parameter optionality, auth requirements, and preconditions
-   Assigns confidence scores and risk tags
-   Emits canonical `ActionCatalog` JSON

#### Layer 5 — Gateway

-   Reads from an `ActionCatalog`
-   Generates OpenAPI 3.1 spec
-   Serves REST API for action execution, session management, and catalog inspection
-   Manages auth tokens, session bootstrapping, request templating, and rate limiting
-   Writes structured audit logs per execution

#### Orchestrator

-   Coordinates layers 1–5 in sequence or in parallel slices
-   Manages job queue, status tracking, error escalation, and re-run scheduling
-   Exposes a single `POST /jobs` API that accepts an APK and returns a job ID
-   Notifies a webhook or polling endpoint when a job transitions state

### Data flow

```
┌──────────┐     IngestManifest     ┌────────────────┐   RawStaticFinding[]
│  APK     │ ─────────────────────► │ Static Analyzer│ ─────────────────────┐
│  Upload  │                        └────────────────┘                      │
│          │     IngestManifest     ┌────────────────┐   TraceRecord[]       │
│          │ ─────────────────────► │Dynamic Analyzer│ ──────────────────── ►│
└──────────┘                        └────────────────┘                      │
                                                                             ▼
                                                                   ┌──────────────┐
                                                                   │  Normalizer  │
                                                                   │  (Merger)    │
                                                                   └──────┬───────┘
                                                                          │ ActionCatalog
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │  Gateway     │
                                                                   │  + OpenAPI   │
                                                                   └──────────────┘
```

## 3\. Repository Layout

Use a mono-repo with Yarn/npm workspaces (if TypeScript/Node) or Python namespace packages (if pure Python). The following layout supports independent deployment of each layer while sharing common types through the `packages/` tree.

```
repo/
├── apps/
│   ├── extractor/           # Layer 1+2: ingest + static analysis service
│   │   ├── src/
│   │   │   ├── ingest.py
│   │   │   ├── parsers/
│   │   │   │   ├── retrofit.py
│   │   │   │   ├── okhttp.py
│   │   │   │   ├── webview.py
│   │   │   │   ├── jsasset.py
│   │   │   │   └── deeplink.py
│   │   │   └── cli.py
│   │   ├── tests/
│   │   ├── fixtures/        # Known APKs and expected output snapshots
│   │   └── pyproject.toml
│   ├── analyzer/            # Layer 3: dynamic analysis service
│   │   ├── src/
│   │   │   ├── emulator.py
│   │   │   ├── frida_runner.py
│   │   │   ├── capture.py
│   │   │   ├── explorer.py  # UI traversal / DroidBot integration
│   │   │   └── cli.py
│   │   ├── frida_scripts/
│   │   │   ├── okhttp3.js
│   │   │   ├── retrofit.js
│   │   │   ├── webview.js
│   │   │   ├── urlconnection.js
│   │   │   └── tls_keylog.js
│   │   └── tests/
│   ├── gateway/             # Layer 5: gateway API service
│   │   ├── src/
│   │   │   ├── main.py      # FastAPI app
│   │   │   ├── executor.py
│   │   │   ├── session.py
│   │   │   ├── auth.py
│   │   │   ├── audit.py
│   │   │   └── rate_limit.py
│   │   └── tests/
│   └── orchestrator/        # Job queue + pipeline coordinator
│       ├── src/
│       │   ├── jobs.py
│       │   ├── pipeline.py
│       │   └── api.py
│       └── tests/
│
├── packages/
│   ├── core-schema/         # Shared Pydantic models + JSON schemas
│   │   ├── models/
│   │   │   ├── ingest_manifest.py
│   │   │   ├── raw_finding.py
│   │   │   ├── trace_record.py
│   │   │   ├── action_object.py
│   │   │   └── action_catalog.py
│   │   └── tests/
│   ├── trace-model/         # Merger, confidence scorer, inference engine
│   │   ├── src/
│   │   │   ├── merger.py
│   │   │   ├── scorer.py
│   │   │   └── inference.py
│   │   └── tests/
│   ├── openapi-gen/         # ActionCatalog → OpenAPI 3.1 spec generator
│   │   ├── src/
│   │   │   └── generator.py
│   │   └── tests/
│   └── replay-engine/       # HAR replay + response diffing
│       ├── src/
│       │   ├── replayer.py
│       │   └── differ.py
│       └── tests/
│
├── infra/
│   ├── docker/
│   │   ├── extractor.Dockerfile
│   │   ├── analyzer.Dockerfile
│   │   ├── gateway.Dockerfile
│   │   └── docker-compose.yml
│   ├── emulator/
│   │   ├── avd_config.ini   # Android Virtual Device template
│   │   └── setup.sh
│   ├── frida/
│   │   ├── server_download.sh
│   │   └── push_server.sh
│   └── ci/
│       ├── .github/
│       │   └── workflows/
│       │       ├── test.yml
│       │       └── e2e.yml
│       └── scripts/
│
├── samples/
│   ├── test_apps/           # Small synthetic APKs with known endpoint sets
│   └── reference_hars/      # HAR exports for replay regression tests
│
├── tests/
│   └── e2e/                 # End-to-end pipeline tests
│
└── docs/
    ├── architecture.md
    ├── schema_reference.md
    └── agent_prompt_library.md
```

## 4\. Core Data Schemas

Every layer boundary is a validated JSON document. These schemas are defined in `packages/core-schema` using Pydantic v2 for Python-side validation and exported as JSON Schema files for use by other tools and the gateway.

### 4.1 ActionObject Schema

This is the central model that flows from Layer 4 into Layer 5. Every field that the gateway uses to execute a request must be present and validated here. Downstream code must never accept a raw endpoint string.

```
from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum

class AuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    COOKIE = "cookie"
    APIKEY = "apikey"
    OAUTH2 = "oauth2"
    DEVICE_BOUND = "device_bound"

class ParamSchema(BaseModel):
    name: str
    location: Literal["path", "query", "header", "body", "cookie"]
    required: bool
    type: str                     # JSON schema type: string, number, boolean, object, array
    example: Optional[str] = None
    description: Optional[str] = None
    sensitive: bool = False       # True for tokens, passwords, device IDs

class EvidenceRef(BaseModel):
    source_type: Literal["smali", "har", "pcap", "jsasset", "frida_trace"]
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    timestamp_ms: Optional[int] = None  # For runtime traces
    ui_activity: Optional[str] = None
    ui_event: Optional[str] = None

class ActionObject(BaseModel):
    action_id: str               # Stable UUID, deterministic from host+path+method
    source: Literal["static", "dynamic", "merged"]
    app_id: str
    package_name: str
    version_name: str
    version_code: int

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    url_template: str            # RFC 6570-style template: /users/{user_id}/profile
    base_url: str                # e.g. https://api.example.com
    params: list[ParamSchema]

    auth_requirements: list[AuthType]
    session_dependencies: list[str]  # action_ids that must be executed first
    preconditions: list[str]         # human-readable precondition descriptions

    confidence_score: float           # 0.0–1.0
    evidence: list[EvidenceRef]
    risk_tags: list[str]              # "login","payment","2fa","captcha","device_binding"

    is_idempotent: Optional[bool] = None
    is_paginated: Optional[bool] = None
    pagination_pattern: Optional[str] = None  # "cursor", "offset", "page"

    approved: bool = False
    approved_by: Optional[str] = None
    notes: Optional[str] = None
```

### 4.2 TraceRecord Schema

Emitted by the dynamic analyzer for every observed network request. The Frida hook must populate all mandatory fields; optional fields are filled in by post-processing.

```
class TraceRecord(BaseModel):
    trace_id: str               # UUID
    app_id: str
    session_id: str             # One session per emulator run
    timestamp_ms: int

    method: str
    url: str                    # Full URL as observed
    request_headers: dict[str, str]
    request_body_raw: Optional[bytes] = None
    request_body_parsed: Optional[dict] = None

    response_status: Optional[int] = None
    response_headers: Optional[dict[str, str]] = None
    response_body_raw: Optional[bytes] = None
    response_body_parsed: Optional[dict] = None
    response_time_ms: Optional[int] = None

    # UI context captured at the moment of the request
    ui_activity: Optional[str] = None
    ui_fragment: Optional[str] = None
    ui_event_type: Optional[str] = None  # "click", "scroll", "system", "background"
    ui_element_id: Optional[str] = None

    # Code context from Frida stack trace
    call_stack: list[str] = []
    invoking_class: Optional[str] = None
    invoking_method: Optional[str] = None

    tls_intercepted: bool = False
    pinning_bypassed: bool = False
```

### 4.3 OpenAPI Generation Contract

The `openapi-gen` package takes an `ActionCatalog` and emits a valid OpenAPI 3.1 YAML/JSON document. Only actions with `approved=True` and `confidence_score >= 0.6` are included in the output by default. Both thresholds are configurable.

```
# packages/openapi-gen/src/generator.py  (pseudocode summary)

def generate_openapi(catalog: ActionCatalog, config: OpenAPIGenConfig) -> dict:
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": f"Gateway API — {catalog.package_name} {catalog.version_name}",
            "version": catalog.version_name,
        },
        "servers": [{"url": config.gateway_base_url}],
        "paths": {},
        "components": {"securitySchemes": {}, "schemas": {}}
    }
    for action in catalog.actions:
        if not (action.approved and action.confidence_score >= config.min_confidence):
            continue
        path = f"/apps/{catalog.app_id}/actions/{action.action_id}/execute"
        spec["paths"][path] = _build_path_item(action)
    return spec

def _build_path_item(action: ActionObject) -> dict:
    # Maps ActionObject fields to OpenAPI PathItem + Operation objects
    # Parameters mapped from action.params by location
    # requestBody built from body params with inferred JSON schema
    # security requirement built from action.auth_requirements
    # x-risk-tags and x-confidence added as extension fields
    ...
```

## 5\. Milestone Breakdown and Task Specs

Each milestone is written as a self-contained task spec that can be handed directly to an AI coding agent. Each spec includes: the exact file scope, the implementation steps, the test requirement, and the acceptance gate that must pass before the next milestone begins.

M1 Static Extractor Library — *packages/core-schema + apps/extractor*

#### Scope

-   Define `IngestManifest`, `RawStaticFinding`, and `ActionObject` models in `packages/core-schema`
-   Implement APK ingestion (wrap `apktool` via subprocess) in `apps/extractor/src/ingest.py`
-   Implement five parser modules: `retrofit.py`, `okhttp.py`, `webview.py`, `jsasset.py`, `deeplink.py`
-   Implement CLI: `python -m extractor analyze --apk path/to/app.apk --out results/`

#### Parser implementation guidance

-   **retrofit.py:** scan smali files for `Lretrofit2/http/GET;`, `POST;`, etc. using regex on the annotation string literals. Extract the URL path string. Also extract `@Path`, `@Query`, `@Header`, `@Body` parameter annotations from the same method block.
-   **okhttp.py:** scan for `Lokhttp3/Request$Builder` and `Ljava/net/URL;`. Extract `url(` argument strings and any chained `.addHeader` or `.post(` calls within a 20-line window.
-   **webview.py:** scan for `addJavascriptInterface` calls. Extract the interface object name and registered name. Also scan for `loadUrl(` and `evaluateJavascript(` patterns.
-   **jsasset.py:** scan all `.js` files in `assets/` and `res/` for `fetch(`, `XMLHttpRequest`, `axios`, and calls to any WebView bridge interface name found by `webview.py`.
-   **deeplink.py:** parse `AndroidManifest.xml` intent filters with `VIEW` action and `http`/`https` or custom scheme data elements.

#### Test requirement

Provide at least two fixture APKs in `apps/extractor/fixtures/` (a minimal synthetic Retrofit app and a minimal synthetic OkHttp app). Write snapshot tests that compare extractor output JSON to stored golden files. Tests must run with `pytest apps/extractor/tests/` without an Android SDK. Use pre-decompiled smali fixtures, not live APK decompilation, so tests are fast and offline.

#### Acceptance gate

All snapshot tests pass. Running against the provided reference APKs in `samples/test_apps/` produces output that includes at least one `RawStaticFinding` per known endpoint in the ground-truth list. Do not advance to M2 if any parser raises an unhandled exception on well-formed smali input.

M2 Emulator Launcher and Frida Hooks — *apps/analyzer + infra/frida*

#### Scope

-   Implement emulator lifecycle management in `apps/analyzer/src/emulator.py`: start, wait-for-boot, install APK, take snapshot, restore snapshot, stop
-   Implement Frida server push and process attachment in `apps/analyzer/src/frida_runner.py`
-   Write four Frida hook scripts in `apps/analyzer/frida_scripts/`
-   Implement request/response capture and initial `TraceRecord` emission in `apps/analyzer/src/capture.py`

#### Frida hook specifications

**okhttp3.js** — Hook `OkHttpClient.newCall(Request)` and `Call.execute()`/`enqueue(Callback)`. On every call, capture: URL, method, headers, request body (limit to first 64 KB). On every response, capture: status code, response headers, response body (limit to first 64 KB). Emit a structured JSON event via `send()`. Do not modify request or response.

**retrofit.js** — Hook `ServiceMethod.invoke()` (Retrofit 2.x). Capture the method name, base URL, relative URL, annotations, and argument values. Correlate with OkHttp-level traces via shared request ID injected into a custom header (strip before send to avoid server errors).

**webview.js** — Hook `WebView.loadUrl()`, `loadDataWithBaseURL()`, and `evaluateJavascript()`. Also hook the registered JS bridge interface's public methods by name. Capture all arguments and return values.

**urlconnection.js** — Hook `java.net.HttpURLConnection.connect()`, `getOutputStream()`, `getInputStream()`, and the stream close events. Reconstruct request/response from these events in a stateful buffer per connection object.

#### Emulator setup requirements

-   Use Android API 30 (x86\_64) image by default; make API level configurable
-   Frida server version must match the Frida Python package version (pin both in `requirements.txt`)
-   Certificate pinning bypass: apply `objection`'s pinning bypass script before attaching domain-specific hooks
-   Store AVD config as a reproducible template in `infra/emulator/avd_config.ini`
-   Support headless mode (no display) for CI execution via `-no-window -no-audio` emulator flags

#### Test requirement

Build a minimal Android test app (`samples/test_apps/controlled_retrofit/`) that makes exactly three known HTTPS requests on launch. Write an integration test that launches the emulator (or a mocked emulator with recorded ADB responses), runs the Frida hooks, and confirms that all three expected `TraceRecord` objects are emitted. The test must complete within 5 minutes on a standard CI runner.

#### Acceptance gate

Integration test passes. The hook scripts do not crash the target app. Each `TraceRecord` emitted by the capture layer validates against the Pydantic model without error.

M3 Trace Schema and Storage — *packages/core-schema (trace) + apps/analyzer (storage)*

#### Scope

-   Finalize `TraceRecord` Pydantic model in `packages/core-schema/models/trace_record.py`
-   Implement a `TraceStore` class in `apps/analyzer/src/capture.py` backed by SQLite for development and an optional S3-compatible object store for production
-   Implement HAR export from a `TraceStore` instance
-   Implement UI correlation: ingest Android accessibility event log and join to trace records by timestamp proximity (within 250 ms window)

#### Storage design

Use SQLite with three tables: `sessions`, `traces`, and `ui_events`. Index on `session_id` and `timestamp_ms`. Store request and response bodies as compressed BLOB (zlib). Expose a Python API — not direct SQL — from `TraceStore`; internal SQL is an implementation detail.

For production, support writing trace JSON-lines files to S3-compatible storage. Implement this as a configurable storage backend, not a hardcoded code path.

#### HAR export

Implement `TraceStore.export_har(session_id) -> dict` that produces a valid HAR 1.2 document. Validate against the HAR JSON schema from the W3C Web Performance Working Group specification. The HAR export is the primary format for the replay engine in M6.

#### Acceptance gate

HAR export output passes HAR schema validation. Round-trip test: import a known HAR file, export it, compare key fields — method, URL, status, and timing — within acceptable tolerance. All `TraceRecord` objects in storage validate against the Pydantic model.

M4 Merger and Action Inference — *packages/trace-model*

#### Scope

-   Implement `merger.py`: merge `RawStaticFinding[]` and `TraceRecord[]` into `ActionObject[]`
-   Implement `scorer.py`: assign confidence scores
-   Implement `inference.py`: infer parameter optionality, pagination, auth requirements, and idempotency

#### Merge algorithm

1.  **URL normalization:** strip query strings, replace path segments that look like UUIDs, integers, or base64 with template variables. Use the pattern: segments matching `[0-9a-f-]{36}` become `{uuid}`, pure integer segments become `{id}`.
2.  **Clustering:** group findings by `(host, normalized_path, method)` tuple. Each cluster becomes one candidate `ActionObject`.
3.  **Merge within cluster:** union all observed headers and query parameters. Mark a parameter as required if it appears in >80% of observations from a given source type. Mark it optional otherwise.
4.  **Source type priority:** if both static and dynamic observations exist for a cluster, prefer dynamic for URL template, parameter names, and auth type. Keep static evidence references. Set `source = "merged"`.
5.  **Deduplication:** assign `action_id` as a deterministic UUID derived from `SHA-1(package_name + method + normalized_url_template)`. This ensures stable IDs across re-runs.

#### Confidence scoring

Condition

Score adjustment

Dynamic trace exists for this action

+0.40

Static finding exists for this action

+0.25

Both static and dynamic agree on URL template

+0.15

Response body was captured (200 status)

+0.10

URL contains opaque hash or is >3 path segments

\-0.10

Static-only, URL contains string concatenation patterns

\-0.15

Native library is in call stack (hard-to-verify)

\-0.20

Clamp final score to `[0.0, 1.0]`. Scores above 0.75 are "high confidence." Scores below 0.40 are flagged for human review and not exported to OpenAPI by default.

#### Risk tag inference

-   `login`: path contains `/auth`, `/login`, `/signin`, `/token`, or response sets a cookie or bearer token
-   `payment`: path contains `/pay`, `/charge`, `/order`, `/checkout`, or body contains `amount`/`price`/`card_number`
-   `2fa`: path contains `/otp`, `/verify`, `/mfa`
-   `device_binding`: request includes Android ID, build fingerprint, or advertising ID
-   `captcha`: response body contains `captcha`, `recaptcha`, `hcaptcha` keys

#### Acceptance gate

Run merger against M1+M3 outputs from the controlled reference app. The output ActionCatalog must contain exactly the known endpoint count (ground truth in `samples/test_apps/` readme). No duplicates. All `action_id` values are stable across two consecutive re-runs on the same inputs.

M5 OpenAPI Export and Gateway Scaffolding — *packages/openapi-gen + apps/gateway*

#### Scope

-   Implement `packages/openapi-gen/src/generator.py` as specified in §4.3
-   Implement `apps/gateway/src/main.py` as a FastAPI application
-   Implement `apps/gateway/src/executor.py`: translate an `ActionObject` into live HTTP requests
-   Implement `apps/gateway/src/session.py`: manage auth tokens and session cookies per tenant
-   Implement `apps/gateway/src/audit.py`: structured JSON audit log per execution

#### Gateway REST surface

```
GET    /apps                                       # list indexed apps
GET    /apps/{app_id}                              # app metadata
GET    /apps/{app_id}/actions                      # list ActionObjects (with filter params)
GET    /apps/{app_id}/actions/{action_id}          # single ActionObject detail
PATCH  /apps/{app_id}/actions/{action_id}          # approve / annotate
POST   /apps/{app_id}/actions/{action_id}/execute  # execute action
GET    /apps/{app_id}/spec.json                    # OpenAPI 3.1 JSON spec
GET    /apps/{app_id}/spec.yaml                    # OpenAPI 3.1 YAML spec
POST   /apps/{app_id}/sessions/start               # bootstrap a session (login + token store)
DELETE /apps/{app_id}/sessions/{session_id}        # clear session
POST   /jobs                                       # submit APK for analysis
GET    /jobs/{job_id}                              # job status
```

#### Executor design

The executor translates a gateway execution request into one or more live HTTP requests directed at the actual app backend. It must:

-   Look up the `ActionObject` from the catalog
-   Retrieve the active session token/cookies from `SessionStore`
-   Validate the caller-supplied parameters against the action's `params` schema
-   Instantiate the URL template with path and query parameters
-   Attach auth headers from the session
-   Make the HTTP request with configurable timeout and retry policy
-   Log request and response to the audit log with a correlation ID
-   Return a normalized `ExecutionResult` to the caller

The executor must never inject credentials into logs. Sensitive fields defined in `ParamSchema.sensitive = True` must be masked in audit output.

#### Session manager

For apps with a `login` risk-tagged action, the session manager can run that action first with user-supplied credentials, extract the resulting auth token or cookie, and store it keyed by `(app_id, tenant_id)`. Subsequent action executions in the same session automatically attach the stored credential. Credentials are stored encrypted at rest using Fernet symmetric encryption with a per-deployment key.

#### Acceptance gate

OpenAPI output validates via `openapi-spec-validator` (Python package). Gateway start-up test confirms all registered routes respond to an OPTIONS preflight. Execute one action end-to-end against the mock backend built in M2 tests. Audit log entry is written and parses as valid JSON for each execution.

M6 Replay Engine and Session Manager — *packages/replay-engine*

#### Scope

-   Implement `packages/replay-engine/src/replayer.py`: load a HAR file and replay each request, capturing actual responses
-   Implement `packages/replay-engine/src/differ.py`: compare replayed responses to original HAR responses
-   Integrate replay as a scheduled regression job in the orchestrator

#### Replayer

The replayer reads a HAR file, iterates entries in order, respects original timing intervals (with configurable speed multiplier), and fires each request through the gateway executor (not directly to the backend). This ensures the session and auth layers are exercised. It records a `ReplayResult` for each entry: `status_match`, `body_similarity`, `latency_ms`, `error` (if any).

#### Differ

The differ compares original and replayed responses using:

-   **Status code match:** exact match required; mismatch is a hard failure
-   **Body structural similarity:** for JSON responses, compare key sets (not values) using Jaccard similarity. A score below 0.85 raises an alert.
-   **Value drift detection:** for numeric values, flag drift greater than 5% on the same key across 3 consecutive replays
-   **Schema regression:** if a key present in the original response is absent in the replayed response, flag as a potential API change

The differ emits a `DiffReport` JSON document that the orchestrator stores and uses to update the action catalog's confidence score downward when regressions are detected.

#### Acceptance gate

Run replay against the reference HAR in `samples/reference_hars/`. All requests replay without error. Differ produces a `DiffReport` with zero hard failures. Intentionally inject one status code regression into the replay target; confirm the differ detects and reports it.

M7 Review CLI and Approval Workflow — *apps/orchestrator*

#### Scope

-   Implement a CLI tool `python -m orchestrator review --app-id <id>` for human review of discovered actions
-   Implement the approval workflow: mark actions as approved, rejected, or needing clarification
-   Implement a webhook notification system for job completion and regression alerts
-   Implement export: `python -m orchestrator export --app-id <id> --format postman|openapi|curl`

#### Review CLI behavior

The review CLI must present each unreviewed action with: method, URL template, confidence score, risk tags, evidence summary, and example request. The reviewer types `a` (approve), `r` (reject), `s` (skip), or `n <note>` (add note and skip). All decisions are persisted to the action catalog via the gateway PATCH endpoint. The CLI must not require a running emulator or live app.

#### Export formats

-   **openapi:** uses `openapi-gen` package, approved + high-confidence only
-   **postman:** generate a Postman Collection v2.1 JSON from the same filter set
-   **curl:** emit a shell script with one `curl` command per approved action, with placeholder variable substitution for auth tokens and required parameters

#### Acceptance gate

Review workflow test: load an action catalog with 10 actions, run the review CLI in non-interactive mode with a fixture input file, confirm that 5 are approved and 5 rejected. Run export in all three formats; validate OpenAPI output with spec-validator; validate Postman output with the Postman schema; execute the generated curl script against the mock backend without error.

## 6\. AI Agent Prompt Templates

These prompts are designed for use with Claude Code, Google Antigravity, or any code-generation agent that accepts a system context and a task description. Each prompt is scoped to exactly one milestone. Do not combine milestones in one prompt session — agent performance degrades significantly with overly broad task descriptions.

### Global system context (prepend to every prompt)

System Context — paste before every milestone prompt

```
You are working in a mono-repo for APK endpoint extraction and gateway automation.
The goal of this system is: take an Android APK, discover its network behavior through
static analysis and dynamic instrumentation, normalize the findings into ActionObject
instances, and expose those actions through a RESTful gateway service.

Language: Python 3.11+ throughout. Use Pydantic v2 for all data models.
Framework: FastAPI for the gateway service. pytest for all tests.

Coding rules:
- Make small, testable changes only. One logical change per commit.
- Preserve existing interfaces unless the task explicitly replaces them.
- Write or update tests for every new function or class.
- When uncertain about expected behavior, inspect fixture files before coding.
- Prefer deterministic parsers over heuristics. Heuristics must be documented.
- Never skip schema validation when reading external data (APK output, Frida events, HAR).
- Never log or store sensitive values (tokens, passwords, device identifiers) unmasked.
- If a function exceeds 60 lines, split it.

Directory layout reference:
- packages/core-schema/ — shared Pydantic models (read-only unless task explicitly modifies)
- apps/extractor/ — static analysis service
- apps/analyzer/ — dynamic analysis service
- apps/gateway/ — gateway REST API
- packages/trace-model/ — merger and inference engine
- packages/openapi-gen/ — ActionCatalog to OpenAPI converter
- packages/replay-engine/ — HAR replay and response differ
- infra/ — Docker, emulator config, Frida scripts, CI

Before starting any task:
1. Read the relevant existing source files and tests.
2. Read the schema models in packages/core-schema/models/.
3. Confirm your understanding by restating what you will implement in 3 bullet points.
4. Implement.
5. Run tests.
6. Fix any failures.
7. Report what was done, what tests pass, and any open questions.
```

### Milestone-specific task prompts

M1 Task Prompt — Static Extractor Library

```
Current milestone: M1 — Static Extractor Library

Files to create or modify:
- packages/core-schema/models/ingest_manifest.py   (create)
- packages/core-schema/models/raw_finding.py        (create)
- apps/extractor/src/ingest.py                      (create)
- apps/extractor/src/parsers/retrofit.py            (create)
- apps/extractor/src/parsers/okhttp.py              (create)
- apps/extractor/src/parsers/webview.py             (create)
- apps/extractor/src/parsers/jsasset.py             (create)
- apps/extractor/src/parsers/deeplink.py            (create)
- apps/extractor/src/cli.py                         (create)
- apps/extractor/tests/test_retrofit_parser.py      (create)
- apps/extractor/tests/test_okhttp_parser.py        (create)
- apps/extractor/fixtures/retrofit_sample.smali     (create — a minimal synthetic smali file)
- apps/extractor/fixtures/okhttp_sample.smali       (create — a minimal synthetic smali file)

Task steps:
1. Define IngestManifest and RawStaticFinding Pydantic models.
2. Implement the ingest function that calls apktool via subprocess and returns IngestManifest.
   Make apktool path configurable. Raise IngestError with a clear message if apktool fails.
3. Implement the retrofit parser. It must:
   - Accept a list of smali file paths.
   - Return a list of RawStaticFinding objects.
   - Detect @GET, @POST, @PUT, @PATCH, @DELETE, @HEAD annotations in smali.
   - Extract the URL path string from the annotation value.
   - Detect @Path, @Query, @Header, @Body parameters in the same method.
4. Implement the remaining four parsers using the patterns described in the architecture spec.
5. Implement the CLI: accept --apk or --smali-dir, run all parsers, write output JSON.
6. Write snapshot tests for the retrofit and okhttp parsers using the fixture smali files.

Acceptance: pytest apps/extractor/tests/ passes with zero failures.
Do not proceed to any other milestone tasks.
```

M2 Task Prompt — Frida Hooks

```
Current milestone: M2 — Emulator Launcher and Frida Hooks

Prerequisite: M1 is complete. packages/core-schema/models/ contains validated models.

Files to create or modify:
- packages/core-schema/models/trace_record.py       (create)
- apps/analyzer/src/emulator.py                     (create)
- apps/analyzer/src/frida_runner.py                 (create)
- apps/analyzer/src/capture.py                      (create)
- apps/analyzer/frida_scripts/okhttp3.js            (create)
- apps/analyzer/frida_scripts/retrofit.js           (create)
- apps/analyzer/frida_scripts/webview.js            (create)
- apps/analyzer/frida_scripts/urlconnection.js      (create)
- apps/analyzer/tests/test_capture.py               (create)

Task steps:
1. Define TraceRecord Pydantic model per the schema in the architecture spec.
2. Implement emulator.py: start_avd(), wait_for_boot(timeout=120), install_apk(),
   take_snapshot(), restore_snapshot(), stop_avd(). Use subprocess to call
   emulator and adb binaries. Make SDK path configurable via ANDROID_HOME env var.
3. Implement frida_runner.py: push_server(), start_server(), attach(package_name),
   run_script(script_path), stop(). Use the frida Python package.
4. Write the okhttp3.js Frida script. It must hook:
   - com.squareup.okhttp3.OkHttpClient.newCall (OkHttp 3.x)
   - okhttp3.OkHttpClient.newCall (OkHttp 4.x)
   On call execution, send a JSON event with: url, method, headers (object),
   requestBodyText (string, first 65536 bytes), responseStatus (int),
   responseHeaders (object), responseBodyText (string, first 65536 bytes).
   Use frida's interceptor, not reflection, for performance.
5. Write the remaining three Frida scripts following the same send-JSON-event pattern.
6. Implement capture.py: connect to Frida message stream, parse emitted JSON events,
   construct TraceRecord objects, store in-memory list for test inspection.
7. Write tests using a mock Frida message feed (a fixture JSON file of pre-recorded
   Frida send() events from the controlled test app). No live emulator required for tests.

Acceptance: pytest apps/analyzer/tests/ passes. All TraceRecord objects from
the mock feed validate against the Pydantic model without error.
```

M4 Task Prompt — Merger and Inference

```
Current milestone: M4 — Merger and Action Inference

Prerequisites: M1 output (RawStaticFinding list) and M3 output (TraceRecord list)
are both available in JSON fixture files at:
  samples/test_apps/controlled_retrofit/static_findings.json
  samples/test_apps/controlled_retrofit/trace_records.json

The ground truth for this test app is: 5 distinct ActionObjects
(GET /users, GET /users/{id}, POST /users, PUT /users/{id}, DELETE /users/{id})

Files to create or modify:
- packages/trace-model/src/merger.py    (create)
- packages/trace-model/src/scorer.py    (create)
- packages/trace-model/src/inference.py (create)
- packages/core-schema/models/action_catalog.py (create)
- packages/trace-model/tests/test_merger.py (create)

Task steps:
1. Define ActionCatalog as a Pydantic model: app metadata + list of ActionObject.
2. Implement URL normalization in merger.py:
   - Replace UUID-pattern segments with {uuid}
   - Replace pure integer segments with {id}
   - Lowercase scheme and host
   - Strip trailing slash
3. Implement the cluster-and-merge algorithm as described in the spec.
   action_id must be deterministic: SHA-1(package_name + ":" + method + ":" + normalized_url)
   encoded as a UUID string.
4. Implement confidence scoring in scorer.py using the scoring table in the spec.
5. Implement risk tag inference in inference.py using the keyword rules in the spec.
6. Implement auth requirement inference: if any TraceRecord for this cluster has an
   Authorization header, set auth_requirements to [AuthType.BEARER] (or detect Basic
   vs Bearer from the header value prefix).
7. Write tests that run the merger against the fixture files and assert:
   - Exactly 5 ActionObjects are produced
   - All action_ids are stable across two consecutive runs
   - All risk_tags for the POST /users action include at least one expected tag

Acceptance: pytest packages/trace-model/tests/ passes. Merger output validates
against ActionCatalog Pydantic model.
```

M5 Task Prompt — Gateway

```
Current milestone: M5 — OpenAPI Export and Gateway

Prerequisite: M4 is complete. A sample ActionCatalog JSON is available at:
  samples/test_apps/controlled_retrofit/action_catalog.json

Files to create or modify:
- packages/openapi-gen/src/generator.py        (create)
- packages/openapi-gen/tests/test_generator.py (create)
- apps/gateway/src/main.py                     (create)
- apps/gateway/src/executor.py                 (create)
- apps/gateway/src/session.py                  (create)
- apps/gateway/src/audit.py                    (create)
- apps/gateway/tests/test_gateway.py           (create)

Task steps:
1. Implement generator.py: ActionCatalog → OpenAPI 3.1 dict (as specified in §4.3).
   Only include actions where approved=True and confidence_score >= config.min_confidence.
   Add x-risk-tags and x-confidence as OpenAPI extension fields on each operation.
2. Write a test that generates OpenAPI from the fixture catalog and validates it with
   the openapi-spec-validator Python package.
3. Implement main.py as a FastAPI application with all routes listed in the spec.
4. Implement executor.py. Use httpx (async) as the HTTP client.
   Validate all parameters against the ActionObject schema before making the request.
   Mask sensitive fields in the audit log (replace value with "***REDACTED***").
5. Implement session.py: in-memory session store for development (keyed by app_id +
   tenant_id). Sessions expire after 3600 seconds. Implement encrypt/decrypt for
   stored credentials using cryptography.fernet.
6. Implement audit.py: write one JSON line per execution to a configurable log file.
   Fields: timestamp, correlation_id, app_id, action_id, tenant_id, request_url
   (masked), response_status, latency_ms, error (if any).
7. Write gateway integration tests using FastAPI TestClient. Test:
   - GET /apps/{app_id}/actions returns the catalog
   - POST /apps/{app_id}/actions/{action_id}/execute with mock httpx returns 200
   - PATCH approve endpoint sets approved=True
   - GET /apps/{app_id}/spec.json returns valid OpenAPI

Acceptance: pytest apps/gateway/tests/ and pytest packages/openapi-gen/tests/ both pass.
OpenAPI output validates. No credentials appear unmasked in audit log output.
```

## 7\. Validation and Test Matrix

Each layer has independent unit and integration tests. The end-to-end test runs the full pipeline on a set of reference apps and measures discovery performance against ground truth.

Test type

Scope

Tool

Pass criterion

Parser unit tests

Each parser in `apps/extractor/`

pytest + smali fixtures

100% of known endpoints in fixture detected; zero false positives on empty input

Frida hook tests

`apps/analyzer/frida_scripts/`

Mock Frida message feed (JSON fixtures)

All TraceRecord fields populated; no schema validation errors

Schema validation

All Pydantic models

pytest + hypothesis for property-based testing

No invalid model instances accepted; all required fields enforced

Merger correctness

`packages/trace-model/`

pytest + ground-truth fixture

Exact endpoint count match; deterministic IDs across re-runs

OpenAPI validation

`packages/openapi-gen/`

openapi-spec-validator

Zero validation errors on any output

Gateway API tests

`apps/gateway/`

FastAPI TestClient + httpx mock

All routes return correct status codes; auth and audit behavior verified

Replay regression

`packages/replay-engine/`

HAR replay against mock server

Zero diff failures on known-good HAR; injected regression detected

End-to-end pipeline

Full pipeline on 3 reference apps

Docker Compose + emulator (CI nightly)

Precision >0.80, recall >0.70 on ground-truth endpoint sets

### Differential testing

For each reference app in `samples/test_apps/`, maintain a ground-truth JSON file listing the known endpoints. After each pipeline run, compute:

-   **Precision** = (correctly discovered endpoints) / (total discovered endpoints)
-   **Recall** = (correctly discovered endpoints) / (total known endpoints)
-   **False positive rate** = (unknown endpoints discovered) / (total discovered)

Track these metrics over time. A precision drop of more than 5 percentage points between runs signals a regression in the parser or merger layer. A recall drop of more than 5 percentage points signals a regression in the extractor or Frida hook layer.

## 8\. Practical Constraints and Risk Register

**Design philosophy:** This is a semi-automated analysis platform, not a magic converter. Treat hard cases as input to a human review queue, not as failures of the pipeline. Reliability comes from knowing what the system does not know.

Constraint

Impact

Mitigation

Code obfuscation (ProGuard/R8)

Retrofit and OkHttp class names are remapped; smali parsers miss them

Fall back to string literal scanning regardless of class names; Frida hooks target JVM method signatures at runtime, bypassing renaming

Certificate pinning

Dynamic capture fails — TLS handshake rejected

Apply `objection` universal pinning bypass before attaching domain hooks; flag as `pinning_bypassed=True` in TraceRecord; log bypass status in DiffReport

Dynamic code loading (DexClassLoader)

Endpoints in dynamically loaded dex are invisible to static analysis

Frida hook on `DexClassLoader.loadClass()` to capture loaded classes at runtime; extract URLs from loaded dex in-memory

Native HTTP (NDK / Cronet)

Java-layer hooks miss native requests entirely

Capture at TLS layer via `tls_keylog.js` (SSLKEYLOGFILE hook) + mitmproxy decrypt; mark as `invoking_class = "native"`

Hardware attestation / device binding

Requests require specific device identifiers the emulator cannot provide

Tag action with `device_binding` risk tag; escalate to manual review; document as "not automatable in emulator" in notes field

CAPTCHA

UI traversal blocked; login flow cannot be automated

Tag action with `captcha` risk tag; implement human-in-the-loop pause in explorer.py: stop traversal, notify operator via webhook, wait for manual completion

Emulator detection

App changes behavior or exits on emulator

Apply standard emulator masking (hide `ro.product.model`, etc.) via Frida hooks on Build class fields; document in `infra/frida/`

Multi-step auth flows (OAuth2, PKCE)

Session bootstrap requires browser redirect and callback handling

Implement a configurable auth flow driver in `session.py` with support for custom pre-auth scripts; manual credential injection as fallback

## 9\. Infrastructure and CI Pipeline

### Docker Compose topology

```
# infra/docker/docker-compose.yml (summary)
services:
  extractor:
    build: { context: ../../, dockerfile: infra/docker/extractor.Dockerfile }
    volumes: [apk_store:/data/apks, results_store:/data/results]
    environment: [ANDROID_HOME=/opt/android-sdk]

  analyzer:
    build: { context: ../../, dockerfile: infra/docker/analyzer.Dockerfile }
    privileged: true          # Required for KVM access (hardware-accelerated emulator)
    devices: [/dev/kvm]
    volumes: [results_store:/data/results]
    environment: [FRIDA_SERVER_VERSION=16.x.x]

  gateway:
    build: { context: ../../, dockerfile: infra/docker/gateway.Dockerfile }
    ports: ["8080:8080"]
    environment: [CATALOG_DIR=/data/results, AUDIT_LOG=/data/audit.jsonl]
    volumes: [results_store:/data/results, audit_store:/data]

  orchestrator:
    build: { context: ../../, dockerfile: infra/docker/orchestrator.Dockerfile }
    depends_on: [extractor, analyzer, gateway]
    ports: ["8000:8000"]

volumes:
  apk_store:
  results_store:
  audit_store:
```

### CI pipeline stages

Stage

Trigger

What runs

Blocking

Lint

Every push

ruff, mypy, black --check

Yes

Unit tests

Every push

pytest packages/ apps/ (no emulator)

Yes

Schema validation

Every push

openapi-spec-validator on generated spec

Yes

Integration tests

PR to main

pytest with mock Frida feed and mock httpx

Yes

E2E pipeline

Nightly, main branch

Full pipeline on reference APKs with live emulator

No (alert on failure)

Replay regression

Nightly, main branch

HAR replay against mock backend

No (alert on >5% drift)

**KVM note:** Hardware-accelerated Android emulators require KVM (Kernel-based Virtual Machine). The CI runner must support nested virtualization. On GitHub Actions, use a `ubuntu-latest` runner with the `reactivecircus/android-emulator-runner` action for the E2E stage.

## 10\. Recommended MVP Scope

The full seven-milestone plan takes several weeks of agent-assisted development. If you need to demonstrate the workflow first, build the following MVP. It covers M1, M2, and the gateway execute path from M5, omitting the merger (M4) and replay engine (M6). The MVP demonstrates the pipeline's structure and will quickly reveal the hard problems in your target app set.

MVP component

From milestone

What to build

APK upload and static extraction

M1

Full extractor with Retrofit and OkHttp parsers; CLI and JSON output

Frida-based request capture

M2

okhttp3.js hook + capture.py; HAR export

Manual action list

M4 (simplified)

No automatic merger; export static findings directly as a flat action list, confidence = 0.5 for all

Gateway execute button

M5 (partial)

POST /execute endpoint; executor and session manager; no OpenAPI export yet

Approval CLI

M7 (partial)

Simple interactive CLI to approve/reject actions; persists to JSON file

The MVP takes roughly 3 focused agent sessions (M1, M2, gateway slice). It gives you:

-   A working APK ingestion and static finding tool you can run immediately
-   A Frida capture environment that produces HAR files you can inspect in a browser
-   A minimal gateway that can replay any approved action interactively
-   Concrete data to evaluate what the hard cases are for your target APK set

From the MVP, you add the merger (M4), OpenAPI export (M5), and replay engine (M6) as incremental improvements, each of which adds automation around processes that the MVP already handles manually.

## References

1.  [Serhatcck/Android-API-Extractor — Extract API endpoints in APK (GitHub)](https://github.com/Serhatcck/Android-API-Extractor)
2.  [Frida for App Dynamic Analysis and Reverse Engineering — Apriorit](https://www.apriorit.com/dev-blog/web-frida-dynamic-analysis)
3.  [AndrewWalsh/at-your-service — Generate OpenAPI 3.1 from network traffic (GitHub)](https://github.com/AndrewWalsh/at-your-service)
4.  [nshuba/NoMoATS — System for capturing Android traffic and labeling with 3rd-party libraries (GitHub)](https://github.com/nshuba/NoMoATS)
5.  [Build web apps in WebView — Android Developers](https://developer.android.com/develop/ui/views/layout/webapps/webview)
6.  [Dynamic analysis with Frida — Vinnie dot Work](https://www.vinnie.work/docs/AndroidApplicationAnalysis/dynamic-with-frida)
7.  [Open Traffic Generator (GitHub)](https://github.com/open-traffic-generator)