"""Pure exhaustive mapping. Candidate failure is never proof of impossibility."""
from .models import Decision

BRANCH_STATES = {Decision.WITNESS_VALID: "FEASIBLE",
                 Decision.TARGET_CONTRADICTS_EVIDENCE: "INFEASIBLE",
                 Decision.CANDIDATE_INVALID: "UNKNOWN", Decision.UNDETERMINED: "UNKNOWN"}
LABELS = {("FEASIBLE", "INFEASIBLE"): "SUPPORTS",
          ("INFEASIBLE", "FEASIBLE"): "REFUTES",
          ("FEASIBLE", "FEASIBLE"): "NOT ENOUGH INFO",
          ("INFEASIBLE", "INFEASIBLE"): "UNRESOLVED_CONTRADICTION"}


def adjudicate(true_decision, false_decision):
    states = tuple(BRANCH_STATES[Decision(d)] for d in (true_decision, false_decision))
    return {"true_state": states[0], "false_state": states[1],
            "label": LABELS.get(states, "UNRESOLVED_BRANCH")}
