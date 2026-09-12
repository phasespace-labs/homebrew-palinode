"""Prepare a reviewed formula update from a published Palinode stable release."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib
from urllib.request import urlopen


UPSTREAM = "phasespace-labs/palinode"
TAP = "phasespace-labs/homebrew-palinode"
FORMULA = Path("Formula/palinode.rb")
TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
URL = re.compile(r'^  url "https://github.com/phasespace-labs/palinode/archive/refs/tags/(v[\d.]+)\.tar\.gz"$', re.M)
CHECKSUM = re.compile(r'^  sha256 "[a-f0-9]{64}"$', re.M)


def run(*args: str, data: str | None = None) -> str:
    return subprocess.run(args, input=data, text=True, capture_output=True, check=True).stdout.strip()


def api(path: str, payload: dict | None = None) -> dict | list | None:
    if payload is None:
        output = run("gh", "api", path)
    else:
        output = run("gh", "api", "--method", "POST", path, "--input", "-", data=json.dumps(payload))
    return json.loads(output) if output else None


def version(tag: str) -> tuple[int, int, int]:
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"Expected a stable vMAJOR.MINOR.PATCH tag, got {tag!r}")
    return tuple(int(part) for part in match.groups())


def select_release(releases: list[dict], requested: str = "") -> dict:
    stable = [r for r in releases if not r.get("draft") and not r.get("prerelease")
              and r.get("published_at") and TAG.fullmatch(r.get("tag_name", ""))]
    if not stable:
        raise ValueError("No published stable Palinode release found")
    latest = max(stable, key=lambda r: version(r["tag_name"]))
    if requested:
        version(requested)
        if requested != latest["tag_name"]:
            raise ValueError(f"{requested} is not the latest public stable release ({latest['tag_name']})")
    return latest


def latest_release(requested: str = "") -> dict:
    pages = json.loads(run("gh", "api", f"repos/{UPSTREAM}/releases?per_page=100", "--paginate", "--slurp"))
    return select_release([release for page in pages for release in page], requested)


def formula_tag(text: str) -> str:
    matches = URL.findall(text)
    if len(matches) != 1:
        raise ValueError("Formula must contain exactly one Palinode stable archive URL")
    version(matches[0])
    return matches[0]


def archive_url(tag: str) -> str:
    version(tag)
    return f"https://github.com/{UPSTREAM}/archive/refs/tags/{tag}.tar.gz"


def archive_checksum(tag: str) -> str:
    # Never send the GitHub API token to the archive redirect destination.
    with urlopen(archive_url(tag), timeout=60) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    return verify_archive(archive, tag)


def verify_archive(archive: bytes, tag: str) -> str:
    version(tag)
    if len(archive) > 64 * 1024 * 1024:
        raise ValueError("Release archive exceeds 64 MiB")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        member = source.getmember(f"palinode-{tag[1:]}/pyproject.toml")
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError("Release pyproject.toml is not a small regular file")
        with source.extractfile(member) as metadata:
            project = tomllib.loads(metadata.read().decode())["project"]
    if project["name"] != "palinode" or project["version"] != tag[1:]:
        raise ValueError("Release tag and packaged project version disagree")
    return hashlib.sha256(archive).hexdigest()


def render_formula(text: str, tag: str, checksum: str) -> str:
    current = formula_tag(text)
    if version(tag) < version(current):
        raise ValueError(f"Refusing formula downgrade {current} -> {tag}")
    if not re.fullmatch(r"[a-f0-9]{64}", checksum) or len(CHECKSUM.findall(text)) != 1:
        raise ValueError("Expected one formula checksum and a valid replacement SHA-256")
    result = URL.sub(f'  url "{archive_url(tag)}"', text)
    return CHECKSUM.sub(f'  sha256 "{checksum}"', result)


def validation(pr: dict, branch: str) -> None:
    sha = pr["head"]["sha"]
    runs = api(f"repos/{TAP}/actions/workflows/ci.yml/runs?event=workflow_dispatch&branch={branch}&head_sha={sha}")
    if not runs["workflow_runs"]:
        api(f"repos/{TAP}/actions/workflows/ci.yml/dispatches", {"ref": branch})
    print(f"Awaiting review/validation: {pr['html_url']} (head {sha})")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as output:
            output.write(f"Formula update is **pending review**, not published: {pr['html_url']}\n\n"
                         f"Validation targets `{sha}`. Merge only after Formula CI passes.\n")


def open_update(requested: str = "") -> None:
    if run("git", "status", "--porcelain"):
        raise ValueError("Run the updater from a clean tap checkout")
    if run("git", "remote", "get-url", "origin") not in (
        f"https://github.com/{TAP}", f"https://github.com/{TAP}.git", f"git@github.com:{TAP}.git"
    ):
        raise ValueError("origin is not the Palinode tap")
    run("git", "fetch", "origin", "main")
    baseline = run("git", "show", f"origin/main:{FORMULA}") + "\n"
    tag = latest_release(requested)["tag_name"]
    current = formula_tag(baseline)
    if version(current) >= version(tag):
        print(f"Tap is current: {current}; newest published stable release: {tag}")
        return
    branch = f"automation/palinode-{tag}"
    prs = api(f"repos/{TAP}/pulls?head=phasespace-labs:{branch}&state=all&per_page=100")
    if prs:
        pr = prs[0]
        if pr["state"] != "open":
            raise ValueError(f"Existing update PR is closed: {pr['html_url']}; investigate before retrying")
        remote = run("gh", "api", f"repos/{TAP}/contents/{FORMULA}?ref={branch}", "--jq", ".content")
        import base64
        if formula_tag(base64.b64decode(remote).decode()) != tag:
            raise ValueError("Existing update branch does not contain its named release")
        validation(pr, branch)
        return

    remote_branch = run("git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if remote_branch:
        run("git", "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")
        changed = run("git", "diff", "--name-only", "origin/main..." + f"origin/{branch}")
        if changed not in ("", str(FORMULA)):
            raise ValueError("Refusing to reuse an automation branch with non-formula changes")
        run("git", "switch", "--detach", f"origin/{branch}")
        run("git", "merge", "--no-edit", "origin/main")
    else:
        run("git", "switch", "--detach", "origin/main")
    checksum = archive_checksum(tag)
    text = FORMULA.read_text()
    updated = render_formula(text, tag, checksum)
    if text != updated:
        FORMULA.write_text(updated)
        run("git", "add", str(FORMULA))
        run("git", "commit", "-m", f"palinode {tag[1:]}\n\nSource: https://github.com/{UPSTREAM}/releases/tag/{tag}")

    # Recheck after network/build preparation; a delayed job cannot publish an older candidate.
    latest_release(tag)
    run("git", "fetch", "origin", "main")
    if version(formula_tag(run("git", "show", f"origin/main:{FORMULA}"))) >= version(tag):
        print("Another update has already reached main; no PR needed")
        return
    run("git", "push", "origin", f"HEAD:refs/heads/{branch}")
    body = (f"Update Palinode from {current} to [{tag}](https://github.com/{UPSTREAM}/releases/tag/{tag}).\n\n"
            f"Archive SHA-256: `{checksum}`. The archive's package metadata matches the release tag.\n\n"
            "Formula CI checks clean installation, entry points, save/search and MCP connectivity, "
            "and upgrade preservation of an existing memory store. Review its result before merging.\n\n"
            "This PR is generated by the stable-release updater; it does not merge or publish itself.")
    pr = api(f"repos/{TAP}/pulls", {"title": f"palinode {tag[1:]}", "head": branch, "base": "main", "body": body})
    validation(pr, branch)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", default="", help="Require this tag to be the latest public stable release")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="Update the local formula only")
    mode.add_argument("--check", action="store_true", help="Fail if the local formula is not current")
    mode.add_argument("--open-pr", action="store_true", help="Create or resume a tap update PR and dispatch validation")
    args = parser.parse_args()
    if args.open_pr:
        open_update(args.release_tag)
        return
    tag = latest_release(args.release_tag)["tag_name"]
    current = formula_tag(FORMULA.read_text())
    if args.check:
        if current != tag:
            raise ValueError(f"Homebrew distribution outstanding: formula {current}, release {tag}")
        print(f"Formula is current: {tag}")
    else:
        FORMULA.write_text(render_formula(FORMULA.read_text(), tag, archive_checksum(tag)))
        print(f"Prepared {tag}; review git diff and run Formula CI before publishing")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr)
        raise SystemExit(str(error)) from error
