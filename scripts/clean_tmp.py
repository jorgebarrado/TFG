#!/usr/bin/env python3
# Limpia la carpeta tmp/ del repositorio.
# Sin argumentos borra todo el contenido. Con --keep-days conserva los más recientes.
# Con --keep-folder conserva una subcarpeta concreta. Con una carpeta como argumento borra solo esa.

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "tmp"


def _mtime(path: Path) -> datetime:
    try:
        if path.is_file():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        mtimes = [path.stat().st_mtime] + [
            f.stat().st_mtime for f in path.rglob("*") if f.is_file()
        ]
        return datetime.fromtimestamp(max(mtimes), tz=timezone.utc)
    except OSError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _size_label(path: Path) -> str:
    try:
        if path.is_file():
            total = path.stat().st_size
        else:
            total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        for unit in ("B", "KB", "MB", "GB"):
            if total < 1024:
                return f"{total:.0f} {unit}"
            total /= 1024
        return f"{total:.1f} TB"
    except OSError:
        return ""


def _is_within(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _delete(path: Path) -> bool:
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True
    except OSError as exc:
        print(f"  ! Error borrando {path.name}: {exc}", file=sys.stderr)
        return False


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [s/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _classify(
    entries: list[Path],
    *,
    keep_days: int | None,
    keep_folders: set[str],
) -> tuple[list[tuple[Path, str]], list[Path]]:
    kept: list[tuple[Path, str]] = []
    deleted: list[Path] = []
    now = datetime.now(tz=timezone.utc)
    for entry in entries:
        if entry.name in keep_folders:
            kept.append((entry, "--keep-folder"))
            continue
        if keep_days is not None:
            cutoff = now - timedelta(days=keep_days)
            mt = _mtime(entry)
            if mt >= cutoff:
                kept.append((entry, f"modificado el {mt.strftime('%Y-%m-%d')}"))
                continue
        deleted.append(entry)
    return kept, deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Limpia la carpeta tmp/ del repositorio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Ejemplos:
  python scripts/clean_tmp.py                              # borra todo tmp/
  python scripts/clean_tmp.py reference_regression         # borra solo tmp/reference_regression/
  python scripts/clean_tmp.py --keep-days 3                # conserva los de los últimos 3 días
  python scripts/clean_tmp.py --keep-folder grobid_eval    # conserva tmp/grobid_eval/
  python scripts/clean_tmp.py --keep-folder a --keep-folder b  # conserva varias carpetas
  python scripts/clean_tmp.py -y                           # sin confirmación interactiva
""",
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="Subcarpeta dentro de tmp/ a limpiar. Si no se indica, limpia todo tmp/.",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        metavar="N",
        default=None,
        help="Conserva entradas modificadas en los últimos N días.",
    )
    parser.add_argument(
        "--keep-folder",
        action="append",
        metavar="NOMBRE",
        dest="keep_folders",
        default=[],
        help="Nombre de subcarpeta de tmp/ a conservar. Se puede repetir.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Ejecuta sin pedir confirmación.",
    )
    args = parser.parse_args()

    if not TMP_DIR.exists():
        print(f"La carpeta tmp/ no existe ({TMP_DIR})")
        return 0

    # Determinar el ámbito de la operación
    if args.folder:
        target = (TMP_DIR / args.folder).resolve()
        if not _is_within(TMP_DIR, target):
            print(f"Error: '{args.folder}' debe estar dentro de tmp/", file=sys.stderr)
            return 1
        if not target.exists():
            print(f"No existe: tmp/{args.folder}")
            return 1
        scope = [target]
        scope_label = f"tmp/{args.folder}/"
    else:
        scope = sorted(TMP_DIR.iterdir())
        scope_label = "tmp/"

    kept, to_delete = _classify(
        scope,
        keep_days=args.keep_days,
        keep_folders=set(args.keep_folders),
    )

    if not to_delete:
        print("Nada que borrar.")
        return 0

    print(f"Ámbito: {scope_label}\n")
    if kept:
        print("Se conservan:")
        for path, reason in kept:
            print(f"  + {path.name:<40}  {reason}")
        print()
    print("Se borrarán:")
    for path in to_delete:
        print(f"  - {path.name:<40}  {_size_label(path)}")

    if not args.yes:
        print()
        if not _confirm("¿Continuar?"):
            print("Cancelado.")
            return 0

    print()
    deleted = sum(1 for path in to_delete if _delete(path))
    print(f"Eliminados: {deleted} / {len(to_delete)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
