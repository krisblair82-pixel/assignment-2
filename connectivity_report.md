=== Connectivity probe (scrubbed: key never printed) ===
probe time: 2026-10-07 17:43:23

## 9001 Vision LLM (Qwen3.6-35B-A3B)
models route: http://dobolyi.com:9001/v1/models  (0.1s)
served models: ['cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit']
GET /v1/models -> 200 (0.1s)
chat/completions -> 200 (0.2s) content=None has_reasoning_field=True

## 9002 Text embeddings (Nemotron-3-Embed-1B)
models route: http://dobolyi.com:9002/v1/models  (0.1s)
served models: ['nvidia/Nemotron-3-Embed-1B-BF16']
discovered paths: ['/load', '/version', '/health', '/metrics', '/tokenize', '/detokenize', '/v1/models', '/ping', '/invocations', '/pooling', '/v1/embeddings', '/v2/embed', '/score', '/v1/score', '/rerank', '/v1/rerank', '/v2/rerank']
POST /v1/embeddings -> 200 (0.2s) dim=2048

## 9003 Visual embeddings (Qwen3-VL-Embedding-2B)
models route: http://dobolyi.com:9003/v1/models  (0.1s)
served models: ['Qwen/Qwen3-VL-Embedding-2B']
discovered paths: None
POST /v1/embeddings (text input) -> 404 (0.1s): {"detail": "Not Found"}
POST /embeddings (text input) -> 200 (0.2s) dim=2048

## 9004 Multimodal rerank (Qwen3-VL-Reranker-2B)
models route: http://dobolyi.com:9004/v1/models  (0.2s)
served models: ['Qwen/Qwen3-VL-Reranker-2B']
discovered paths: ['/load', '/version', '/health', '/metrics', '/tokenize', '/detokenize', '/v1/models', '/ping', '/invocations', '/pooling', '/classify', '/score', '/v1/score', '/rerank', '/v1/rerank', '/v2/rerank']
POST /v1/score -> 400 (0.2s): {"error": {"message": "7 validation errors:\n  {'type': 'missing', 'loc': ('body', 'function-after[_merge_instruction_into_kwargs(), function-wrap[__log_extra_fields__()]]', 'queries'), 'msg': 'Field required', 'input': {'model': 'Qwen/Qwen3-VL-Reran
POST /v1/rerank -> 200 (0.2s) body={"id": "score-b5c2e2f703f9d48a", "model": "Qwen/Qwen3-VL-Reranker-2B", "usage": {"prompt_tokens": 152, "total_tokens": 152}, "results": [{"index": 1, "document": {"text": "sales rose 12% this quarter", "multi_modal": null}, "relevance_score": 0.6027259826660156}, {"index": 0, "document": {"text": "t

## 9005 Document parsing (dots.mocr)
models route: http://dobolyi.com:9005/v1/models  (0.1s)
served models: ['dots.mocr']
discovered paths: None
(full parse test deferred until course materials are available)
