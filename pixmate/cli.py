"""CLI argument parsing for PixMate."""

import argparse
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pixmate",
        description="Terminal pixel art companion for Claude Code sessions",
        epilog="Examples:\n"
               "  pixmate -- claude            # Wrap Claude Code session\n"
               "  pixmate --demo               # Run demo mode\n"
               "  pixmate --replay events.jsonl # Replay logged session\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--demo", action="store_true",
        help="Run demo mode (simulated events, no real session)",
    )
    parser.add_argument(
        "--replay", metavar="PATH",
        help="Replay a logged event session",
    )
    parser.add_argument(
        "--display", choices=["tmux-split", "inline", "standalone", "auto"],
        default="auto",
        help="Display mode (default: auto)",
    )
    parser.add_argument(
        "--width", type=int, default=20,
        help="Companion panel width in columns (default: 20)",
    )
    parser.add_argument(
        "--log", metavar="PATH",
        help="Log events to file for replay",
    )
    parser.add_argument(
        "--config", metavar="PATH",
        help="Path to config file",
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="Force ASCII-only rendering",
    )
    parser.add_argument(
        "--fps", type=float, default=6.0,
        help="Max animation frame rate (default: 6)",
    )
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="Replay speed multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--loops", type=int, default=1,
        help="Number of demo loops (default: 1)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "command", nargs="*",
        help="Command to wrap (e.g., 'claude')",
    )

    args = parser.parse_args(argv)

    # Handle -- separator
    if "--" in (argv or sys.argv[1:]):
        raw = argv or sys.argv[1:]
        sep_idx = raw.index("--")
        pre = raw[:sep_idx]
        post = raw[sep_idx + 1:]
        args = parser.parse_args(pre)
        args.command = post

    return args
