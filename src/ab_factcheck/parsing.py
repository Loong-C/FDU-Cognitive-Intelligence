"""Strict final-answer parsing without correcting the model's answer."""

import re

VERDICT = re.compile(r"Verdict\s*:\s*(SUPPORTS|REFUTES|NOT\s+ENOUGH\s+INFO)\s*", re.I)
WORLD = re.compile(r"^CLAIM-(TRUE|FALSE)\s+WORLD\s*:\s*(POSSIBLE|IMPOSSIBLE)\s*$", re.I | re.M)


def world_label(true: str, false: str) -> str | None:
    return {("POSSIBLE", "IMPOSSIBLE"): "SUPPORTS", ("IMPOSSIBLE", "POSSIBLE"): "REFUTES",
            ("POSSIBLE", "POSSIBLE"): "NOT ENOUGH INFO"}.get((true, false))


def parse_response(text: str, arm: str, finish_reason: str | None) -> dict:
    result = {
        "predicted_label": None, "claim_true_world": None, "claim_false_world": None,
        "world_reason_true": None, "world_reason_false": None, "derived_label": None,
        "parse_status": "invalid", "consistency_status": "not_applicable" if arm == "A0" else "unavailable",
        "parse_error": None,
    }
    final_text = text.strip()
    if not final_text:
        result["parse_error"] = "empty_output"
        return result
    match = VERDICT.fullmatch(final_text.splitlines()[-1].strip())
    if match:
        result["predicted_label"] = " ".join(match[1].upper().split())
    if finish_reason != "stop":
        result["parse_error"] = "truncated" if finish_reason == "length" else "unexpected_finish_reason"
        return result
    if not match:
        result["parse_error"] = "missing_final_verdict"
        return result
    if arm != "A0":
        verdict_start = final_text.rfind(final_text.splitlines()[-1])
        body = final_text[:verdict_start]
        worlds = list(WORLD.finditer(body))
        if len(worlds) < 2 or [m[1].upper() for m in worlds[-2:]] != ["TRUE", "FALSE"]:
            result["parse_error"] = "missing_world_status"
            return result
        true_match, false_match = worlds[-2:]
        true, false = true_match[2].upper(), false_match[2].upper()
        result.update(claim_true_world=true, claim_false_world=false)
        for key, section in (
            ("world_reason_true", body[true_match.end():false_match.start()]),
            ("world_reason_false", body[false_match.end():]),
        ):
            reason = re.fullmatch(r"\s*Reason\s*:\s*(.+?)\s*", section, flags=re.I | re.S)
            if not reason:
                result["parse_error"] = "missing_world_reason"
                return result
            result[key] = reason[1].strip()
        result["derived_label"] = world_label(true, false)
        if result["derived_label"] is None:
            result.update(consistency_status="both_impossible", parse_error="both_impossible")
            return result
        result["consistency_status"] = "consistent" if result["derived_label"] == result["predicted_label"] else "inconsistent"
    result["parse_status"] = "ok"
    return result
