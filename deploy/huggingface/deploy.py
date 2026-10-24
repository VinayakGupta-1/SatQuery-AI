"""Publish SatQuery AI to a Hugging Face Space (Docker SDK).

    hf auth login                                   # once, with a write token
    python deploy/huggingface/deploy.py             # -> <you>/satquery-ai
    python deploy/huggingface/deploy.py --with-models

The Space builds the root ``Dockerfile`` and serves the workspace and the API
on one public URL, ``https://<you>-satquery-ai.hf.space``.

Only files tracked by git are uploaded, so ``backend/.env`` and anything else
git ignores can never reach the Space. The Space gets its own ``README.md``
(this folder's), because Hugging Face reads its settings from that file's
front matter.

``--with-models`` copies ``SATQUERY_AGENT_API_KEY`` from ``backend/.env`` into
the Space as an encrypted secret and turns the vision features on. Visitors
then share that key's free-tier quota. Without it the Space reads questions
with the offline rules and the vision tools say they are switched off. Sign-in
is never configured: Supabase's built-in mailer only reaches members of the
project's organisation, so a public demo runs open.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPACE_README = os.path.join(REPO_ROOT, "deploy", "huggingface", "README.md")

#: What the image needs; everything else in the repository stays out.
INCLUDED = (
    "Dockerfile",
    ".dockerignore",
    "LICENSE",
    "backend/app/",
    "backend/scripts/",
    "backend/requirements-lock.txt",
    "frontend/",
)


def tracked_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return sorted(
        path for path in listed.split("\0")
        if path and (path in INCLUDED or path.startswith(tuple(p for p in INCLUDED if p.endswith("/"))))
    )


def read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--space", help="owner/name (default: <you>/satquery-ai)")
    parser.add_argument("--private", action="store_true", help="create the Space private")
    parser.add_argument(
        "--with-models", action="store_true",
        help="copy the Groq key from backend/.env as a Space secret and enable vision",
    )
    args = parser.parse_args()

    api = HfApi()
    owner = api.whoami()["name"]
    repo_id = args.space or f"{owner}/satquery-ai"

    api.create_repo(
        repo_id, repo_type="space", space_sdk="docker",
        private=args.private, exist_ok=True,
    )

    files = tracked_files()
    operations: list = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=os.path.join(REPO_ROOT, path))
        for path in files
    ]
    operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=SPACE_README))

    # Files removed from the repository since the last deploy leave the Space too.
    keep = set(files) | {"README.md", ".gitattributes"}
    operations += [
        CommitOperationDelete(path_in_repo=path)
        for path in api.list_repo_files(repo_id, repo_type="space")
        if path not in keep
    ]

    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    api.create_commit(
        repo_id, repo_type="space", operations=operations,
        commit_message=f"Deploy SatQuery AI at {head}",
    )
    print(f"Uploaded {len(files) + 1} files to spaces/{repo_id}")

    if args.with_models:
        env = read_env_file(os.path.join(REPO_ROOT, "backend", ".env"))
        key = env.get("SATQUERY_AGENT_API_KEY", "")
        if not key:
            print("backend/.env has no SATQUERY_AGENT_API_KEY; models not enabled.")
        else:
            api.add_space_secret(repo_id, "SATQUERY_AGENT_API_KEY", key)
            api.add_space_variable(repo_id, "SATQUERY_VQA_ENABLED", "true")
            print("Set the SATQUERY_AGENT_API_KEY secret and SATQUERY_VQA_ENABLED=true")

    subdomain = repo_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    print(f"Space:  https://huggingface.co/spaces/{repo_id}")
    print(f"App:    https://{subdomain}.hf.space   (live once the build finishes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
