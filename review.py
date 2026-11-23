# the human checkpoint: nothing reaches the real clones or the resume folder without a yes
import re
import shutil
import subprocess

import config


def ask(question):
    return input(f"{question} [y/N] ").strip().lower() == "y"


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def apply_patch(patch, repo):
    print(f"\n{patch.name} -> {repo}")
    print(git(repo, "apply", "--stat", str(patch)).stdout)
    touched = [line.split("\t")[-1] for line in git(repo, "apply", "--numstat", str(patch)).stdout.splitlines()]
    dirty = git(repo, "status", "--porcelain", "--", *touched).stdout.strip()
    if dirty:
        print(f"skipped, these files have local changes:\n{dirty}")
        return
    # apply to the index, which is lf like the patch, then check the files out so they get local line endings
    check = git(repo, "apply", "--cached", "--check", str(patch), check=False)
    if check.returncode != 0:
        print(f"skipped, the patch does not apply here:\n{check.stderr}")
        return
    print(f"full diff: {patch}")
    if not ask("apply and stage it?"):
        return
    git(repo, "apply", "--cached", str(patch))
    git(repo, "checkout", "--", *touched)
    print("staged, review with git diff --cached and commit when happy")


def next_resume_path():
    versions = [int(m.group(1)) for p in config.downloads.glob("Rooney_James_Owino_Resume_v*.pdf")
                if (m := re.search(r"_v(\d+)\.pdf$", p.name))]
    return config.downloads / f"Rooney_James_Owino_Resume_v{max(versions, default=1) + 1}.pdf"


def apply_resume(md, pdf):
    if not md.exists():
        return
    print(f"\nnew resume text: {md}")
    if pdf.exists():
        print(f"new resume pdf: {pdf}")
    if not ask("keep this resume?"):
        return
    config.resume_source.parent.mkdir(exist_ok=True)
    shutil.copy(md, config.resume_source)
    print(f"saved the source to {config.resume_source}")
    if pdf.exists():
        target = next_resume_path()
        shutil.copy(pdf, target)
        print(f"saved the pdf as {target}, the old versions are untouched")


def review(out_dir):
    for name, repo in config.clones.items():
        patch = out_dir / f"{name}.patch"
        if patch.exists():
            apply_patch(patch, repo)
    apply_resume(out_dir / "resume.md", out_dir / "resume.pdf")
