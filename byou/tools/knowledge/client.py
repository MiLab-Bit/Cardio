"""
Knowledge Tool — 知识库管理工具

管理 BD 知识和经验库，支持知识的存储和检索。
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """BD 知识库"""

    def __init__(self, base_path: str = "./data/knowledge"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

        # 知识分类
        self.categories = [
            "industry_insights",    # 行业洞察
            "competitor_intel",     # 竞品情报
            "bd_scripts",           # BD 话术模板
            "objection_handling",   # 异议处理
            "success_cases",        # 成功案例
            "failed_cases",         # 失败教训
        ]

        for cat in self.categories:
            (self.base_path / cat).mkdir(exist_ok=True)

    async def store(self, category: str, key: str, data: dict) -> bool:
        """存储知识条目"""
        if category not in self.categories:
            raise ValueError(f"未知知识类别: {category}")

        file_path = self.base_path / category / f"{key}.json"
        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("知识已存储: %s/%s", category, key)
        return True

    async def retrieve(self, category: str, key: str) -> Optional[dict]:
        """检索知识条目"""
        file_path = self.base_path / category / f"{key}.json"
        if not file_path.exists():
            return None

        return json.loads(file_path.read_text(encoding="utf-8"))

    async def search(self, query: str, category: Optional[str] = None) -> list[dict]:
        """搜索知识（基于文件名和内容的简单匹配）"""
        results = []
        search_paths = (
            [self.base_path / category] if category
            else [self.base_path / cat for cat in self.categories]
        )

        for sp in search_paths:
            if not sp.exists():
                continue
            for f in sp.glob("*.json"):
                if query.lower() in f.stem.lower():
                    data = json.loads(f.read_text(encoding="utf-8"))
                    results.append({
                        "category": sp.name,
                        "key": f.stem,
                        "data": data,
                    })

        return results

    async def list_categories(self) -> list[str]:
        """列出所有知识类别及其条目数"""
        result = []
        for cat in self.categories:
            cat_path = self.base_path / cat
            count = len(list(cat_path.glob("*.json"))) if cat_path.exists() else 0
            result.append(f"{cat} ({count})")
        return result
