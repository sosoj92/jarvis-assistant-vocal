"""Abstraction d'impression : aucune impression sans appel explicite confirme."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.config import reglage

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PrintResult:
    printer: str
    pages: int
    executed: bool


class PrinterBackend(Protocol):
    def print_pdf(self, path: Path, execute: bool = False) -> PrintResult: ...


def available_printers() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    command = "Get-Printer | Select-Object Name,DriverName,PortName | ConvertTo-Json -Compress"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=15, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    data = json.loads(result.stdout)
    rows = [data] if isinstance(data, dict) else data
    return [{str(k): str(v or "") for k, v in row.items()} for row in rows if isinstance(row, dict)]


def choose_printer(name: str = "") -> dict[str, str]:
    configured = reglage(
        "signal_matin.imprimante", reglage("journal_matin.imprimante", ""))
    requested = (name or str(configured or "")).strip().lower()
    printers = available_printers()
    if requested:
        for printer in printers:
            if printer.get("Name", "").strip().lower() == requested:
                return printer
        raise RuntimeError(f"Imprimante configuree introuvable : {requested}")
    candidates = [
        printer for printer in printers
        if printer.get("Name", "").lower() not in {
            "fax", "microsoft print to pdf", "onenote (desktop)",
        }
    ]
    if not candidates:
        raise RuntimeError("Aucune imprimante physique Windows n'a ete trouvee.")
    if len(candidates) > 1:
        raise RuntimeError(
            "Plusieurs imprimantes sont disponibles. Renseigne signal_matin.imprimante."
        )
    return candidates[0]


class WindowsRasterPrinter:
    """Rend les pages PDF en PNG puis utilise le pilote Windows selectionne."""

    def __init__(self, printer_name: str = "", duplex: bool = False):
        self.printer_name = printer_name
        self.duplex = duplex

    def print_pdf(self, path: Path, execute: bool = False) -> PrintResult:
        path = path.resolve()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise FileNotFoundError(f"PDF introuvable : {path}")
        printer = choose_printer(self.printer_name)
        if not execute:
            return PrintResult(printer=printer["Name"], pages=0, executed=False)
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise RuntimeError("pdftoppm est requis pour imprimer le PDF.")
        script = ROOT / "scripts" / "imprimer_image_windows.ps1"
        if not script.is_file():
            raise RuntimeError("Le backend d'impression Windows est absent.")

        with tempfile.TemporaryDirectory(prefix="signal-matin-") as tmp:
            prefix = str(Path(tmp) / "page")
            render = subprocess.run(
                [pdftoppm, "-png", "-r", "180", str(path), prefix],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, check=False,
            )
            if render.returncode != 0:
                raise RuntimeError(f"Rendu PDF impossible : {render.stderr.strip()}")
            pages = sorted(Path(tmp).glob("page-*.png"))
            if not pages:
                raise RuntimeError("Le PDF ne contient aucune page imprimable.")
            command = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-DossierImages", str(tmp),
                "-Imprimante", printer["Name"],
            ]
            if self.duplex:
                command.append("-RectoVerso")
            result = subprocess.run(
                command,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180, check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Impression impossible : {detail}")
        return PrintResult(printer=printer["Name"], pages=len(pages), executed=True)
