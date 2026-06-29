use pyo3::prelude::*;
use regex::Regex;
use std::sync::LazyLock;

/// 预编译正则 (全局单例，避免重复编译)
static PHONE_CN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:(?:\+?86)?[-\s]?)?1[3-9]\d{2}[-\s]?\d{4}[-\s]?\d{4}").unwrap()
});
static PHONE_LANDLINE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:0\d{2,3}[-－]\s?)?\d{7,8}(?:[-－]\d{1,6})?").unwrap()
});
static EMAIL: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[a-zA-Z0-9][\w.+-]*@[a-zA-Z0-9][\w-]*\.[a-zA-Z0-9][\w.-]*[a-zA-Z]").unwrap()
});
static URL: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"https?://(?:www\.)?[a-zA-Z0-9][-\w]*(?:\.[a-zA-Z][-\w]*)+(?:/[^\s]*)?|www\.[a-zA-Z0-9][-\w]*(?:\.[a-zA-Z][-\w]*)+(?:/[^\s]*)?"
    ).unwrap()
});
static WECHAT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:微信|WeChat|wechat|VX|vx)[:：]?\s*([a-zA-Z][\w_-]{5,19})").unwrap()
});
static NOT_NAME: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"有限公司|股份|集团|科技|技术|信息|咨询|服务|贸易|实业|手机|电话|邮箱|传真|地址|网址|官网|邮编|微信|QQ|扫一扫|二维码|关注|公众号|小程序").unwrap()
});

/// Rust 实现的名片 OCR 字段提取器。
///
/// 对应 Python 侧: byou.tools.ocr.ocr_field_extractor.FieldExtractor
///
/// 性能: 正则用 regex crate (基于 RE2)，比 Python re 快 2-5x。
///       预编译正则全局单例，无重复编译开销。
#[pyfunction]
pub fn extract_fields_rs(
    lines_json: &str,
) -> PyResult<String> {
    // lines_json: JSON array of {text, center_x, center_y, confidence}
    let lines: Vec<OCRTextLine> = serde_json::from_str(lines_json)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid JSON: {}", e)))?;

    let result = extract_from_lines(&lines);
    let json = serde_json::to_string(&result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("JSON serialize error: {}", e)))?;

    Ok(json)
}

#[pyfunction]
pub fn extract_fields_from_text_rs(text: &str) -> PyResult<String> {
    let lines = vec![OCRTextLine {
        text: text.to_string(),
        center_x: 0.0,
        center_y: 0.0,
        confidence: 1.0,
    }];
    let result = extract_from_lines(&lines);
    let json = serde_json::to_string(&result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("JSON serialize error: {}", e)))?;
    Ok(json)
}

/// OCR 文本行 (简化表示)
#[derive(serde::Deserialize, serde::Serialize)]
struct OCRTextLine {
    text: String,
    center_x: f32,
    center_y: f32,
    confidence: f32,
}

/// 提取结果 (对应 Python FieldCandidates)
#[derive(serde::Serialize)]
struct ExtractResult {
    phone: String,
    phones: Vec<String>,
    email: String,
    emails: Vec<String>,
    website: String,
    websites: Vec<String>,
    wechat: String,
    name_candidate: String,
    title_candidates: Vec<String>,
    company_candidates: Vec<String>,
    address_candidates: Vec<String>,
    all_text: String,
    ocr_confidence: f32,
    low_confidence_lines: Vec<String>,
}

impl ExtractResult {
    fn new() -> Self {
        Self {
            phone: String::new(),
            phones: Vec::new(),
            email: String::new(),
            emails: Vec::new(),
            website: String::new(),
            websites: Vec::new(),
            wechat: String::new(),
            name_candidate: String::new(),
            title_candidates: Vec::new(),
            company_candidates: Vec::new(),
            address_candidates: Vec::new(),
            all_text: String::new(),
            ocr_confidence: 0.0,
            low_confidence_lines: Vec::new(),
        }
    }
}

