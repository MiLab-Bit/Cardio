"""Real model engine — Qwen2.5-0.5B 替代启发式引擎。

使用 llama-cpp-python 加载 GGUF 模型，通过 prompt 模板完成分类、路由、压缩等任务。
无模型时自动降级到启发式引擎，对测试和运行零干扰。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

# 尝试导入 llama-cpp-python（GGUF v3 兼容）
try:
    from llama_cpp import Llama  # noqa: F401
    _HAS_LLAMA_CPP = True
except ImportError:
    _HAS_LLAMA_CPP = False

from .types import (
    ClassificationLabel,
    ClassifyData,
    ClassifyResult,
    CompressData,
    CompressResult,
    ExtractData,
    ExtractResult,
    ExtractedField,
    RankedItem,
    RerankData,
    RerankResult,
    RouteData,
    RouteResult,
    RouteTarget,
    SLMCapability,
)

logger = logging.getLogger(__name__)

# ── TF-IDF imports ────────────────────────────────────────────

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


def _tokenize(text: str) -> str:
    if _HAS_JIEBA:
        return " ".join(jieba.cut(text))
    return text


# ═══════════════════════════════════════════════════════════════
# Model pool
# ═══════════════════════════════════════════════════════════════

_MODEL: Any = None
_MODEL_PATH: str | None = None
_MODEL_LOAD_FAILED: bool = False
_MAX_TOKENS_CLASSIFY = 30
_MAX_TOKENS_EXTRACT = 64
_MAX_TOKENS_COMPRESS = 128
_MAX_TOKENS_ROUTE = 30

_MODEL_CANDIDATES = [
    # 相对路径（跨平台）
    "models/qwen2.5-0.5b-instruct-q4_0.gguf",
    "models/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    # 绝对路径（Windows）
    r"Z:\Dev\Byou\models\qwen2.5-0.5b-instruct-q4_0.gguf",
    r"Z:\Dev\Byou\models\qwen2.5-0.5b-instruct-q4_k_m.gguf",
    # 绝对路径（Linux/macOS）
    "/models/qwen2.5-0.5b-instruct-q4_0.gguf",
    os.path.expanduser("~/models/qwen2.5-0.5b-instruct-q4_0.gguf"),
]


def _find_model_path() -> str | None:
    """自动探测模型文件路径（跨平台）"""
    import glob as _glob
    
    # 1. 从环境变量读取
    env_path = os.getenv("BYOU_SLM_MODEL_PATH")
    if env_path and os.path.isfile(env_path):
        logger.info("Using model from BYOU_SLM_MODEL_PATH: %s", env_path)
        return env_path
    
    # 2. 从 settings 读取
    try:
        from byou.config import get_settings
        settings = get_settings()
        if hasattr(settings, 'slm_model_path') and settings.slm_model_path:
            if os.path.isfile(settings.slm_model_path):
                return settings.slm_model_path
    except Exception:
        pass
    
    # 3. 搜索候选路径
    for pat in _MODEL_CANDIDATES:
        # 处理相对路径（相对于项目根目录）
        if not os.path.isabs(pat):
            abs_pat = os.path.join(os.getcwd(), pat)
            matches = _glob.glob(abs_pat)
            if matches:
                return matches[0]
        # 绝对路径直接用 glob
        matches = _glob.glob(pat)
        if matches:
            return matches[0]
    
    return None


def get_model(model_path: str | None = None) -> Any:
    """懒加载 Qwen2.5-0.5B GGUF 模型（单例）。

    如果模型加载失败一次就不再重试（避免拖慢每次测试）。
    """
    global _MODEL, _MODEL_PATH, _MODEL_LOAD_FAILED

    if _MODEL_LOAD_FAILED:
        return None

    if _MODEL is not None:
        return _MODEL

    if not _HAS_LLAMA_CPP:
        _MODEL_LOAD_FAILED = True
        logger.info("llama-cpp-python not installed, using heuristic fallback")
        return None

    if model_path is None:
        model_path = _find_model_path()

    if model_path is None:
        logger.info("Qwen2.5-0.5B model file not found, using heuristic fallback")
        _MODEL_LOAD_FAILED = True
        return None

    if not os.path.isfile(model_path):
        logger.warning("Model file does not exist: %s", model_path)
        _MODEL_LOAD_FAILED = True
        return None

    try:
        logger.info("Loading Qwen2.5-0.5B GGUF from %s ...", model_path)
        _MODEL = Llama(
            model_path=model_path,
            n_ctx=2048,
            n_threads=4,
            n_gpu_layers=0,
            verbose=False,
        )
        _MODEL_PATH = model_path
        logger.info("Qwen2.5-0.5B loaded successfully via llama-cpp-python")
        return _MODEL
    except Exception as exc:
        logger.warning(
            "Failed to load Qwen2.5-0.5B GGUF (%s), using heuristic fallback", exc
        )
        _MODEL = None
        _MODEL_LOAD_FAILED = True
        return None


def model_available() -> bool:
    """检测真实模型是否可用（触发懒加载验证）"""
    if not _HAS_LLAMA_CPP:
        return False
    if _MODEL_LOAD_FAILED:
        return False
    if _MODEL is not None:
        return True
    # 实际尝试加载模型验证可用性
    return get_model() is not None


def _llm_generate(prompt: str, max_tokens: int = 30) -> str:
    """调用 Qwen 模型生成 (llama-cpp-python)"""
    model = get_model()
    if model is None:
        return ""

    try:
        result = model(prompt, max_tokens=max_tokens, temperature=0.0, echo=False)
        if isinstance(result, dict):
            return (result.get("choices", [{}])[0].get("text", "") or "").strip()
        return ""
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# Prompt templates
# ═══════════════════════════════════════════════════════════════

CLASSIFY_PROMPT = """<|im_start|>system
你是一个精确的分类器。根据输入文本输出最匹配的单个标签，只输出标签名，不要解释。
<|im_end|>
<|im_start|>user
文本: {text}
候选标签: {labels}
<|im_end|>
<|im_start|>assistant
"""

ROUTE_PROMPT = """<|im_start|>system
你是一个意图路由器。根据用户查询输出目标 capability，只输出 capability 名称。
<|im_end|>
<|im_start|>user
查询: {query}
候选: {targets}
<|im_end|>
<|im_start|>assistant
"""

EXTRACT_PROMPT = """<|im_start|>system
你是一个信息抽取器。从输入文本中抽取指定字段，输出 JSON。
<|im_end|>
<|im_start|>user
文本: {text}
需要抽取的字段: {fields}
输出格式: JSON，key 是字段名，value 是抽取的值。如果没有找到某字段，值设为 null。
<|im_end|>
<|im_start|>assistant
"""

COMPRESS_PROMPT = """<|im_start|>system
你是一个文本压缩器。从长文本中提取关键句子，输出压缩后的文本。
<|im_end|>
<|im_start|>user
文本: {text}
要求: 保留关键信息，删除冗余和噪音，压缩到 {max_chars} 字符以内。
输出: 直接输出压缩后的文本，不要加说明。
<|im_end|>
<|im_start|>assistant
"""


# ═══════════════════════════════════════════════════════════════
# Real engines
# ═══════════════════════════════════════════════════════════════


class RealClassifier:
    """基于 Qwen2.5-0.5B 的真实分类器"""

    async def classify(
        self, text: str, labels: list[str] | None = None,
        context_tag: str = "default", multi_label: bool = False,
    ) -> ClassifyResult:
        t0 = time.perf_counter()

        if not text.strip():
            return ClassifyResult(
                capability=SLMCapability.CLASSIFY, model="none",
                data=ClassifyData(), confidence=0.0, latency_ms=0,
            )

        if labels is None:
            labels = ["other"]

        # Phase 1: heuristic pre-check — if strong keyword match found, skip LLM
        heuristic = self._heuristic_precheck(text, labels)
        if heuristic is not None:
            latency = (time.perf_counter() - t0) * 1000
            return ClassifyResult(
                capability=SLMCapability.CLASSIFY,
                model="qwen2.5-0.5b+heuristic",
                data=heuristic,
                confidence=0.95,
                latency_ms=round(latency, 2),
            )

        # Phase 2: try LLM
        model = get_model()
        if model is None:
            return _empty_classify_result("model not loaded")

        prompt = CLASSIFY_PROMPT.format(text=text[:500], labels=", ".join(labels))
        raw = _llm_generate(prompt, max_tokens=_MAX_TOKENS_CLASSIFY)

        label = raw.strip().strip('"').strip("'")
        if label not in labels:
            for l in labels:
                if l.lower() in raw.lower():
                    label = l
                    break
            else:
                label = labels[0] if labels else "other"

        data = ClassifyData(
            labels=[
                ClassificationLabel(
                    label=label, score=0.85, rationale=f"model output: {raw}"
                )
            ],
            top_label=label,
            top_score=0.85,
        )
        latency = (time.perf_counter() - t0) * 1000

        return ClassifyResult(
            capability=SLMCapability.CLASSIFY,
            model="qwen2.5-0.5b",
            data=data,
            confidence=0.85,
            latency_ms=round(latency, 2),
        )

    @staticmethod
    def _heuristic_precheck(
        text: str, labels: list[str]
    ) -> ClassifyData | None:
        """强关键词预检：当文本明显匹配某个标签时，不走 LLM"""
        # Strong keyword → label mapping (high confidence, unambiguous)
        strong_keywords: dict[str, list[str]] = {
            "risk_check": ["诉讼", "行政处罚", "经营异常", "失信", "破产", "清算"],
            "company_background": ["公司简介", "企业概况", "主营业务"],
            "website_research": ["官网", "网站", "域名"],
            "product_research": ["产品", "解决方案", "服务范围"],
            "competitor_research": ["竞争对手", "竞品", "市场分析"],
            "contact_find": ["联系方式", "电话", "邮箱", "地址"],
            # page_type labels
            "official_website": ["官网", "官方网站"],
            "news_article": ["新闻", "快讯", "报道"],
            "lawsuit": ["诉讼", "被告", "原告", "判决", "起诉"],
            "penalty": ["行政处罚", "罚款", "处罚决定书"],
            "abnormal_operation": ["经营异常", "经营异常名录"],
            "bankruptcy": ["破产", "清算", "重整"],
            "negative_news": ["负面", "曝光", "投诉"],
        }

        for label in labels:
            keywords = strong_keywords.get(label, [])
            if not keywords:
                continue
            for kw in keywords:
                if kw in text:
                    # Strong match found — skip LLM
                    return ClassifyData(
                        labels=[
                            ClassificationLabel(
                                label=label, score=1.0,
                                rationale=f"heuristic keyword '{kw}' matched"
                            )
                        ],
                        top_label=label,
                        top_score=1.0,
                    )

        return None

    async def classify_research_intent(self, query: str) -> ClassifyResult:
        labels = [
            "company_background", "product_research", "competitor_research",
            "risk_check", "contact_find", "website_research", "other",
        ]
        return await self.classify(query, labels, context_tag="research_intent")

    async def classify_page_type(self, snippet: str) -> ClassifyResult:
        labels = [
            "official_website", "news_article", "report_white_paper",
            "social_media", "recruitment", "registration_record", "other",
        ]
        return await self.classify(snippet, labels, context_tag="page_type")

    async def classify_customer_level(self, profile_text: str) -> ClassifyResult:
        labels = ["A", "B", "C", "D"]
        return await self.classify(profile_text, labels, context_tag="customer_level")

    async def classify_risk_signals(self, text: str) -> ClassifyResult:
        labels = [
            "lawsuit", "dishonesty", "bankruptcy", "operational_abnormal",
            "tax_violation", "negative_news", "no_risk",
        ]
        return await self.classify(text, labels, context_tag="risk_signals", multi_label=True)

    async def classify_quality_issues(self, text: str) -> ClassifyResult:
        labels = [
            "missing_fields", "data_inconsistency", "low_confidence",
            "outdated_info", "incomplete_reasoning", "no_issues",
        ]
        return await self.classify(text, labels, context_tag="quality_issues", multi_label=True)


class RealRouter:
    """基于 Qwen2.5-0.5B 的真实路由器"""

    async def route_intent_to_capability(self, query: str) -> RouteResult:
        t0 = time.perf_counter()

        if not query.strip():
            return RouteResult(
                capability=SLMCapability.ROUTE, model="none",
                data=RouteData(), confidence=0.0, latency_ms=0,
            )

        targets = [
            "COMPANY_LOOKUP", "RISK_ASSESSMENT", "CONTACT_SEARCH",
            "WEB_RESEARCH", "COMPETITOR_ANALYSIS", "GENERAL_RESEARCH",
        ]

        model = get_model()
        if model is None:
            return _empty_route_result("model not loaded")

        prompt = ROUTE_PROMPT.format(query=query[:300], targets=", ".join(targets))
        raw = _llm_generate(prompt, max_tokens=_MAX_TOKENS_ROUTE)

        target = raw.strip().strip('"').strip("'")
        if target not in targets:
            for t in targets:
                if t.lower() in raw.lower():
                    target = t
                    break
            else:
                target = "GENERAL_RESEARCH"

        intent_map = {
            "COMPANY_LOOKUP": "company_background",
            "RISK_ASSESSMENT": "risk_check",
            "CONTACT_SEARCH": "contact_find",
            "WEB_RESEARCH": "website_research",
            "COMPETITOR_ANALYSIS": "competitor_research",
            "GENERAL_RESEARCH": "general",
        }

        data = RouteData(
            targets=[RouteTarget(target=target, score=0.85)],
            top_target=target,
            top_score=0.85,
            intent=intent_map.get(target, "general"),
        )
        latency = (time.perf_counter() - t0) * 1000

        return RouteResult(
            capability=SLMCapability.ROUTE,
            model="qwen2.5-0.5b",
            data=data,
            confidence=0.85,
            latency_ms=round(latency, 2),
        )

    async def route_to_agent(self, query: str) -> RouteResult:
        t0 = time.perf_counter()
        agents = [
            "researcher", "extractor", "strategist", "synthesizer", "critic", "general",
        ]

        model = get_model()
        if model is None:
            return _empty_route_result("model not loaded")

        prompt = ROUTE_PROMPT.format(query=query[:300], targets=", ".join(agents))
        raw = _llm_generate(prompt, max_tokens=_MAX_TOKENS_ROUTE)

        target = raw.strip().strip('"').strip("'")
        if target not in agents:
            target = "general"

        data = RouteData(
            targets=[RouteTarget(target=target, score=0.85)],
            top_target=target,
            top_score=0.85,
        )
        latency = (time.perf_counter() - t0) * 1000

        return RouteResult(
            capability=SLMCapability.ROUTE,
            model="qwen2.5-0.5b",
            data=data,
            confidence=0.85,
            latency_ms=round(latency, 2),
        )

    async def route_tool_capability(self, query: str) -> RouteResult:
        return await self.route_intent_to_capability(query)


class RealExtractor:
    """基于 Qwen2.5-0.5B 的真实抽取器"""

    async def extract(
        self, text: str, fields: list[str] | None = None,
        context_tag: str = "default",
    ) -> ExtractResult:
        import json as _json

        t0 = time.perf_counter()

        if not text.strip():
            return ExtractResult(
                capability=SLMCapability.EXTRACT, model="none",
                data=ExtractData(), confidence=0.0, latency_ms=0,
            )

        if fields is None:
            fields = [
                "company_name", "email", "phone_cn", "website",
                "person_name", "title",
            ]

        # Phase 1: heuristic pre-extract (regex for emails, phones, websites)
        heuristic_fields = self._heuristic_extract(text, fields)

        # Phase 2: try LLM for remaining fields not captured heuristically
        missing_fields = [
            f for f in fields
            if not any(hf.field_name == f for hf in heuristic_fields)
        ]

        if not missing_fields:
            latency = (time.perf_counter() - t0) * 1000
            return ExtractResult(
                capability=SLMCapability.EXTRACT,
                model="qwen2.5-0.5b+heuristic",
                data=ExtractData(
                    fields=heuristic_fields,
                    text_length=len(text),
                    fields_found=len(heuristic_fields),
                ),
                confidence=0.95,
                latency_ms=round(latency, 2),
            )

        model = get_model()
        if model is None:
            if heuristic_fields:
                latency = (time.perf_counter() - t0) * 1000
                return ExtractResult(
                    capability=SLMCapability.EXTRACT,
                    model="heuristic_fallback",
                    data=ExtractData(
                        fields=heuristic_fields,
                        text_length=len(text),
                        fields_found=len(heuristic_fields),
                    ),
                    confidence=0.6,
                    latency_ms=round(latency, 2),
                )
            return _empty_extract_result("model not loaded")

        prompt = EXTRACT_PROMPT.format(text=text[:800], fields=", ".join(missing_fields))
        raw = _llm_generate(prompt, max_tokens=_MAX_TOKENS_EXTRACT)

        extracted_fields = list(heuristic_fields)
        try:
            raw_clean = raw.strip()
            if "```json" in raw_clean:
                raw_clean = raw_clean.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_clean:
                raw_clean = raw_clean.split("```")[1].split("```")[0].strip()

            data = _json.loads(raw_clean)
            if isinstance(data, dict):
                for field_name, value in data.items():
                    if value and value not in ("null", None, ""):
                        extracted_fields.append(ExtractedField(
                            field_name=field_name,
                            value=str(value),
                            confidence=0.85,
                            source_span=str(value),
                        ))
        except (_json.JSONDecodeError, IndexError):
            import re as _re
            for field_name in fields:
                pat = rf"{field_name}\s*[:：]\s*(.+?)(?:\n|$)"
                m = _re.search(pat, raw, _re.IGNORECASE)
                if m:
                    val = m.group(1).strip().strip('"').strip("'")
                    if val:
                        extracted_fields.append(ExtractedField(
                            field_name=field_name,
                            value=val,
                            confidence=0.7,
                            source_span=val,
                        ))

        data = ExtractData(
            fields=extracted_fields,
            text_length=len(text),
            fields_found=len(extracted_fields),
        )
        latency = (time.perf_counter() - t0) * 1000

        return ExtractResult(
            capability=SLMCapability.EXTRACT,
            model="qwen2.5-0.5b",
            data=data,
            confidence=0.85 if extracted_fields else 0.3,
            latency_ms=round(latency, 2),
        )

    async def extract_company_fields(self, text: str) -> ExtractResult:
        fields = [
            "company_name", "phone_cn", "email", "website",
            "ceo_name", "industry", "address",
        ]
        return await self.extract(text, fields, context_tag="company")

    @staticmethod
    def _heuristic_extract(
        text: str, fields: list[str]
    ) -> list[ExtractedField]:
        """强模式抽取：email、电话、URL 等高信号字段走正则，不依赖 LLM"""
        import re as _re
        results: list[ExtractedField] = []

        patterns = [
            ("email", _re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')),
            ("phone_cn", _re.compile(r'1[3-9]\d{9}')),
            ("website", _re.compile(r'(?:https?://)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?')),
        ]

        wanted = set(fields)
        for field_name, pattern in patterns:
            if field_name not in wanted:
                continue
            m = pattern.search(text)
            if m:
                val = m.group(0)
                results.append(ExtractedField(
                    field_name=field_name,
                    value=val,
                    confidence=0.99,
                    source_span=val,
                ))

        return results


class RealCompressor:
    """基于 Qwen2.5-0.5B 的真实压缩器"""

    async def compress(
        self, text: str, max_chars: int = 500, target_ratio: float = 0.3,
    ) -> CompressResult:
        t0 = time.perf_counter()

        if not text.strip():
            return CompressResult(
                capability=SLMCapability.COMPRESS, model="none",
                data=CompressData(
                    compressed_text="", original_length=0,
                    compressed_length=0, key_sentences=[],
                ),
                confidence=0.0, latency_ms=0,
            )

        if len(text) <= max_chars:
            return CompressResult(
                capability=SLMCapability.COMPRESS, model="identity",
                data=CompressData(
                    compressed_text=text, original_length=len(text),
                    compressed_length=len(text), key_sentences=[text],
                ),
                confidence=1.0, latency_ms=0,
            )

        model = get_model()
        if model is None:
            return _empty_compress_result("model not loaded", len(text))

        prompt = COMPRESS_PROMPT.format(text=text[:2000], max_chars=max_chars)
        raw = _llm_generate(prompt, max_tokens=_MAX_TOKENS_COMPRESS)

        compressed = raw.strip()
        if len(compressed) > max_chars:
            compressed = compressed[:max_chars]

        key_sentences = [
            s.strip() for s in compressed.split("\n")
            if s.strip() and len(s.strip()) >= 5
        ]
        if not key_sentences:
            key_sentences = [compressed]

        latency = (time.perf_counter() - t0) * 1000

        return CompressResult(
            capability=SLMCapability.COMPRESS,
            model="qwen2.5-0.5b",
            data=CompressData(
                compressed_text=compressed,
                original_length=len(text),
                compressed_length=len(compressed),
                key_sentences=key_sentences,
            ),
            confidence=0.8,
            latency_ms=round(latency, 2),
        )

    async def compress_browser_snippet(
        self, text: str, max_chars: int = 500,
    ) -> CompressResult:
        return await self.compress(text, max_chars=max_chars)


class RealReranker:
    """基于 TF-IDF + Cosine 的真实重排器"""

    def __init__(self):
        if not _HAS_SKLEARN:
            raise ImportError(
                "scikit-learn required for RealReranker. pip install scikit-learn"
            )

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]],
        top_k: int = 5, min_score: float = 0.0,
    ) -> RerankResult:
        t0 = time.perf_counter()

        if not candidates:
            return RerankResult(
                capability=SLMCapability.RERANK, model="tfidf_cosine",
                data=RerankData(items=[], query=query),
                confidence=0.0, latency_ms=0,
            )

        texts = [c.get("text", "") for c in candidates]

        vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4), max_features=5000,
        )

        try:
            tfidf_matrix = vectorizer.fit_transform([query] + texts)
            query_vec = tfidf_matrix[0:1]
            doc_vecs = tfidf_matrix[1:]
            similarities = cosine_similarity(query_vec, doc_vecs)[0]

            items: list[RankedItem] = []
            for idx, sim in enumerate(similarities):
                if sim >= min_score:
                    items.append(RankedItem(
                        id=candidates[idx].get("id", str(idx)),
                        text=texts[idx],
                        score=round(float(sim), 4),
                        metadata=candidates[idx].get("metadata", {}),
                    ))

            items.sort(key=lambda x: x.score, reverse=True)
            items = items[:top_k]

            gap = items[0].score - items[1].score if len(items) >= 2 else 0.5
            confidence = min(1.0, max(0.3, 0.5 + gap * 2))
            latency = (time.perf_counter() - t0) * 1000

            return RerankResult(
                capability=SLMCapability.RERANK,
                model="tfidf_cosine",
                data=RerankData(
                    items=items, query=query,
                    candidates_count=len(candidates),
                ),
                confidence=round(confidence, 4),
                latency_ms=round(latency, 2),
            )

        except Exception:
            items = [
                RankedItem(
                    id=c.get("id", str(i)), text=c.get("text", ""),
                    score=0.5, metadata=c.get("metadata", {}),
                )
                for i, c in enumerate(candidates[:top_k])
            ]
            latency = (time.perf_counter() - t0) * 1000
            return RerankResult(
                capability=SLMCapability.RERANK, model="tfidf_cosine",
                data=RerankData(
                    items=items, query=query,
                    candidates_count=len(candidates),
                ),
                confidence=0.3, latency_ms=round(latency, 2),
            )


# ── Empty result helpers ───────────────────────────────────────


def _empty_classify_result(reason: str = "") -> ClassifyResult:
    return ClassifyResult(
        capability=SLMCapability.CLASSIFY, model="none",
        data=ClassifyData(), confidence=0.0, latency_ms=0,
        needs_escalation=True, escalation_reason=reason,
    )


def _empty_route_result(reason: str = "") -> RouteResult:
    return RouteResult(
        capability=SLMCapability.ROUTE, model="none",
        data=RouteData(), confidence=0.0, latency_ms=0,
        needs_escalation=True, escalation_reason=reason,
    )


def _empty_extract_result(reason: str = "") -> ExtractResult:
    return ExtractResult(
        capability=SLMCapability.EXTRACT, model="none",
        data=ExtractData(), confidence=0.0, latency_ms=0,
        needs_escalation=True, escalation_reason=reason,
    )


def _empty_compress_result(
    reason: str = "", original_length: int = 0,
) -> CompressResult:
    return CompressResult(
        capability=SLMCapability.COMPRESS, model="none",
        data=CompressData(
            compressed_text="", original_length=original_length,
            compressed_length=0, key_sentences=[],
        ),
        confidence=0.0, latency_ms=0,
        needs_escalation=True, escalation_reason=reason,
    )
