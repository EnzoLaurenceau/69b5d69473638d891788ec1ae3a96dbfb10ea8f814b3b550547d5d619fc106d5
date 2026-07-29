"""
apptension.py — SaaS Boilerplate (apptension/saas-boilerplate)
===============================================================
Stack SaaS full-stack : React + Django + AWS (auth, Stripe, multi-tenant).
Scaffold clone-on-need — base d'un SaaS livrable.
OpenHands part de ce scaffold pour les implémentations SaaS.

⚠️  Vérifier la licence avant toute revente commerciale.

Usage :
    from tools.product_bricks.saas_starters import apptension
    dest = apptension.scaffold("mon_saas", mvp_output_path)
    print(apptension.readme(dest)[:500])
"""
from __future__ import annotations
import subprocess
from pathlib import Path

REPO = "https://github.com/apptension/saas-boilerplate"
LICENSE_NOTE = "Vérifier LICENSE du repo avant revente commerciale."
STACK = "React + Django + AWS (auth Cognito, Stripe, multi-tenant)"


def scaffold(project_name: str, target_dir: str | Path) -> Path:
    """Clone le boilerplate dans target_dir/project_name (shallow clone)."""
    dest = Path(target_dir) / project_name
    if dest.exists():
        print(f"apptension: {dest} existe — skip clone")
        return dest
    subprocess.run(
        ["git", "clone", "--depth", "1", REPO, str(dest)],
        check=True,
    )
    print(f"apptension: scaffold → {dest}")
    print(f"apptension: ⚠️  {LICENSE_NOTE}")
    return dest


def readme(project_path: str | Path, lines: int = 100) -> str:
    """Premiers N lignes du README du scaffold."""
    f = Path(project_path) / "README.md"
    if not f.exists():
        return "README non trouvé"
    return "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[:lines])


if __name__ == "__main__":
    print(f"apptension saas-boilerplate")
    print(f"Stack : {STACK}")
    print(f"Repo  : {REPO}")
    print(f"⚠️   {LICENSE_NOTE}")
    print("Usage : apptension.scaffold('mon_saas', '/path/to/mvp_output')")
