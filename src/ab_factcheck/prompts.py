"""Frozen prompt templates. Dataset metadata is never accepted by the renderer."""

import json
import re

from .common import ARMS, ROOT, file_hash, sha256

EXAMPLE_EVIDENCE = "In a fictional greenhouse, Neris watered the silver fern on Monday."
EXAMPLE_CLAIM = "Neris watered the silver fern on Tuesday."


class PromptSet:
    def __init__(self, directory, arms=None):
        self.directory = directory
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.arms = tuple(manifest.get("arms", ARMS))
        if self.arms == ("A2", "B2", "C2"):
            from .structured import response_format_for
            if manifest.get("response_formats") != {arm: response_format_for(arm) for arm in self.arms}:
                raise ValueError("Frozen schemas differ from the implemented protocol")
        self.templates = {}
        self.hashes = {}
        for arm in self.arms:
            parts = {}
            for role in ("system", "user"):
                name = f"{arm}_{role}.txt"
                if file_hash(directory / name) != manifest["sha256"][name]:
                    raise ValueError(f"Frozen prompt changed: {name}")
                parts[role] = (directory / name).read_text(encoding="utf-8")
            self.templates[arm] = parts
            self.hashes[arm] = sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode())
        before, after = self.arms[1:]
        example_name = f"{after}_example.txt"
        example_path = directory / example_name
        if file_hash(example_path) != manifest["sha256"][example_name]:
            raise ValueError("Frozen example changed")
        example = example_path.read_text(encoding="utf-8")
        b1, c1 = self.templates[before], self.templates[after]
        expected = b1["user"].replace("EVIDENCE:\n{evidence}", example + "\nEVIDENCE:\n{evidence}", 1)
        if c1["system"] != b1["system"] or c1["user"] != expected:
            raise ValueError(f"{after} must differ from {before} only by the frozen example")
        for parts in self.templates.values():
            if parts["user"].count("{claim}") != 1 or parts["user"].count("{evidence}") != 1:
                raise ValueError("Prompt requires exactly one occurrence of each data placeholder")
        if arms is not None:
            if not arms or any(arm not in self.arms for arm in arms):
                raise ValueError("Requested arm absent from frozen prompt manifest")
            self.arms = tuple(arms)
            self.templates = {arm: self.templates[arm] for arm in self.arms}
            self.hashes = {arm: self.hashes[arm] for arm in self.arms}

    def render(self, arm: str, *, claim: str, evidence: str) -> list[dict]:
        values = {"claim": claim, "evidence": evidence}
        user = re.sub(r"\{(claim|evidence)\}", lambda match: values[match[1]], self.templates[arm]["user"])
        return [{"role": "system", "content": self.templates[arm]["system"]}, {"role": "user", "content": user}]

    def validate_example(self, rows: list[dict]) -> None:
        for row in rows:
            if row["evidence"].strip().casefold() == EXAMPLE_EVIDENCE.casefold() or row["claim"].strip().casefold() == EXAMPLE_CLAIM.casefold():
                raise ValueError(f"Illustrative example overlaps benchmark: {row['id']}")
