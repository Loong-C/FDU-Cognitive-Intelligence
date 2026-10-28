"""Fifteen hand-written semantic ASTs, plus hostile/invalid input and replay checks."""
import copy
import json

import httpx
import pytest
import z3

from ab_factcheck.common import ROOT
from ab_factcheck.symbolic_z3.logic import InvalidAST, compile_document, parse, solve
from ab_factcheck.symbolic_z3.schema import build_schema, load_schema
from ab_factcheck.symbolic_z3.experiment import digest, messages, selection, receive, process
from ab_factcheck.symbolic_z3.client import SymbolicClient
from ab_factcheck.groq_client import GroqStop
from ab_factcheck.worlds_v5.client import Halt


def c(name): return {"op": "const", "name": name}
def v(name): return {"op": "var", "name": name}
def n(value): return {"op": "int", "value": value}
def p(name, *args): return {"op": "pred", "name": name, "args": list(args)}
def f(name, *args): return {"op": "fun", "name": name, "args": list(args)}
def b(op, left, right): return {"op": op, "left": left, "right": right}
def neg(arg): return {"op": "not", "arg": arg}
def group(op, *args): return {"op": op, "args": list(args)}
def q(op, name, type_, body): return {"op": op, "variables": [{"name": name, "type": type_}], "body": body}


def doc(evidence, claim):
    return {"status": "OK", "symbols": {
        "constants": [{"name": name, "type": type_, "aliases": []} for name, type_ in
                      [("Alex", "Person"), ("Sam", "Person"), ("EventA", "Event"), ("Report", "Proposition")]],
        "predicates": [{"name": name, "arg_types": types} for name, types in
                       [("Won", ["Person", "Award", "Int"]), ("Regional", ["Award"]),
                        ("Member", ["Person"]), ("Denied", ["Person", "Proposition"]),
                        ("Alleged", ["Proposition"]), ("Happened", ["Proposition"]),
                        ("Office", ["Person", "Int"]), ("Visit", ["Person", "Int"])]],
        "functions": [{"name": name, "arg_types": types, "return_type": "Int"} for name, types in
                      [("Count", ["Event"]), ("Year", ["Event"]), ("Born", ["Person"])]]},
        "evidence": [{"source_quote": "source", "formula": e} for e in evidence],
        "claim": {"formula": claim}, "notes": []}


award_a = q("exists", "a", "Award", group("and", p("Regional", v("a")), p("Won", c("Alex"), v("a"), n(2021))))
award_b = q("exists", "b", "Award", group("and", p("Regional", v("b")), p("Won", c("Sam"), v("b"), n(2021))))
only_alex = q("forall", "x", "Person", b("implies", p("Member", v("x")), b("eq", v("x"), c("Alex"))))


CASES = [
    ("positive", doc([p("Member", c("Alex"))], p("Member", c("Alex"))), "SUPPORTS"),
    ("negative", doc([neg(p("Member", c("Alex")))], p("Member", c("Alex"))), "REFUTES"),
    ("independent_awards", doc([award_a], award_b), "NOT ENOUGH INFO"),
    ("unique", doc([p("Member", c("Alex")), only_alex, b("ne", c("Alex"), c("Sam"))], p("Member", c("Sam"))), "REFUTES"),
    ("open_list", doc([p("Member", c("Alex"))], p("Member", c("Sam"))), "NOT ENOUGH INFO"),
    ("closed_list", doc([only_alex], q("exists", "x", "Person", group("and", p("Member", v("x")), b("ne", v("x"), c("Alex"))))), "REFUTES"),
    ("count_boundary", doc([b("eq", f("Count", c("EventA")), n(124999))], b("eq", f("Count", c("EventA")), n(125000))), "REFUTES"),
    ("count_upper_bound", doc([b("le", f("Count", c("EventA")), n(125010))], b("gt", f("Count", c("EventA")), n(125010))), "REFUTES"),
    ("relative_date", doc([b("eq", f("Year", c("EventA")), b("add", b("add", n(2017), n(2)), n(4)))], b("eq", f("Year", c("EventA")), n(2023))), "SUPPORTS"),
    ("denial", doc([p("Denied", c("Alex"), c("Report"))], p("Happened", c("Report"))), "NOT ENOUGH INFO"),
    ("disproven_report", doc([p("Alleged", c("Report")), neg(p("Happened", c("Report")))], p("Happened", c("Report"))), "REFUTES"),
    ("first_event", doc([q("forall", "y", "Int", b("implies", p("Visit", c("Alex"), v("y")), b("ge", v("y"), n(2023))))], q("exists", "y", "Int", group("and", p("Visit", c("Alex"), v("y")), b("lt", v("y"), n(2023))))), "REFUTES"),
    ("interval", doc([q("forall", "y", "Int", b("implies", group("and", b("ge", v("y"), n(2023)), b("le", v("y"), n(2027))), p("Office", c("Alex"), v("y"))))], p("Office", c("Alex"), n(2026))), "SUPPORTS"),
    ("ambiguous_reference", doc([group("or", p("Member", c("Alex")), p("Member", c("Sam")))], p("Member", c("Alex"))), "NOT ENOUGH INFO"),
    ("inconsistent_evidence", doc([p("Member", c("Alex")), neg(p("Member", c("Alex")))], p("Member", c("Sam"))), "UNSUPPORTED"),
]


