#!/usr/bin/env python3
"""
Recuento de magnitudes del proyecto CiteCheck para la tabla de la memoria
(sección «Dimensión del sistema»).

Uso (desde la RAÍZ del repositorio, en la rama de trabajo):
    python scripts/gen_metricas.py

Funciona en Windows, Linux y macOS. Solo usa la biblioteca estándar.
Pega la salida completa en el chat para rellenar la tabla.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()

# Directorios a excluir del recuento
EXCLUDE_DIRS = {
    ".git", ".venv", ".venv311", "venv", "node_modules", "__pycache__",
    "dist", "build", "staticfiles", ".pytest_cache", "media",
}

def walk_files(exts):
    """Itera ficheros con las extensiones dadas, excluyendo EXCLUDE_DIRS."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in filenames:
            if Path(f).suffix.lower() in exts:
                yield Path(dirpath) / f

def count_lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0

def loc(exts, exclude_substr=None):
    files = lines = 0
    for p in walk_files(exts):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if exclude_substr and any(s in rel for s in exclude_substr):
            continue
        files += 1
        lines += count_lines(p)
    return files, lines

def grep_count(exts, pattern, exclude_substr=None):
    rx = re.compile(pattern)
    total = 0
    for p in walk_files(exts):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if exclude_substr and any(s in rel for s in exclude_substr):
            continue
        try:
            total += len(rx.findall(p.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            pass
    return total

def git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             cwd=ROOT, timeout=60)
        return out.stdout.strip()
    except Exception:
        return ""

def main():
    print(f"Repositorio: {ROOT}")
    rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if rama:
        print(f"Rama actual: {rama}")
    print("-" * 56)

    # --- Código ---
    f_py, l_py = loc({".py"}, exclude_substr=["/migrations/", "migrations/"])
    f_mig, l_mig = loc({".py"})
    l_mig_only = l_mig - l_py
    f_js, l_js = loc({".js", ".jsx", ".ts", ".tsx"})
    f_html, l_html = loc({".html"})
    f_css, l_css = loc({".css", ".scss"})

    print(f"Python (sin migraciones): {f_py} ficheros, {l_py} líneas")
    print(f"  (migraciones aparte:    {l_mig_only} líneas)")
    print(f"JS/JSX/TS (lector React): {f_js} ficheros, {l_js} líneas")
    print(f"Plantillas HTML:          {f_html} ficheros, {l_html} líneas")
    print(f"CSS/SCSS:                 {f_css} ficheros, {l_css} líneas")

    # --- Django ---
    n_modelos = grep_count({".py"}, r"class\s+\w+\(.*models\.Model",
                           exclude_substr=["/migrations/"])
    n_migr = sum(1 for p in walk_files({".py"})
                 if "migrations" in str(p) and p.name != "__init__.py")
    n_rutas = grep_count({".py"}, r"\b(?:path|re_path)\s*\(")
    n_tests = grep_count({".py"}, r"\bdef\s+test_\w+")
    print(f"Modelos (models.Model):   {n_modelos}")
    print(f"Migraciones:              {n_migr}")
    print(f"Rutas URL (path/re_path): {n_rutas}")
    print(f"Funciones de test:        {n_tests}")

    # --- Dependencias ---
    req = ROOT / "requirements.txt"
    if req.exists():
        deps = [l for l in req.read_text(encoding="utf-8", errors="ignore").splitlines()
                if l.strip() and not l.strip().startswith(("#", "-"))]
        print(f"Dependencias Python:      {len(deps)}")
    pkg = ROOT / "frontend_reader" / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            nd = len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))
            print(f"Dependencias npm:         {nd}")
        except json.JSONDecodeError:
            pass

    # --- Git ---
    n_commits = git("rev-list", "--count", "HEAD")
    dias = git("log", "--format=%ad", "--date=short")
    n_dias = len(set(dias.splitlines())) if dias else 0
    primero = git("log", "--reverse", "--format=%ad", "--date=short")
    primero = primero.splitlines()[0] if primero else "?"
    ultimo = dias.splitlines()[0] if dias else "?"
    print(f"Commits:                  {n_commits}")
    print(f"Días con actividad:       {n_dias}  ({primero} -> {ultimo})")
    print("-" * 56)
    print("Pega esta salida completa en el chat.")

if __name__ == "__main__":
    sys.exit(main())
