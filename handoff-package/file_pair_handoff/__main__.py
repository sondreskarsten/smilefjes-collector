from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract import verify_draft_release_assets, verify_local_pair


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="file-pair-handoff")
    commands = parser.add_subparsers(dest="command", required=True)

    local = commands.add_parser("verify-local")
    local.add_argument("--data", required=True)
    local.add_argument("--metadata", required=True)

    release = commands.add_parser("verify-draft-release")
    release.add_argument("--release-json", required=True)
    release.add_argument("--data", required=True)
    release.add_argument("--metadata", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "verify-local":
        pair = verify_local_pair(args.data, args.metadata)
        value = {role: fact.as_dict() for role, fact in pair.items()}
    else:
        release = json.loads(Path(args.release_json).read_text(encoding="utf-8"))
        selected = verify_draft_release_assets(release, args.data, args.metadata)
        value = {
            role: {"name": asset["name"], "size": asset["size"]}
            for role, asset in selected.items()
        }
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
