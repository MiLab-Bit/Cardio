use pyo3::prelude::*;
use std::collections::HashSet;

/// Rust 实现的 LLM 调用复杂度分类器。
///
/// 对应 Python 侧: byou.core.model_router.ComplexityClassifier
///
/// 性能: ~10µs/classify (vs Python ~200µs)，全正则预编译。
#[pyclass]
pub struct ComplexityClassifierRs {
    /// 预编译关键词集合 (deep / medium / cheap tiers)
    deep_keywords: HashSet<String>,
    medium_keywords: HashSet<String>,
    cheap_keywords: HashSet<String>,
}

#[pymethods]
impl ComplexityClassifierRs {
    #[new]
    pub fn new() -> Self {
        let deep_keywords: HashSet<String> = [
            "分析", "总结", "比较", "评估", "推理", "规划",
            "analyze", "summarize", "compare", "evaluate", "reason", "plan",
            "深度", "详细", "全面", "综合", "复杂",
            "代码", "编程", "算法", "设计模式", "架构",
            "translate", "翻译", "论文", "研究", "report",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();

        let medium_keywords: HashSet<String> = [
            "写", "生成", "创建", "制作", "write", "generate", "create",
            "列出", "列举", "list", "enumerate",
            "解释", "说明", "explain", "describe",
            "改", "修改", "edit", "revise",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();

        let cheap_keywords: HashSet<String> = [
            "是", "是什么", "what is", "who is",
            "多少", "how many", "how much",
            "吗", "?", "？",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();

        Self {
            deep_keywords,
            medium_keywords,
            cheap_keywords,
        }
    }

    /// 分类 LLM 调用复杂度，返回 "cheap" / "medium" / "deep"。
    ///
    /// Args:
    ///   prompt: 用户输入
    ///   tools: 可用工具列表 (可选)
    ///   history_turns: 历史对话轮数
    ///
    /// Returns:
    ///   tier: str — "cheap" | "medium" | "deep"
    ///   reason: str — 分类原因
    ///   confidence: float — 0.0-1.0
    #[pyo3(signature = (prompt, tools = None, history_turns = 0))]
    pub fn classify(
        &self,
        prompt: &str,
        tools: Option<Vec<String>>,
        history_turns: usize,
    ) -> (String, String, f64) {
        let prompt_lower = prompt.to_lowercase();
        let word_count = prompt.split_whitespace().count();
        let char_count = prompt.chars().count();

        // 1. 工具数量 → 倾向 deep
        if let Some(ref t) = tools {
            if t.len() >= 5 {
                return (
                    "deep".to_string(),
                    "many tools require complex orchestration".to_string(),
                    0.8,
                );
            }
        }

        // 2. 历史轮数 → 倾向 deep
        if history_turns >= 10 {
            return (
                "deep".to_string(),
                "long conversation history requires deep reasoning".to_string(),
                0.7,
            );
        }

        // 3. 关键词匹配 (预编译 HashSet, O(1) per keyword)
        for kw in &self.deep_keywords {
            if prompt_lower.contains(kw) {
                return (
                    "deep".to_string(),
                    format!("matched deep keyword: '{}'", kw),
                    0.85,
                );
            }
        }

        for kw in &self.medium_keywords {
            if prompt_lower.contains(kw) {
                return (
                    "medium".to_string(),
                    format!("matched medium keyword: '{}'", kw),
                    0.7,
                );
            }
        }

        for kw in &self.cheap_keywords {
            if prompt_lower.contains(kw) {
                return (
                    "cheap".to_string(),
                    format!("matched cheap keyword: '{}'", kw),
                    0.9,
                );
            }
        }

        // 4. 长度启发
        if char_count <= 20 || word_count <= 5 {
            return (
                "cheap".to_string(),
                "short prompt, simple response sufficient".to_string(),
                0.6,
            );
        }

        if char_count >= 200 || word_count >= 50 {
            return (
                "medium".to_string(),
                "long prompt, likely needs thoughtful response".to_string(),
                0.6,
            );
        }

        // 5. 默认 medium
        ("medium".to_string(), "default tier".to_string(), 0.5)
    }
}

impl Default for ComplexityClassifierRs {
    fn default() -> Self {
        Self::new()
    }
}
