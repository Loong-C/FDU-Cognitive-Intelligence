"""Input-only negation, fixed polarity map and label-symmetric consistency gate."""
import json

from ..common import LABELS, ROOT
from ..macro_v7.inference import messages as nli_messages, schema, parse, digest

FLIP = {"SUPPORTS": "REFUTES", "REFUTES": "SUPPORTS", "NOT ENOUGH INFO": "NOT ENOUGH INFO"}


def negate(claim):
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("Nonempty claim text required")
    # JSON quotation preserves the entire original proposition, including scope.
    return "It is not the case that the following statement holds: " + json.dumps(claim, ensure_ascii=False)


def messages(node, *, claim, evidence, root=ROOT):
    if node == "baseline":
        return nli_messages("baseline", claim=claim, evidence=evidence, root=root)
    if node not in ("positive", "negative"):
        raise ValueError("Unknown inference node")
    return nli_messages("nli", claim=negate(claim) if node == "negative" else claim, evidence=evidence, root=root)


def request(node, *, claim, evidence, root=ROOT):
    return {"messages": messages(node, claim=claim, evidence=evidence, root=root),
            "response_format": schema("baseline" if node == "baseline" else "nli"),
            "max_completion_tokens": 1024 if node == "baseline" else 512}


def label(node, record):
    return parse("baseline" if node == "baseline" else "nli", record)["label"]


def needs_negative(baseline, positive):
    return positive in LABELS and positive != baseline


def decide(baseline, positive, negative=None):
    """Negative is the raw NLI prediction about NOT(C), never about C itself."""
    if positive not in LABELS:
        return baseline, "invalid_positive_fallback"
    if baseline == positive:
        return baseline, "baseline_positive_agree"
    if negative is None:
        return "INVALID", "pending_negative"
    if negative not in FLIP:
        return baseline, "invalid_negative_fallback"
    if positive == FLIP[negative]:
        return positive, "negation_consistent_override"
    return baseline, "negation_inconsistent_fallback"


def synthetic_cases():
    # Generic symbolic propositions, independent of every benchmark example.
    return [
        {"id": "atom_true", "evidence": "Proposition P is true. Proposition Q is false.", "claim": "Proposition P is true.", "gold": "SUPPORTS"},
        {"id": "atom_false", "evidence": "Proposition P is true. Proposition Q is false.", "claim": "Proposition Q is true.", "gold": "REFUTES"},
        {"id": "atom_open", "evidence": "Proposition P is true. Proposition Q is false.", "claim": "Proposition R is true.", "gold": "NOT ENOUGH INFO"},
        {"id": "conjunction_true", "evidence": "Propositions P and Q are both true.", "claim": "Both P and Q are true.", "gold": "SUPPORTS"},
        {"id": "conjunction_false", "evidence": "Proposition P is true and proposition Q is false.", "claim": "Both P and Q are true.", "gold": "REFUTES"},
        {"id": "conjunction_open", "evidence": "Proposition P is true. No information about Q is provided.", "claim": "Both P and Q are true.", "gold": "NOT ENOUGH INFO"},
        {"id": "disjunction_true", "evidence": "Proposition P is true. No information about Q is provided.", "claim": "At least one of P and Q is true.", "gold": "SUPPORTS"},
        {"id": "disjunction_false", "evidence": "Propositions P and Q are both false.", "claim": "At least one of P and Q is true.", "gold": "REFUTES"},
        {"id": "disjunction_open", "evidence": "Proposition R is true. No information about P or Q is provided.", "claim": "At least one of P and Q is true.", "gold": "NOT ENOUGH INFO"},
    ]
