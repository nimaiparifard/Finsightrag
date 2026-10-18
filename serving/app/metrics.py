from prometheus_client import Counter, Histogram

REQUESTS = Counter("finsight_requests_total", "Queries", ["endpoint", "status", "config"])
LATENCY = Histogram("finsight_request_seconds", "End-to-end latency", ["endpoint"],
                    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60))
REFUSALS = Counter("finsight_refusals_total", "Answers refused as 'not found'")
CACHE_HITS = Counter("finsight_cache_hits_total", "Semantic cache hits")
TOKENS = Counter("finsight_llm_tokens_total", "LLM tokens", ["kind"])
GUARDRAIL_FAIL = Counter("finsight_guardrail_failures_total", "Answers failing citation/number checks")
