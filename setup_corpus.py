"""Clone the reference corpus into work/corpus. Safe to re-run."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent / "work" / "corpus"
REPOS = {
    "payloads": "https://github.com/swisskyrepo/PayloadsAllTheThings.git",
    "prompts": "https://github.com/elder-plinius/CL4R1T4S.git",
    "awesome": "https://github.com/Hack-with-Github/Awesome-Hacking.git",
    "book": "https://github.com/trimstray/the-book-of-secret-knowledge.git",
    "tools": "https://github.com/Z4nzu/hackingtool.git",
    "ciphey": "https://github.com/bee-san/Ciphey.git",
    "rea": "https://github.com/morluto/rea.git",
}

ROOT.mkdir(parents=True, exist_ok=True)
for name, url in REPOS.items():
    dest = ROOT / name
    if dest.exists():
        print(f"skip {name}")
        continue
    print(f"clone {name}")
    subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=False)
print("done")