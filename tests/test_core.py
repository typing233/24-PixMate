"""Tests for PixMate core components."""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pixmate.events import Event, EventType, EventSource, Direction
from pixmate.state_machine import StateMachine
from pixmate.event_parser import EventParser
from pixmate.terminal_detect import detect_terminal, TerminalProfile, ColorDepth
from pixmate.animation.renderer import Renderer
from pixmate.animation.sprites import BUILTIN_SPRITES
from pixmate.claude_log_reader import parse_log_entry


def test_state_machine_basic():
    sm = StateMachine()
    assert sm.current_name == "idle"

    result = sm.process_event(Event(EventType.USER_INPUT))
    assert result is not None
    assert sm.current_name == "listening"

    result = sm.process_event(Event(EventType.THINKING_START))
    assert result is not None
    assert sm.current_name == "thinking"

    result = sm.process_event(Event(EventType.STREAM_START))
    assert result is not None
    assert sm.current_name == "typing"

    result = sm.process_event(Event(EventType.TOOL_START))
    assert result is not None
    assert sm.current_name == "working"

    result = sm.process_event(Event(EventType.ERROR))
    assert result is not None
    assert sm.current_name == "confused"

    result = sm.process_event(Event(EventType.SUCCESS))
    assert result is not None
    assert sm.current_name == "celebrating"

    result = sm.process_event(Event(EventType.CANCEL))
    assert result is not None
    assert sm.current_name == "idle"

    print("  [PASS] test_state_machine_basic")


def test_state_machine_retry():
    sm = StateMachine()
    sm.force_state("confused")
    result = sm.process_event(Event(EventType.RETRY))
    assert result is not None
    assert sm.current_name == "thinking"
    print("  [PASS] test_state_machine_retry")


def test_state_machine_permission_response():
    sm = StateMachine()
    sm.force_state("listening")
    result = sm.process_event(Event(EventType.PERMISSION_RESPONSE, data={"accepted": True}))
    assert result is not None
    assert sm.current_name == "working"
    print("  [PASS] test_state_machine_permission_response")


def test_state_machine_concurrent_task():
    sm = StateMachine()
    sm.force_state("idle")
    result = sm.process_event(Event(EventType.CONCURRENT_TASK))
    assert result is not None
    assert sm.current_name == "working"
    print("  [PASS] test_state_machine_concurrent_task")


def test_state_machine_timeout():
    sm = StateMachine()
    sm.force_state("celebrating")
    sm._entered_at = time.monotonic() - 10.0
    result = sm.check_timeout()
    assert result is not None
    assert sm.current_name == "idle"
    print("  [PASS] test_state_machine_timeout")


def test_event_parser_input():
    parser = EventParser()

    events = parser.feed(b"\x03", Direction.INPUT)
    assert any(e.type == EventType.CANCEL for e in events)

    events = parser.feed(b"hello", Direction.INPUT)
    assert any(e.type == EventType.USER_INPUT for e in events)

    print("  [PASS] test_event_parser_input")


def test_event_parser_spinner():
    parser = EventParser()

    events = parser.feed("⠋".encode(), Direction.OUTPUT)
    assert any(e.type == EventType.THINKING_START for e in events)

    print("  [PASS] test_event_parser_spinner")


def test_event_parser_tool_detection():
    parser = EventParser()

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


def test_event_parser_permission_response():
    parser = EventParser()

    # First trigger a permission prompt to set state
    parser.feed("Allow this? [Y/n]".encode(), Direction.OUTPUT)
    assert parser._awaiting_permission

    # User responds with 'y'
    events = parser.feed(b"y", Direction.INPUT)
    assert any(e.type == EventType.PERMISSION_RESPONSE for e in events)
    resp = [e for e in events if e.type == EventType.PERMISSION_RESPONSE][0]
    assert resp.data["accepted"] is True
    assert not parser._awaiting_permission

    print("  [PASS] test_event_parser_permission_response")


def test_event_parser_retry():
    parser = EventParser()

    data = "Retrying request (attempt 2)...".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.RETRY for e in events)

    print("  [PASS] test_event_parser_retry")


def test_event_parser_concurrent_task():
    parser = EventParser()

    data = "╭─ Background task-1 ───╮".encode()
    events = parser.feed(data, Direction.OUTPUT)
    assert any(e.type == EventType.CONCURRENT_TASK for e in events)

    print("  [PASS] test_event_parser_concurrent_task")


