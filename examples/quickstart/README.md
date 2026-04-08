# 🚀 Shadow APK Gateway — 30-Second Quickstart

Get a working gateway serving a sample API catalog in under a minute.

## 1. Clone and install

```bash
git clone https://github.com/usemanusai/shadow-apk-gateway.git
cd shadow-apk-gateway
pip install -e ".[dev]"
```

## 2. Start the gateway with the sample catalog

```bash
export GATEWAY_CATALOGS_DIR=examples/quickstart
uvicorn apps.gateway.src.main:app --host 0.0.0.0 --port 8080
```

## 3. Verify

```bash
# Health check
curl http://localhost:8080/health

# List loaded apps
curl http://localhost:8080/apps

# List actions for the demo app
curl http://localhost:8080/apps/quickstart-demo/actions

# View the OpenAPI 3.1 spec
curl http://localhost:8080/apps/quickstart-demo/spec.json | jq .
```

## 4. Execute an action

Call the approved `GET /api/v1/users/{user_id}` action through the gateway:

```bash
curl -X POST http://localhost:8080/apps/quickstart-demo/actions/qs-action-get-users/execute \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "user_id": 42,
      "fields": "name,email"
    }
  }'
```

> **Note:** This will attempt a real HTTP request to `https://api.example.com`.
> In a real workflow, `base_url` would point to the actual app backend.

## 5. Export the OpenAPI spec to disk

```bash
python -m apps.gateway.src.review_cli export examples/quickstart/catalog.json --out-dir ./output
```

---

**This uses a sample catalog.** To analyze a real APK, see the [Static analysis](../../README.md#-static-analysis) and [Dynamic analysis](../../README.md#-dynamic-analysis) sections in the main README.
