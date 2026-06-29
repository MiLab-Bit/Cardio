"""Enrichment Subsystem — Identity Resolver.

企业身份解析器:
- 输入: company name / domain / person name
- 输出: CompanyIdentity (含去重、多候选排序)
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from byou.tools.enrichment.types import CompanyIdentity, SourceType

logger = logging.getLogger(__name__)

# 公司名后缀 (中文)
_COMPANY_SUFFIX_PATTERNS = re.compile(
    r"(有限公司|股份有限公司|有限责任公司|集团有限公司|合伙企业|总公司|分公司|"
    r"中心|研究院|学校|医院|银行|合作社|厂|店|部|行|所|处|院|会|站|社|馆|园)$"
)

# 集团公司等模式的识别
_GROUP_PATTERN = re.compile(r"(集团|控股|投资)")

# 常见 LLC/Inc/Corp 后缀
_ENGLISH_SUFFIXES = re.compile(
    r",?\s*(Inc\.?|Corp\.?|Corporation|LLC|L\.L\.C\.?|Ltd\.?|Limited|"
    r"Co\.?|Company|PLC|LLP|GmbH|S\.A\.|S\.A\.R\.L\.|S\.R\.L\.|Pty\.?\s*Ltd\.?|"
    r"B\.V\.|N\.V\.|KK|K\.K\.|株式会社|有限公司)$", re.IGNORECASE
)


class IdentityResolver:
    """企业身份标准化与匹配"""

    # ── 标准化 ────────────────────────────────────

    @staticmethod
    def normalize_name(name: str) -> str:
        """标准化公司名: 去除多余空格/括号/标点"""
        if not name:
            return ""
        # 全角→半角
        name = name.replace("（", "(").replace("）", ")").replace("，", ",")
        # 合并多个空格
        name = re.sub(r"\s+", " ", name).strip()
        # 移除城市/省份前缀 (但有风险, 仅当括号内时)
        # e.g. "北京)科技有限公司" → "北京科技有限公司" (不推荐, 保留)
        return name

    @staticmethod
    def extract_core_name(name: str) -> str:
        """提取核心企业名 (去除地域和后缀)"""
        name = IdentityResolver.normalize_name(name)
        # 去除英文后缀
        name = _ENGLISH_SUFFIXES.sub("", name)
        # 去除中文后缀
        name = _COMPANY_SUFFIX_PATTERNS.sub("", name)
        # 去除省市区县前缀 (仅匹配常见行政区划词)
        name = re.sub(
            r"^[\u4e00-\u9fff]+?[省市县区自治旗]", "", name
        ).strip()
        return name

    @staticmethod
    def extract_domain_from_url(url: str) -> str:
        """从 URL 提取域名"""
        if not url:
            return ""
        if not url.startswith("http"):
            url = "https://" + url
        return urlparse(url).netloc.lower()

    # ── 匹配 ──────────────────────────────────────

    def resolve(
        self,
        company_name: str = "",
        domain: str = "",
        *,
        search_results: list[dict] | None = None,
    ) -> CompanyIdentity:
        """解析企业身份。

        优先度: 统一信用代码 > 公司全称 > 域名 > 模糊匹配
        """
        identity = CompanyIdentity()

        if not company_name and not domain:
            return identity

        name = self.normalize_name(company_name)
        domain = self.extract_domain_from_url(domain)

        # 从搜索结果中匹配
        candidates = search_results or []

        if name:
            identity.name = name
            identity.aliases = self._generate_aliases(name)
            identity.short_names = [self.extract_core_name(name)]

        if domain:
            identity.domains = [domain]

        # 如果有搜索结果, 做精确匹配
        if candidates and name:
            matched = self._match_candidates(name, candidates)
            if matched:
                identity.candidates = candidates[:5]
                identity.resolution_confidence = matched.get("confidence", 0.7)
                identity.is_fuzzy_match = matched.get("fuzzy", False)
                identity.unified_social_credit_code = matched.get("credit_code", "")
                identity.registration_number = matched.get("reg_number", "")

        identity.resolution_confidence = max(identity.resolution_confidence, 0.8 if name else 0.0)
        # is_fuzzy_match 如果已经设置说明是模糊匹配
        if not identity.is_fuzzy_match and identity.resolution_confidence < 0.8:
            identity.is_fuzzy_match = True

        return identity

    @staticmethod
    def _generate_aliases(name: str) -> list[str]:
        """生成可能的别名"""
        aliases = [name]
        core = IdentityResolver.extract_core_name(name)
        if core and core != name:
            aliases.append(core)
        # 去括号内容
        no_paren = re.sub(r"\(.*?\)", "", name).strip()
        if no_paren != name:
            aliases.append(no_paren)
        return list(dict.fromkeys(aliases))  # 去重保序

    @staticmethod
    def _match_candidates(name: str, candidates: list[dict]) -> dict | None:
        """在候选列表中匹配公司名"""
        if not candidates:
            return None

        core = IdentityResolver.extract_core_name(name)

        for c in candidates:
            c_name = c.get("name", "")
            if not c_name:
                continue

            # 精确匹配
            if IdentityResolver.normalize_name(c_name) == name:
                return {"confidence": 1.0, "fuzzy": False, **c}

            # 核心名匹配
            c_core = IdentityResolver.extract_core_name(c_name)
            if c_core and c_core == core:
                return {"confidence": 0.85, "fuzzy": False, **c}

        # 模糊匹配: 第一个候选取 0.5 置信度
        if candidates:
            return {"confidence": 0.5, "fuzzy": True, **candidates[0]}

        return None


class DomainResolver:
    """域名 → 公司身份反查"""

    @staticmethod
    def guess_company_from_domain(domain: str) -> str:
        """从域名推测公司名 (启发式, 只用作搜索 query)"""
        if not domain:
            return ""
        # 去掉 www. 和 TLD
        domain = domain.lower().replace("www.", "")
        parts = domain.split(".")
        if len(parts) >= 2:
            # e.g. alibaba.com → 阿里巴巴 / alibaba
            core = parts[0]
            # 尝试常见的拼音→中文映射 (非常有限)
            map_py_cn = {
                "alibaba": "阿里巴巴",
                "tencent": "腾讯",
                "baidu": "百度",
                "huawei": "华为",
                "xiaomi": "小米",
                "jd": "京东",
                "meituan": "美团",
                "bytedance": "字节跳动",
                "netease": "网易",
                "sensetime": "商汤科技",
            }
            return map_py_cn.get(core, core.replace("-", " ").title())
        return domain

    @staticmethod
    def extract_domains_from_links(links: list[dict[str, str]]) -> list[str]:
        """从搜索结果链接中提取独特域名"""
        domains = set()
        for link in links:
            href = link.get("href", "")
            if href and href.startswith("http"):
                d = IdentityResolver.extract_domain_from_url(href)
                if d:
                    domains.add(d)
        return list(domains)[:10]
