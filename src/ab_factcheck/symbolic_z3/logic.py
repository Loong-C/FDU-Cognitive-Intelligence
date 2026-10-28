"""Type check and compile AST data, never model-supplied code or source prose."""
from dataclasses import dataclass
import json
import time

from jsonschema import Draft202012Validator
import z3

from .schema import load_schema


class InvalidAST(ValueError):
    pass


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidAST("duplicate JSON key")
            result[key] = value
        return result
    if not isinstance(raw, str) or len(raw) > 200000:
        raise InvalidAST("invalid JSON size/type")
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(InvalidAST("nonfinite JSON")))
    except (ValueError, RecursionError) as exc:
        raise InvalidAST("invalid JSON: " + type(exc).__name__) from None


def validate(document, evidence_text, schema=None):
    # Bound recursive input before a recursive schema validator/compiler sees it.
    stack, nodes = [(document, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > 12000 or depth > 64:
            raise InvalidAST("AST resource limit")
        if isinstance(value, dict):
            stack.extend((x, depth + 1) for x in value.values())
        elif isinstance(value, list):
            stack.extend((x, depth + 1) for x in value)
    error = next(Draft202012Validator(schema or load_schema()).iter_errors(document), None)
    if error:
        raise InvalidAST("schema violation at " + "/".join(map(str, error.absolute_path)))
    if document["status"] == "UNSUPPORTED":
        if document["evidence"] or document["claim"] is not None or any(document["symbols"].values()):
            raise InvalidAST("UNSUPPORTED requires empty symbols/evidence and null claim")
        return
    if not document["evidence"] or document["claim"] is None:
        raise InvalidAST("OK requires evidence and claim")
    for entry in document["evidence"]:
        if not entry["source_quote"].strip() or entry["source_quote"] not in evidence_text:
            raise InvalidAST("source_quote is not an exact contiguous evidence substring")


@dataclass
class Compiled:
    evidence: list
    claim: object

    def constraints(self):
        return {"evidence": [x.sexpr() for x in self.evidence], "claim": self.claim.sexpr()}


class Compiler:
    def __init__(self, symbols):
        self.sorts = {"Int": z3.IntSort()}
        self.constants, self.aliases, self.predicates, self.functions = {}, {}, {}, {}
        declared = set()
        for kind in ("constants", "predicates", "functions"):
            for declaration in symbols[kind]:
                name = declaration["name"]
                if name in declared:
                    raise InvalidAST("duplicate symbol: " + name)
                declared.add(name)
        for decl in symbols["constants"]:
            name, type_ = decl["name"], decl["type"]
            if type_ == "Int":
                raise InvalidAST("use integer literals or integer attributes, not Int entity constants")
            self.constants[name] = (z3.Const("entity_" + name, self.sort(type_)), type_)
            for alias in decl["aliases"]:
                if not alias.strip() or alias in self.aliases or alias in declared:
                    raise InvalidAST("ambiguous or colliding alias")
                self.aliases[alias] = name
        for kind, table in (("predicates", self.predicates), ("functions", self.functions)):
            for decl in symbols[kind]:
                result = "Bool" if kind == "predicates" else decl["return_type"]
                return_sort = z3.BoolSort() if result == "Bool" else self.sort(result)
                table[decl["name"]] = (z3.Function(kind + "_" + decl["name"],
                    *[self.sort(t) for t in decl["arg_types"]], return_sort), decl["arg_types"], result)

    def sort(self, name):
        if name == "Bool":
            raise InvalidAST("Bool is reserved; propositions are entities, not truth values")
        if name not in self.sorts:
            self.sorts[name] = z3.DeclareSort("type_" + name)
        return self.sorts[name]

    def application(self, node, table, env):
        if node["name"] not in table:
            raise InvalidAST("undeclared symbol: " + node["name"])
        function, arg_types, return_type = table[node["name"]]
        args = [self.term(x, env) for x in node["args"]]
        if [t for _, t in args] != arg_types:
            raise InvalidAST("argument type/arity mismatch: " + node["name"])
        return function(*[value for value, _ in args]), return_type

    def term(self, node, env):
        op = node["op"]
        if op == "int":
            if type(node["value"]) is not int:
                raise InvalidAST("integer literal required")
            return z3.IntVal(node["value"]), "Int"
        if op == "const":
            name = self.aliases.get(node["name"], node["name"])
            if name not in self.constants:
                raise InvalidAST("undeclared constant")
            return self.constants[name]
        if op == "var":
            if node["name"] not in env:
                raise InvalidAST("unbound variable")
            return env[node["name"]]
        if op == "fun":
            return self.application(node, self.functions, env)
        left, lt = self.term(node["left"], env)
        right, rt = self.term(node["right"], env)
        if lt != "Int" or rt != "Int":
            raise InvalidAST("arithmetic requires integers")
        return (left + right if op == "add" else left - right), "Int"

    def formula(self, node, env=None):
        env = {} if env is None else env
        op = node["op"]
        if op == "pred":
            return self.application(node, self.predicates, env)[0]
        if op == "not":
            return z3.Not(self.formula(node["arg"], env))
        if op in ("and", "or"):
            return (z3.And if op == "and" else z3.Or)(*[self.formula(x, env) for x in node["args"]])
        if op == "implies":
            return z3.Implies(self.formula(node["left"], env), self.formula(node["right"], env))
        if op in ("exists", "forall"):
            scope, variables = dict(env), []
            for decl in node["variables"]:
                name, type_ = decl["name"], decl["type"]
                if name in scope:
                    raise InvalidAST("duplicate/shadowed bound variable")
                variable = z3.Const("bound_" + name, self.sort(type_))
                scope[name] = (variable, type_)
                variables.append(variable)
            return (z3.Exists if op == "exists" else z3.ForAll)(variables, self.formula(node["body"], scope))
        left, lt = self.term(node["left"], env)
        right, rt = self.term(node["right"], env)
        if lt != rt or (op not in ("eq", "ne") and lt != "Int"):
            raise InvalidAST("comparison type mismatch")
        return {"eq": lambda: left == right, "ne": lambda: left != right,
                "lt": lambda: left < right, "le": lambda: left <= right,
                "gt": lambda: left > right, "ge": lambda: left >= right}[op]()


def compile_document(document, evidence_text, schema=None):
    validate(document, evidence_text, schema)
    if document["status"] == "UNSUPPORTED":
        return None
    compiler = Compiler(document["symbols"])
    return Compiled([compiler.formula(x["formula"]) for x in document["evidence"]],
                    compiler.formula(document["claim"]["formula"]))


def solve(document, evidence_text, *, timeout_ms=3000, solver_factory=z3.Solver):
    started = time.perf_counter()
    result = {"label": "UNSUPPORTED", "sat_e": None, "sat_e_c": None, "sat_e_not_c": None,
              "reason": None, "unknown_reasons": {}, "constraints": None,
              "z3_version": z3.get_version_string()}
    try:
        compiled = compile_document(document, evidence_text)
        if compiled is None:
            result["reason"] = "formalizer_unsupported"
        else:
            result["constraints"] = compiled.constraints()
            solver = solver_factory()
            solver.set(timeout=timeout_ms, random_seed=42)
            solver.add(*compiled.evidence)

            def check(key):
                answer = str(solver.check())
                result[key] = answer
                if answer == "unknown":
                    result["unknown_reasons"][key] = solver.reason_unknown()
                return answer

            if check("sat_e") != "sat":
                result["reason"] = "inconsistent_evidence" if result["sat_e"] == "unsat" else "solver_unknown_or_abnormal"
            else:
                for key, formula in (("sat_e_c", compiled.claim), ("sat_e_not_c", z3.Not(compiled.claim))):
                    solver.push()
                    solver.add(formula)
                    check(key)
                    solver.pop()
                pair = (result["sat_e_c"], result["sat_e_not_c"])
                result["label"] = {("sat", "unsat"): "SUPPORTS", ("unsat", "sat"): "REFUTES",
                                   ("sat", "sat"): "NOT ENOUGH INFO"}.get(pair, "UNSUPPORTED")
                if result["label"] == "UNSUPPORTED":
                    result["reason"] = "solver_unknown_or_abnormal"
    except (InvalidAST, z3.Z3Exception, RecursionError) as exc:
        result["reason"] = type(exc).__name__ + ": " + str(exc)
    result["solve_seconds"] = time.perf_counter() - started
    return result
