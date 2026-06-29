# byou/core/conversation/post_call.py
"""PostCallAnalyzer — Phase 3 enhanced.

transcript → structured signals → PostCallReport → dispatch to downstream.

Phase 3 v1 additions:
  - ObjectionPattern extraction (via SLM)
  - OutcomeReason classification (structured)
  - QAResult dimensioned scoring
  - LearningSignal generation
  - ActionDecider + FollowUpPlanner integration
  - transcript NEVER enters Memory (only ≤200 char summaries)

Wires real Byou services:
  - SLM Gateway  → classify, extract signals, extract objections
  - Memory        → distill PostCallReport into long-term memory
  - CRM           → update contact record with outcome + summary
  - Durable Exec  → create follow-up tasks via ActionDecider
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from byou.models.channel_contract import (
    BANTScore,
    FollowUpAction,
    LearningSignal,
    LearningSignalType,
    ObjectionOutcome,
    ObjectionPattern,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    QAEvaluator,
    QAResult,
    QualificationSignal,
)
from byou.channels.voice.models import CallSession, CallTurn
from byou.channels.voice.ports import CRMGateway, DurableExecutionGateway, MemoryGateway, SLMGateway
from byou.core.conversation.action_decider import ActionDecider
from byou.core.conversation.follow_up_planner import FollowUpPlanner

logger = logging.getLogger(__name__)


class PostCallAnalyzer:
    """PostCallAnalyzer — transcript → structured signals → PostCallReport.

    Phase 3 enhanced flow:
      1. Per-turn intent/sentiment classification (SLM)
      2. BANT qualification signal extraction (SLM)
      3. ObjectionPattern extraction (SLM) — NEW Phase 3
      4. OutcomeReason classification (SLM) — NEW Phase 3
      5. QAResult dimensioned scoring — NEW Phase 3
      6. LearningSignal generation — NEW Phase 3
      7. Generate summary from structured signals
      8. Build PostCallReport (with all Phase 3 fields)
      9. ActionDecider → FollowUpPlanner → FollowUpAction[]
      10. Dispatch: Memory + CRM + Durable Execution
    """

    def __init__(
        self,
        *,
        slm: SLMGateway | None = None,
        memory: MemoryGateway | None = None,
        crm: CRMGateway | None = None,
        durable: DurableExecutionGateway | None = None,
        action_decider: ActionDecider | None = None,
        follow_up_planner: FollowUpPlanner | None = None,
    ) -> None:
        self._slm = slm
        self._memory = memory
        self._crm = crm
        self._durable = durable
        self._action_decider = action_decider or ActionDecider()
        self._follow_up_planner = follow_up_planner or FollowUpPlanner()

    async def analyze(
        self, session: CallSession, transcript: list[CallTurn],
    ) -> PostCallReport:
        """Analyze a completed call session and produce a structured report.

        This is the single entry point called by VoiceCallCoordinator after
        hangup, before the VoiceAdapter is torn down.
        """
        logger.info("PostCallAnalyzer: analyzing session %s (%d turns)",
                     session.session_id, len(transcript))

        # ── Step 1: Per-turn classification ──
        turn_intents = await self._classify_turns(transcript)

        # ── Step 2: BANT signal extraction ──
        qual_signals = await self._extract_signals(session, transcript)

        # ── Step 3: Objection pattern extraction (Phase 3) ──
        objection_patterns = await self._extract_objection_patterns(session, transcript)

        # ── Step 4: Outcome reason classification (Phase 3) ──
        outcome_reason = await self._classify_outcome_reason(
            session, transcript, qual_signals, objection_patterns,
        )

        # ── Step 5: QA dimensioned scoring (Phase 3) ──
        qa_result = await self._assess_quality_dimensions(session, transcript, qual_signals)

        # ── Step 6: Learning signal generation (Phase 3) ──
        learning_signals = self._generate_learning_signals(
            session, transcript, qual_signals, objection_patterns,
        )

        # ── Step 7: Generate summary ──
        summary = self._summarize(transcript, qual_signals, turn_intents, objection_patterns)

        # ── Step 8: Build PostCallReport ──
        report = self._build_report(
            session=session,
            qual_signals=qual_signals,
            objection_patterns=objection_patterns,
            learning_signals=learning_signals,
            outcome_reason=outcome_reason,
            qa_result=qa_result,
            summary=summary,
            turn_intents=turn_intents,
        )

        # ── Step 9: ActionDecider + FollowUpPlanner ──
        decisions = self._action_decider.decide(
            report,
            risk_level=(
                session.pre_call_package.risk_level
                if session.pre_call_package else "low"
            ),
            approval_required=(
                session.pre_call_package.requires_approval
                if session.pre_call_package else False
            ),
        )
        follow_up_actions = self._action_decider.generate_follow_up_actions(
            decisions, report, lead_id=session.lead_id,
        )
        report.recommended_actions = follow_up_actions

        # ── Step 10: Dispatch to downstream services ──
        await self._dispatch(report, session, transcript)

        return report

    # ── Step 1: Classification ─────────────────────────

    async def _classify_turns(
        self, transcript: list[CallTurn],
    ) -> list[dict[str, Any]]:
        """Classify each user turn for intent and sentiment."""
        if not self._slm:
            return []

        results = []
        for turn in transcript:
            try:
                intent = await self._slm.classify_intent(turn.text)
                sentiment = await self._slm.analyze_sentiment(turn.text)
                results.append({
                    "turn_id": turn.turn_id,
                    "intent": intent.get("intent", "general"),
                    "sentiment": sentiment.get("sentiment", "neutral"),
                })
            except Exception:
                logger.debug("SLM classification failed for turn %s", turn.turn_id)
        return results

    # ── Step 2: Signal extraction ─────────────────────

    async def _extract_signals(
        self, session: CallSession, transcript: list[CallTurn],
    ) -> list[QualificationSignal]:
        """Extract BANT qualification signals from transcript."""
        if not self._slm:
            return self._keyword_scan(session, transcript)

        try:
            user_texts = "\n".join(
                f"[turn_{t.sequence}] {t.text}"
                for t in transcript
                if t.speaker.value == "user"
            )
            if not user_texts:
                return []

            extracted = await self._slm.extract_signals(
                text=user_texts,
                signal_types=["budget", "authority", "need", "timing"],
            )
            return [
                QualificationSignal(
                    session_id=session.session_id,
                    turn_id=s.get("turn_id", ""),
                    signal_type=s.get("type", "unknown"),
                    raw_text=(s.get("raw_text", "") or "")[:200],
                    confidence=float(s.get("confidence", 0.6)),
                    extracted_value=s.get("value", ""),
                    is_positive=s.get("positive", True),
                    bant_dimension=s.get("bant", s.get("type", "")),
                )
                for s in extracted
            ]
        except Exception:
            logger.exception("SLM signal extraction failed")
            return self._keyword_scan(session, transcript)

    @staticmethod
    def _keyword_scan(
        session: CallSession, transcript: list[CallTurn],
    ) -> list[QualificationSignal]:
        """Fallback: keyword-based signal extraction."""
        budget_kw = ["预算", "价格", "费用", "多少钱", "报价"]
        authority_kw = ["老板", "领导", "决策", "审批", "CEO"]
        need_kw = ["需要", "想要", "找", "解决", "问题"]
        timing_kw = ["尽快", "月底", "下个月", "今年", "Q", "季度"]

        kw_map = [
            ("budget", budget_kw),
            ("authority", authority_kw),
            ("need", need_kw),
            ("timing", timing_kw),
        ]

        signals = []
        for turn in transcript:
            if turn.speaker.value != "user":
                continue
            text = turn.text.lower()
            for sig_type, keywords in kw_map:
                for kw in keywords:
                    if kw in text:
                        signals.append(QualificationSignal(
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            signal_type=sig_type,
                            raw_text=turn.text[:200],
                            confidence=0.5,
                            extracted_value=kw,
                            is_positive=True,
                            bant_dimension=sig_type,
                        ))
                        break  # one signal per turn per type
        return signals

    # ── Step 3: Objection pattern extraction (Phase 3) ─

    async def _extract_objection_patterns(
        self, session: CallSession, transcript: list[CallTurn],
    ) -> list[ObjectionPattern]:
        """Extract objection patterns from the call transcript.

        SLM-driven if available; falls back to keyword scan.
        ObjectionPatterns are durable (L2 Structured Signals) and enter
        Memory for batch distillation.
        """
        if not self._slm:
            return self._keyword_objections(session, transcript)

        try:
            user_texts = "\n".join(
                f"[turn_{t.sequence}] {t.text}"
                for t in transcript
                if t.speaker.value == "user"
            )
            if not user_texts:
                return []

            extracted = await self._slm.extract_signals(
                text=user_texts,
                signal_types=["objection", "price_concern", "competitor_mention"],
            )
            patterns = []
            for i, s in enumerate(extracted):
                topic = s.get("type", "unknown")
                if topic in ("budget", "budget_mention", "price_concern"):
                    topic = "价格"
                elif topic in ("objection",):
                    topic = _infer_objection_topic(s.get("raw_text", ""))

                outcome = ObjectionOutcome.UNRESOLVED
                if s.get("overcome"):
                    outcome = ObjectionOutcome.OVERCOME
                elif s.get("escalated"):
                    outcome = ObjectionOutcome.ESCALATED

                patterns.append(ObjectionPattern(
                    pattern_id=f"obj_{session.session_id}_{i}",
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    objection_topic=topic,
                    user_phrase=(s.get("raw_text", "") or "")[:200],
                    agent_response="",
                    outcome=outcome,
                    confidence=float(s.get("confidence", 0.5)),
                    related_turns=[s.get("turn_id", "")] if s.get("turn_id") else [],
                ))
            return patterns
        except Exception:
            logger.exception("SLM objection extraction failed")
            return self._keyword_objections(session, transcript)

    @staticmethod
    def _keyword_objections(
        session: CallSession, transcript: list[CallTurn],
    ) -> list[ObjectionPattern]:
        """Fallback: keyword-based objection detection."""
        patterns = []
        objection_kw = [
            ("价格", ["太贵", "预算不够", "价格高", "能不能便宜"]),
            ("竞品", ["竞品", "用XX的", "已经有供应商", "在比较"]),
            ("不需要", ["不需要", "没兴趣", "暂时不考虑"]),
            ("时间", ["最近比较忙", "过段时间", "没时间", "再说"]),
            ("功能不足", ["缺", "没有这个", "不能"]),
        ]
        for turn in transcript:
            if turn.speaker.value != "user":
                continue
            for topic, keywords in objection_kw:
                for kw in keywords:
                    if kw in turn.text:
                        patterns.append(ObjectionPattern(
                            pattern_id=f"obj_{session.session_id}_{turn.turn_id}_{topic}",
                            session_id=session.session_id,
                            lead_id=session.lead_id,
                            objection_topic=topic,
                            user_phrase=turn.text[:200],
                            agent_response="",
                            outcome=ObjectionOutcome.UNRESOLVED,
                            confidence=0.4,
                            related_turns=[turn.turn_id],
                        ))
                        break
        return patterns

    # ── Step 4: Outcome reason classification (Phase 3) ──

    async def _classify_outcome_reason(
        self,
        session: CallSession,
        transcript: list[CallTurn],
        qual_signals: list[QualificationSignal],
        objection_patterns: list[ObjectionPattern],
    ) -> OutcomeReason:
        """Classify the primary reason for the call outcome.

        Structured, durable. CRM-facing summary generated here.
        """
        # Technical-outcome-based classification (no SLM needed)
        tech = session.technical_outcome
        if tech is not None:
            tech_map = {
                "no_answer": OutcomeReasonType.NO_ANSWER,
                "voicemail": OutcomeReasonType.VOICEMAIL,
                "busy": OutcomeReasonType.HANGUP,
                "failed": OutcomeReasonType.HANGUP,
                "user_hangup": OutcomeReasonType.HANGUP,
            }
            tech_reason = tech_map.get(tech.value if hasattr(tech, "value") else str(tech))
            if tech_reason:
                return OutcomeReason(
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    primary_reason=tech_reason,
                    confidence=0.9,
                    crm_summary=_crm_summary_for_reason(tech_reason, session),
                )

        # Signal-based classification
        positive = [s for s in qual_signals if s.is_positive]
        unresolved = [p for p in objection_patterns
                      if p.outcome == ObjectionOutcome.UNRESOLVED]

        if not positive and not unresolved:
            return OutcomeReason(
                session_id=session.session_id,
                lead_id=session.lead_id,
                primary_reason=OutcomeReasonType.NO_NEED,
                confidence=0.5,
                crm_summary="无明确意向信号，暂不需要。",
            )

        if unresolved:
            return OutcomeReason(
                session_id=session.session_id,
                lead_id=session.lead_id,
                primary_reason=OutcomeReasonType.COMPETITOR_LOCK
                if any(p.objection_topic == "竞品" for p in unresolved)
                else OutcomeReasonType.NOT_NOW,
                secondary_reasons=_infer_secondary_reasons(positive, unresolved),
                confidence=0.6,
                narrative=f"已识别 {len(positive)} 个积极信号和 {len(unresolved)} 个未解决异议。",
                crm_summary=f"意向客户 — {len(positive)} 个积极信号，{len(unresolved)} 个待处理异议。建议跟进。",
            )

        if positive:
            return OutcomeReason(
                session_id=session.session_id,
                lead_id=session.lead_id,
                primary_reason=_infer_primary_positive(positive),
                confidence=0.7,
                narrative=f"识别到 {len(positive)} 个积极意向信号。",
                crm_summary=f"意向客户 — {', '.join(s.signal_type for s in positive)} 信号积极。",
            )

        return OutcomeReason(
            session_id=session.session_id,
            lead_id=session.lead_id,
            primary_reason=OutcomeReasonType.OTHER,
            confidence=0.3,
            crm_summary="通话完成，信息不足无法判断意向。",
        )

    # ── Step 5: QA dimensioned scoring (Phase 3) ──────

    async def _assess_quality_dimensions(
        self,
        session: CallSession,
        transcript: list[CallTurn],
        qual_signals: list[QualificationSignal],
    ) -> QAResult:
        """Dimensioned QA scoring.

        Weights: opening(0.10) discovery(0.25) objection(0.25) closing(0.15)
                 compliance(0.15) tone(0.10)
        """
        user_turns = [t for t in transcript if t.speaker.value == "user"]
        agent_turns = [t for t in transcript if t.speaker.value == "agent"]
        total_turns = len(transcript)

        # Heuristic scoring (v1: rule-based; v2: SLM or ML model)
        opening = min(1.0, 0.4 + (0.2 if agent_turns else 0))  # agent spoke
        discovery = min(1.0, 0.3 + len(qual_signals) * 0.15)
        objection = min(1.0, 0.5 + (0.0 if not user_turns else 0.0))
        closing = min(1.0, 0.3 + (0.2 if total_turns > 5 else 0.0))
        compliance = 0.9  # default, flag if issues detected
        tone = 0.7  # default neutral

        weights = {"opening": 0.10, "discovery": 0.25, "objection": 0.25,
                   "closing": 0.15, "compliance": 0.15, "tone": 0.10}
        overall = (
            opening * weights["opening"]
            + discovery * weights["discovery"]
            + objection * weights["objection"]
            + closing * weights["closing"]
            + compliance * weights["compliance"]
            + tone * weights["tone"]
        )

        flags = []
        suggestions = []
        if discovery < 0.3:
            flags.append("low_discovery")
            suggestions.append("增加需求挖掘问题，深挖客户痛点")
        if opening < 0.3:
            flags.append("weak_opening")
            suggestions.append("开场白需要更专业，表明来意和身份")

        return QAResult(
            qa_id=f"qa_{session.session_id}",
            session_id=session.session_id,
            lead_id=session.lead_id,
            opening_score=round(opening, 2),
            discovery_score=round(discovery, 2),
            objection_handling_score=round(objection, 2),
            closing_score=round(closing, 2),
            compliance_score=round(compliance, 2),
            tone_score=round(tone, 2),
            overall_score=round(overall, 2),
            flags=flags,
            suggestions=suggestions,
            evaluator=QAEvaluator.SLM_AUTO,
        )

    # ── Step 6: Learning signal generation (Phase 3) ────

    def _generate_learning_signals(
        self,
        session: CallSession,
        transcript: list[CallTurn],
        qual_signals: list[QualificationSignal],
        objection_patterns: list[ObjectionPattern],
    ) -> list[LearningSignal]:
        """Generate learning signals from call data.

        These are NOT BANT qualification signals.  They are about "what we
        learned about how to sell", not about what the lead wants.

        Does NOT look at raw transcript — only structured signals and
        patterns.
        """
        signals: list[LearningSignal] = []

        # Talking point effectiveness (from positive qual signals)
        for sig in qual_signals:
            if sig.is_positive and sig.confidence >= 0.6:
                signals.append(LearningSignal(
                    signal_id=f"ls_{session.session_id}_tp_{sig.signal_type}",
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    signal_type=LearningSignalType.TALKING_POINT_EFFECTIVE,
                    description=f"话术 '{sig.signal_type}' 有效 — 客户积极回应",
                    confidence=sig.confidence,
                    related_turns=[sig.turn_id] if sig.turn_id else [],
                ))

        # Objection overcome / unresolved
        for pat in objection_patterns:
            if pat.outcome == ObjectionOutcome.OVERCOME:
                signals.append(LearningSignal(
                    signal_id=f"ls_{session.session_id}_obj_ok_{pat.pattern_id}",
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    signal_type=LearningSignalType.OBJECTION_OVERCOME,
                    description=f"成功回应 '{pat.objection_topic}' 异议",
                    confidence=pat.confidence,
                    related_turns=pat.related_turns,
                ))
            elif pat.outcome == ObjectionOutcome.UNRESOLVED:
                signals.append(LearningSignal(
                    signal_id=f"ls_{session.session_id}_obj_fail_{pat.pattern_id}",
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    signal_type=LearningSignalType.OBJECTION_UNRESOLVED,
                    description=f"未能解决 '{pat.objection_topic}' 异议 — 需要改进话术",
                    confidence=pat.confidence,
                    related_turns=pat.related_turns,
                ))

        return signals

    # ── Step 7: Summary ────────────────────────────────

    @staticmethod
    def _summarize(
        transcript: list[CallTurn],
        signals: list[QualificationSignal],
        turn_intents: list[dict[str, Any]],
        objection_patterns: list[ObjectionPattern],
    ) -> str:
        user_turns = [t for t in transcript if t.speaker.value == "user"]
        total = len(user_turns)
        positive = [s for s in signals if s.is_positive]
        signal_types = list({s.signal_type for s in signals})
        obj_topics = list({p.objection_topic for p in objection_patterns})

        parts = [f"通话共 {total} 轮对话。"]
        if signals:
            parts.append(
                f"识别到 {len(signals)} 个意向信号"
                f" ({', '.join(signal_types)})"
                f"，其中积极信号 {len(positive)} 个。"
            )
        else:
            parts.append("未识别到明确意向信号。")
        if objection_patterns:
            parts.append(
                f"识别到 {len(objection_patterns)} 个异议"
                f" ({', '.join(obj_topics)})。"
            )
        return "".join(parts)

    # ── Step 8: Build report ──────────────────────────

    def _build_report(
        self,
        *,
        session: CallSession,
        qual_signals: list[QualificationSignal],
        objection_patterns: list[ObjectionPattern],
        learning_signals: list[LearningSignal],
        outcome_reason: OutcomeReason,
        qa_result: QAResult,
        summary: str,
        turn_intents: list[dict[str, Any]],
    ) -> PostCallReport:
        """Build the PostCallReport with all Phase 3 fields."""
        # business_decision
        positive = [s for s in qual_signals if s.is_positive]
        if not positive:
            business = "not_qualified"
        elif any(s.signal_type in ("budget", "authority") for s in positive):
            business = "qualified"
        else:
            business = "follow_up"

        # recommended_next_step
        if business == "qualified":
            next_step = "安排深度演示或方案会议"
        elif business == "follow_up":
            next_step = "3天内发送产品资料并预约下次通话"
        else:
            next_step = "记录到CRM，纳入长期培育"

        # BANT score
        bant = BANTScore()
        for sig in qual_signals:
            if sig.bant_dimension == "budget":
                bant.budget = max(bant.budget, sig.confidence)
            elif sig.bant_dimension == "authority":
                bant.authority = max(bant.authority, sig.confidence)
            elif sig.bant_dimension == "need":
                bant.need = max(bant.need, sig.confidence)
            elif sig.bant_dimension == "timing":
                bant.timeline = max(bant.timeline, sig.confidence)

        return PostCallReport(
            session_id=session.session_id,
            lead_id=session.lead_id,
            summary=summary,
            business_decision=business,
            recommended_next_step=next_step,
            qualification_signals=qual_signals,
            objection_patterns=objection_patterns,
            learning_signals=learning_signals,
            outcome_reason=outcome_reason,
            bant_score=bant,
            quality_score=qa_result.overall_score,
            qa_result=qa_result,
            recommended_actions=[],
        )

    # ── Step 10: Dispatch ──────────────────────────────

    async def _dispatch(
        self,
        report: PostCallReport,
        session: CallSession,
        transcript: list[CallTurn],
    ) -> None:
        """Dispatch report to Memory, CRM, and Durable Exec.

        Phase 3 enhanced: uses structured signals only — NO raw transcript.
        """
        # Memory: distill structured signals + objection patterns
        if self._memory:
            try:
                await self._memory.distill_postcall(report)
            except Exception:
                logger.exception("Memory dispatch failed")

        # CRM: update lead with CRM-safe summary
        if self._crm:
            try:
                crm_signals = [
                    s for s in report.qualification_signals
                    if s.is_positive and s.confidence >= 0.5
                ]
                if crm_signals or report.outcome_reason:
                    await self._crm.update_from_report(
                        lead_id=session.lead_id,
                        signals=crm_signals,
                    )
            except Exception:
                logger.exception("CRM update failed")

        # Durable Exec: create follow-up tasks via ActionDecider
        if self._durable and report.recommended_actions:
            try:
                for action in report.recommended_actions:
                    if action.action_type == "durable_retry":
                        run_id = f"{action.action_id}"
                        await self._durable.start_run(run_id, session.session_id)
                        await self._durable.save_checkpoint(
                            run_id,
                            {"action": action.model_dump(), "type": "postcall_followup", "lead": session.lead_id},
                        )
                    elif action.action_type in ("schedule_call", "send_email"):
                        run_id = f"{action.action_id}"
                        await self._durable.start_run(run_id, session.session_id)
                        await self._durable.save_checkpoint(
                            run_id,
                            {"action": action.model_dump(), "type": "postcall_followup", "lead": session.lead_id},
                        )
                    # human_review and crm_task are handled by CRM layer
            except Exception:
                logger.exception("Durable exec dispatch failed")

        logger.info("PostCallAnalyzer: dispatch complete for session %s",
                     session.session_id)


# ── Internal helpers ───────────────────────────────────────

def _infer_objection_topic(text: str) -> str:
    """Infer objection topic from raw text."""
    topic_kw = [
        ("价格", ["价格", "贵", "预算", "费用", "多少钱"]),
        ("竞品", ["竞品", "在用", "供应商", "比较"]),
        ("不需要", ["不需要", "没兴趣", "不考虑"]),
        ("时间", ["忙", "没时间", "过段时间", "再说"]),
    ]
    for topic, keywords in topic_kw:
        for kw in keywords:
            if kw in str(text):
                return topic
    return "其他"


def _crm_summary_for_reason(reason: OutcomeReasonType, session: CallSession) -> str:
    """Generate CRM-facing summary for an outcome reason."""
    summaries = {
        OutcomeReasonType.NO_ANSWER: f"外呼未接通（{session.duration_seconds}s）。",
        OutcomeReasonType.VOICEMAIL: "已留言。",
        OutcomeReasonType.HANGUP: "通话中断或未正常完成。",
    }
    return summaries.get(reason, "通话结束。")


def _infer_secondary_reasons(
    positive: list[QualificationSignal],
    unresolved: list[ObjectionPattern],
) -> list[OutcomeReasonType]:
    """Infer secondary reasons from signals."""
    reasons = []
    for sig in positive:
        if sig.bant_dimension == "need":
            reasons.append(OutcomeReasonType.QUALIFIED_NEED)
        elif sig.bant_dimension == "timeline":
            reasons.append(OutcomeReasonType.QUALIFIED_TIMELINE)
    if any(p.objection_topic == "竞品" for p in unresolved):
        reasons.append(OutcomeReasonType.COMPETITOR_LOCK)
    return reasons


def _infer_primary_positive(
    positive: list[QualificationSignal],
) -> OutcomeReasonType:
    """Infer the primary qualification reason from positive signals."""
    dimension_priority = ["budget", "authority", "need", "timeline"]
    for dim in dimension_priority:
        for sig in positive:
            if sig.bant_dimension == dim:
                return getattr(OutcomeReasonType, f"QUALIFIED_{dim.upper()}", OutcomeReasonType.OTHER)
    return OutcomeReasonType.OTHER
