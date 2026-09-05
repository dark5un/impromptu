"""Task 15 (RED): package helpers — chapters, description, loudnorm cmd, thumb cmd."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import (
    format_timestamp, plan_chapters, description_md, loudnorm_cmd,
    thumbnail_cmd, upload_checklist, tts_cmd, local_tts_cmd,
)

PLAN = {
    "fps": 30, "width": 1920, "height": 1080, "title": "Demo Video",
    "scenes": [
        {"mode": "fullscreen", "graphic": None, "title": "Hook",
         "start_sec": 0.0, "end_sec": 12.0,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "corner", "graphic": 0, "title": "Numbers",
         "start_sec": 12.0, "end_sec": 35.0,
         "transition": "fade", "transition_duration": 0.5},
    ],
}


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65) == "01:05"
    assert format_timestamp(3661) == "1:01:01"


def test_plan_chapters():
    ch = plan_chapters(PLAN)
    assert ch == [(0.0, "Hook"), (12.0, "Numbers")]


def test_description_md_has_title_and_chapters():
    md = description_md(PLAN)
    assert "Demo Video" in md
    assert "00:00 Hook" in md
    assert "00:12 Numbers" in md


def test_loudnorm_cmd_targets_minus14():
    cmd = loudnorm_cmd("in.mp4", "out.mp4")
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in " ".join(cmd)
    assert cmd[:2] == ["ffmpeg", "-y"]


def test_thumbnail_cmd_grabs_1280x720():
    cmd = thumbnail_cmd("in.mp4", "thumb.png", ss=5.0)
    joined = " ".join(cmd)
    assert "1280:720" in joined
    assert "thumb.png" in joined


def test_upload_checklist_never_autouploads(tmp_path):
    text = upload_checklist(PLAN, "final_loudnorm.mp4", tmp_path / "out")
    assert (tmp_path / "out" / "upload-checklist.md").exists()
    assert "NEVER" in text
    assert "youtube.com/upload" in text


def test_tts_cmd_container_arg_order(tmp_path):
    dst = tmp_path / "voice.wav"
    cmd = tts_cmd("hello", dst, voice="af_heart", speed=1.0)
    assert cmd[:4] == ["podman", "run", "--rm", "--entrypoint"]
    assert "--entrypoint" in cmd and cmd.index("--entrypoint") < cmd.index("localhost/hyperframes-render:latest")
    assert cmd[cmd.index("--voice") + 1] == "af_heart"


def test_local_tts_cmd(tmp_path):
    dst = tmp_path / "voice.wav"
    cmd = local_tts_cmd("hello", dst)
    assert cmd[:3] == ["hyperframes", "tts", "hello"]
    assert cmd[cmd.index("--output") + 1] == str(dst)
