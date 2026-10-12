"""Deploy EDGAR.AI to a Hugging Face Space (Docker).

Usage:   python deploy_to_hf.py <hf-username>/<space-name>
Needs:   pip install huggingface_hub   and   hf auth login   (a token with write access)

Uploads the files tracked by git (so .env and other local files never leave your machine), with
hf-space/README.md as the Space's README (it holds the Space settings). Hugging Face then builds the
Dockerfile. Add the GROQ_API_KEY secret in the Space settings yourself.
"""

import subprocess
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

ROOT = Path(__file__).parent
SKIP = ("demo-screenshots/", "README.md", "hf-space/")   # the GitHub README and images aren't needed to run


def main(repo_id: str) -> None:
    api = HfApi()
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    files = [f for f in tracked if f and not f.startswith(SKIP)]
    operations = [CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(ROOT / f)) for f in files]
    operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(ROOT / "hf-space" / "README.md")))
    api.create_commit(repo_id, repo_type="space", operations=operations,
                      commit_message="Deploy EDGAR.AI from GitHub (advaithajith-coder/edgar-ai)")
    print(f"Uploaded {len(operations)} files. Build log and app: https://huggingface.co/spaces/{repo_id}")
    print("Next: Settings > Variables and secrets > New secret > GROQ_API_KEY")


if __name__ == "__main__":
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit(__doc__)
    main(sys.argv[1])
