"""Load versioned prompts for native Codex agents, not the frozen API runtime."""
from pathlib import Path
import argparse

VERSION = "molecular_chain_v1"
ROLES = ("explorer", "investigator", "critic")
PROMPT_ROOT = Path(__file__).resolve().parents[2] / "docs" / "agents" / VERSION


def load_prompt(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}; expected one of {ROLES}")
    root = PROMPT_ROOT.resolve()
    return (root / "COMMON.md").read_text(encoding="utf-8") + "\n\n" + (
        root / f"{role.upper()}.md"
    ).read_text(encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=ROLES)
    print(load_prompt(parser.parse_args().role))
