# Dependencias y Limitaciones

Este documento describe las fronteras técnicas del sistema, las dependencias externas críticas y las condiciones bajo las cuales la funcionalidad puede degradarse.

## Dependencias Externas

### 1. Semantic Scholar API (Crítica)
*   **Uso:** Fuente primaria de metadatos, grafos de citas y enlaces a PDFs Open Access.
*   **Dependencia:** `citations/services/semantic_scholar_client.py`.
*   **Riesgo:**
    *   **Rate Limits:** La API pública tiene límites estrictos. Sin una API Key, el sistema puede ser bloqueado (HTTP 429) si muchos usuarios realizan búsquedas simultáneas.
    *   **Disponibilidad:** Si Semantic Scholar cae, la búsqueda de citas y la creación de reportes basada en búsqueda automática dejará de funcionar.

### 2. CrossRef API (Secundaria)
*   **Uso:** Fuente alternativa de metadatos bibliográficos.
*   **Riesgo:** Menor. Se usa principalmente para completar datos faltantes. Es más lenta pero más estable.

### 3. DBLP API
*   **Uso:** Importación de publicaciones al perfil del usuario.
*   **Riesgo:** Bajo. Si falla, solo afecta a la funcionalidad de "Poblar perfil", no al núcleo de reportes.

---

## Limitaciones de Procesamiento de PDF

El sistema de extracción de contexto (`papermage_extractor.py`) tiene limitaciones inherentes a la naturaleza de los archivos PDF.

### 1. PDFs sin Capa de Texto (Escaneados)
*   **Problema:** Muchos papers antiguos son imágenes escaneadas.
*   **Comportamiento Actual:** El sistema extraerá una cadena vacía o basura. No encontrará ninguna cita.
*   **Solución (No implementada):** Se requeriría un paso de OCR (Tesseract) previo, lo cual es computacionalmente costoso.

### 2. PDFs con Layouts Complejos (Doble columna, Sidebars)
*   **Problema:** El parser `PDFPlumber` a veces mezcla el texto de dos columnas si no están bien delimitadas, creando oraciones sin sentido ("El gato [1] saltó sobre... la luna [2]").
*   **Impacto:** Los snippets extraídos pueden contener texto desordenado, dificultando la lectura humana.

### 3. PDFs Protegidos / Encriptados
*   **Comportamiento:** La librería lanzará una excepción y el análisis fallará.

---

## Limitaciones de Acceso (Open Access)

El sistema **solo puede analizar automáticamente el texto de artículos Open Access**.

*   **Paywalls (IEEE, Elsevier, Springer):** Si un artículo citador está detrás de un muro de pago, Semantic Scholar no devolverá un `openAccessPdf`.
*   **Consecuencia:** El sistema detectará que la cita existe (por metadatos), pero **no podrá extraer el contexto** ni mostrar qué se dice.
*   **Fallback:** En estos casos, el usuario debe (teóricamente) subir el PDF manualmente, pero esto depende de que el usuario tenga acceso legal al archivo.

---

## Fallbacks del Sistema

| Fallo | Comportamiento del Sistema | Acción del Usuario |
| :--- | :--- | :--- |
| **API Semantic Scholar Caída** | Error 502 en endpoints de búsqueda. | Debe introducir metadatos manualmente (si la UI lo permite) o esperar. |
| **PDF no descargable** | Error en extracción, el reporte se crea sin contextos. | Puede intentar subir el PDF manualmente si lo tiene. |
| **PDF sin texto (Imagen)** | Proceso termina con 0 contextos encontrados. | Debe copiar y pegar el texto manualmente en la descripción del reporte. |
