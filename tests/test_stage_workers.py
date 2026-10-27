"""The studio's stage workers exist in the repo, with the format skill
installed on every one of them (docs/animation-studio.md §2, §3)."""

from pathlib import Path

import pytest

from app import pipeline

REPO = Path(__file__).resolve().parents[1]
WORKERS = REPO / "workers"


@pytest.mark.parametrize("worker", pipeline.workers_needed())
def test_stage_worker_has_a_brief_and_the_social_short_skill(worker):
    claude_md = WORKERS / worker / "CLAUDE.md"
    skill = WORKERS / worker / ".claude" / "skills" / "social-short" / "SKILL.md"

    assert claude_md.is_file(), f"{worker} has no CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    for heading in ("## Role", "## What it does", "## What it must not do", "## Output format"):
        assert heading in text, f"{worker}: missing {heading}"
    assert "report_result" in text, f"{worker}: must say how to report"
    assert "@../_shared/COMMS.md" in text, f"{worker}: must point at the comms rules"
    assert skill.is_file(), f"{worker} lacks the social-short skill"
    assert skill.read_text(encoding="utf-8").startswith("---\nname: social-short")


def test_every_stage_worker_has_the_same_skill_text():
    texts = {
        (WORKERS / w / ".claude" / "skills" / "social-short" / "SKILL.md").read_text(encoding="utf-8")
        for w in pipeline.workers_needed()
    }
    assert len(texts) == 1, "the format skill drifted between workers"


def test_makers_and_reviewers_point_at_the_right_artifacts():
    expectations = {
        "scriptwriter": "01-script.md",
        "script-reviewer": "02-script-review.md",
        "storyboarder": "03-storyboard/",
        "storyboard-reviewer": "04-storyboard-review.md",
        "asset-maker": "05-assets.md",
        "asset-reviewer": "06-asset-review.md",
        "renderer": "07-render/",
        "render-reviewer": "08-render-review.md",
    }
    for worker, artifact in expectations.items():
        assert artifact in (WORKERS / worker / "CLAUDE.md").read_text(encoding="utf-8"), worker
