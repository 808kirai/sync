# shared settings for setup_agent.py and run.py
from pathlib import Path

home = Path.home()
project_dir = Path(__file__).parent
ids_file = project_dir / "agent_ids.json"
runs_dir = project_dir / "runs"
resume_source = project_dir / "resume" / "resume.md"

github_user = "808kirai"
downloads = home / "Downloads"

# where each patch from the agent gets applied
clones = {
    "myPortfolio": home / "OneDrive" / "Desktop" / "myPortfolio",
    "808kirai": home / "808kirai",
}

model = {"id": "claude-opus-5-5", "effort": "medium"}

# hard cap per run in us cents, the session pauses when it gets there
default_budget_cents = 300

environment_config = {
    "type": "cloud",
    "networking": {
        "type": "limited",
        # github for cloning the public repos, package managers for pytest and reportlab
        "allowed_hosts": ["github.com"],
        "allow_package_managers": True,
    },
}

tools = [
    {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": True, "permission_policy": {"type": "auto"}},
        "configs": [
            {"name": "web_fetch", "enabled": False},
            {"name": "web_search", "enabled": False},
        ],
    },
]

system_prompt = """you keep a developer's public profile honest and current. the developer is github user 808kirai.

what you work on
- the portfolio site - repo 808kirai/myPortfolio, static html deployed on vercel
- the github profile readme - repo 808kirai/808kirai, README.md
- the resume - /mnt/session/uploads/resume.pdf, plus /mnt/session/uploads/resume.md when it exists. when resume.md exists it is the source to edit
- the developer's other public repos, which are the evidence for what those three documents claim

how to work
- start by running python /mnt/session/uploads/measure.py with every repo named in the task. it clones them into /workspace/repos and writes /workspace/facts.json with commit counts, test function counts and the head commit of each. treat those numbers as ground truth
- the repos are public so no token is needed. you cannot push
- facts.json counts def test_ functions, so parametrized cases are not expanded. when a claimed test count differs from it, install that repo's requirements and run pytest --collect-only -q before calling it a mismatch, and say which count you used
- never invent, estimate or round a number. if something cannot be measured, leave the text as it is and flag it in the report
- keep edits small. match the existing wording, html structure, css classes and tone. do not redesign anything or add sections the developer did not ask for
- no emojis, and no note saying ai made a change

what to deliver in /mnt/session/outputs/
- report.md - every claim you checked, with where it appears, the claimed value, the measured value, how you measured it, and match, mismatch or unverifiable. then a list of the changes you made
- myPortfolio.patch and 808kirai.patch - made with git diff in each clone against its default branch, only when that repo has changes. check each one with git apply --check on a fresh clone
- resume.md and resume.pdf - only when the resume needs changes. resume.md is the full resume text in markdown. build resume.pdf from it with reportlab as one a4 page with the same sections, in the same order, as the original
- leave out any file that has no changes"""

# starter rubric for the grader, tune the criteria as you see what runs produce
rubric = """- /mnt/session/outputs/report.md exists
- report.md lists every repo named in the task with its commit count, test count and head commit from /workspace/facts.json, and says when a test count came from pytest collection instead
- report.md lists every checkable claim in the resume, the profile readme and the portfolio pages, with where it appears, the claimed value, the measured value and match, mismatch or unverifiable
- every mismatch is fixed in a patch or in resume.md, or the report says why it was left alone
- every change asked for in the developer's note is made, or the report says why not
- each patch applies cleanly with git apply --check on a fresh clone of its repo's default branch
- no number in a changed file is a guess. unverifiable claims are left as they were and flagged in the report
- when resume.pdf is present it is one page and keeps the original resume's sections in the same order
- changed files keep their original style, layout and wording except where a fix needs it"""
