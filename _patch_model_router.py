"""Patch model_router.py: add Rust delegation to TaskComplexityClassifier.classify()"""
import re

with open("/z/Dev/Byou/byou/core/model_router.py", encoding="utf-8") as f:
    content = f.read()

# Check if Rust delegation already added
if "self._use_rust" in content and "self._rs.classify" in content:
    print("OK: Rust delegation already present in classify()")
else:
    # Find: after force_tier check, before "reasons: list[str] = []"
    # We need to insert the Rust delegation block
    old = '        reasons: list[str] = []\n        scores: list[float] = []'
    new = (
        '        # Rust acceleration: delegate to Rust if available\n'
        '        if self._use_rust:\n'
        '            tier_str, reason, conf = self._rs.classify(prompt, tools, history_turns)\n'
        '            tier = ModelTier(tier_str)\n'
        '            return ComplexityScore(\n'
        '                overall=conf,\n'
        '                tier_suggestion=tier,\n'
        '                reasons=[reason],\n'
        '            )\n\n'
        '        reasons: list[str] = []\n'
        '        scores: list[float] = []'
    )
    if old in content:
        content = content.replace(old, new, 1)
        print("OK: Rust delegation added to classify()")
    else:
        print("WARN: target string not found, classify() may have changed")

    with open("/z/Dev/Byou/byou/core/model_router.py", "w", encoding="utf-8") as f:
        f.write(content)

# Verify syntax
import ast
try:
    with open("/z/Dev/Byou/byou/core/model_router.py", encoding="utf-8") as f:
        ast.parse(f.read())
    print("OK: model_router.py syntax valid")
except SyntaxError as e:
    print(f"SYNTAX ERROR line {e.lineno}: {e.msg}")