fn extract_from_lines(lines: &[OCRTextLine]) -> ExtractResult {
    let mut result = ExtractResult::new();
    result.all_text = lines.iter().map(|l| l.text.as_str()).collect::<Vec<_>>().join("\n");

    let full_text = result.all_text.as_str();

    // Layer 1: 正则字段
    // 手机号
    for m in PHONE_CN.find_iter(full_text) {
        let phone = clean_phone(m.as_str());
        if !result.phones.contains(&phone) {
            result.phones.push(phone.clone());
        }
    }
    if let Some(p) = result.phones.first() {
        result.phone = p.clone();
    }

    // 座机 (无手机号时)
    if result.phone.is_empty() {
        if let Some(m) = PHONE_LANDLINE.find(full_text) {
            let phone = m.as_str().trim().to_string();
            if phone.len() >= 10 {
                result.phone = phone.clone();
                result.phones.push(phone);
            }
        }
    }

    // 邮箱
    for m in EMAIL.find_iter(full_text) {
        let email = m.as_str().to_lowercase();
        if !result.emails.contains(&email) {
            result.emails.push(email.clone());
        }
    }
    if let Some(e) = result.emails.first() {
        result.email = e.clone();
    }

    // 网址
    for m in URL.find_iter(full_text) {
        let url = m.as_str().trim().to_string();
        if !result.websites.contains(&url) {
            result.websites.push(url.clone());
        }
    }
    if let Some(w) = result.websites.first() {
        result.website = w.clone();
    }

    // 微信
    for m in WECHAT.captures_iter(full_text) {
        if let Some(cap) = m.get(1) {
            result.wechat = cap.as_str().to_string();
            break;
        }
    }

    // Layer 2: 位置启发
    // 姓名: 2-4 个纯中文字符
    let sorted_by_y = {
        let mut v: Vec<_> = lines.iter().enumerate().collect();
        v.sort_by(|a, b| a.1.center_y.partial_cmp(&b.1.center_y).unwrap());
        v
    };

    for (_, line) in &sorted_by_y {
        let text = line.text.trim();
        if looks_like_name(text) {
            result.name_candidate = text.to_string();
            break;
        }
    }

    // 职位: 含职位关键词的行
    let title_keywords = [
        "CEO", "CTO", "CFO", "COO", "CMO", "CIO", "董事长", "总裁", "总经理",
        "总监", "Director", "VP", "SVP", "经理", "Manager", "工程师", "Engineer",
        "架构师", "设计师", "分析师", "顾问", "合伙人", "代表", "专员",
    ];

    for line in lines {
        let text = line.text.trim();
        for kw in title_keywords.iter() {
            if text.contains(kw) && text.len() <= 20 {
                result.title_candidates.push(text.to_string());
                break;
            }
        }
    }

    // 公司: 含公司后缀
    let company_suffixes = ["有限公司", "股份", "集团", "科技", "技术", "信息", "实业", "贸易"];
    for line in lines {
        let text = line.text.trim();
        for s in company_suffixes.iter() {
            if text.contains(s) && text != result.name_candidate {
                result.company_candidates.push(text.to_string());
                break;
            }
        }
    }

    result
}

fn looks_like_name(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    // 去常见称谓
    let clean = text.replace("先生", "").replace("女士", "").replace("小姐", "").replace("老师", "").replace("总$", "").replace("董$", "");
    let chinese_count = clean.chars().filter(|c|('\u{4e00}'..='\u{9fff}').contains(&(*c as u32))).count();
    clean.len() >= 2 && clean.len() <= 4 && chinese_count == clean.chars().count()
}

fn clean_phone(phone: &str) -> String {
    phone.chars().filter(|c| ![' ', '-', '＋', '+'].contains(c)).collect()
}

fn _clean_phone_py(s: &str) -> String {
    s.chars().filter(|c| ![' ', '-', '＋', '+'].contains(c)).collect()
}
