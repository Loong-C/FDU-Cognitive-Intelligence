"""Frozen prompt templates. Dataset metadata is never accepted by the renderer."""

import json
import re

from .common import ARMS, ROOT, file_hash, sha256

EXAMPLE_EVIDENCE = "In a fictional greenhouse, Neris watered the silver fern on Monday."
EXAMPLE_CLAIM = "Neris watered the silver fern on Tuesday."


class PromptSet:
    def __init__(self, directory):
        self.directory = directory
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.templates = {}
        self.hashes = {}
        for arm in ARMS:
            parts = {}
            for role in ("system", "user"):
                name = f"{arm}_{role}.txt"
                if file_hash(directory / name) != manifest["sha256"][name]:
                    raise ValueError(f"Frozen prompt changed: {name}")
                parts[role] = (directory / name).read_text(encoding="utf-8")
            self.templates[arm] = parts
            self.hashes[arm] = sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode())
        example_path = directory / "C1_example.txt"
        if file_hash(example_path) != manifest["sha256"]["C1_example.txt"]:
            raise ValueError("Frozen example changed")
        example = example_path.read_text(encoding="utf-8")
        b1, c1 = self.templates["B1"], self.templates["C1"]
        expected = b1["user"].replace("EVIDENCE:\n{evidence}", example + "\nEVIDENCE:\n{evidence}", 1)
        if c1["system"] != b1["system"] or c1["user"] != expected:
            raise ValueError("C1 must differ from B1 only by the frozen example")
        for parts in self.templates.values():
            if parts["user"].count("{claim}") != 1 or parts["user"].count("{evidence}") != 1:
                raise ValueError("Prompt requires exactly one occurrence of each data placeholder")

    def render(self, arm: str, *, claim: str, evidence: str) -> list[dict]:
        values = {"claim": claim, "evidence": evidence}
        user = re.sub(r"\{(claim|evidence)\}", lambda match: values[match[1]], self.templates[arm]["user"])
        return [{"role": "system", "content": self.templates[arm]["system"]}, {"role": "user", "content": user}]

    def validate_example(self, rows: list[dict]) -> None:
        for row in rows:
            if row["evidence"].strip().casefold() == EXAMPLE_EVIDENCE.casefold() or row["claim"].strip().casefold() == EXAMPLE_CLAIM.casefold():
                raise ValueError(f"Illustrative example overlaps benchmark: {row['id']}")
