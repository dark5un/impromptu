"""Task 16 (RED): --vertical re-layouts the HF project to 1080x1920."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import build_hf_project
from test_build_hf import PLAN


def test_vertical_layout(tmp_path):
    index = build_hf_project(PLAN, presenter_src="p.mp4",
                             presenter_duration=12.0,
                             out_dir=tmp_path / "vert", vertical=True)
    html = Path(index).read_text()
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html
    assert "width=1080, height=1920" in html


def test_landscape_unchanged(tmp_path):
    index = build_hf_project(PLAN, presenter_src="p.mp4",
                             presenter_duration=12.0,
                             out_dir=tmp_path / "land")
    html = Path(index).read_text()
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
