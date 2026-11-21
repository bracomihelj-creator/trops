"""Vasco uvoz: odkrivanje IF* (IR) / kp* (PR) in razvrstitev knjig."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from trops_studio.money import ProjestError, normalize_text

EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
ZIP_EXTENSIONS = {".zip"}


def normalize_vasco_stem(path: Path) -> str:
    return re.sub(r"\s+", " ", path.stem).strip()


def classify_vasco_kind(path: Path) -> str | None:
    """IF* / darila/fitnes → IR; kp* / kpf → PR."""
    stem = normalize_vasco_stem(path).casefold()
    compact = re.sub(r"[\s_\-]+", "", stem)
    if compact.startswith("if") or "daril" in stem or "fitnes" in stem or "fitness" in stem:
        return "IR"
    if compact.startswith("kp") or compact.startswith("kpf") or "prejet" in stem:
        return "PR"
    return None


def ir_group_from_document(document_no: str, fallback: str = "IR") -> str:
    """Darila = listina 3…, Fitnes = listina 2…."""
    digits = re.sub(r"\D", "", str(document_no or ""))
    if digits.startswith("3"):
        return "Darila"
    if digits.startswith("2"):
        return "Fitness"
    return fallback or "IR"


def ir_book_from_filename(path: Path) -> str:
    stem = normalize_vasco_stem(path).casefold()
    if "daril" in stem:
        return "Darila"
    if "fitnes" in stem or "fitness" in stem:
        return "Fitness"
    return normalize_text(path.stem) or "IR"


def discover_vasco_files(folder: Path) -> tuple[list[Path], list[Path]]:
    folder = Path(folder)
    if not folder.is_dir():
        raise ProjestError(f"Mapa ne obstaja: {folder}")
    ir_files: list[Path] = []
    pr_files: list[Path] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.suffix.casefold() not in EXCEL_EXTENSIONS:
            continue
        kind = classify_vasco_kind(path)
        if kind == "IR":
            ir_files.append(path)
        elif kind == "PR":
            pr_files.append(path)
    return ir_files, pr_files


def classify_selected_files(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    ir_files: list[Path] = []
    pr_files: list[Path] = []
    unknown: list[str] = []
    for path in paths:
        kind = classify_vasco_kind(path)
        if kind == "IR":
            ir_files.append(path)
        elif kind == "PR":
            pr_files.append(path)
        else:
            unknown.append(path.name)
    if unknown:
        raise ProjestError(
            "Neznane Vasco datoteke (pričakujem IF* = IR, kp* = PR):\n" + "\n".join(unknown)
        )
    return ir_files, pr_files


def pick_three_vasco_files(folder: Path) -> tuple[Path | None, Path | None, Path | None]:
    """Iz mape izberi tipične 3 datoteke: Darila, Fitness, PR (KPF)."""
    ir_files, pr_files = discover_vasco_files(folder)
    darila: Path | None = None
    fitness: Path | None = None
    for path in ir_files:
        book = ir_book_from_filename(path)
        if book == "Darila" and darila is None:
            darila = path
        elif book == "Fitness" and fitness is None:
            fitness = path
    # Če manjka ime v datoteki, vzemi prvi/drugi IF*
    leftover = [p for p in ir_files if p not in {darila, fitness}]
    if darila is None and leftover:
        darila = leftover.pop(0)
    if fitness is None and leftover:
        fitness = leftover.pop(0)
    pr_file = pr_files[0] if pr_files else None
    return darila, fitness, pr_file


def extract_vasco_zip(zip_path: Path, dest: Path | None = None) -> Path:
    """Razširi ZIP v začasno mapo (ali dest) in vrni mapo z Exceli."""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise ProjestError(f"ZIP ne obstaja: {zip_path}")
    if zip_path.suffix.casefold() not in ZIP_EXTENSIONS:
        raise ProjestError(f"Ni ZIP datoteka: {zip_path.name}")
    out = Path(dest) if dest is not None else Path(tempfile.mkdtemp(prefix="trops_vasco_"))
    out.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(out)
    except zipfile.BadZipFile as exc:
        raise ProjestError(f"Poškodovan ZIP: {zip_path.name}") from exc
    # Če so Exceli v podmapi, poišči prvo mapo z IF*/kp*
    excel_here = [
        p
        for p in out.iterdir()
        if p.is_file() and p.suffix.casefold() in EXCEL_EXTENSIONS and classify_vasco_kind(p)
    ]
    if excel_here:
        return out
    for sub in sorted(out.rglob("*")):
        if not sub.is_dir():
            continue
        found = [
            p
            for p in sub.iterdir()
            if p.is_file() and p.suffix.casefold() in EXCEL_EXTENSIONS and classify_vasco_kind(p)
        ]
        if found:
            return sub
    raise ProjestError(f"V ZIP ni Vasco Excel datotek (IF* / kp*): {zip_path.name}")


def resolve_vasco_sources(
    *,
    folder: Path | None = None,
    zip_path: Path | None = None,
    ir_darila: Path | None = None,
    ir_fitnes: Path | None = None,
    pr_file: Path | None = None,
) -> tuple[Path | None, Path | None, Path | None, Path | None]:
    """
    Vrni (darila, fitness, pr, temp_dir).
    temp_dir je nastavljen samo pri ZIP (klicatelj naj počisti).
    """
    temp_dir: Path | None = None
    work_folder = folder
    if zip_path is not None:
        temp_dir = Path(tempfile.mkdtemp(prefix="trops_vasco_"))
        work_folder = extract_vasco_zip(Path(zip_path), dest=temp_dir)
    if work_folder is not None:
        darila, fitness, pr = pick_three_vasco_files(Path(work_folder))
        return darila, fitness, pr, temp_dir
    return (
        Path(ir_darila) if ir_darila else None,
        Path(ir_fitnes) if ir_fitnes else None,
        Path(pr_file) if pr_file else None,
        None,
    )


def cleanup_temp_dir(temp_dir: Path | None) -> None:
    if not temp_dir:
        return
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


def snapshot_last_vasco_import(
    *,
    cache_dir: Path | None,
    origin: Mapping[str, Any] | None,
    ir_files: Sequence[Path],
    pr_files: Sequence[Path],
    used_temp: bool,
) -> dict[str, str]:
    """Zapomni si zadnji uvoz (mapa, ZIP, datoteke). ZIP kopira v cache_dir."""
    origin = dict(origin or {})
    ir_paths = [Path(p) for p in ir_files if Path(p).is_file()]
    pr_paths = [Path(p) for p in pr_files if Path(p).is_file()]
    dest_dir = Path(cache_dir) if used_temp and cache_dir is not None else None
    if dest_dir is not None:
        dest_dir.mkdir(parents=True, exist_ok=True)

    def _store(src: Path) -> str:
        if dest_dir is None:
            return str(src)
        target = dest_dir / src.name
        shutil.copy2(src, target)
        return str(target)

    darila = ""
    fitness = ""
    for path in ir_paths:
        stored = _store(path)
        book = ir_book_from_filename(path)
        if book == "Darila" and not darila:
            darila = stored
        elif book == "Fitness" and not fitness:
            fitness = stored
        elif not darila:
            darila = stored
        elif not fitness:
            fitness = stored
    pr_stored = _store(pr_paths[0]) if pr_paths else ""

    directory = str(origin.get("dir") or "").strip()
    if not directory:
        first = next((p for p in (darila, fitness, pr_stored) if p), "")
        if first:
            directory = str(Path(first).parent)
    return {
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(origin.get("source") or ("zip" if used_temp else "folder")),
        "dir": directory,
        "zip": str(origin.get("zip") or ""),
        "ir_darila": darila,
        "ir_fitnes": fitness,
        "pr": pr_stored,
    }
