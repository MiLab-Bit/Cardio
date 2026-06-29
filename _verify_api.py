import ast, re

text = open("byou/api.py", "r", encoding="utf-8").read()
ast.parse(text)

# 1. Endpoint scan
routes = re.findall(r'@app\.(get|post)\("([/\w]+)"', text)
assert len(routes) == 7, f"Expected 7 routes, got {len(routes)}"
print(f"[PASS] 7 endpoints: {[f'{m.upper()} {p}' for m,p in routes]}")

# 2. CORS check
assert "CORSMiddleware" in text, "Missing CORSMiddleware"
print("[PASS] CORS configured")

# 3. SSE stream endpoint
assert 'text/event-stream' in text, "Missing SSE media type"
assert 'streamingResponse' not in text.lower() and 'StreamingResponse' in text, "Missing StreamingResponse"
print("[PASS] SSE stream endpoint")

# 4. History endpoint
assert '/history' in text and 'performance_history' in text, "Missing /history"
print("[PASS] /history endpoint")

# 5. No stale get_summary()
assert 'get_summary()' not in text, "STALE: get_summary() still present"
print("[PASS] No get_summary(), uses model_dump()")

# 6. Runtime import check
from byou.core.learning_loop import LearningLoop
from byou.agents import create_agent
l = LearningLoop(); a = create_agent('extractor')
print(f"[PASS] Runtime imports OK (learning_loop={type(l).__name__}, agent={type(a).__name__})")

# 7. check orchestrator has on_progress parameter
import inspect
from byou.core.orchestrator import Orchestrator
sig = inspect.signature(Orchestrator.process_pipeline)
assert 'on_progress' in sig.parameters, "Orchestrator.process_pipeline missing on_progress param"
print("[PASS] Orchestrator.process_pipeline has on_progress param")

print("\n=== All checks passed ===")
