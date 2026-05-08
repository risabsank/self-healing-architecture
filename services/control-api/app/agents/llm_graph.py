import json
from typing import Any, TypedDict

from app.agents.llm import ClaudeClient, incident_system_prompt
from app.agents.state import Evidence, IncidentAnalysis, LLMIncidentDecision

try:
    from langgraph.graph import END, StateGraph
except ImportError:
    END = None
    StateGraph = None


class LLMGraphState(TypedDict, total=False):
    analysis: IncidentAnalysis
    prompt: str
    decision: LLMIncidentDecision


def run_llm_incident_graph(analysis: IncidentAnalysis) -> IncidentAnalysis:
    state: LLMGraphState = {"analysis": analysis}
    if StateGraph is None:
        return run_sequential(state)["analysis"]
    return run_langgraph(state)["analysis"]


def run_langgraph(state: LLMGraphState) -> LLMGraphState:
    graph = StateGraph(LLMGraphState)
    graph.add_node("build_prompt", build_prompt_node)
    graph.add_node("call_claude", call_claude_node)
    graph.add_node("apply_decision", apply_decision_node)
    graph.set_entry_point("build_prompt")
    graph.add_edge("build_prompt", "call_claude")
    graph.add_edge("call_claude", "apply_decision")
    graph.add_edge("apply_decision", END)
    return graph.compile().invoke(state)


def run_sequential(state: LLMGraphState) -> LLMGraphState:
    state = build_prompt_node(state)
    state = call_claude_node(state)
    return apply_decision_node(state)


def build_prompt_node(state: LLMGraphState) -> LLMGraphState:
    analysis = state["analysis"]
    state["prompt"] = json.dumps(incident_prompt_payload(analysis), default=str)
    return state


def call_claude_node(state: LLMGraphState) -> LLMGraphState:
    state["decision"] = ClaudeClient().complete_json(
        incident_system_prompt(),
        state["prompt"],
        LLMIncidentDecision,
    )
    return state


def apply_decision_node(state: LLMGraphState) -> LLMGraphState:
    analysis = state["analysis"]
    decision = state["decision"]
    analysis.hypotheses = sorted(decision.hypotheses, key=lambda item: item.confidence, reverse=True)
    analysis.mitigations = sorted(decision.mitigations, key=lambda item: item.rank)
    analysis.reasoning_summary = decision.reasoning_summary
    analysis.reasoning_provider = "claude"
    return state


def compact_evidence(item: Evidence, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "source": item.source,
        "kind": item.kind,
        "summary": item.summary,
        "confidence": item.confidence,
        "content": item.content,
    }


def incident_prompt_payload(analysis: IncidentAnalysis) -> dict[str, Any]:
    return {
        "task": "Diagnose the incident and select bounded remediation candidates.",
        "output_schema": LLMIncidentDecision.model_json_schema(),
        "incident_id": analysis.incident_id,
        "sandbox_id": analysis.sandbox_id,
        "evidence": [compact_evidence(item, index) for index, item in enumerate(analysis.evidence)],
    }
