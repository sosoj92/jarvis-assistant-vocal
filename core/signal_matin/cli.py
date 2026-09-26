"""Commandes generate / preview / print / data de Signal Matin."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import webbrowser
from pathlib import Path

from .mock_data import construire_demo
from .normalizer import charger_edition, ecrire_edition, normaliser_edition
from .pdf import generer_pdf
from .printer import WindowsRasterPrinter
from .renderer import write_html
from .sources import construire_edition_live

ROOT = Path(__file__).resolve().parents[2]


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date attendue : AAAA-MM-JJ") from error


def _paths(date: dt.date, output: Path | None = None) -> tuple[Path, Path, Path]:
    stem = f"{date.isoformat()}-signal-matin"
    pdf = output or ROOT / "output" / "pdf" / f"{stem}.pdf"
    html = ROOT / "output" / "preview" / f"{stem}.html"
    data = ROOT / "output" / "data" / f"{stem}.json"
    return pdf, html, data


def _edition(args):
    if args.input:
        return charger_edition(Path(args.input), mode=args.mode)
    if args.demo:
        return normaliser_edition(construire_demo(args.date), mode=args.mode)
    now = dt.datetime.combine(args.date, dt.datetime.now().astimezone().timetz())
    return construire_edition_live(now=now, mode=args.mode)


def _generate(args, pdf: bool = True):
    edition = _edition(args)
    pdf_path, html_path, data_path = _paths(args.date, Path(args.output) if args.output else None)
    ecrire_edition(edition, data_path)
    write_html(edition, html_path)
    if pdf:
        generer_pdf(edition, pdf_path, html_path=html_path)
    return edition, pdf_path, html_path, data_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-morning-paper",
        description="Genere le journal personnel A4 Signal Matin.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command):
        command.add_argument("--demo", action="store_true", help="utilise l'edition fictive complete")
        command.add_argument("--input", help="JSON MorningEdition deja normalise")
        command.add_argument("--date", type=_date, default=dt.date.today())
        command.add_argument("--mode", choices=("auto", "compact", "standard", "extended"), default="auto")
        command.add_argument("--output", help="chemin PDF de sortie")

    generate = sub.add_parser("generate", help="genere JSON, HTML et PDF")
    common(generate)
    preview = sub.add_parser("preview", help="genere et ouvre la preview HTML")
    common(preview)
    preview.add_argument("--no-open", action="store_true", help="n'ouvre pas le navigateur")
    data = sub.add_parser("data", help="genere uniquement le JSON normalise")
    common(data)
    print_cmd = sub.add_parser("print", help="genere puis envoie explicitement a l'imprimante")
    common(print_cmd)
    print_cmd.add_argument("--printer", default="", help="nom exact de la file Windows")
    print_cmd.add_argument(
        "--duplex", action="store_true",
        help="imprime en recto verso, retournement sur le bord long",
    )
    print_cmd.add_argument("--confirm", action="store_true", help="autorise reellement l'impression")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo and args.input:
        raise SystemExit("Choisis --demo ou --input, pas les deux.")

    if args.command == "data":
        edition = _edition(args)
        _, _, data_path = _paths(args.date, Path(args.output) if args.output else None)
        ecrire_edition(edition, data_path)
        print(f"JSON genere : {data_path}")
        return 0

    edition, pdf_path, html_path, data_path = _generate(args, pdf=args.command != "preview")
    if args.command == "preview":
        if not args.no_open:
            webbrowser.open(html_path.resolve().as_uri())
        print(f"Preview generee : {html_path}")
        print(f"JSON valide : {data_path}")
        return 0

    if args.command == "print":
        result = WindowsRasterPrinter(
            args.printer, duplex=args.duplex,
        ).print_pdf(pdf_path, execute=args.confirm)
        if not result.executed:
            print(f"Impression preparee pour '{result.printer}', mais non envoyee.")
            print("Relance avec --confirm pour imprimer reellement.")
            return 2
        print(f"{result.pages} page(s) envoyee(s) a {result.printer}.")
        return 0

    print(f"PDF genere : {pdf_path}")
    print(f"Preview : {html_path}")
    print(f"JSON : {data_path}")
    print(f"Mode : {edition.edition.density.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
