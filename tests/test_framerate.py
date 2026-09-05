"""Task 4 (RED): parse_framerate must replace eval() and handle 0/0."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import parse_framerate


def test_parses_simple_fraction():
    assert parse_framerate("30/1") == 30.0


def test_parses_ntsc_rational():
    assert abs(parse_framerate("30000/1001") - 29.97002997) < 1e-6


def test_parses_plain_integer():
    assert parse_framerate("25") == 25.0


def test_zero_denominator_returns_zero_not_crash():
    assert parse_framerate("0/0") == 0.0


def test_garbage_returns_zero_not_crash():
    assert parse_framerate("bogus") == 0.0
