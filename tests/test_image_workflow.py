"""Haelt die Garantien der Image-Auslieferung (Spec image-auslieferung) am Workflow fest.

Jedes neue `latest` wird auf dem NAS ohne weiteren Handgriff ausgerollt. Ein verrutschter
Ausloeser, ein fehlendes Test-Gate oder ein zu frueh gesetztes `latest` fiele erst dort auf.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"
BUILD_CHECK = ROOT / ".github" / "workflows" / "build-check.yml"
ZENTRAL = "Krinke-IT-Consulting/renovate/.github/workflows/build-check.yml"

BILDRELEVANT = {
    "app/**",
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    ".github/workflows/image.yml",
}


def _wf() -> dict:
    with WORKFLOW.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _on() -> dict:
    # PyYAML liest den Schluessel `on` als Boolean True.
    wf = _wf()
    return wf.get("on", wf.get(True))


def _jobs() -> dict:
    return _wf()["jobs"]


def _needs(job: str) -> set[str]:
    needs = _jobs()[job].get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _uses_aller_schritte() -> list[str]:
    uses = []
    for job in _jobs().values():
        if "uses" in job:
            uses.append(job["uses"])
        uses += [s["uses"] for s in job.get("steps", []) if "uses" in s]
    return uses


def _step_text(job: str) -> list[str]:
    return [
        " ".join(str(v) for v in step.values())
        for step in _jobs()[job].get("steps", [])
    ]


def test_ausloeser_nur_main_und_manuell():
    on = _on()
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["main"]


def test_pfadfilter_umfasst_genau_die_bildrelevanten_dateien():
    assert set(_on()["push"]["paths"]) == BILDRELEVANT


def test_aelterer_lauf_wird_abgebrochen():
    concurrency = _wf()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "${{" not in str(concurrency["group"]), "eine feste Gruppe fuer alle Laeufe"


def test_minimale_rechte():
    assert _wf()["permissions"] == {"contents": "read"}


def test_build_check_ist_derselbe_zentrale_workflow_wie_fuer_pull_requests():
    uses = _jobs()["build-check"]["uses"]
    pin = re.search(rf"{re.escape(ZENTRAL)}@([0-9a-f]{{40}})", BUILD_CHECK.read_text())
    assert pin, "build-check.yml bindet den zentralen Workflow nicht mehr gepinnt ein"
    assert uses == f"{ZENTRAL}@{pin.group(1)}"
    assert "secrets" not in _jobs()["build-check"]


def test_lint_fuehrt_ruff_check_aus():
    assert any("ruff check" in t for t in _step_text("lint"))


def test_bau_erst_nach_pruefung_und_merge_erst_nach_bau():
    assert _needs("build") == {"build-check", "lint"}
    assert "build" in _needs("merge")


def test_matrix_baut_beide_plattformen():
    plattformen = {e["platform"] for e in _jobs()["build"]["strategy"]["matrix"]["include"]}
    assert plattformen == {"linux/amd64", "linux/arm64"}


def test_latest_nur_im_merge_job_und_erst_nach_plattformpruefung():
    for name, job in _jobs().items():
        if name != "merge":
            assert ":latest" not in yaml.safe_dump(job), f"latest in Job {name}"
    texte = _step_text("merge")
    pruefung = next(i for i, t in enumerate(texte) if "imagetools inspect" in t)
    latest = next(i for i, t in enumerate(texte) if ":latest" in t)
    assert pruefung < latest


def test_latest_nur_fuer_main():
    texte = _jobs()["merge"]["steps"]
    schritt = next(s for s in texte if ":latest" in " ".join(str(v) for v in s.values()))
    assert "refs/heads/main" in str(schritt.get("if", ""))


def test_alle_actions_auf_commit_sha_gepinnt():
    for uses in _uses_aller_schritte():
        assert re.search(r"@[0-9a-f]{40}$", uses), f"nicht gepinnt: {uses}"


def test_registry_schluessel_nur_aus_secret():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.SCW_REGISTRY_SECRET_KEY" in text
    assert "nologin" in text
