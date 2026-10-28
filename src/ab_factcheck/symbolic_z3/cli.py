"""Run with python -m ab_factcheck.symbolic_z3.cli."""
import argparse
import json
from pathlib import Path

from ..common import ROOT, atomic_json
from ..groq_client import GroqStop
from .experiment import EXPERIMENT, execute, freeze, process, verify_freeze
from .logic import compile_document, parse, solve


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frozen v6: extract -> validate -> compile -> solve -> report")
    parser.add_argument("stage", choices=("freeze", "probe", "extract", "validate", "compile", "solve", "report"))
    parser.add_argument("--ast", type=Path)
    parser.add_argument("--evidence", type=Path, help="UTF-8 file containing original evidence")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    try:
        if args.stage == "freeze":
            result = {"selected": len(freeze()["rows"])}
        elif args.stage in ("probe", "extract"):
            execute(probe=args.stage == "probe", limit=args.limit)
            return
        elif args.stage == "report":
            from .report import report
            result = report()
        elif args.ast:
            if args.evidence is None:
                parser.error("--evidence is required with --ast")
            ast = parse(args.ast.read_text(encoding="utf-8"))
            evidence = args.evidence.read_text(encoding="utf-8")
            if args.stage == "solve":
                result = solve(ast, evidence)
            else:
                compiled = compile_document(ast, evidence)
                result = {"valid": True, "status": ast["status"]}
                if args.stage == "compile":
                    result["constraints"] = compiled.constraints() if compiled else None
        else:
            manifest = verify_freeze()
            results = []
            for item in manifest["rows"]:
                path = ROOT / EXPERIMENT / "records" / (item["id"] + ".json")
                if path.exists():
                    result = process(json.loads(path.read_text(encoding="utf-8")), item["evidence"])
                    atomic_json(ROOT / EXPERIMENT / "solved" / (item["id"] + ".json"), result)
                    results.append({"id": item["id"], "label": result["label"], "reason": result.get("reason")})
            result = {"stage": args.stage, "records": results}
        if args.output:
            atomic_json(args.output, result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (GroqStop, ValueError) as exc:
        print("STOP: " + str(exc))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
