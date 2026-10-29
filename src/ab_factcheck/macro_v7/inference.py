"""Only claim/evidence cross the inference boundary. No label or metadata inputs."""
import json

import jsonschema

from ..common import LABELS, ROOT, sha256
from ..structured import response_format_for, strict_json

RELATIONS = {"ENTAILMENT": "SUPPORTS", "CONTRADICTION": "REFUTES", "NEUTRAL": "NOT ENOUGH INFO"}
ARMS = ("baseline", "nli", "certificate", "dual")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def schema(arm):
    if arm == "baseline":
        return response_format_for("A2")
    if arm == "nli":
        fields = {"relation": {"type": "string", "enum": list(RELATIONS)}, "justification": {"type": "string"}}
    elif arm == "certificate":
        fields = {"justification": {"type": "string"}, "verdict": {"type": "string", "enum": list(LABELS)}}
    elif arm == "dual":
        fields = {"justification": {"type": "string"}, "claim_entailed": {"type": "boolean"}, "negation_entailed": {"type": "boolean"}}
    else:
        raise ValueError("Unknown arm")
    return {"type": "json_schema", "json_schema": {"name": "macro_" + arm, "strict": True,
        "schema": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}}


def messages(arm, *, claim: str, evidence: str, root=ROOT):
    if arm not in ARMS or not isinstance(claim, str) or not isinstance(evidence, str):
        raise ValueError("Only explicit text inputs accepted")
    if arm == "baseline":
        # Same text and response schema as the historical A27 baseline.
        system = (root / "prompts/v2/A2_system.txt").read_text(encoding="utf-8")
        template = (root / "prompts/v2/A2_user.txt").read_text(encoding="utf-8")
        import re
        user = re.sub(r"\{(claim|evidence)\}", lambda m: {"claim": claim, "evidence": evidence}[m[1]], template)
    else:
        system = (root / f"prompts/v7/{arm}_system.txt").read_text(encoding="utf-8")
        names = ("PREMISE", "HYPOTHESIS") if arm == "nli" else ("EVIDENCE", "CLAIM")
        user = f"{names[0]}:\n{evidence}\n\n{names[1]}:\n{claim}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(arm, record):
    if record.get("provider_validation_issues") or record.get("finish_reason") != "stop":
        return {"label": "INVALID", "error": "provider_or_finish"}
    try:
        value = strict_json(record["raw_response"])
        jsonschema.validate(value, schema(arm)["json_schema"]["schema"])
    except (ValueError, KeyError, TypeError, jsonschema.ValidationError):
        return {"label": "INVALID", "error": "schema"}
    if arm in ("baseline", "certificate"):
        label = value["verdict"]
    elif arm == "nli":
        label = RELATIONS[value["relation"]]
    else:
        label = {(True, False): "SUPPORTS", (False, True): "REFUTES",
                 (False, False): "NOT ENOUGH INFO", (True, True): "INVALID"}[(value["claim_entailed"], value["negation_entailed"])]
    return {"label": label, "object": value, "error": "inconsistent_entailment" if label == "INVALID" else None}


def conservative_consensus(baseline, alternatives):
    """Predeclared, label-symmetric unanimity gate; never sees gold or mechanism."""
    if alternatives and alternatives[0] in LABELS and len(set(alternatives)) == 1:
        return alternatives[0]
    return baseline
