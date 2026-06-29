"""CUA Subsystem — Computer-Use Agent 浏览器自动化工具。

6 层架构 + 运行时引擎:
├── perception       感知层：UI 元素识别、文本提取
├── semantic_align   语义对齐层：元素语义理解
├── state_modeling   状态建模层：操作状态追踪
├── planning         规划层：任务分解与路径规划
├── execution        执行层：浏览器操作执行
├── validation       验证层：操作结果校验与重试
└── runtime          运行时引擎：6 层流水线编排
"""

from byou.tools.cua.runtime import CuaRuntime, CuaTask, ExecutionStatus

__all__ = ["CuaRuntime", "CuaTask", "ExecutionStatus"]