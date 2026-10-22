"""Small explicit JSON schemas and deterministic v2 classification; no answer repair."""

import json

from .common import LABELS, STRUCTURED_ARMS
from .parsing import world_label

STATES = ("POSSIBLE", "IMPOSSIBLE")


def schema_for(arm: str) -> dict:
    if arm not in STRUCTURED_ARMS:
        raise ValueError(f"Not a structured arm: {arm}")
    properties = ({"verdict": {"type": "string", "enum": list(LABELS)}, "reason": {"type": "string"}}
                  if arm == "A2" else {
                      "true_world": {"type": "string", "enum": list(STATES)},
                      "false_world": {"type": "string", "enum": list(STATES)},
                      "true_reason": {"type": "string"}, "false_reason": {"type": "string"}})
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def response_format_for(arm: str) -> dict:
    # b11669 server-common.cpp reads json_schema.schema, despite README's
    # top-level schema example. A real adversarial probe guards this contract.
    return {"type": "json_schema", "json_schema": {
        "name": "direct_classification" if arm == "A2" else "world_classification",
        "strict": True, "schema": schema_for(arm)}}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text):
    def invalid_constant(value):
        raise ValueError(f"Non-JSON constant: {value}")
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def matches_schema(value, schema):
    return (isinstance(value, dict) and set(value) == set(schema["required"])
            and all(isinstance(value[key], str) and ("enum" not in spec or value[key] in spec["enum"])
                    for key, spec in schema["properties"].items()))


def parse_structured(text: str, arm: str, finish_reason: str | None) -> dict:
    schema = schema_for(arm)
    result = {"output_protocol": "json_schema_v2", "predicted_label": None, "derived_label": None,
              "claim_true_world": None, "claim_false_world": None, "world_reason_true": None,
              "world_reason_false": None, "direct_reason": None, "parsed_object": None,
              "json_valid": False, "fields_valid": False, "protocol_valid": False,
              "logic_valid": None, "truncated": finish_reason == "length",
              "parse_status": "invalid", "parse_error": None, "reason_quality_flags": [],
              "reason_quality_status": "not_assessed", "consistency_status": "unavailable"}
    try:
        value = strict_json(text)
        result["json_valid"] = True
        result["parsed_object"] = value
    except (ValueError, TypeError):
        value = None
    result["fields_valid"] = result["json_valid"] and matches_schema(value, schema)
    if finish_reason != "stop":
        result["parse_error"] = "truncated" if finish_reason == "length" else "unexpected_finish_reason"
        return result
    if not result["json_valid"]:
        result["parse_error"] = "empty_output" if not text.strip() else "invalid_json"
        return result
    if not result["fields_valid"]:
        result["parse_error"] = "invalid_fields"
        return result
    result["protocol_valid"] = True
    reasons = ["reason"] if arm == "A2" else ["true_reason", "false_reason"]
    result["reason_quality_flags"] = [f"empty_{key}" for key in reasons if not value[key].strip()]
    result["reason_quality_status"] = "empty_reason" if result["reason_quality_flags"] else "requires_human_review"
    if arm == "A2":
        result.update(predicted_label=value["verdict"], direct_reason=value["reason"], consistency_status="not_applicable")
    else:
        label = world_label(value["true_world"], value["false_world"])
        result.update(claim_true_world=value["true_world"], claim_false_world=value["false_world"],
                      world_reason_true=value["true_reason"], world_reason_false=value["false_reason"],
                      derived_label=label if label is not None else "INVALID_LOGIC", logic_valid=label is not None)
        if label is None:
            result.update(parse_error="INVALID_LOGIC", consistency_status="both_impossible")
            return result
        result.update(predicted_label=label, consistency_status="derived_from_worlds")
    result["parse_status"] = "ok"
    return result
