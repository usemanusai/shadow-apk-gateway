<p align="center">
  <img src="https://img.shields.io/badge/Shadow--APK--Gateway-v1.0.0-blueviolet?style=for-the-badge&logo=android&logoColor=white" alt="Version"/>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Frida-FF6B35?style=for-the-badge&logo=hackthebox&logoColor=white" alt="Frida"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">
  🛡️ Shadow APK Gateway
</h1>

<p align="center">
  <strong>Universal Android APK Endpoint Extraction & Programmable API Gateway</strong>
</p>

<p align="center">
  <em>
    Drop in an APK. Get back a fully documented, executable REST API.<br/>
    Static analysis × Dynamic instrumentation × Automated replay — unified in one pipeline.
  </em>
</p>

<br/>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-features">Features</a> •
  <a href="#-api-reference">API Reference</a> •
  <a href="#-faq--deep-dives">FAQ</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

## 🧠 What Is This?

**Shadow APK Gateway** is a first-of-its-kind platform that **reverse-engineers Android applications into fully executable API gateways** — automatically.

Most mobile apps are just thin wrappers around REST APIs. Shadow APK Gateway peels back the wrapper:

1. **Extracts** every HTTP endpoint from APK bytecode (Retrofit annotations, OkHttp builders, WebView bridges, JS assets)
2. **Validates** them through live Frida instrumentation on an emulator
3. **Merges** static + dynamic evidence into a high-confidence action catalog
4. **Generates** an OpenAPI 3.1 spec and serves a live, executable gateway

The result? You go from `.apk` → **fully documented, callable API** in minutes.

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repo
git clone https://github.com/usemanusai/shadow-apk-gateway.git
cd shadow-apk-gateway

# Install with all dependencies
pip install -e ".[dev]"
```

### Analyze an APK (Static Only)

```bash
python -m apps.extractor.src.cli analyze ./my-app.apk --output ./output
```

### Start the Gateway

```bash
# Start the API server
uvicorn apps.gateway.src.main:app --host 0.0.0.0 --port 8080

# Or with Docker
docker-compose up
```

### Review Discovered Actions

```bash
# List all discovered endpoints
python -m apps.gateway.src.review_cli list-actions ./output/catalog.json

# Interactive review session
python -m apps.gateway.src.review_cli review ./output/catalog.json --reviewer "analyst"

# Auto-approve high-confidence actions
python -m apps.gateway.src.review_cli approve ./output/catalog.json --confidence-min 0.75
```

---

## 🏗 Architecture

```
                         ┌───────────────────────────────────────────┐
                         │              Shadow APK Gateway           │
                         └──────────────────┬────────────────────────┘
                                            │
          ┌─────────────────────────────────┼─────────────────────────────────┐
          │                                 │                                 │
   ┌──────▼──────┐                  ┌───────▼───────┐                ┌────────▼────────┐
   │   Layer 1   │                  │   Layer 3     │                │   Layer 5       │
   │   Ingest    │                  │   Dynamic     │                │   Gateway       │
   │             │                  │   Analysis    │                │                 │
   │  APK → dex  │                  │  Emulator +   │                │  REST API +     │
   │  → smali    │                  │  Frida hooks  │                │  OpenAPI spec   │
   └──────┬──────┘                  └───────┬───────┘                └────────▲────────┘
          │                                 │                                 │
   ┌──────▼──────┐                  ┌───────▼───────┐                ┌────────┴────────┐
   │   Layer 2   │                  │   Layer 3.5   │                │   Layer 4       │
   │   Static    │──────────────────▶   Trace       │────────────────▶   Merger +      │
   │   Parsers   │   RawFindings    │   Storage     │  TraceRecords  │   Scorer        │
   │             │                  │   (SQLite)    │                │                 │
   │  Retrofit   │                  │   + HAR       │                │  URL normalize  │
   │  OkHttp     │                  │   export      │                │  Clustering     │
   │  WebView    │                  │               │                │  Confidence     │
   │  JS assets  │                  │               │                │  scoring        │
   │  Deep links │                  │               │                │                 │
   └─────────────┘                  └───────────────┘                └─────────────────┘