def test_event_parser_check_idle():
    parser = EventParser(idle_timeout=0.1)

    # Feed some data
    parser.feed(b"hello", Direction.OUTPUT)
    # Immediately check — should not be idle
    events = parser.check_idle()
    assert not any(e.type == EventType.IDLE for e in events)

    # Wait past idle timeout
    time.sleep(0.15)
    events = parser.check_idle()
    assert any(e.type == EventType.IDLE for e in events)

    print("  [PASS] test_event_parser_check_idle")


def test_event_parser_stream_end_on_silence():
    parser = EventParser(idle_timeout=5.0, streaming_threshold=10.0)

    # Simulate rapid output to trigger streaming
    for _ in range(5):
        parser.feed(b"x" * 100, Direction.OUTPUT)
        time.sleep(0.01)

    assert parser._is_streaming

    # Wait 1.1s for stream-end detection
    parser._last_data_time = time.monotonic() - 1.1
    events = parser.check_idle()
    assert any(e.type == EventType.STREAM_END for e in events)
    assert not parser._is_streaming

    print("  [PASS] test_event_parser_stream_end_on_silence")


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


def test_claude_log_parser_tool_use():
    entry = {
        "type": "assistant",
        "role": "assistant",
        "content": [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ],
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.THINKING_START for e in events)
    assert any(e.type == EventType.TOOL_START and e.data.get("tool") == "Bash" for e in events)
    assert all(e.source == EventSource.CLAUDE_LOG for e in events)
    print("  [PASS] test_claude_log_parser_tool_use")


def test_claude_log_parser_user_message():
    entry = {"type": "human", "role": "user", "content": "Fix the bug"}
    events = parse_log_entry(entry)
    assert any(e.type == EventType.USER_INPUT for e in events)
    assert events[0].data["text"] == "Fix the bug"
    print("  [PASS] test_claude_log_parser_user_message")


def test_claude_log_parser_tool_result_error():
    entry = {
        "type": "tool_result",
        "role": "tool",
        "name": "Bash",
        "is_error": True,
        "content": "command not found",
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.ERROR for e in events)
    print("  [PASS] test_claude_log_parser_tool_result_error")


def test_claude_log_parser_permission():
    entry = {"type": "permission_request", "tool": "Bash"}
    events = parse_log_entry(entry)
    assert any(e.type == EventType.PERMISSION_PROMPT for e in events)

    entry = {"type": "permission_response", "accepted": True}
    events = parse_log_entry(entry)
    assert any(e.type == EventType.PERMISSION_RESPONSE for e in events)
    assert events[0].data["accepted"] is True
    print("  [PASS] test_claude_log_parser_permission")


def test_claude_log_parser_retry():
    entry = {"type": "retry", "error": "rate_limit"}
    events = parse_log_entry(entry)
    assert any(e.type == EventType.RETRY for e in events)
    print("  [PASS] test_claude_log_parser_retry")


def test_event_source_field():
    e = Event(EventType.TOOL_START, source=EventSource.CLAUDE_LOG, data={"tool": "Read"})
    assert e.source == EventSource.CLAUDE_LOG
    assert "claude_log" in repr(e)

    e2 = Event(EventType.IDLE, source=EventSource.INTERNAL)
    assert e2.source == EventSource.INTERNAL
    print("  [PASS] test_event_source_field")


def run_all_tests():
    print("\n=== PixMate Test Suite ===\n")
    tests = [
        test_state_machine_basic,
        test_state_machine_retry,
        test_state_machine_permission_response,
        test_state_machine_concurrent_task,
        test_state_machine_timeout,
        test_event_parser_input,
        test_event_parser_spinner,
        test_event_parser_tool_detection,
        test_event_parser_error,
        test_event_parser_success,
        test_event_parser_permission,
        test_event_parser_permission_response,
        test_event_parser_retry,
        test_event_parser_concurrent_task,
        test_event_parser_check_idle,
        test_event_parser_stream_end_on_silence,
        test_renderer_truecolor,
        test_renderer_ascii,
        test_renderer_256color,
        test_sprites_valid,
        test_ansi_stripping,
        test_terminal_detect,
        test_claude_log_parser_tool_use,
        test_claude_log_parser_user_message,
        test_claude_log_parser_tool_result_error,
        test_claude_log_parser_permission,
        test_claude_log_parser_retry,
        test_event_source_field,
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
            print(f"  [ERROR] {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*40}\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
