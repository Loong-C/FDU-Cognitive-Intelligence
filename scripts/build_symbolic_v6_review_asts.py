"""Source-based reference ASTs authored by the reviewing assistant, not a human panel.

This script never loads gold labels, historical predictions, or model outputs.
Each case is explicitly authored from the frozen evidence/claim. These references
are diagnostic corrections, never replacements for received model ASTs.
"""
from itertools import combinations
import json

from ab_factcheck.common import ROOT, frozen_json
from ab_factcheck.symbolic_z3.experiment import EXPERIMENT
from ab_factcheck.symbolic_z3.logic import compile_document


def c(name): return {"op": "const", "name": name}
def v(name): return {"op": "var", "name": name}
def n(value): return {"op": "int", "value": value}
def p(name, *args): return {"op": "pred", "name": name, "args": list(args)}
def f(name, *args): return {"op": "fun", "name": name, "args": list(args)}
def b(op, left, right): return {"op": op, "left": left, "right": right}
def neg(arg): return {"op": "not", "arg": arg}
def conj(*args): return args[0] if len(args) == 1 else {"op": "and", "args": list(args)}
def disj(*args): return args[0] if len(args) == 1 else {"op": "or", "args": list(args)}
def q(op, variables, body):
    return {"op": op, "variables": [{"name": name, "type": type_} for name, type_ in variables], "body": body}


class Document:
    def __init__(self, row):
        self.row = row
        self.ast = {"status": "OK", "symbols": {"constants": [], "predicates": [], "functions": []},
                    "evidence": [], "claim": None, "notes": []}

    def constant(self, name, type_, *aliases):
        self.ast["symbols"]["constants"].append({"name": name, "type": type_, "aliases": list(aliases)})
        return c(name)

    def predicate(self, name, *types):
        self.ast["symbols"]["predicates"].append({"name": name, "arg_types": list(types)})

    def function(self, name, *types):
        self.ast["symbols"]["functions"].append({"name": name, "arg_types": list(types), "return_type": "Int"})

    def add(self, formula, quote=None):
        self.ast["evidence"].append({"source_quote": quote or self.row["evidence"], "formula": formula})

    def claim(self, formula):
        self.ast["claim"] = {"formula": formula}

    def note(self, text): self.ast["notes"].append(text)


def award(d, person, year, witness, kind="AwardKind"):
    return q("exists", [(witness, "Award")], conj(p(kind, v(witness)), p("Won", person, v(witness), n(year))))


