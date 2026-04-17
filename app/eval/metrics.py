from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any

from app.eval.judge import Judge


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricResult:
    metric_name: str
    score: float
    label: str
    reasoning: str | None = None
    raw: dict[str, Any] | None = None


class BaseMetricEvaluator:
    metric_name: str

    def __init__(self, judge: Judge, provider: str = "mock", model: str = "mock") -> None:
        self.judge = judge
        self.provider = provider
        self.model = model

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        judge_result = self.judge.evaluate(
            prompt=prompt,
            response=response,
            context=context,
            provider=self.provider,
            model=self.model,
        )
        result = MetricResult(
            metric_name=self.metric_name,
            score=float(judge_result.get("score", 0.0)),
            label=str(judge_result.get("label", "bad")),
            reasoning=judge_result.get("reasoning"),
            raw=judge_result,
        )
        logger.debug(
            "Metric=%s provider=%s model=%s judge_result=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            judge_result,
            result.score,
            result.label,
        )
        return result


class RelevanceEvaluator(BaseMetricEvaluator):
    metric_name = "relevance"


class ContextPrecisionEvaluator(BaseMetricEvaluator):
    metric_name = "context_precision"

    _STOPWORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "your",
    }

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _extract_source_text(source: Any) -> str:
        if isinstance(source, str):
            return source.strip()
        if isinstance(source, dict):
            for key in ("snippet", "text", "content"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if value is not None:
                    text = str(value).strip()
                    if text:
                        return text
            return ""
        value = getattr(source, "snippet", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "content", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return str(source).strip()

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return {token for token in tokens if token not in cls._STOPWORDS}

    @classmethod
    def _heuristic_relevance_score(cls, prompt: str, expected_answer: str, source_text: str) -> float:
        prompt = prompt.strip()
        expected_answer = expected_answer.strip()
        source_text = source_text.strip()
        if not prompt or not expected_answer or not source_text:
            return 0.0

        combined_text = f"{prompt} {expected_answer}".strip()
        combined_lower = combined_text.lower()
        source_lower = source_text.lower()
        if combined_lower in source_lower or source_lower in combined_lower:
            return 1.0

        combined_tokens = cls._tokenize(combined_text)
        source_tokens = cls._tokenize(source_text)
        if not combined_tokens or not source_tokens:
            return 0.0

        overlap = combined_tokens & source_tokens
        if not overlap:
            return 0.0

        prompt_coverage = len(overlap) / len(combined_tokens)
        source_coverage = len(overlap) / len(source_tokens)
        return max(prompt_coverage, source_coverage)

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        expected_answer = response.strip() if isinstance(response, str) else str(response).strip()
        sources = context or []
        source_texts = [self._extract_source_text(source) for source in sources]
        source_texts = [text for text in source_texts if text]

        if not source_texts:
            return MetricResult(
                metric_name=self.metric_name,
                score=0.0,
                label="low",
                reasoning="No sources to evaluate.",
                raw={
                    "relevant_sources": 0,
                    "total_sources": 0,
                    "irrelevant_sources": [],
                    "source_scores": [],
                },
            )

        relevant_sources = 0
        irrelevant_sources: list[str] = []
        source_scores: list[float] = []

        for source_text in source_texts:
            judge_result = self.judge.evaluate(
                prompt=(
                    "Evaluate whether this retrieved source is relevant to answering the question "
                    "and supporting the expected answer.\n"
                    f"Question: {prompt}\n"
                    f"Expected answer: {expected_answer}"
                ),
                response=source_text,
                context=[],
                provider=self.provider,
                model=self.model,
            )
            score = float(judge_result.get("score", 0.0))
            heuristic_score = self._heuristic_relevance_score(prompt, expected_answer, source_text)
            source_score = max(score, heuristic_score)
            source_scores.append(source_score)
            if source_score > 0.7:
                relevant_sources += 1
            else:
                irrelevant_sources.append(source_text)

        precision = relevant_sources / len(source_texts)
        result = MetricResult(
            metric_name=self.metric_name,
            score=precision,
            label=self._label_for_score(precision),
            reasoning=f"{relevant_sources}/{len(source_texts)} sources relevant to the query.",
            raw={
                "relevant_sources": relevant_sources,
                "total_sources": len(source_texts),
                "irrelevant_sources": irrelevant_sources,
                "source_scores": source_scores,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s sources=%s source_scores=%s relevant_sources=%s irrelevant_sources=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            source_texts,
            source_scores,
            relevant_sources,
            irrelevant_sources,
            result.score,
            result.label,
        )
        return result


class ContextRecallEvaluator(BaseMetricEvaluator):
    metric_name = "context_recall"

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _extract_source_text(source: Any) -> str:
        if isinstance(source, str):
            return source.strip()
        if isinstance(source, dict):
            for key in ("snippet", "text", "content"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if value is not None:
                    text = str(value).strip()
                    if text:
                        return text
            return ""
        value = getattr(source, "snippet", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "content", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return str(source).strip()

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        expected_answer = response.strip() if isinstance(response, str) else str(response).strip()
        source_texts = [self._extract_source_text(source) for source in (context or [])]
        source_texts = [text for text in source_texts if text]

        if not source_texts:
            return MetricResult(
                metric_name=self.metric_name,
                score=0.0,
                label="low",
                reasoning="No retrieved sources available.",
                raw={
                    "missing_info": "No retrieved sources available.",
                    "total_sources": 0,
                    "source_texts": [],
                },
            )

        evaluation_prompt = (
            "Context recall evaluation.\n"
            f"Question: {prompt}\n"
            f"Expected answer: {expected_answer}\n"
            "Does the retrieved context contain all information needed to answer the question?\n"
            "Score 1.0 if the context is sufficient, 0.0 if important information is missing, "
            "and use intermediate values for partial coverage."
        )

        judge_result = self.judge.evaluate(
            prompt=evaluation_prompt,
            response=expected_answer,
            context=source_texts,
            provider=self.provider,
            model=self.model,
        )

        score = float(judge_result.get("score", 0.0))
        missing_info = str(judge_result.get("reasoning") or "").strip()
        result = MetricResult(
            metric_name=self.metric_name,
            score=score,
            label=self._label_for_score(score),
            reasoning=missing_info or "Retrieved context recall evaluated by judge.",
            raw={
                "missing_info": missing_info,
                "expected_answer": expected_answer,
                "source_texts": source_texts,
                "judge_result": judge_result,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s expected_answer=%s source_texts=%s judge_result=%s final_score=%s label=%s missing_info=%s",
            self.metric_name,
            self.provider,
            self.model,
            expected_answer,
            source_texts,
            judge_result,
            result.score,
            result.label,
            missing_info,
        )
        return result


class GroundednessEvaluator(BaseMetricEvaluator):
    metric_name = "groundedness"

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _extract_source_text(source: Any) -> str:
        if isinstance(source, str):
            return source.strip()
        if isinstance(source, dict):
            for key in ("snippet", "text", "content"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if value is not None:
                    text = str(value).strip()
                    if text:
                        return text
            return ""
        value = getattr(source, "snippet", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(source, "content", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return str(source).strip()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [part.strip() for part in parts if part and part.strip()]

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        sentences = self._split_sentences(response)
        source_texts = [self._extract_source_text(source) for source in (context or [])]
        source_texts = [text for text in source_texts if text]

        if not sentences:
            return MetricResult(
                metric_name=self.metric_name,
                score=0.0,
                label="low",
                reasoning="No sentences to evaluate.",
                raw={
                    "grounded_sentences": 0,
                    "total_sentences": 0,
                    "unsupported_sentences": [],
                    "sentence_support_scores": [],
                },
            )

        grounded_sentences = 0
        unsupported_sentences: list[str] = []
        sentence_support_scores: list[float] = []

        for sentence in sentences:
            supported = False
            best_score = 0.0

            for source_text in source_texts:
                judge_result = self.judge.evaluate(
                    prompt=prompt,
                    response=sentence,
                    context=[source_text],
                    provider=self.provider,
                    model=self.model,
                )
                score = float(judge_result.get("score", 0.0))
                if score > best_score:
                    best_score = score
                if score > 0.7:
                    supported = True
                    break

            sentence_support_scores.append(best_score)
            if supported:
                grounded_sentences += 1
            else:
                unsupported_sentences.append(sentence)

        total_sentences = len(sentences)
        grounded_ratio = grounded_sentences / total_sentences
        result = MetricResult(
            metric_name=self.metric_name,
            score=grounded_ratio,
            label=self._label_for_score(grounded_ratio),
            reasoning=f"{grounded_sentences}/{total_sentences} sentences supported by retrieved sources.",
            raw={
                "grounded_sentences": grounded_sentences,
                "total_sentences": total_sentences,
                "unsupported_sentences": unsupported_sentences,
                "sentence_support_scores": sentence_support_scores,
                "source_texts": source_texts,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s sentences=%s sentence_support_scores=%s grounded_sentences=%s unsupported_sentences=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            sentences,
            sentence_support_scores,
            grounded_sentences,
            unsupported_sentences,
            result.score,
            result.label,
        )
        return result


class RetrievalQualityEvaluator(BaseMetricEvaluator):
    metric_name = "retrieval_quality"

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        precision_evaluator = ContextPrecisionEvaluator(self.judge, self.provider, self.model)
        recall_evaluator = ContextRecallEvaluator(self.judge, self.provider, self.model)

        precision_result = precision_evaluator.evaluate(prompt=prompt, response=response, context=context)
        recall_result = recall_evaluator.evaluate(prompt=prompt, response=response, context=context)

        precision = float(precision_result.score)
        recall = float(recall_result.score)
        quality = (precision + recall) / 2.0

        result = MetricResult(
            metric_name=self.metric_name,
            score=quality,
            label=self._label_for_score(quality),
            reasoning="Average of context precision and context recall.",
            raw={
                "precision": precision,
                "recall": recall,
                "precision_raw": precision_result.raw,
                "recall_raw": recall_result.raw,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s precision=%s recall=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            precision,
            recall,
            result.score,
            result.label,
        )
        return result


class CompletenessEvaluator(BaseMetricEvaluator):
    metric_name = "completeness"

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        judge_result = self.judge.evaluate(
            prompt=prompt,
            response=response,
            context=context,
            provider=self.provider,
            model=self.model,
        )
        score = float(judge_result.get("completeness", judge_result.get("score", 0.0)))
        result = MetricResult(
            metric_name=self.metric_name,
            score=score,
            label=self._label_for_score(score),
            reasoning=judge_result.get("reasoning"),
            raw=judge_result,
        )
        logger.debug(
            "Metric=%s provider=%s model=%s judge_result=%s completeness_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            judge_result,
            result.score,
            result.label,
        )
        return result


class FaithfulnessEvaluator(BaseMetricEvaluator):
    metric_name = "faithfulness"

    _STOPWORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "your",
    }

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [part.strip() for part in parts if part and part.strip()]

    @staticmethod
    def _flatten_context(context: list[Any]) -> str:
        pieces: list[str] = []
        for item in context:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = str(item.get("text", ""))
            else:
                text = str(getattr(item, "text", item))

            text = text.strip()
            if text:
                pieces.append(text)

        return " ".join(pieces)

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return {token for token in tokens if token not in cls._STOPWORDS}

    @classmethod
    def _heuristic_grounding_score(cls, sentence: str, context_text: str) -> float:
        sentence = sentence.strip()
        context_text = context_text.strip()
        if not sentence or not context_text:
            return 0.0

        sentence_lower = sentence.lower()
        context_lower = context_text.lower()
        if sentence_lower in context_lower or context_lower in sentence_lower:
            return 1.0

        sentence_tokens = cls._tokenize(sentence)
        context_tokens = cls._tokenize(context_text)
        if not sentence_tokens or not context_tokens:
            return 0.0

        overlap = sentence_tokens & context_tokens
        if not overlap:
            return 0.0

        sentence_coverage = len(overlap) / len(sentence_tokens)
        context_coverage = len(overlap) / len(context_tokens)
        return max(sentence_coverage, context_coverage)

    @staticmethod
    def _label_for_score(score: float) -> str:
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        sentences = self._split_sentences(response)
        total_sentences = len(sentences)
        context_text = self._flatten_context(context)

        if total_sentences == 0:
            return MetricResult(
                metric_name=self.metric_name,
                score=0.0,
                label="low",
                reasoning="No sentences to evaluate.",
                raw={
                    "grounded_sentences": 0,
                    "total_sentences": 0,
                    "sentence_scores": [],
                },
            )

        grounded_sentences = 0
        sentence_scores: list[float] = []

        for sentence in sentences:
            judge_result = self.judge.evaluate(
                prompt=prompt,
                response=sentence,
                context=context,
                provider=self.provider,
                model=self.model,
            )
            judge_score = float(judge_result.get("score", 0.0))
            heuristic_score = self._heuristic_grounding_score(sentence, context_text)
            sentence_score = max(judge_score, heuristic_score)
            sentence_scores.append(sentence_score)
            if sentence_score >= 0.5:
                grounded_sentences += 1

        score = grounded_sentences / total_sentences
        result = MetricResult(
            metric_name=self.metric_name,
            score=score,
            label=self._label_for_score(score),
            reasoning=f"{grounded_sentences}/{total_sentences} sentences grounded.",
            raw={
                "grounded_sentences": grounded_sentences,
                "total_sentences": total_sentences,
                "sentence_scores": sentence_scores,
                "context_text": context_text,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s sentences=%s sentence_scores=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            sentences,
            sentence_scores,
            result.score,
            result.label,
        )
        return result


class HallucinationEvaluator(BaseMetricEvaluator):
    metric_name = "hallucination"

    _STOPWORDS = FaithfulnessEvaluator._STOPWORDS

    @staticmethod
    def _extract_claims(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [part.strip() for part in parts if part and part.strip()]

    @staticmethod
    def _flatten_context(context: list[Any]) -> str:
        pieces: list[str] = []
        for item in context:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = str(item.get("text", ""))
            else:
                text = str(getattr(item, "text", item))

            text = text.strip()
            if text:
                pieces.append(text)

        return " ".join(pieces)

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return {token for token in tokens if token not in cls._STOPWORDS}

    @classmethod
    def _heuristic_grounding_score(cls, claim: str, context_text: str) -> float:
        claim = claim.strip()
        context_text = context_text.strip()
        if not claim or not context_text:
            return 0.0

        claim_lower = claim.lower()
        context_lower = context_text.lower()
        if claim_lower in context_lower or context_lower in claim_lower:
            return 1.0

        claim_tokens = cls._tokenize(claim)
        context_tokens = cls._tokenize(context_text)
        if not claim_tokens or not context_tokens:
            return 0.0

        overlap = claim_tokens & context_tokens
        if not overlap:
            return 0.0

        claim_coverage = len(overlap) / len(claim_tokens)
        context_coverage = len(overlap) / len(context_tokens)
        return max(claim_coverage, context_coverage)

    @staticmethod
    def _label_for_rate(rate: float) -> str:
        if rate >= 0.5:
            return "high"
        if rate >= 0.2:
            return "medium"
        return "low"

    def evaluate(self, prompt: str, response: str, context: list) -> MetricResult:
        claims = self._extract_claims(response)
        total_claims = len(claims)
        context_text = self._flatten_context(context)

        if total_claims == 0:
            return MetricResult(
                metric_name=self.metric_name,
                score=0.0,
                label="low",
                reasoning="No claims to evaluate.",
                raw={
                    "hallucination_rate": 0.0,
                    "unsupported_claims": 0,
                    "total_claims": 0,
                    "claim_scores": [],
                },
            )

        unsupported_claims = 0
        claim_scores: list[float] = []

        for claim in claims:
            judge_result = self.judge.evaluate(
                prompt=prompt,
                response=claim,
                context=context,
                provider=self.provider,
                model=self.model,
            )
            judge_score = float(judge_result.get("score", 0.0))
            heuristic_score = self._heuristic_grounding_score(claim, context_text)
            grounded_score = max(judge_score, heuristic_score)
            claim_scores.append(grounded_score)
            if grounded_score < 0.5:
                unsupported_claims += 1

        hallucination_rate = unsupported_claims / total_claims
        score = hallucination_rate
        label = self._label_for_rate(hallucination_rate)

        result = MetricResult(
            metric_name=self.metric_name,
            score=score,
            label=label,
            reasoning=f"{unsupported_claims}/{total_claims} claims unsupported.",
            raw={
                "hallucination_rate": hallucination_rate,
                "unsupported_claims": unsupported_claims,
                "total_claims": total_claims,
                "claim_scores": claim_scores,
                "context_text": context_text,
            },
        )
        logger.debug(
            "Metric=%s provider=%s model=%s claims=%s claim_scores=%s unsupported_claims=%s final_score=%s label=%s",
            self.metric_name,
            self.provider,
            self.model,
            claims,
            claim_scores,
            unsupported_claims,
            result.score,
            result.label,
        )
        return result


METRICS: dict[str, type[BaseMetricEvaluator]] = {
    "relevance": RelevanceEvaluator,
    "context_precision": ContextPrecisionEvaluator,
    "context_recall": ContextRecallEvaluator,
    "groundedness": GroundednessEvaluator,
    "retrieval_quality": RetrievalQualityEvaluator,
    "completeness": CompletenessEvaluator,
    "faithfulness": FaithfulnessEvaluator,
    "hallucination": HallucinationEvaluator,
}