@pytest.mark.parametrize("name,ast,expected", CASES, ids=[c[0] for c in CASES])
def test_fifteen_semantic_asts(name, ast, expected):
    result = solve(ast, "source")
    assert result["label"] == expected, result
    if expected == "UNSUPPORTED":
        assert result["sat_e"] == "unsat" and result["sat_e_c"] is None
    else:
        assert result["sat_e"] == "sat"
        assert (result["sat_e_c"], result["sat_e_not_c"]) == {
            "SUPPORTS": ("sat", "unsat"), "REFUTES": ("unsat", "sat"),
            "NOT ENOUGH INFO": ("sat", "sat")}[expected]


@pytest.mark.parametrize("formula", [p("Missing", c("Alex")), p("Member", n(1)), p("Member"),
    p("Member", v("x")), b("eq", c("Alex"), c("EventA")), b("lt", c("Alex"), c("Sam")),
    b("eq", b("add", c("Alex"), n(1)), n(2)),
    q("exists", "x", "Person", q("forall", "x", "Person", p("Member", v("x")))),
    {"op": "python", "code": "print('not executed')"}, {"op": "int", "value": True}])
def test_type_scope_and_schema_rejection(formula):
    assert solve(doc([formula], p("Member", c("Alex"))), "source")["label"] == "UNSUPPORTED"


def test_quote_alias_unsupported_and_duplicate_keys():
    ast = doc([p("Member", c("Alex"))], p("Member", c("Sam")))
    assert solve(ast, "different text")["label"] == "UNSUPPORTED"
    ast["symbols"]["constants"][0]["aliases"] = ["Al"]
    ast["claim"]["formula"] = p("Member", c("Al"))
    assert solve(ast, "source")["label"] == "SUPPORTS"
    ast["symbols"]["constants"][1]["aliases"] = ["Al"]
    assert solve(ast, "source")["label"] == "UNSUPPORTED"
    with pytest.raises(InvalidAST): parse('{"status": "OK", "status": "UNSUPPORTED"}')
    with pytest.raises(InvalidAST): parse('{"x": NaN}')
    ast = {"status": "UNSUPPORTED", "symbols": {"constants": [], "predicates": [], "functions": []}, "evidence": [], "claim": None, "notes": ["outside DSL"]}
    assert solve(ast, "source")["reason"] == "formalizer_unsupported"
    ast["claim"] = {"formula": p("Member", c("Alex"))}
    assert solve(ast, "source")["reason"].startswith("InvalidAST")


def test_unknown_is_never_a_verdict():
    class UnknownSolver:
        def set(self, **kw): pass
        def add(self, *args): pass
        def check(self): return z3.unknown
        def reason_unknown(self): return "injected timeout"
    result = solve(CASES[0][1], "source", solver_factory=UnknownSolver)
    assert result["label"] == "UNSUPPORTED"
    assert result["unknown_reasons"] == {"sat_e": "injected timeout"}


