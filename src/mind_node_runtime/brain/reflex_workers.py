"""
Reflex Worker Abstraction for 1B Specialized Models.

Provides fast, local structured extraction, classification, routing, compression,
and pattern matching without sovereign write authority or direct graph mutation.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


class ReflexWorkerResult:
    def __init__(
        self,
        worker: str,
        output: Dict[str, Any],
        confidence: float,
        evidence_spans: List[str],
        unknowns: List[str],
        abstained: bool = False,
        model_version: str = "1b-reflex-v1",
    ) -> None:
        self.worker = worker
        self.output = output
        self.confidence = confidence
        self.evidence_spans = evidence_spans
        self.unknowns = unknowns
        self.abstained = abstained
        self.model_version = model_version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker": self.worker,
            "output": self.output,
            "confidence": round(self.confidence, 4),
            "evidence_spans": self.evidence_spans,
            "unknowns": self.unknowns,
            "abstained": self.abstained,
            "model_version": self.model_version,
            "measurement_status": "inferred" if not self.abstained else "unknown",
        }


class PerceptClassifier:
    """Worker 1: Classifies raw sensory input into structured domain, type, and intent."""

    def process(self, text: str) -> ReflexWorkerResult:
        if not text or not text.strip():
            return ReflexWorkerResult("percept_classifier", {}, 0.0, [], ["empty_input"], abstained=True)

        lowered = text.lower()
        domain = "general"
        content_type = "text_statement"

        if any(w in lowered for w in [" fatigue", "épuisé", "douleur", "faim", "sommeil", "mal"]):
            domain = "somatic_metabolic"
            content_type = "body_signal"
        elif any(w in lowered for w in ["peur", "colère", "joie", "triste", "marre", "bloque"]):
            domain = "affective_limbic"
            content_type = "affect_signal"
        elif any(w in lowered for w in ["outil", "api", "code", "graphe", "mcp", "execute"]):
            domain = "executive_tool"
            content_type = "action_request"

        return ReflexWorkerResult(
            worker="percept_classifier",
            output={"domain": domain, "content_type": content_type, "length": len(text)},
            confidence=0.85,
            evidence_spans=[text[:50]],
            unknowns=[],
        )


class StructuredExtractor:
    """Worker 2: Extracts named entities, dates, actions, and explicit parameters into JSON."""

    def process(self, text: str) -> ReflexWorkerResult:
        if not text:
            return ReflexWorkerResult("structured_extractor", {}, 0.0, [], ["empty_input"], abstained=True)

        entities = re.findall(r"\b[A-Z][a-z0-9_]+\b", text)
        numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text)

        return ReflexWorkerResult(
            worker="structured_extractor",
            output={
                "named_entities": list(set(entities)),
                "numerical_values": numbers,
                "raw_span_count": len(text.split()),
            },
            confidence=0.90,
            evidence_spans=entities[:5],
            unknowns=[],
        )


class EventCandidateExtractor:
    """Worker 3: Formats a short episode into candidate Moment fields."""

    def process(self, text: str, source_actor: str = "human:user") -> ReflexWorkerResult:
        return ReflexWorkerResult(
            worker="event_candidate_extractor",
            output={
                "candidate_moment_type": "observation",
                "summary": text[:120].strip(),
                "source_actor": source_actor,
                "requires_ratification": False,
            },
            confidence=0.88,
            evidence_spans=[text[:60]],
            unknowns=[],
        )


class IntentRouter:
    """Worker 4: Maps user intent to candidate tool, role, or execution pipeline."""

    def process(self, text: str, available_tools: List[str]) -> ReflexWorkerResult:
        lowered = text.lower()
        selected_tool: Optional[str] = None

        for tool in available_tools:
            if tool.lower() in lowered:
                selected_tool = tool
                break

        if not selected_tool and "graphe" in lowered:
            selected_tool = "graph_query"

        return ReflexWorkerResult(
            worker="intent_router",
            output={
                "recommended_tool": selected_tool,
                "candidate_roles": ["companion", "architect"],
                "requires_confirmation": selected_tool is None,
            },
            confidence=0.82 if selected_tool else 0.50,
            evidence_spans=[selected_tool] if selected_tool else [],
            unknowns=["tool_choice"] if not selected_tool else [],
        )


class ContextCompressor:
    """Worker 5: Compresses a bounded subgraph / context window into a clean summary."""

    def process(self, items: List[Dict[str, Any]]) -> ReflexWorkerResult:
        if not items:
            return ReflexWorkerResult("context_compressor", {"summary": ""}, 1.0, [], [], abstained=True)

        summaries = [str(item.get("name", item.get("id", ""))) for item in items[:5]]
        combined = "; ".join(filter(None, summaries))

        return ReflexWorkerResult(
            worker="context_compressor",
            output={"summary": combined, "item_count": len(items)},
            confidence=0.92,
            evidence_spans=summaries,
            unknowns=[],
        )


class PatternMatcher:
    """Worker 6: Matches current activation against subentity signatures."""

    def process(self, activation_text: str, known_signatures: Dict[str, List[str]]) -> ReflexWorkerResult:
        matches = []
        lowered = activation_text.lower()

        for subentity_id, keywords in known_signatures.items():
            hit_count = sum(1 for kw in keywords if kw.lower() in lowered)
            if hit_count > 0:
                matches.append({"subentity_id": subentity_id, "score": hit_count / len(keywords)})

        matches.sort(key=lambda x: x["score"], reverse=True)

        return ReflexWorkerResult(
            worker="pattern_matcher",
            output={"candidate_subentities": matches},
            confidence=0.80 if matches else 0.30,
            evidence_spans=[m["subentity_id"] for m in matches],
            unknowns=[] if matches else ["no_signature_matched"],
        )