```

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🔍 Static Analysis
- **5 specialized parsers**: Retrofit annotations, OkHttp builder chains, WebView bridges, JS asset scanning, deep link extraction
- Pattern matching on Dalvik bytecode (smali)
- Dynamic URL detection and obfuscation awareness

</td>
<td width="50%">

### 🎯 Dynamic Analysis
- **Full emulator lifecycle**: create, boot, install, snapshot, teardown
- **Frida instrumentation**: OkHttp3, Retrofit, WebView, URLConnection, TLS
- **Universal SSL pinning bypass** for intercepting HTTPS traffic
- Automated UI traversal (DroidBot-style exploration)

</td>
</tr>
<tr>
<td>

### 🧬 Intelligent Merging
- URL normalization (UUIDs, integers, base64, hex → template vars)
- Deterministic clustering by `host + method + path`
- Cross-source confidence scoring with 8 signal rules
- Risk tag inference: login, payment, 2FA, device binding

</td>
<td>

### 🌐 Executable Gateway
- **Live action execution** with parameter validation & auth injection
- OpenAPI 3.1 spec generation (JSON + YAML)
- Encrypted session management (Fernet)
- Rate limiting, audit logging with PII masking
- HAR replay engine with response diffing

</td>
</tr>
</table>

---

## 📂 Project Structure

```
shadow-apk-gateway/
│
├── 📦 packages/                    # Shared libraries
│   ├── core_schema/                # Pydantic v2 data models
│   │   └── models/
│   │       ├── ingest_manifest.py  # Layer 1: APK metadata
│   │       ├── raw_finding.py      # Layer 2: Static findings
│   │       ├── trace_record.py     # Layer 3: Dynamic captures
│   │       ├── action_object.py    # Normalized API action
│   │       └── action_catalog.py   # Collection of actions
│   │
│   ├── trace_model/                # Merge + scoring engine
│   │   └── src/
│   │       ├── merger.py           # URL normalization & clustering
│   │       ├── scorer.py           # Confidence scoring (Table 2)
│   │       └── inference.py        # Risk, auth, pagination inference
│   │
│   ├── openapi_gen/                # OpenAPI 3.1 spec generator
│   │   └── src/generator.py
│   │
│   └── replay_engine/              # HAR replay + response diffing
│       └── src/
│           ├── replayer.py
│           └── differ.py
│
├── 🔧 apps/                        # Application services
│   ├── extractor/                   # M1: Static extraction pipeline
│   │   ├── src/
│   │   │   ├── ingest.py           # APK unpacking (apktool)
│   │   │   ├── cli.py              # Command-line interface
│   │   │   └── parsers/            # 5 protocol-specific parsers
│   │   │       ├── retrofit.py
│   │   │       ├── okhttp.py
│   │   │       ├── webview.py
│   │   │       ├── jsasset.py
│   │   │       └── deeplink.py
│   │   └── tests/
│   │
│   ├── analyzer/                    # M2-M3: Dynamic analysis
│   │   ├── src/
│   │   │   ├── emulator.py         # AVD lifecycle management
│   │   │   ├── frida_runner.py     # Frida server + script exec
│   │   │   ├── capture.py          # Message → TraceRecord
│   │   │   ├── explorer.py         # Automated UI traversal
│   │   │   ├── trace_store.py      # SQLite persistence
│   │   │   └── har_export.py       # HAR 1.2 import/export
│   │   └── frida_scripts/           # Injection hooks
│   │       ├── okhttp3.js
│   │       ├── retrofit.js
│   │       ├── webview.js
│   │       ├── urlconnection.js
│   │       └── tls_keylog.js
│   │
│   └── gateway/                     # M5-M7: REST gateway
│       └── src/
│           ├── main.py             # FastAPI application
│           ├── executor.py         # Action → HTTP request
│           ├── session.py          # Encrypted credential store
│           ├── orchestrator.py     # Full pipeline automation
│           ├── review_cli.py       # Rich terminal review tool
│           ├── audit.py            # Structured audit logging
│           ├── rate_limit.py       # Token bucket limiter
│           └── auth.py             # API key middleware
│
├── 🧪 tests/                       # Unit test suite
├── 🐳 Dockerfile                   # Multi-stage production build
├── 🐳 docker-compose.yml           # Service orchestration
└── 📋 pyproject.toml               # Project configuration
```

---

## 📡 API Reference

### Core Endpoints

| Endpoint | Method | Description |
|:--|:--:|:--|
| `/apps` | `GET` | List all indexed applications |
| `/apps/{id}` | `GET` | Retrieve app metadata & stats |
| `/apps/{id}/actions` | `GET` | List discovered API actions |
| `/apps/{id}/actions/{aid}` | `GET` | Full action detail with evidence |
| `/apps/{id}/actions/{aid}` | `PATCH` | Approve, reject, or annotate an action |
| `/apps/{id}/actions/{aid}/execute` | `POST` | **Execute** the action with live HTTP |
| `/apps/{id}/spec.json` | `GET` | Download OpenAPI 3.1 spec (JSON) |
| `/apps/{id}/spec.yaml` | `GET` | Download OpenAPI 3.1 spec (YAML) |
| `/apps/{id}/sessions/start` | `POST` | Bootstrap an authenticated session |
| `/jobs` | `POST` | Submit an APK for full pipeline analysis |

### Example: Execute a Discovered Action

```bash
curl -X POST http://localhost:8080/apps/abc123/actions/action-001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "user_id": 42,
      "fields": "name,email"
    },
    "session_id": "sess_xxxx"
  }'
