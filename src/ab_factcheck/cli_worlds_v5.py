"""Run python -m ab_factcheck.cli_worlds_v5 --help for reproducible v5 stages."""
import argparse
import json

from .common import ROOT, atomic_json, now
from .groq_client import GroqStop, exclusive, load_local_key
from .worlds_v5.client import WorldClient
from .worlds_v5.evaluation import report
from .worlds_v5.experiment import Experiment, load_config
from .worlds_v5.selection import freeze


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "probe", "smoke", "freeze", "run", "report"))
    parser.add_argument("--config", type=__import__("pathlib").Path, default=ROOT / "configs/experiment_worlds_v5.json")
    parser.add_argument("--phase", choices=("smoke", "fresh"), default="smoke")
    parser.add_argument("--env-local", action="store_true")
    parser.add_argument("--free-plan-confirmed", action="store_true")
    args = parser.parse_args(argv)
    client, exp = None, None
    try:
        config = load_config(args.config)
        if args.command == "freeze":
            m = freeze(ROOT, ROOT / config["manifest"])
            print(json.dumps({d: {k: v[k] for k in ("n", "group_count", "label_counts")} for d, v in m["datasets"].items()}))
            return 0
        phase = "fresh" if args.command == "run" else args.phase
        exp = Experiment(config, phase=phase)
        if args.command == "doctor":
            print(json.dumps({"model": config["model"]["model_id"], "prompt_hashes_verified": True,
                              "phase": phase, "network_requested": False}))
            return 0
        if args.command == "report":
            r = report(exp)
            print(json.dumps({k: r[k] for k in ("state", "planned_items", "v5_completed", "baseline_completed")}))
            return 0
        if args.command in ("probe", "smoke") and phase != "smoke":
            raise GroqStop("Technical and synthetic calls belong to the smoke phase")
        if args.env_local:
            load_local_key(ROOT)
        client = WorldClient(config["model"], ROOT / "outputs/groq/quota.json", free_plan_confirmed=args.free_plan_confirmed)
        exp.dag.client = client
        with exclusive(exp.directory / "run.lock"):
            exp.initialize()
            try:
                getattr(exp, args.command)()
            finally:
                report(exp)
        return 0
    except (GroqStop, ValueError, OSError, KeyError) as exc:
        safe = client.clean(str(exc)) if client else str(exc)
        if exp:
            atomic_json(exp.directory / "last_stop.json", {"time": now(), "type": type(exc).__name__, "reason": safe})
        print("STOP: " + safe, flush=True)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; inflight markers retained. Audit before resuming.")
        return 130
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
