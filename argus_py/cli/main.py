"""CLI entry point for Argus."""

import argparse
import sys

from argus_py.core.constants import PROJECT_NAME, PROJECT_VERSION


def main():
    parser = argparse.ArgumentParser(
        prog=PROJECT_NAME,
        description="AI Native Test Platform",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROJECT_NAME} {PROJECT_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a blackbox test task")
    run_parser.add_argument("--goal", required=True, help="Test goal in natural language")
    run_parser.add_argument("--url", required=True, help="Starting URL")
    run_parser.add_argument("--max-steps", type=int, default=20, help="Max action steps")
    run_parser.add_argument("--timeout", type=int, default=300, help="Task timeout in seconds")

    args = parser.parse_args()

    if args.command == "run":
        print(f"[TODO] Running task: goal='{args.goal}', url='{args.url}'")
        print("T005-T007 not yet implemented")
        sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
