"""The gateway's one event shape, shared by every provider adapter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    type: str
    """token | tool_call | usage | done | error"""
    text: str = ""
    id: str | None = None
    name: str | None = None
    args: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None
    """US$; None = the provider did not say (the client prices it from config.yaml)."""
    kind: str | None = None
    """error kind: key_required | spend_cap | price_unknown | invalid | quota | provider | bad_output"""

    def as_dict(self) -> dict:
        d: dict = {"type": self.type}
        if self.type == "token":
            d["text"] = self.text
        elif self.type == "tool_call":
            d.update(id=self.id, name=self.name, args=self.args)
        elif self.type == "usage":
            d.update(prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens, cost=self.cost)
        elif self.type == "error":
            d.update(kind=self.kind, text=self.text)
        return d
