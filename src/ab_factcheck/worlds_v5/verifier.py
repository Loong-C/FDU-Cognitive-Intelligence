"""Branch-local independent verification, without classification or history."""
from .models import Candidate, Problem


class Verifier:
    def __init__(self, branch, prompts):
        if branch not in ("T", "F"):
            raise ValueError("Unknown branch")
        self.role = "verifier_true" if branch == "T" else "verifier_false"
        self.prompts = prompts

    def request(self, problem: Problem, candidate: Candidate):
        return self.prompts.render(self.role, problem, candidate), self.prompts.response_format(self.role)
