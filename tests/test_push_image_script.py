"""Prueft die Gates des Push-Skripts, ohne Docker aufzurufen.

Alle Tests laufen ueber `--dry-run`: die Gates (Login, sauberer Worktree) und
die Tag-Ableitung greifen dort vollstaendig, der eigentliche Build nicht.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push-image.sh"
REGISTRY = "rg.nl-ams.scw.cloud/krinke-dockersolutions"
REGISTRY_HOST = "rg.nl-ams.scw.cloud"


def _git(repo: Path, *args: str) -> str:
    """Git im Testrepo, mit fixer Identitaet damit Commits ohne globale Config gehen."""
    out = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    """Mini-Repo mit einer Kopie des Push-Skripts, sauber committet.

    Die zusaetzliche `nutzlast.txt` ist getrackt und dient als Objekt fuer den
    Dirty-Test: das Skript selbst darf dafuer nicht veraendert werden, denn ein
    ueberschriebenes Skript wuerde gar nichts mehr pruefen und der Test waere
    gruen, ohne das Gate zu beruehren.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "push-image.sh")
    (repo / "scripts" / "push-image.sh").chmod(0o755)
    (repo / "nutzlast.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _docker_config(tmp_path: Path, host: str | None = REGISTRY_HOST) -> Path:
    """Docker-Config-Verzeichnis; host=None erzeugt eine Config ohne Login."""
    cfg_dir = tmp_path / "dockercfg"
    cfg_dir.mkdir()
    auths = {host: {}} if host else {}
    (cfg_dir / "config.json").write_text(json.dumps({"auths": auths}), encoding="utf-8")
    return cfg_dir


def _run(repo: Path, cfg_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOCKER_CONFIG": str(cfg_dir)}
    return subprocess.run(
        ["bash", str(repo / "scripts" / "push-image.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_dry_run_baut_beide_plattformen_und_beide_tags(tmp_path):
    repo = _make_repo(tmp_path)
    sha = _git(repo, "rev-parse", "--short", "HEAD")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode == 0, res.stderr
    assert "--platform linux/amd64,linux/arm64" in res.stdout
    assert f"{REGISTRY}/lector:latest" in res.stdout
    assert f"{REGISTRY}/lector:git-{sha}" in res.stdout
    assert "--push" in res.stdout


def test_dry_run_baut_nicht_wirklich(tmp_path):
    """Der Build-Befehl wird nur ausgegeben, nicht ausgefuehrt."""
    repo = _make_repo(tmp_path)

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.stdout.count("[dry-run]") == 1


def test_schmutziger_worktree_bricht_ab(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "neu.txt").write_text("uncommittet", encoding="utf-8")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode != 0
    assert "sauber" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_geaenderte_datei_bricht_ab(tmp_path):
    """Auch eine Aenderung an einer getrackten Datei zaehlt als schmutzig.

    Geaendert wird `nutzlast.txt`, nicht das Skript: ein ueberschriebenes Skript
    wuerde nichts mehr pruefen und der Test waere aus dem falschen Grund gruen.
    """
    repo = _make_repo(tmp_path)
    (repo / "nutzlast.txt").write_text("geaendert\n", encoding="utf-8")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode != 0
    assert "sauber" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_fehlender_login_bricht_ab(tmp_path):
    repo = _make_repo(tmp_path)

    res = _run(repo, _docker_config(tmp_path, host=None), "--dry-run")

    assert res.returncode != 0
    assert "docker login" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_fehlende_docker_config_bricht_ab(tmp_path):
    """Gar keine config.json ist kein Crash, sondern dieselbe klare Meldung."""
    repo = _make_repo(tmp_path)
    leer = tmp_path / "leer"
    leer.mkdir()

    res = _run(repo, leer, "--dry-run")

    assert res.returncode != 0
    assert "docker login" in res.stderr
