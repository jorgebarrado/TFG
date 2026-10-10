# Comando de gestión: carga datos de ejemplo (usuarios, reportes, comentarios y votos) para la demo pública.
"""
Management command: seed_demo
=============================
Rellena una base de datos vacía con contenido de ejemplo para la demo.

Los reportes usan los DOI de prueba de Crossref (prefijo 10.5555, artículos
ficticios del "Journal of Psychoceramics"): sus metadatos se resuelven de
verdad, pero no se acusa a ningún artículo real de citar mal.

Es idempotente: si el usuario demo ya existe no hace nada.

Uso:
    python manage.py seed_demo
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from citations.models import Comment, IncorrectCitation, Vote
from citations.services.evidence import normalize_evidence_items
from citations.services.report_tags import apply_report_tags

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-citecheck"

AVISO = "Reporte de ejemplo de la demo: los artículos son ficticios (DOI de prueba de Crossref)."

REPORTS = [
    {
        "author": "demo",
        "title": "Se atribuye al original un resultado experimental que no contiene",
        "doi_original": "10.5555/12345678",
        "original_title": "Toward a Unified Theory of High-Energy Metaphysics: Silly String Theory",
        "doi_incorrect": "10.5555/12345679",
        "types": ["not said"],
        "areas": ["PHY"],
        "reason": (
            "El artículo citante afirma que el original «demuestra experimentalmente» "
            "la teoría, pero el original es un trabajo puramente teórico y no incluye "
            "ningún experimento ni medición. " + AVISO
        ),
        "evidence": (
            "As experimentally demonstrated by Carberry [1], the unified theory "
            "holds for all energy ranges considered in this work."
        ),
        "comments": [
            ("ana_revisora", "Coincido: he revisado el original y no hay sección experimental."),
            ("demo", "Gracias por comprobarlo. Añadiré la página exacta de la cita."),
        ],
        "votes": {"ana_revisora": 1, "carlos_lector": 1},
    },
    {
        "author": "ana_revisora",
        "title": "Conclusión generalizada más allá de lo que dice el original",
        "doi_original": "10.5555/12345680",
        "original_title": "A Methodology for the Emulation of Architecture",
        "doi_incorrect": "10.5555/12345681",
        "types": ["misinterpretation"],
        "areas": ["CIS"],
        "reason": (
            "El original propone una metodología y la evalúa en un único caso de "
            "estudio; el citante la presenta como validada «de forma general» en "
            "cualquier arquitectura. " + AVISO
        ),
        "evidence": (
            "This methodology has been shown to work for arbitrary architectures [7], "
            "so we adopt it without further validation."
        ),
        "comments": [
            ("carlos_lector", "¿Podría ser solo una redacción poco afortunada del citante?"),
        ],
        "votes": {"demo": 1, "carlos_lector": -1},
    },
    {
        "author": "carlos_lector",
        "title": "Cita usada como apoyo de una afirmación de otro ámbito",
        "doi_original": "10.5555/666655554444",
        "original_title": "The Memory Bus Considered Harmful",
        "doi_incorrect": "10.5555/12345679",
        "types": ["contextual misattribution"],
        "areas": ["CIS", "ENG"],
        "reason": (
            "El original trata sobre el bus de memoria; el citante lo usa para "
            "justificar una afirmación sobre clientes ligeros en red, un contexto "
            "que el original no aborda. " + AVISO
        ),
        "evidence": (
            "Thin clients are known to degrade under network contention [12]."
        ),
        "comments": [],
        "votes": {"demo": 1},
    },
]


class Command(BaseCommand):
    help = "Carga usuarios, reportes, comentarios y votos de ejemplo para la demo."

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username=DEMO_USERNAME).exists():
            self.stdout.write("Datos de ejemplo ya cargados; no se hace nada.")
            return

        # Solo el usuario demo tiene contraseña; los demás no pueden iniciar sesión.
        users = {
            name: User.objects.create_user(username=name)
            for name in ("ana_revisora", "carlos_lector")
        }
        users[DEMO_USERNAME] = User.objects.create_user(
            username=DEMO_USERNAME, password=DEMO_PASSWORD
        )

        for data in REPORTS:
            citation = IncorrectCitation(
                author=users[data["author"]],
                doi_original=data["doi_original"],
                doi_incorrect=data["doi_incorrect"],
                incorrect_reason=data["reason"],
                metadata_original={
                    "title": data["original_title"],
                    "title_override": data["title"],
                },
                citation_contexts=normalize_evidence_items(
                    data["evidence"],
                    default_source="manual",
                    default_article="citing",
                    default_kind="manual_text",
                ),
            )
            apply_report_tags(citation, data["types"], data["areas"])
            citation.save()

            for username, content in data["comments"]:
                Comment.objects.create(
                    citation=citation, author=users[username], content=content
                )
            for username, value in data["votes"].items():
                Vote.objects.create(
                    citation=citation, user=users[username], value=value
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo cargada: {len(REPORTS)} reportes. "
                f"Usuario '{DEMO_USERNAME}' / contraseña '{DEMO_PASSWORD}'."
            )
        )
