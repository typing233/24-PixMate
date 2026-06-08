"""PixMate entry point: orchestrates all components."""

import asyncio
import sys
import signal

from .cli import parse_args
from .config import load_config, PixMateConfig
from .events import Event, EventType, Direction
from .event_parser import EventParser
from .event_log import EventLog
from .state_machine import StateMachine
from .terminal_detect import detect_terminal, ColorDepth
from .display.manager import choose_display, StandaloneDisplay
from .animation.renderer import Renderer
from .replay import ReplayPlayer
from .demo import DemoRunner
from .pty_proxy import PtyProxy


STATE_LABELS = {
    "idle": "Idle",
    "listening": "Listening...",
    "thinking": "Thinking...",
    "typing": "Writing...",
    "working": "Working...",
    "confused": "Error!",
    "celebrating": "Done!",
    "sleeping": "zzZ...",
}


async def run_demo(config: PixMateConfig, args) -> None:
    profile = detect_terminal()
    if args.ascii:
        profile.unicode = False
        profile.color_depth = ColorDepth.NONE

    display = StandaloneDisplay()
    display.setup(profile)

    sm = StateMachine()
    runner = DemoRunner(sm, display)

    try:
        await runner.run(loops=args.loops)
    finally:
        display.teardown()


async def run_replay(config: PixMateConfig, args) -> None:
    profile = detect_terminal()
    if args.ascii:
        profile.unicode = False
        profile.color_depth = ColorDepth.NONE

    display = StandaloneDisplay()
    display.setup(profile)

    sm = StateMachine()
    player = ReplayPlayer(sm, display)

    try:
        await player.play(args.replay, speed=args.speed)
    finally:
        display.teardown()


async def run_proxy(config: PixMateConfig, args) -> int:
    profile = detect_terminal()
    if args.ascii:
        profile.unicode = False
        profile.color_depth = ColorDepth.NONE

    display_mode = args.display if args.display != "auto" else config.display_mode
    if display_mode == "auto":
        display_mode = "tmux-split" if profile.in_tmux else "inline"

    display = choose_display(display_mode, profile)
    companion_width = display.companion_width

    display.setup(profile)

    sm = StateMachine()
    parser = EventParser(
        streaming_threshold=config.streaming_threshold,
        idle_timeout=config.idle_timeout,
    )

    event_log = None
    log_path = args.log or (config.log_path if config.log_events else "")
    if log_path:
        event_log = EventLog(log_path)

    # Animation loop state
    animation_task: asyncio.Task | None = None
    running = True

    async def animation_loop():
        while running:
            state = sm.current
            display.draw_frame(state.animation_key)

            timeout_state = sm.check_timeout()
            if timeout_state:
                label = STATE_LABELS.get(timeout_state.name, "")
                display.draw_label(label)

            fps = min(state.frame_rate, args.fps)
            await asyncio.sleep(1.0 / max(fps, 0.5))

    def on_data(data: bytes, direction: Direction) -> None:
        events = parser.feed(data, direction)
        for event in events:
            old_state = sm.current_name
            new_state = sm.process_event(event)
            if new_state:
                label = STATE_LABELS.get(new_state.name, "")
                display.draw_label(label)
                if event_log:
                    event_log.record(event, old_state, new_state.name)
            elif event_log:
                event_log.record(event, old_state, old_state)

    proxy = PtyProxy(companion_width=companion_width)

    animation_task = asyncio.create_task(animation_loop())

    try:
        exit_code = await proxy.run(args.command, on_data)
    finally:
        running = False
        if animation_task:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass
        display.teardown()
        if event_log:
            event_log.close()

    return exit_code


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    # Apply CLI overrides
    if args.width:
        config.companion_width = args.width
    if args.fps:
        config.max_fps = args.fps
    if args.ascii:
        config.ascii_only = True

    if args.demo:
        try:
            asyncio.run(run_demo(config, args))
        except KeyboardInterrupt:
            pass
        return

    if args.replay:
        try:
            asyncio.run(run_replay(config, args))
        except KeyboardInterrupt:
            pass
        return

    if not args.command:
        print("Usage: pixmate [OPTIONS] -- COMMAND...")
        print("       pixmate --demo")
        print("       pixmate --replay FILE")
        print("\nRun 'pixmate --help' for full options.")
        sys.exit(1)

    try:
        exit_code = asyncio.run(run_proxy(config, args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
