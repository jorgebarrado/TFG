# Dependencias y Limitaciones

Este documento describe las fronteras técnicas del sistema, las dependencias externas críticas y las condiciones bajo las cuales la funcionalidad puede degradarse.

## Resumen de Dependencias Externas

| Servicio | Criticidad | Uso Principal | Riesgo Principal | Fallback |
| :--- | :--- | :--- | :--- | :--- |
| **Semantic Scholar API** | 🔴 Alta | Búsqueda de papers, grafo de citas, enlaces a PDF. | Rate Limits, API Downtime. | CrossRef (Parcial/Lento), Entrada Manual. |
| **CrossRef API** | 🟡 Media | Metadatos bibliográficos complementarios. | Lenta, datos incompletos. | Semantic Scholar. |
| **DBLP API** | 🟢 Baja | Importación de perfil de usuario. | Fallo en importación. | Edición manual de perfil. |
| **Google/ORCID Auth** | 🔴 Alta | Login de usuarios. | Credenciales inválidas. | Login local (si habilitado). |

## Limitaciones de Procesamiento de PDF

El sistema de extracción de contexto (`papermage_extractor.py`) tiene limitaciones inherentes a la naturaleza de los archivos PDF.

| Tipo de PDF | Comportamiento | Causa Técnica | Solución Potencial |
| :--- | :--- | :--- | :--- |
| **PDF Nativo (Texto seleccionable)** | ✅ Funciona | PaperMage extrae el texto correctamente. | - |
| **PDF Escaneado (Imagen)** | ❌ Falla | No hay capa de texto. `pages.spans` vacío. | Implementar OCR (Tesseract) previo. |
| **PDF Encriptado/Protegido** | ❌ Falla | `PDFPlumber` lanza excepción de seguridad. | Desencriptar (si legal) o pedir otro archivo. |
| **Doble Columna Compleja** | ⚠️ Parcial | A veces mezcla líneas de col. izq. con der. | Mejorar heurística de layout en PaperMage. |

## Limitaciones de Acceso (Open Access)

El sistema **solo puede analizar automáticamente el texto de artículos Open Access**.

*   **Paywalls (IEEE, Elsevier, Springer):** Si un artículo citador está detrás de un muro de pago, Semantic Scholar no devolverá un `openAccessPdf`.
*   **Consecuencia:** El sistema detectará que la cita existe (por metadatos), pero **no podrá extraer el contexto** ni mostrar qué se dice.
*   **Acción de Usuario:** Debe subir el PDF manualmente si tiene acceso legal.

## Fallbacks del Sistema

| Fallo | Comportamiento del Sistema | Acción del Usuario |
| :--- | :--- | :--- |
| **API Semantic Scholar Caída** | Error 502 en endpoints de búsqueda. | Debe introducir metadatos manualmente (si la UI lo permite) o esperar. |
| **PDF no descargable** | Error en extracción, el reporte se crea sin contextos. | Puede intentar subir el PDF manualmente si lo tiene. |
| **PDF sin texto (Imagen)** | Proceso termina con 0 contextos encontrados. | Debe copiar y pegar el texto manualmente en la descripción del reporte. |