```

---

## 🧪 Testing

```bash
# Run full test suite
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=packages --cov=apps -v
```

**Current status:** `41 tests passing` across scorer, merger, capture, OpenAPI generator, and gateway components.

---

## 📊 Confidence Scoring

Every discovered action receives a confidence score (0.0 → 1.0) based on evidence signals:

| Signal | Weight | Description |
|:--|:--:|:--|
| Dynamic trace exists | **+0.40** | Frida captured a live request |
| Static finding exists | **+0.25** | Parser found bytecode evidence |
| URL templates agree | **+0.15** | Static and dynamic URLs match |
| HTTP 2xx response seen | **+0.10** | Endpoint returned a success status |
| Static-only with concatenation | **−0.15** | URL built dynamically, less reliable |
| Native library in call stack | **−0.20** | May be an internal/native call |
| Opaque hash in URL | **−0.10** | Non-deterministic URL segment |

| Score Range | Label | Meaning |
|:--:|:--:|:--|
| `≥ 0.75` | 🟢 **High** | Strong evidence from multiple sources |
| `0.40 – 0.74` | 🟡 **Medium** | Likely valid, may need review |
| `< 0.40` | 🔴 **Low** | Uncertain, requires manual verification |

---

## ❓ FAQ & Deep Dives

<details>
<summary><strong>💡 "Why does reverse-engineering APK endpoints matter?"</strong></summary>

<br/>

Think of a mobile app like a restaurant menu — what you see on your phone is just the presentation. Behind every "Add to Cart" button, every login screen, and every feed refresh is an **API call to a backend server**. These hidden API calls are the *real* interface to the service.

**Why should you care?**

- **Security researchers** need to understand what data an app sends and receives to find vulnerabilities
- **QA engineers** want to test backend behavior without clicking through UI flows manually
- **Competitive analysts** study how apps structure their backend services
- **Developers** rebuilding or integrating with third-party services need the actual API contracts

Shadow APK Gateway automates what used to take security researchers **days of manual work**: decompiling, reading bytecode, setting up proxy interception, correlating requests — and turns it into a **single command**.

</details>

<details>
<summary><strong>🔐 "How does the SSL pinning bypass work — and why is it important?"</strong></summary>

<br/>

**The problem:** Modern apps use "certificate pinning" — they hardcode which SSL certificates they trust, so even if you set up a proxy (like mitmproxy or Burp Suite), the app refuses to talk to it. It's like an app that only accepts phone calls from specific phone numbers.

**Our solution:** The `tls_keylog.js` Frida script hooks into the Java security layer at runtime and:

1. **Overrides `TrustManager`** — the component that validates server certificates — to trust everything
2. **Patches `OkHostnameVerifier`** — so the hostname check always passes
3. **Exports TLS session keys** in NSS Key Log format for Wireshark-compatible packet decryption

This is the same approach used by professional penetration testers, but fully automated and integrated into the capture pipeline. The intercepted traffic flows directly into `TraceRecord` objects — no manual proxy setup required.

> **Note:** This only works on devices/emulators you control. It does not bypass TLS on production servers.

</details>

<details>
<summary><strong>🧬 "What's the difference between static and dynamic analysis?"</strong></summary>

<br/>

Imagine you're trying to understand how a car works:

| Approach | Analogy | In Shadow APK Gateway |
|:--|:--|:--|
| **Static analysis** | Reading the car's blueprints and manual | Decompiling the APK to smali bytecode and scanning for HTTP patterns (`@GET`, `@POST`, URL strings, OkHttp builders) |
| **Dynamic analysis** | Driving the car and watching the dashboard | Running the app on an emulator with Frida hooks that intercept every actual HTTP request in real-time |

**Neither is sufficient alone:**

- Static analysis finds endpoints that might never be called (dead code, A/B test branches, deprecated features)
- Dynamic analysis only captures what happens during a test run (might miss rarely-triggered endpoints)

Shadow APK Gateway **merges both**: when static and dynamic evidence agree on the same endpoint, confidence is high (`≥ 0.75`). When only one source finds it, the score is lower and it's flagged for manual review.

</details>

<details>
<summary><strong>⚡ "Why generate an OpenAPI spec? Can't I just use cURL?"</strong></summary>

<br/>

You absolutely *can* use cURL — and the gateway supports direct execution via `POST /execute`. But the OpenAPI spec unlocks an entirely different class of workflows:

- **Auto-generate client SDKs** in any language (Python, TypeScript, Go, Java) using tools like `openapi-generator`
- **Import into Postman, Insomnia, or Swagger UI** for visual API exploration
- **Contract testing** — compare the spec against actual responses to detect API drift
- **Documentation** — the spec *is* the documentation, always in sync with what was actually discovered

Think of it this way: the raw endpoint list is a phone book. The OpenAPI spec is a **fully interactive directory** with types, auth requirements, and example values — generated automatically from evidence, not guesswork.

</details>

<details>
<summary><strong>🔄 "What is HAR replay and response diffing?"</strong></summary>

<br/>

**HAR (HTTP Archive)** is a standard format that captures full HTTP conversations — requests, responses, headers, timing, everything. It's what Chrome DevTools exports when you click "Save as HAR."

Shadow APK Gateway captures traffic in HAR format during dynamic analysis, then offers two powerful capabilities:

1. **Replay** — Re-execute the exact same requests later to verify the API still behaves the same way. Useful for regression testing or verifying that an endpoint hasn't changed between app versions.

2. **Response diffing** — Compare the original captured response with the replayed response.  The differ checks:
   - **Status code matching** — did `200 OK` become `401 Unauthorized`?
   - **Body similarity** — Jaccard comparison of JSON keys to detect structural changes
   - **Schema regression** — fields that existed before but are now missing

This is essentially **automated API regression testing**, derived entirely from observed app behavior.

</details>

<details>
<summary><strong>🛡️ "Is this tool meant for hacking apps?"</strong></summary>

<br/>

**No.** Shadow APK Gateway is a **security research and development tool** designed for:

- **Security auditors** testing apps they have authorization to assess
- **Developers** reverse-engineering their own apps for documentation or migration
- **QA teams** building automated test suites from observed API behavior
- **Researchers** studying mobile app architectures and common patterns

All dynamic analysis runs on **local emulators you control**. The tool does not attack, exploit, or connect to servers you don't own. The SSL pinning bypass only works on the instrumented device/emulator, not on remote servers.

**Always ensure you have proper authorization before analyzing any application.**

</details>

---

## 🗺 Roadmap

| Milestone | Status | Description |
|:--|:--:|:--|
| M1 — Static Extractor | ✅ Complete | APK ingestion + 5 bytecode parsers |
| M2 — Dynamic Analyzer | ✅ Complete | Emulator lifecycle + Frida instrumentation |
| M3 — Trace Storage | ✅ Complete | SQLite persistence + HAR export |
| M4 — Merger & Scorer | ✅ Complete | URL normalization + confidence scoring |
| M5 — Gateway & OpenAPI | ✅ Complete | REST API + spec generation |
| M6 — Replay Engine | ✅ Complete | HAR replay + response diffing |
| M7 — Orchestrator | ✅ Complete | End-to-end pipeline automation |
| M8 — Web Dashboard | 🔜 Planned | Visual action catalog explorer |
| M9 — Multi-APK Diffing | 🔜 Planned | Compare API surfaces across app versions |
| M10 — CI/CD Integration | 🔜 Planned | GitHub Actions for automated analysis |

---

## 🐳 Docker

```bash
# Build and run
docker-compose up --build

# Gateway available at http://localhost:8080
# API docs at http://localhost:8080/docs
```

The Docker image includes:
- Python 3.11 slim runtime
- OpenJDK 17 (for apktool)
- All Python dependencies pre-installed
- Health check on `/apps` endpoint

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/shadow-apk-gateway.git
cd shadow-apk-gateway

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run linter
ruff check .

# Run type checker
mypy packages/ apps/
```

### Contribution Areas

- 🔌 **New parsers** — Volley, Apollo GraphQL, gRPC/protobuf
- 🧪 **Test coverage** — integration tests, property-based testing
- 📱 **Dynamic analysis** — iOS support, real device support
- 🎨 **Web dashboard** — React/Next.js frontend for the gateway API
- 📖 **Documentation** — tutorials, video walkthroughs, example analyses

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <strong>Built with 🔬 for the security research community</strong>
  <br/>
  <sub>
    If Shadow APK Gateway helps your research, consider giving it a ⭐
  </sub>
</p>