@pytest.mark.parametrize("answers", [("sat", "unknown", "sat"), ("sat", "sat", "unknown"), ("sat", "unsat", "unsat")])
def test_unknown_or_abnormal_pair_is_unsupported(answers):
    class Solver:
        def __init__(self): self.answers = iter(answers)
        def set(self, **kw): pass
        def add(self, *args): pass
        def push(self): pass
        def pop(self): pass
        def check(self): return next(self.answers)
        def reason_unknown(self): return "injected timeout"
    result = solve(CASES[0][1], "source", solver_factory=Solver)
    assert result["label"] == "UNSUPPORTED" and result["reason"] == "solver_unknown_or_abnormal"


def test_quotes_are_provenance_only_and_resource_limits():
    ast = copy.deepcopy(CASES[0][1])
    compiled = compile_document(ast, "source plus another quote").constraints()
    ast["evidence"][0]["source_quote"] = "another quote"
    assert compile_document(ast, "source plus another quote").constraints() == compiled
    formula = p("Member", c("Alex"))
    for _ in range(70): formula = neg(formula)
    assert "resource limit" in solve(doc([formula], formula), "source")["reason"]


def test_all_scheduled_metrics_keep_unsupported_in_denominator():
    from ab_factcheck.worlds_v5.evaluation import metrics
    rows = [{"gold": "SUPPORTS", "V6": "SUPPORTS"}, {"gold": "REFUTES", "V6": "UNSUPPORTED"},
            {"gold": "NOT ENOUGH INFO", "V6": None}]
    result = metrics(rows, "V6")
    assert result["accuracy_all_scheduled"] == 1 / 3
    assert result["coverage"] == 1 / 3 and result["conditional_accuracy"] == 1
    assert result["classes"]["REFUTES"]["recall"] == 0


def test_schema_frozen_selection_and_input_isolation():
    assert build_schema() == load_schema()
    manifest, evaluation = selection()
    from collections import Counter
    assert len(manifest["rows"]) == 42
    assert set(Counter((r["dataset"], r["mechanism"]) for r in manifest["rows"]).values()) == {3}
    assert manifest == selection()[0]
    for r in manifest["rows"]:
        payload = messages(r["evidence"], r["claim"])
        assert r["id"] not in json.dumps(payload)
        assert payload[1]["content"] == (ROOT / "prompts/v6/user.txt").read_text(encoding="utf-8").format(
            evidence=r["evidence"], claim=r["claim"])
        assert set(payload[1]) == {"role", "content"}


def test_receive_once_resume_and_ambiguous_halt(tmp_path):
    config = json.loads((ROOT / "configs/experiment_symbolic_z3_v6.json").read_text())
    item = {"id": "x", "evidence": "source", "claim": "test", "input_sha256": digest("x")}
    class Fake:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return {"raw_response": json.dumps(CASES[0][1]), "provider_validation_issues": [], "finish_reason": "stop"}
    client = Fake()
    path = tmp_path / "one.json"
    first = receive(path, item, client, config)
    assert receive(path, item, client, config) == first and client.calls == 1
    assert process(first, "source")["label"] == "SUPPORTS"
    with pytest.raises(GroqStop): receive(path, {**item, "claim": "changed"}, client, config)
    class Ambiguous:
        last_attempts = []
        def complete(self, **kwargs): raise Halt("timeout", ambiguous=True)
    with pytest.raises(Halt): receive(tmp_path / "two.json", item, Ambiguous(), config)
    with pytest.raises(GroqStop): receive(tmp_path / "two.json", item, client, config)


def test_output_limit_and_strict_request(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-offline-key")
    config = json.loads((ROOT / "configs/experiment_symbolic_z3_v6.json").read_text())
    config["model"]["proxy_mode"] = "direct"
    def handler(request):
        payload = json.loads(request.content)
        assert payload["reasoning_effort"] == "none"
        assert payload["max_completion_tokens"] == 4096
        assert payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"model": "qwen/qwen3.8-27b", "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    client = SymbolicClient(config["model"], tmp_path / "quota.json", config["quota_policy"],
                            free_plan_confirmed=True, transport=httpx.MockTransport(handler))
    from ab_factcheck.symbolic_z3.schema import response_format
    try:
        result = client.complete(messages("source", "test"), response_format=response_format())
        assert result["usage"]["total_tokens"] == 12
    finally:
        client.close()
