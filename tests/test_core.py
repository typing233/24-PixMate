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
    """Real format: assistant with message.content containing tool_use blocks."""
    entry = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "text": "Let me think..."},
                {"type": "tool_use", "name": "Bash", "id": "toolu_1", "input": {"command": "ls"}},
            ],
        },
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.THINKING_START for e in events)
    assert any(e.type == EventType.TOOL_START and e.data.get("tool") == "Bash" for e in events)
    assert all(e.source == EventSource.CLAUDE_LOG for e in events)
    # Check command context extracted from input
    tool_ev = [e for e in events if e.type == EventType.TOOL_START][0]
    assert tool_ev.data["context"] == "ls"
    print("  [PASS] test_claude_log_parser_tool_use")


def test_claude_log_parser_user_message():
    """Real format: type=user with message.content as plain string."""
    entry = {
        "type": "user",
        "message": {"role": "user", "content": "Fix the bug"},
        "uuid": "abc",
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.USER_INPUT for e in events)
    assert events[0].data["text"] == "Fix the bug"
    print("  [PASS] test_claude_log_parser_user_message")


def test_claude_log_parser_tool_result_error():
    """Real format: user message with tool_result block, is_error=True."""
    entry = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_xyz",
                    "is_error": True,
                    "content": "command not found",
                }
            ],
        },
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.ERROR for e in events)
    assert "command not found" in events[0].data["text"]
    print("  [PASS] test_claude_log_parser_tool_result_error")


def test_claude_log_parser_permission():
    """permission-mode entry triggers session_resume (mode change signal)."""
    entry = {"type": "permission-mode", "permissionMode": "default", "sessionId": "abc"}
    events = parse_log_entry(entry)
    assert len(events) == 1
    assert events[0].type == EventType.SESSION_RESUME
    assert events[0].data["mode"] == "default"
    print("  [PASS] test_claude_log_parser_permission")


def test_claude_log_parser_retry():
    """Real format: system entry with subtype=api_error is a retry signal."""
    entry = {
        "type": "system",
        "subtype": "api_error",
        "level": "error",
        "error": {"status": 529, "headers": {}},
    }
    events = parse_log_entry(entry)
    assert any(e.type == EventType.RETRY for e in events)
    assert events[0].data["status"] == 529
    print("  [PASS] test_claude_log_parser_retry")


def test_claude_log_real_format_user_text():
    """Real Claude Code format: type=user with message.content as string."""
    entry = {
        "parentUuid": None,
        "isSidechain": False,
        "type": "user",
        "message": {
            "role": "user",
            "content": "Fix the authentication bug in login.py"
        },
        "uuid": "abc-123",
        "timestamp": "2026-06-08T07:03:58.725Z",
    }
    events = parse_log_entry(entry)
    assert len(events) == 1
    assert events[0].type == EventType.USER_INPUT
    assert "authentication" in events[0].data["text"]
    print("  [PASS] test_claude_log_real_format_user_text")


def test_claude_log_real_format_assistant_thinking_and_tool():
    """Real format: assistant with thinking + tool_use blocks."""
    entry = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "anonymous/orange9",
            "content": [
                {"type": "thinking", "text": "Let me analyze this bug..."},
                {"type": "text", "text": "I'll fix the login flow."},
                {"type": "tool_use", "name": "Edit", "id": "toolu_123",
                 "input": {"file_path": "/app/login.py", "old_string": "x", "new_string": "y"}},
            ],
        },
        "uuid": "def-456",
    }
    events = parse_log_entry(entry)
    types = [e.type for e in events]
    assert EventType.THINKING_START in types
    assert EventType.STREAM_START in types
    assert EventType.TOOL_START in types
    tool_ev = [e for e in events if e.type == EventType.TOOL_START][0]
    assert tool_ev.data["tool"] == "Edit"
    assert tool_ev.data["context"] == "/app/login.py"
    print("  [PASS] test_claude_log_real_format_assistant_thinking_and_tool")


def test_claude_log_real_format_tool_result():
    """Real format: user message containing tool_result blocks."""
    entry = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_bdrk_013ABrWVP",
                    "is_error": False,
                    "content": "(Bash completed with no output)",
                }
            ],
        },
        "uuid": "ghi-789",
    }
    events = parse_log_entry(entry)
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_END
    assert "Bash completed" in events[0].data["text"]
    print("  [PASS] test_claude_log_real_format_tool_result")


