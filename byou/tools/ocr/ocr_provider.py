"""OCR Provider 抽象基类 — 所有 OCR 引擎的唯一接口。

每个引擎实现 detect() + recognize()，路由器 (OCR Router) 自动编排。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

from byou.tools.ocr.ocr_result import OCRBlock, OCRDocument, OCREngineInfo

ImageInput = Union[bytes, str, Path]


class OCRProvider(ABC):
    """OCR 引擎抽象接口。

    子类需实现:
    - engine_info: 返回引擎元信息
    - detect(): 文字检测 → list[OCRBlock]
    - recognize(): 文字识别 → OCRDocument
    - is_available(): 检测引擎是否可用
    """

    # ── 元信息 ──────────────────────────────

    @property
    @abstractmethod
    def engine_info(self) -> OCREngineInfo:
        ...

    # ── 核心方法 ────────────────────────────

    @abstractmethod
    async def detect(self, image: ImageInput) -> list[OCRBlock]:
        """文字检测: 找出图片中的所有文字区域。

        Args:
            image: 图片路径 / bytes / Path 对象

        Returns:
            文字区块列表，每个块包含包围框和块类型
        """
        ...

    @abstractmethod
    async def recognize(
        self,
        image: ImageInput,
        blocks: list[OCRBlock] | None = None,
    ) -> OCRDocument:
        """文字识别: 对全图或指定区块做识别。

        Args:
            image: 图片路径 / bytes / Path 对象
            blocks: 可选，指定要识别的区块列表。
                    为 None 时先检测再识别。

        Returns:
            包含所有识别结果的 OCRDocument
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检测引擎是否可用（依赖已安装 / 模型已下载）。

        Returns:
            True 表示可以直接调用 detect/recognize
        """
        ...

    # ── 组合方法 ────────────────────────────

    async def detect_and_recognize(self, image: ImageInput) -> OCRDocument:
        """便捷组合: 检测 + 识别一条龙。"""
        blocks = await self.detect(image)
        if not blocks:
            return OCRDocument(
                full_text="",
                engine_name=self.engine_info.name,
                engine_info=self.engine_info,
                warnings=["No text detected"],
            )
        return await self.recognize(image, blocks)

    # ── 工具方法 ────────────────────────────

    @staticmethod
    async def _to_thread(func, *args) -> object:
        """在独立线程中执行同步阻塞调用。"""
        return await asyncio.to_thread(func, *args)

    @staticmethod
    def _resolve_path(image: ImageInput) -> str | bytes:
        """将各种输入统一转为文件路径或 bytes。"""
        if isinstance(image, Path):
            return str(image.resolve())
        return image
