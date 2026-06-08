"""Tests for PixMate core components."""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pixmate.events import Event, EventType, Direction
from pixmate.state_machine import StateMachine
from pixmate.event_parser import EventParser
from pixmate.terminal_detect import detect_terminal, TerminalProfile, ColorDepth
from pixmate.animation.renderer import Renderer
from pixmate.animation.sprites import BUILTIN_SPRITES


def test_state_machine_basic():
    sm = StateMachine()
    assert sm.current_name == "idle"

    # User input -> listening
    result = sm.process_event(Event(EventType.USER_INPUT))
    assert result is not None
    assert sm.current_name == "listening"

    # Thinking start -> thinking
    result = sm.process_event(Event(EventType.THINKING_START))
    assert result is not None
    assert sm.current_name == "thinking"

    # Stream start -> typing
    result = sm.process_event(Event(EventType.STREAM_START))
    assert result is not None
    assert sm.current_name == "typing"

    # Tool start -> working
    result = sm.process_event(Event(EventType.TOOL_START))
    assert result is not None
    assert sm.current_name == "working"

    # Error -> confused
    result = sm.process_event(Event(EventType.ERROR))
    assert result is not None
    assert sm.current_name == "confused"

    # Success -> celebrating
    result = sm.process_event(Event(EventType.SUCCESS))
    assert result is not None
    assert sm.current_name == "celebrating"

    # Cancel -> idle
    result = sm.process_event(Event(EventType.CANCEL))
    assert result is not None
    assert sm.current_name == "idle"

    print("  [PASS] test_state_machine_basic")


def test_state_machine_timeout():
    sm = StateMachine()
    sm.force_state("celebrating")
    # Simulate time passing
    sm._entered_at = time.monotonic() - 10.0
    result = sm.check_timeout()
    assert result is not None
    assert sm.current_name == "idle"
    print("  [PASS] test_state_machine_timeout")


def test_event_parser_input():
    parser = EventParser()

    # Ctrl+C detection
    events = parser.feed(b"\x03", Direction.INPUT)
    assert any(e.type == EventType.CANCEL for e in events)

    # Regular input
    events = parser.feed(b"hello", Direction.INPUT)
    assert any(e.type == EventType.USER_INPUT for e in events)

    print("  [PASS] test_event_parser_input")


def test_event_parser_spinner():
    parser = EventParser()

    # Spinner character (thinking)
    events = parser.feed("⠋".encode(), Direction.OUTPUT)
    assert any(e.type == EventType.THINKING_START for e in events)

    print("  [PASS] test_event_parser_spinner")


def test_event_parser_tool_detection():
    parser = EventParser()

    # Tool block with box characters
    data = "╭─ Bash ─────────────────╮".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.TOOL_START for e in events)
    tool_events = [e for e in events if e.type == EventType.TOOL_START]
    assert tool_events[0].data.get("tool") == "Bash"

    print("  [PASS] test_event_parser_tool_detection")


def test_event_parser_error():
    parser = EventParser()

    data = "\x1b[31mError: file not found\x1b[0m".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.ERROR for e in events)

    print("  [PASS] test_event_parser_error")


def test_event_parser_success():
    parser = EventParser()

    data = "✓ Done".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.SUCCESS for e in events)

    print("  [PASS] test_event_parser_success")


def test_event_parser_permission():
    parser = EventParser()

    data = "Allow this action? [Y/n]".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.PERMISSION_PROMPT for e in events)

    print("  [PASS] test_event_parser_permission")


def test_renderer_truecolor():
    profile = TerminalProfile(
        color_depth=ColorDepth.TRUECOLOR,
        unicode=True,
        cols=80, rows=24,
    )
    renderer = Renderer(profile)

    for name in BUILTIN_SPRITES:
        frame = renderer.next_frame(name)
        assert len(frame) > 0
        assert "▀" in frame or "▄" in frame or " " in frame

    print("  [PASS] test_renderer_truecolor")


def test_renderer_ascii():
    profile = TerminalProfile(
        color_depth=ColorDepth.NONE,
        unicode=False,
        cols=80, rows=24,
    )
    renderer = Renderer(profile)

    frame = renderer.next_frame("idle")
    assert "o_o" in frame

    frame = renderer.next_frame("thinking")
    assert "o_O" in frame or "O_o" in frame

    print("  [PASS] test_renderer_ascii")


def test_renderer_256color():
    profile = TerminalProfile(
        color_depth=ColorDepth.COLORS_256,
        unicode=True,
        cols=80, rows=24,
    )
    renderer = Renderer(profile)

    frame = renderer.next_frame("idle")
    assert "\x1b[38;5;" in frame

    print("  [PASS] test_renderer_256color")


def test_sprites_valid():
    for name, sprite in BUILTIN_SPRITES.items():
        assert sprite.width == 12
        assert sprite.height == 12
        assert sprite.frame_count >= 2
        for frame in sprite.frames:
            assert len(frame) == 12
            for row in frame:
                assert len(row) == 12
                for pixel in row:
                    assert 0 <= pixel < len(sprite.palette)

    print("  [PASS] test_sprites_valid")


def test_ansi_stripping():
    parser = EventParser()
    result = parser.strip_ansi("\x1b[31mHello\x1b[0m World")
    assert result == "Hello World"

    result = parser.strip_ansi("\x1b]0;title\x07normal")
    assert result == "normal"

    print("  [PASS] test_ansi_stripping")


def test_terminal_detect():
    profile = detect_terminal()
    assert profile.cols > 0
    assert profile.rows > 0
    assert isinstance(profile.color_depth, ColorDepth)
    print("  [PASS] test_terminal_detect")


def run_all_tests():
    print("\n=== PixMate Test Suite ===\n")
    tests = [
        test_state_machine_basic,
        test_state_machine_timeout,
        test_event_parser_input,
        test_event_parser_spinner,
        test_event_parser_tool_detection,
        test_event_parser_error,
        test_event_parser_success,
        test_event_parser_permission,
        test_renderer_truecolor,
        test_renderer_ascii,
        test_renderer_256color,
        test_sprites_valid,
        test_ansi_stripping,
        test_terminal_detect,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*40}\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