def test_claude_log_real_format_tool_result_error():
    """Real format: tool_result with is_error=True."""
    entry = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_xyz",
                    "is_error": True,
                    "content": "Exit code 1\nTraceback (most recent call last):\n  File...",
                }
            ],
        },
    }
    events = parse_log_entry(entry)
    assert len(events) == 1
    assert events[0].type == EventType.ERROR
    assert "Traceback" in events[0].data["text"]
    print("  [PASS] test_claude_log_real_format_tool_result_error")


def test_claude_log_real_format_system_api_error():
    """Real format: system entry with subtype=api_error → retry."""
    entry = {
        "type": "system",
        "subtype": "api_error",
        "level": "error",
        "error": {"status": 500, "headers": {}},
    }
    events = parse_log_entry(entry)
    assert len(events) == 1
    assert events[0].type == EventType.RETRY
    assert events[0].data["status"] == 500
    print("  [PASS] test_claude_log_real_format_system_api_error")


def test_claude_log_real_format_multiple_tool_results():
    """Real format: multiple tool_result blocks in one message."""
    entry = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": False,
                 "content": "file read ok"},
                {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
                 "content": "permission denied"},
            ],
        },
    }
    events = parse_log_entry(entry)
    assert len(events) == 2
    assert events[0].type == EventType.TOOL_END
    assert events[1].type == EventType.ERROR
    print("  [PASS] test_claude_log_real_format_multiple_tool_results")


def test_parser_tool_and_permission_same_chunk():
    """When tool box header and Allow?[Y/n] arrive in same data chunk,
    both tool_start AND permission_prompt should fire."""
    parser = EventParser()

    # Simulate a single PTY read that contains both
    chunk = "╭─ Bash ─────────────────╮\nAllow this command? [Y/n]".encode()
    events = parser.feed(chunk, Direction.OUTPUT)

    types = [e.type for e in events]
    assert EventType.TOOL_START in types, f"Missing TOOL_START in {types}"
    assert EventType.PERMISSION_PROMPT in types, f"Missing PERMISSION_PROMPT in {types}"
    assert parser._awaiting_permission is True
    print("  [PASS] test_parser_tool_and_permission_same_chunk")


def test_parser_permission_then_user_input_triggers_response():
    """After permission_prompt, user typing 'y' should trigger permission_response,
    NOT a generic user_input event."""
    parser = EventParser()

    # First: output with permission prompt
    parser.feed("Allow execution? [Y/n]".encode(), Direction.OUTPUT)
    assert parser._awaiting_permission is True

    # User types 'y' — should be permission_response
    events = parser.feed(b"y", Direction.INPUT)
    types = [e.type for e in events]
    assert EventType.PERMISSION_RESPONSE in types, f"Expected PERMISSION_RESPONSE, got {types}"
    assert EventType.USER_INPUT not in types, f"Should NOT emit USER_INPUT after permission"
    resp = [e for e in events if e.type == EventType.PERMISSION_RESPONSE][0]
    assert resp.data["accepted"] is True
    assert parser._awaiting_permission is False

    # After permission answered, next input is regular user_input
    events2 = parser.feed(b"hello", Direction.INPUT)
    types2 = [e.type for e in events2]
    assert EventType.USER_INPUT in types2
    print("  [PASS] test_parser_permission_then_user_input_triggers_response")


def test_parser_permission_denied_response():
    """User typing 'n' after permission prompt → accepted=False."""
    parser = EventParser()
    parser.feed("Deny this? [Y/n]".encode(), Direction.OUTPUT)

    events = parser.feed(b"n", Direction.INPUT)
    resp = [e for e in events if e.type == EventType.PERMISSION_RESPONSE]
    assert len(resp) == 1
    assert resp[0].data["accepted"] is False
    print("  [PASS] test_parser_permission_denied_response")


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
        test_claude_log_real_format_user_text,
        test_claude_log_real_format_assistant_thinking_and_tool,
        test_claude_log_real_format_tool_result,
        test_claude_log_real_format_tool_result_error,
        test_claude_log_real_format_system_api_error,
        test_claude_log_real_format_multiple_tool_results,
        test_parser_tool_and_permission_same_chunk,
        test_parser_permission_then_user_input_triggers_response,
        test_parser_permission_denied_response,
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
