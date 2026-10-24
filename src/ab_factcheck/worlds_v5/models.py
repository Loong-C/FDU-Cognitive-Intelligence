"""Narrow, metadata-free interfaces and strict output validation."""
from dataclasses import dataclass
from enum import Enum

from ..structured import matches_schema, strict_json


class Decision(str, Enum):
    WITNESS_VALID = "WITNESS_VALID"
    TARGET_CONTRADICTS_EVIDENCE = "TARGET_CONTRADICTS_EVIDENCE"
    CANDIDATE_INVALID = "CANDIDATE_INVALID"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class Problem:
    evidence: str
    claim: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (self.evidence, self.claim)):
            raise ValueError("Evidence and claim must be nonempty text")


@dataclass(frozen=True)
class Candidate:
    target_condition: str
    candidate_world: str


def validate(text, schema, finish_reason):
    result = {"json_valid": False, "schema_valid": False, "protocol_valid": False,
              "parsed": None, "errors": [], "quality_flags": []}
    try:
        result["parsed"] = strict_json(text)
        result["json_valid"] = True
        result["schema_valid"] = matches_schema(result["parsed"], schema)
    except (ValueError, TypeError):
        result["errors"].append("INVALID_JSON")
    if not result["schema_valid"]:
        result["errors"].append("SCHEMA_MISMATCH")
    if finish_reason != "stop":
        result["errors"].append("TOKEN_TRUNCATED" if finish_reason == "length" else "UNEXPECTED_FINISH_REASON")
    if result["schema_valid"]:
        for key, value in result["parsed"].items():
            if not value.strip():
                result["errors"].append("EMPTY_" + key.upper())
            limit = schema["properties"][key].get("maxLength")
            if limit is not None and len(value) == limit:
                result["quality_flags"].append("REASON_LIMIT_HIT:" + key)
    result["protocol_valid"] = not result["errors"]
    return result
