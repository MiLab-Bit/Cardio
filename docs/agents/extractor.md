# Extractor Agent — 信息提取

## 文件

`byou/agents/extractor.py` → `ExtractorAgent`

## 职责

将非结构化输入（名片图片、会议录音）转化为结构化客户信息。

## 处理流程

```
名片图片 (.jpg/.png)
  └→ OCR 工具 (byou/tools/ocr.py)
       └→ 文本提取
            └→ LLM 结构化解析
                 └→ CustomerProfile

会议录音 (.mp3/.wav)
  └→ ASR 工具 (byou/tools/asr.py)
       └→ 文本转录
            └→ LLM 关键点提取
                 └→ key_points[]
```

## 输入

```python
{
    "card_image_path": "path/to/card.jpg",   # 可选
    "audio_file_path": "path/to/meeting.mp3", # 可选
    "context": {}                              # 额外上下文
}
```

## 输出

```python
{
    "profile": CustomerProfile,  # 结构化客户信息
    "raw_text": str,              # OCR/ASR 原始文本
    "key_points": [str],          # 关键内容要点
    "confidence": float,          # 提取置信度 (0-1)
}
```

## 提取字段

| 字段 | 来源 | 优先级 |
|------|------|--------|
| name | 名片 | 必填 |
| title | 名片 | 重要 |
| company | 名片 | 必填 |
| phone | 名片 | 重要 |
| email | 名片 | 重要 |
| wechat | 名片/对话 | 可选 |
| department | 名片 | 可选 |
| address | 名片 | 可选 |

## 依赖工具

- `byou.tools.ocr.OcrTool` — 图像文字识别
- `byou.tools.asr.AsrTool` — 语音转录

## 设计要点

1. **容错**: 名片和录音至少有一条路径成功即可继续
2. **置信度**: 基于 OCR/ASR 精度 + 字段完整性计算
3. **LLM 增强**: 原始 OCR 文本经 LLM 结构化解析，修正错别字