def build(index, row):
    d = Document(row)
    if index in (0, 1, 2, 6, 7, 8, 18, 19, 20):
        names = {0: ("Donald", "Darnell"), 1: ("Donald", "Darnell"), 2: ("Bill", "Robert"),
                 6: ("KritiSanon", "KritiMalhotra"), 7: ("Kiran", "Sanjay"), 8: ("Kiran", "Sanjay"),
                 18: ("Xabi", "Elena"), 19: ("Vladimir", "Alexander"), 20: ("Vladimir", "Alexander")}[index]
        a, other = [d.constant(name, "Person") for name in names]
        d.predicate("Won", "Person", "Award", "Int")
        d.predicate("AwardKind", "Award")
        # No year is supplied in the two LOOKALIKE examples: existential year.
        year = {0: 2010, 1: 2010, 2: 1998, 18: 2012, 19: 1887, 20: 1887}.get(index)
        def won(person, witness):
            if year is not None: return award(d, person, year, witness)
            return q("exists", [(witness, "Award"), (witness + "Year", "Int")],
                     conj(p("AwardKind", v(witness)), p("Won", person, v(witness), v(witness + "Year"))))
        d.add(b("ne", a, other))
        d.add(won(a if index == 19 else other, "ea"))
        if index in (1, 7, 8): d.add(won(a, "eb"))
        if index == 18:
            d.predicate("WomensGermanAmateurChampionship2012", "Award")
            d.claim(award(d, a, 2012, "ca", "WomensGermanAmateurChampionship2012"))
            d.note("A regional tournament is not identified with the named championship in the claim.")
        else:
            d.claim(won(a, "ca"))
        d.note("Award witnesses are independent; the other person's success adds no negative fact about the claimant.")
    elif index in (3, 4, 5):
        speaker = d.constant("Speaker", "Person")
        proposition = d.constant("ReportedProposition", "Proposition")
        d.predicate("Holds", "Proposition")
        d.predicate("Reported", "Proposition")
        relation = "DeclinedComment" if index == 5 else "Denied"
        d.predicate(relation, "Person", "Proposition")
        quote = next(s.strip() for s in row["evidence"].split(". ") if ("denied" in s or "declined" in s))
        d.add(conj(p("Reported", proposition), p(relation, speaker, proposition)), quote)
        if index == 3: d.add(neg(p("Holds", proposition)), "an investigation later showed the reports to be false")
        d.claim(p("Holds", proposition))
        d.note("ReportedProposition denotes exactly the complete event description in the claim; attribution does not imply its truth value.")
    elif index in (9, 10, 11):
        person = d.constant("Jenna" if index != 10 else "Tim", "Person")
        d.predicate("AwardWin", "Person", "Event")
        d.function("Time", "Event")
        # Ordered integer ticks refine years without assuming previous = previous year.
        win = lambda e: p("AwardWin", person, e)
        during2023 = lambda e: conj(b("ge", f("Time", e), n(20230000)), b("lt", f("Time", e), n(20240000)))
        if index == 10:
            quote = "Tim Burton won the Academy Award for Best Animated Feature in 2023."
            d.add(q("exists", [("current", "Event")], conj(win(v("current")), during2023(v("current")))), quote)
        else:
            parts = [win(v("current")), during2023(v("current")), win(v("prior")),
                     b("lt", f("Time", v("prior")), f("Time", v("current")))]
            if index == 11:
                parts.append(q("forall", [("other", "Event")], b("implies",
                    conj(win(v("other")), b("lt", f("Time", v("other")), f("Time", v("current")))), b("eq", v("other"), v("prior")))))
            d.add(q("exists", [("current", "Event"), ("prior", "Event")], conj(*parts)))
            d.note("Earlier occasion may fall in the same calendar year. No source-based axiom forces a year before 2023; benchmark year-level presupposition is separately discussed.")
        d.claim(q("exists", [("claimEvent", "Event")], conj(win(v("claimEvent")), b("lt", f("Time", v("claimEvent")), n(20230000)))))
    elif index in (12, 13, 14):
        parent = d.constant("Charlie" if index == 13 else "Timothee", "Person")
        names = ["John", "Sam", "Mary"] if index == 13 else ["Pauline", "Alex", "Gabriel"]
        people = {name: d.constant(name, "Person") for name in names}
        relation = "Child" if index == 13 else "Sibling"
        d.predicate(relation, "Person", "Person")
        rel = lambda x: p(relation, parent, x)
        if index == 14:
            quote = "Timoth\u00e9e Chalamet has three siblings, including Pauline and Alex."
            a, b_ = people["Pauline"], people["Alex"]
            t = v("third")
            d.add(q("exists", [("third", "Person")], conj(rel(a), rel(b_), rel(t), b("ne", a, b_), b("ne", a, t), b("ne", b_, t),
                b("ne", parent, a), b("ne", parent, b_), b("ne", parent, t),
                q("forall", [("x", "Person")], b("implies", rel(v("x")), disj(b("eq", v("x"), a), b("eq", v("x"), b_), b("eq", v("x"), t)))))), quote)
        else:
            quote = row["evidence"] if index == 13 else "Chalamet's siblings include Pauline, Gabriel and Alex."
            d.add(conj(*[rel(x) for x in people.values()], *[b("ne", a, b_) for a, b_ in combinations([parent, *people.values()], 2)]), quote)
            if index == 13:
                d.add(q("forall", [("x", "Person")], b("implies", rel(v("x")), disj(*[b("eq", v("x"), x) for x in people.values()]))), quote)
        d.claim(rel(people["Sam" if index == 13 else "Gabriel"]))
    elif index in (15, 16, 17):
        person = d.constant("Jamie" if index == 17 else "Teddy", "Person")
        organization = d.constant("Leicester" if index == 17 else "TheSwims", "Organization")
        d.predicate("Serves", "Person", "Organization", "Int")
        role = lambda year: p("Serves", person, organization, year)
        if index == 15:
            d.add(role(n(2018)))
            d.note("Only the claim-relevant year occupancy is retained; still adds continuation within/before 2018, not service through 2020.")
        elif index == 16:
            d.predicate("Term", "Person", "Organization", "Event")
            d.function("Start", "Event")
            d.function("End", "Event")
            d.add(q("exists", [("first", "Event")], conj(p("Term", person, organization, v("first")),
                b("eq", f("Start", v("first")), n(2015)), b("eq", f("End", v("first")), n(2018)),
                q("forall", [("t", "Event")], b("implies", p("Term", person, organization, v("t")), b("ge", f("Start", v("t")), n(2015)))))))
            d.add(q("forall", [("year", "Int")], b("implies", conj(b("ge", v("year"), n(2015)), b("le", v("year"), n(2018))), role(v("year")))))
            d.note("Ending the first term does not rule out another term in 2020.")
        else:
            intervals = disj(conj(b("ge", v("year"), n(2023)), b("le", v("year"), n(2025))),
                             conj(b("ge", v("year"), n(2026)), b("le", v("year"), n(2027))))
            d.add(q("forall", [("year", "Int")], b("implies", intervals, role(v("year")))))
        d.claim(role(n(2026 if index == 17 else 2020)))
    elif index in (21, 22, 23):
        event = d.constant("Knebworth1996", "Event")
        d.function("Attendance", "Event")
        count = f("Attendance", event)
        d.add(b("ge", count, n(0)))
        d.add(conj(b("ge", count, n(124990)), b("le", count, n(125010))) if index == 21 else b("gt" if index == 22 else "le", count, n(125010)))
        d.claim(b("gt" if index == 22 else "eq", count, n(125010 if index == 22 else 125000)))
    elif index in (24, 25, 26, 30, 31, 32):
        person = d.constant("Keith" if index < 30 else "Romelu", "Person")
        relation = "LivedIn" if index in (24, 25) else "BornIn"
        d.predicate(relation, "Person", "Place")
        locations = {24: ["Portland", "Salem"], 25: ["Portland", "Salem"], 26: ["Seattle"],
                     30: ["Antwerp", "Belgium"], 31: ["Antwerp"], 32: ["Belgium", "Antwerp"]}[index]
        places = {name: d.constant(name, "Place") for name in locations}
        d.add(p(relation, person, places[locations[0]]))
        if index == 24: d.add(p(relation, person, places["Salem"]))
        if index == 30:
            d.predicate("LocatedIn", "Place", "Place")
            d.add(p("LocatedIn", places["Antwerp"], places["Belgium"]))
            d.add(p("BornIn", person, places["Belgium"]))
        d.claim(p(relation, person, places["Salem" if index in (24, 25) else "Seattle" if index == 26 else "Antwerp"]))
        d.note("Living locations are not single-valued. City and containing country are distinct levels of geographic description; country alone does not identify city.")
    elif index in (27, 28, 29):
        person = d.constant("Ahmed", "Person")
        award_ = d.constant("NobelPeace2025", "Award")
        d.predicate("Won", "Person", "Award")
        win = p("Won", person, award_)
        if index == 29:
            d.predicate("WidelyTipped", "Person", "Award")
            d.add(p("WidelyTipped", person, award_))
        else: d.add(win if index == 27 else neg(win))
        d.claim(win)
    elif index in (33, 34, 35):
        film = d.constant("WizardOfOz", "Film")
        d.function("ScheduledPremiereDate", "Film")
        d.function("ActualPremiereDate", "Film")
        d.add(b("eq", f("ScheduledPremiereDate", film), n(19390815 if index == 34 else 19390810)))
        if index == 35: d.add(b("gt", f("ActualPremiereDate", film), n(19390810)))
        else: d.add(b("eq", f("ActualPremiereDate", film), n(19390810 if index == 34 else 19390815)))
        d.claim(b("eq", f("ActualPremiereDate", film), n(19390810)))
        d.note("Dates use ordered YYYYMMDD integers. The described premiere is one event; scheduled and actual attributes remain separate.")
    elif index in (36, 37, 38):
        person = d.constant("Patrick", "Person")
        d.function("DraftYear", "Person")
        d.function("FirstSuperBowlYear", "Person")
        d.function("DescribedMVPReclaimYear", "Person")
        draft, bowl, mvp = (f(name, person) for name in ("DraftYear", "FirstSuperBowlYear", "DescribedMVPReclaimYear"))
        if index == 36:
            d.add(conj(b("eq", mvp, n(2023)), b("eq", bowl, b("sub", mvp, n(4))), b("eq", draft, b("sub", mvp, n(6)))))
        else:
            d.add(b("eq", draft, n(2017)), "In 2017, Patrick Mahomes was drafted by the Chiefs.")
            d.add(b("eq", bowl, b("add", draft, n(2))), "Two years later, he won his first Super Bowl.")
            d.add(b("gt", mvp, bowl))
            if index == 37: d.add(b("le", mvp, b("add", bowl, n(3))), "Within three years of that, he reclaimed the MVP award.")
        d.claim(b("eq", mvp, n(2023)))
        d.note("The claim refers to the described reclaim event, not a hypothetical additional reclaim. Prior MVP holding is background to reclaim and does not fix its year.")
    elif index in (39, 40, 41):
        person = d.constant("Sylvester", "Person")
        d.predicate("Achievement", "Person", "Event")
        d.function("Time", "Event")
        achievement = lambda e: p("Achievement", person, e)
        time = lambda e: f("Time", e)
        current2019 = lambda e: conj(b("ge", time(e), n(20190000)), b("lt", time(e), n(20200000)))
        if index in (39, 41):
            d.add(q("exists", [("only", "Event")], conj(achievement(v("only")), current2019(v("only")),
                q("forall", [("other", "Event")], b("implies", achievement(v("other")), b("eq", v("other"), v("only")))))))
        else:
            events = [v("first"), v("second"), v("third")]
            d.add(q("exists", [("first", "Event"), ("second", "Event"), ("third", "Event")], conj(
                *[achievement(e) for e in events], current2019(events[2]),
                b("lt", time(events[0]), time(events[1])), b("lt", time(events[1]), time(events[2])),
                q("forall", [("prior", "Event")], b("implies", conj(achievement(v("prior")), b("le", time(v("prior")), time(events[2]))),
                    disj(*[b("eq", v("prior"), e) for e in events]))))))
        if index == 39:
            d.claim(q("exists", [("priorClaim", "Event"), ("laterClaim", "Event")], conj(achievement(v("priorClaim")), achievement(v("laterClaim")),
                b("lt", time(v("priorClaim")), time(v("laterClaim"))), b("ge", time(v("laterClaim")), n(20200000)))))
        else:
            events = [v("c" + str(k)) for k in range(4)]
            d.claim(q("exists", [("c" + str(k), "Event") for k in range(4)], conj(
                *[conj(achievement(e), b("lt", time(e), n(20240000))) for e in events],
                *[b("ne", a, b_) for a, b_ in combinations(events, 2)],
                q("forall", [("by2023", "Event")], b("implies", conj(achievement(v("by2023")), b("lt", time(v("by2023")), n(20240000))),
                    disj(*[b("eq", v("by2023"), e) for e in events]))))))
        d.note("Achievement denotes the entire repeated six-decade achievement in both texts; events are counted, not bare year predicates. No later events are excluded by 'third time'.")
    else: raise ValueError(index)
    compile_document(d.ast, row["evidence"])
    return d.ast


def main():
    directory = ROOT / EXPERIMENT
    rows = json.loads((directory / "selection.json").read_text(encoding="utf-8"))["rows"]
    for index, row in enumerate(rows):
        frozen_json(directory / "reviewed_asts" / (row["id"] + ".json"), build(index, row))
    print("Saved 42 independently source-authored diagnostic ASTs; no gold or predictions loaded.")


if __name__ == "__main__": main()
