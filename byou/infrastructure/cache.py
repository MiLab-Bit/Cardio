"""
Cache Layer — 缓存层

提供内存和文件缓存，加速重复查询。
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheLayer:
    """多级缓存"""

    def __init__(self, cache_dir: str = "./data/cache", max_size: int = 1000, ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

        # 内存缓存
        self._memory_cache: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """获取缓存项"""
        # 先查内存
        if key in self._memory_cache:
            timestamp, value = self._memory_cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                logger.debug("缓存命中 (memory): %s", key)
                return value
            else:
                del self._memory_cache[key]

        # 再查文件
        file_path = self._cache_file(key)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                timestamp = data.get("_ts", 0)
                if time.time() - timestamp < self.ttl_seconds:
                    value = data.get("_value")
                    # 回填内存缓存
                    self._memory_cache[key] = (time.time(), value)
                    logger.debug("缓存命中 (disk): %s", key)
                    return value
                else:
                    file_path.unlink()  # 过期删除
            except (json.JSONDecodeError, KeyError):
                pass

        return None

    def set(self, key: str, value: Any) -> None:
        """设置缓存项"""
        now = time.time()

        # 更新内存缓存
        self._memory_cache[key] = (now, value)

        # LRU 淘汰
        if len(self._memory_cache) > self.max_size:
            oldest_key = min(
                self._memory_cache,
                key=lambda k: self._memory_cache[k][0],
            )
            del self._memory_cache[oldest_key]

        # 持久化到文件
        try:
            file_path = self._cache_file(key)
            file_path.write_text(
                json.dumps({"_ts": now, "_value": value}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("缓存持久化失败: %s", e)

    def delete(self, key: str) -> None:
        """删除缓存项"""
        self._memory_cache.pop(key, None)
        file_path = self._cache_file(key)
        if file_path.exists():
            file_path.unlink()

    def clear(self) -> None:
        """清空所有缓存"""
        self._memory_cache.clear()
        for f in self.cache_dir.glob("*.cache.json"):
            f.unlink()
        logger.info("缓存已清空")

    def _cache_file(self, key: str) -> Path:
        """获取缓存文件路径（安全的文件名）"""
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.cache_dir / f"{safe_key}.cache.json"

    def get_stats(self) -> dict:
        """获取缓存统计"""
        file_count = len(list(self.cache_dir.glob("*.cache.json")))
        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": file_count,
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
        }
