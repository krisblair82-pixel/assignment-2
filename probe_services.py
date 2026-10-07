"""Connectivity probe for the class model API endpoints (9001-9005).

Reads credentials from .env (never prints them), probes each service's
routes to discover the exact request format (models list, embeddings,
score/rerank, chat), and writes a scrubbed report to connectivity_report.md.
"""
import json
import os
import urllib.request
import urllib.error
import time

# ---- load .env (no external deps) ----
ENV = {}
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
with open(env_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip()

KEY = ENV.get("CLASS_API_KEY", "")
LLM = ENV.get("LLM_BASE", "")
TEXT_EMB = ENV.get("TEXT_EMBED_BASE", "")
VIS_EMB = ENV.get("VISUAL_EMBED_BASE", "")
RERANK = ENV.get("RERANK_BASE", "")
PARSE = ENV.get("PARSE_BASE", "")

REPORT = []
def log(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    REPORT.append(line)

def http(method, url, body=None, timeout=90):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {KEY}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode("utf-8")
    else:
        data = None
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            dt = time.time() - t0
            try:
                return r.status, json.loads(raw), dt
            except Exception:
                return r.status, raw[:400].decode("utf-8", "replace"), dt
    except urllib.error.HTTPError as e:
        dt = time.time() - t0
        try:
            return e.code, json.loads(e.read()), dt
        except Exception:
            return e.code, {"raw": str(e).split("\n")[0]}, dt
    except Exception as e:
        return None, {"error": type(e).__name__, "detail": str(e)[:200]}, time.time() - t0

def list_models(base):
    """Try the standard vLLM/OpenAI models route (with and without /v1)."""
    for url in (base + "/v1/models", base + "/models"):
        st, body, dt = http("GET", url)
        if st == 200:
            models = [m.get("id") for m in body.get("data", [])]
            return url, models, dt
    return None, None, None

def discover_paths(base):
    """FastAPI/openapi discovery to learn the actual routes."""
    for url in (base + "/openapi.json", base + "/v1/openapi.json"):
        st, body, dt = http("GET", url)
        if st == 200 and isinstance(body, dict) and "paths" in body:
            return list(body["paths"].keys())
    return None

log("=== Connectivity probe (scrubbed: key never printed) ===")
log(f"probe time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
log("")

# ---- 9001 Vision LLM ----
log("## 9001 Vision LLM (Qwen3.6-35B-A3B)")
url, models, dt = list_models(LLM)
log(f"models route: {url}  ({dt:.1f}s)")
log(f"served models: {models}")
st, body, dt = http("GET", LLM + "/models")
log(f"GET /v1/models -> {st} ({dt:.1f}s)")
# tiny chat probe to confirm the chat format works
if models:
    m = models[0]
    payload = {"model": m, "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 16, "temperature": 0.0}
    st, body, dt = http("POST", LLM + "/chat/completions", payload)
    if st == 200:
        msg = body["choices"][0]["message"]
        content = msg.get("content")
        reasoning = bool(msg.get("reasoning"))
        log(f"chat/completions -> {st} ({dt:.1f}s) content={content!r} has_reasoning_field={reasoning}")
    else:
        log(f"chat/completions -> {st} ({dt:.1f}s): {json.dumps(body)[:300]}")

# ---- 9002 Text embeddings ----
log("")
log("## 9002 Text embeddings (Nemotron-3-Embed-1B)")
url, models, dt = list_models(TEXT_EMB)
log(f"models route: {url}  ({dt:.1f}s)")
log(f"served models: {models}")
paths = discover_paths(TEXT_EMB)
log(f"discovered paths: {paths}")
emb_model = models[0] if models else "nvidia/Nemotron-3-Embed-1B-BF16"
for route in ("/v1/embeddings", "/embeddings"):
    payload = {"model": emb_model, "input": "hello world"}
    st, body, dt = http("POST", TEXT_EMB + route, payload)
    if st == 200 and isinstance(body, dict) and "data" in body:
        vec = body["data"][0]["embedding"]
        log(f"POST {route} -> {st} ({dt:.1f}s) dim={len(vec)}")
        break
    else:
        log(f"POST {route} -> {st} ({dt:.1f}s): {json.dumps(body)[:250]}")

# ---- 9003 Visual embeddings ----
log("")
log("## 9003 Visual embeddings (Qwen3-VL-Embedding-2B)")
url, models, dt = list_models(VIS_EMB)
log(f"models route: {url}  ({dt:.1f}s)")
log(f"served models: {models}")
paths = discover_paths(VIS_EMB)
log(f"discovered paths: {paths}")
emb_model = models[0] if models else "Qwen/Qwen3-VL-Embedding-2B"
for route in ("/v1/embeddings", "/embeddings"):
    payload = {"model": emb_model, "input": "a bar chart showing quarterly sales"}
    st, body, dt = http("POST", VIS_EMB + route, payload)
    if st == 200 and isinstance(body, dict) and "data" in body:
        vec = body["data"][0]["embedding"]
        log(f"POST {route} (text input) -> {st} ({dt:.1f}s) dim={len(vec)}")
        break
    else:
        log(f"POST {route} (text input) -> {st} ({dt:.1f}s): {json.dumps(body)[:250]}")

# ---- 9004 Multimodal rerank ----
log("")
log("## 9004 Multimodal rerank (Qwen3-VL-Reranker-2B)")
url, models, dt = list_models(RERANK)
log(f"models route: {url}  ({dt:.1f}s)")
log(f"served models: {models}")
paths = discover_paths(RERANK)
log(f"discovered paths: {paths}")
rr_model = models[0] if models else "Qwen/Qwen3-VL-Reranker-2B"
# try vLLM-style score endpoint, then /rerank
for route in ("/v1/score", "/v1/rerank", "/score", "/rerank"):
    if route.startswith("/v1/score"):
        payload = {"model": rr_model, "query": "quarterly sales figures", "documents": ["the company grew revenue", "sales rose 12% this quarter"]}
    else:
        payload = {"model": rr_model, "query": "quarterly sales figures", "documents": ["the company grew revenue", "sales rose 12% this quarter"]}
    st, body, dt = http("POST", RERANK + route, payload)
    if st == 200:
        log(f"POST {route} -> {st} ({dt:.1f}s) body={json.dumps(body)[:300]}")
        break
    else:
        log(f"POST {route} -> {st} ({dt:.1f}s): {json.dumps(body)[:250]}")

# ---- 9005 Document parsing ----
log("")
log("## 9005 Document parsing (dots.mocr)")
url, models, dt = list_models(PARSE)
log(f"models route: {url}  ({dt:.1f}s)")
log(f"served models: {models}")
paths = discover_paths(PARSE)
log(f"discovered paths: {paths}")
log("(full parse test deferred until course materials are available)")

# ---- write report ----
report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connectivity_report.md")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(REPORT) + "\n")
log("")
log(f"report written to {report_path}")
