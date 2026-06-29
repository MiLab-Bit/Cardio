"""Shared LLM JSON output parser.

Every Agent uses the same parsing logic.  Extracted here to eliminate the
5× duplicated ``_parse_llm_output`` methods.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def parse_llm_json(output: str, *, strict: bool = False) -> dict:
    """Extract and parse a JSON dict from LLM output.

    Handles common formats:
    - Raw JSON string
    - `` ```json ... ``` `` fenced block
    - `` ``` ... ``` `` untyped fenced block
    - Partial / mis-wrapped JSON (best-effort)

    Args:
        output: Raw LLM completion text.
        strict: If True, raise on parse failure instead of returning a
            best-effort fallback dict.

    Returns:
        Parsed dict.  When *strict=False* and parsing fails, a dict with
        key ``"_raw"`` is returned so callers never get a stack trace.
    """
    if not output or not output.strip():
        return {} if not strict else _fail("empty LLM output", strict)

    # Try fenced block extraction first
    match = _FENCE_RE.search(output)
    json_str = match.group(1).strip() if match else output.strip()

    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            return parsed
        # Wrapped in a list? Take first element.
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            return parsed[0]
        return {} if not strict else _fail(f"expected JSON object, got {type(parsed).__name__}", strict)
    except json.JSONDecodeError:
        pass

    # Last resort: try to find a JSON object with brace matching
    brace_start = output.find("{")
    if brace_start == -1:
        if strict:
            raise ValueError(f"no JSON object found in LLM output: {output[:200]}...")
        logger.warning("No JSON braces found in LLM output, returning raw text")
        return {"_raw": output[:2000]}

    depth = 0
    for i in range(brace_start, len(output)):
        if output[i] == "{":
            depth += 1
        elif output[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(output[brace_start : i + 1])
                except json.JSONDecodeError:
                    break

    if strict:
        raise ValueError(f"Cannot parse LLM output as JSON: {output[:200]}...")
    logger.warning("Failed to parse LLM JSON output, returning raw text")
    return {"_raw": output[:2000]}


def _fail(msg: str, strict: bool) -> dict:
    if strict:
        raise ValueError(msg)
    logger.warning("LLM JSON parse: %s", msg)
    return {}
