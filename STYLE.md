# Código, Estilo y Calidad

El proyecto usa Black, isort, Flake8 y pre-commit. La configuración de formato vive en `pyproject.toml`; los hooks están en `.pre-commit-config.yaml`.

## Instalación

```powershell
python -m pip install -U black isort flake8 pre-commit
pre-commit install
```

## Comandos Habituales

```powershell
python -m black .
python -m isort .
python -m flake8
pre-commit run --all-files
```

## Convenciones

- Línea máxima: 88 caracteres.
- Formato Python: Black.
- Orden de imports: isort con perfil Black.
- Excepciones Flake8: `E203` y `W503`, para compatibilidad con Black.
- Evita mezclar refactors de estilo con cambios funcionales o de documentación.
- Mantén los artefactos generados fuera de commits salvo que sean fixtures deliberados.

## Verificación Relevante

Para cambios de backend:

```powershell
python tfg_project/manage.py check
python tfg_project/manage.py test citations
```

Para cambios del reader:

```powershell
cd frontend_reader
npm run build
```

Para cambios en extracción de referencias:

```powershell
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
python scripts/run_reference_regression.py --engine papermage --limit 1
```
