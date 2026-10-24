"""Two isolated construction interfaces; neither receives another node's output."""
from .models import Problem


class Constructor:
    def __init__(self, branch, prompts):
        if branch not in ("T", "F"):
            raise ValueError("Unknown branch")
        self.role = "generator_true" if branch == "T" else "generator_false"
        self.prompts = prompts

    def request(self, problem: Problem):
        return self.prompts.render(self.role, problem), self.prompts.response_format(self.role)
