# Código y Estilo

## Convenciones

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
