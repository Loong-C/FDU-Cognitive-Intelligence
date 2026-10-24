"""Load the attachment verbatim; substitute template slots exactly once."""
import json
import re

from ..common import file_hash
from .models import Candidate, Problem

ROLES = ("generator_true", "generator_false", "verifier_true", "verifier_false")


class FrozenPrompts:
    def __init__(self, directory):
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        expected = {f"{role}_{part}.txt" for role in ROLES for part in ("system", "user")}
        if set(self.manifest["templates"]) != expected:
            raise ValueError("Unexpected v5 template manifest")
        self.templates = {}
        for name, digest in self.manifest["templates"].items():
            if file_hash(directory / name) != digest:
                raise ValueError("Frozen template hash mismatch: " + name)
            self.templates[name] = (directory / name).read_bytes().decode("utf-8")
        if file_hash(directory / "schemas.json") != self.manifest["schemas_sha256"]:
            raise ValueError("Frozen schema hash mismatch")
        self.schemas = json.loads((directory / "schemas.json").read_bytes())

    def schema(self, role):
        return self.schemas[self.manifest["schema_choice"][role]]

    def response_format(self, role):
        return {"type": "json_schema", "json_schema": {
            "name": "v5_" + role, "strict": True, "schema": self.schema(role)}}

    def render(self, role, problem: Problem, candidate: Candidate | None = None):
        if type(problem) is not Problem or role not in ROLES:
            raise TypeError("Only a metadata-free Problem and a known role are accepted")
        verifier = role.startswith("verifier_")
        if verifier != (type(candidate) is Candidate):
            raise TypeError("Only verifiers accept their own candidate")
        values = {"evidence": problem.evidence, "claim": problem.claim}
        if candidate is not None:
            values.update(target_condition=candidate.target_condition, candidate_world=candidate.candidate_world)
        template = self.templates[role + "_user.txt"]
        slots = re.findall(r"\{([a-z_]+)\}", template)
        if set(slots) != set(values) or len(slots) != len(values):
            raise ValueError("Unexpected placeholder contract")
        # re.sub does not revisit inserted text, including braces and backslashes.
        user = re.sub(r"\{([a-z_]+)\}", lambda m: values[m[1]], template)
        return [{"role": "system", "content": self.templates[role + "_system.txt"]},
                {"role": "user", "content": user}]
