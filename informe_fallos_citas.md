# Informe de Diagnóstico: Detección y Deduplicación de Citas

Este informe detalla los resultados obtenidos al ejecutar un diagnóstico sobre los PDFs reales disponibles en `tfg_project/citations/static/citations/PDFs-Reales/`.

El análisis se ha realizado a nivel **backend** simulando el motor de extracción y analizando el comportamiento de las expresiones regulares, la lógica de validación de páginas de bibliografía y la deduplicación espacial.

## PDF Analizado: `2023.emnlp-demo.45.pdf`
- **Total de referencias extraídas:** 6
- **Total de menciones encontradas (vía regex base):** 8
- **Página de inicio de bibliografía detectada:** 7

### 1. Duplicados de menciones (Misma referencia en el mismo párrafo o muy cerca)
Se encontraron menciones duplicadas (la misma cita referenciada varias veces a muy poca distancia).

  - **Fallo:** La Referencia `[2]` aparece 4 veces en la página 4.
  - **Patrón/Motivo:** Misma referencia extraída varias veces en el mismo o adyacente párrafo.
  - **Nivel:** Backend. La lógica de agregación/deduplicación (`build_references_data` o equivalente) en el backend no limpia eficientemente las extracciones que el motor devuelve muy solapadas. El visor pinta múltiples puntos.
  - **Contexto de ejemplo:**
    > >>> doc.paragraphs[0] >>> doc.paragraphs[0].sentences[2] or >>> doc.sentences[2] >>> doc.sentences[2

### 2. Referencias mal detectadas como citas (Menciones dentro de la bibliografía)
- Ningún problema detectado en esta categoría.

### 3. Citas inválidas que aún se detectan (Fuera de rango)
Se detectaron números de cita mayores a la cantidad de referencias extraídas.

  - **Fallo:** Se menciona la referencia `[51]` en la página 4.
  - **Patrón/Motivo:** El índice de cita 51 es mayor que el total de referencias detectadas (6). Esto ocurre cuando hay ruido en el texto (ej. una lista numerada) o el PDF extrae mal las referencias, pero el sistema no filtra las menciones huérfanas.
  - **Nivel:** Backend. El JSON enviado al frontend contiene menciones a IDs que no existen en el array de `references`.
  - **Contexto de ejemplo:**
    > >>> doc.paragraphs[0] >>> doc.paragraphs[0].sentences[2] or >>> doc.sentences[2] >>> doc.sentences[2

  - **Fallo:** Se menciona la referencia `[13]` en la página 4.
  - **Patrón/Motivo:** El índice de cita 13 es mayor que el total de referencias detectadas (6). Esto ocurre cuando hay ruido en el texto (ej. una lista numerada) o el PDF extrae mal las referencias, pero el sistema no filtra las menciones huérfanas.
  - **Nivel:** Backend. El JSON enviado al frontend contiene menciones a IDs que no existen en el array de `references`.
  - **Contexto de ejemplo:**
    > >>> doc.paragraphs[0] >>> doc.paragraphs[0].sentences[2] or >>> doc.sentences[2] >>> doc.sentences[2

  - **Fallo:** Se menciona la referencia `[46]` en la página 4.
  - **Patrón/Motivo:** El índice de cita 46 es mayor que el total de referencias detectadas (6). Esto ocurre cuando hay ruido en el texto (ej. una lista numerada) o el PDF extrae mal las referencias, pero el sistema no filtra las menciones huérfanas.
  - **Nivel:** Backend. El JSON enviado al frontend contiene menciones a IDs que no existen en el array de `references`.
  - **Contexto de ejemplo:**
    > >>> doc.paragraphs[0] >>> doc.paragraphs[0].sentences[2] or >>> doc.sentences[2] >>> doc.sentences[2

  *(... y 1 casos más)*

### 4 y 5. Problemas de formato y agrupaciones raras
- Ningún problema detectado en esta categoría.

---

## PDF Analizado: `education-12-00179-v3.pdf`
- **Total de referencias extraídas:** 11
- **Total de menciones encontradas (vía regex base):** 13
- **Página de inicio de bibliografía detectada:** 6

### 1. Duplicados de menciones (Misma referencia en el mismo párrafo o muy cerca)
- Ningún problema detectado en esta categoría.

### 2. Referencias mal detectadas como citas (Menciones dentro de la bibliografía)
- Ningún problema detectado en esta categoría.

### 3. Citas inválidas que aún se detectan (Fuera de rango)
- Ningún problema detectado en esta categoría.

### 4 y 5. Problemas de formato y agrupaciones raras
- Ningún problema detectado en esta categoría.

---

## PDF Analizado: `education-12-00274.pdf`
- **Total de referencias extraídas:** 53
- **Total de menciones encontradas (vía regex base):** 81
- **Página de inicio de bibliografía detectada:** 19

### 1. Duplicados de menciones (Misma referencia en el mismo párrafo o muy cerca)
Se encontraron menciones duplicadas (la misma cita referenciada varias veces a muy poca distancia).

  - **Fallo:** La Referencia `[2]` aparece 2 veces en la página 1.
  - **Patrón/Motivo:** Misma referencia extraída varias veces en el mismo o adyacente párrafo.
  - **Nivel:** Backend. La lógica de agregación/deduplicación (`build_references_data` o equivalente) en el backend no limpia eficientemente las extracciones que el motor devuelve muy solapadas. El visor pinta múltiples puntos.
  - **Contexto de ejemplo:**
    >   Citation: Chatzopoulos, A.; Kalogiannakis, M.; Papadakis, S.; Papoutsidakis, M. A

  - **Fallo:** La Referencia `[4]` aparece 2 veces en la página 1.
  - **Patrón/Motivo:** Misma referencia extraída varias veces en el mismo o adyacente párrafo.
  - **Nivel:** Backend. La lógica de agregación/deduplicación (`build_references_data` o equivalente) en el backend no limpia eficientemente las extracciones que el motor devuelve muy solapadas. El visor pinta múltiples puntos.
  - **Contexto de ejemplo:**
    >   Citation: Chatzopoulos, A.; Kalogiannakis, M.; Papadakis, S.; Papoutsidakis, M. A

  - **Fallo:** La Referencia `[6]` aparece 2 veces en la página 1.
  - **Patrón/Motivo:** Misma referencia extraída varias veces en el mismo o adyacente párrafo.
  - **Nivel:** Backend. La lógica de agregación/deduplicación (`build_references_data` o equivalente) en el backend no limpia eficientemente las extracciones que el motor devuelve muy solapadas. El visor pinta múltiples puntos.
  - **Contexto de ejemplo:**
    >   Citation: Chatzopoulos, A.; Kalogiannakis, M.; Papadakis, S.; Papoutsidakis, M. A

  *(... y 7 casos más)*

### 2. Referencias mal detectadas como citas (Menciones dentro de la bibliografía)
Se detectaron números como menciones que en realidad forman parte de la sección de Bibliografía.

  - **Fallo:** La Referencia `[47]` se marcó como mención en la página 18 (La bibliografía empieza en la pág 18 index=0).
  - **Patrón/Motivo:** Página 18 está en o después de la sección de referencias (Inicia en 18). El backend no descarta correctamente los hallazgos producidos después del `bibliography_start_page`.
  - **Nivel:** Backend. El JSON final contendrá menciones que en realidad son entradas de la lista de referencias.
  - **Contexto de ejemplo:**
    > Educ. Sci. 2022, 12, 274 18 of 21 Table 14. Descriptive statistics for variables. PEOU PU ATU BIU N

  - **Fallo:** La Referencia `[48]` se marcó como mención en la página 18 (La bibliografía empieza en la pág 18 index=0).
  - **Patrón/Motivo:** Página 18 está en o después de la sección de referencias (Inicia en 18). El backend no descarta correctamente los hallazgos producidos después del `bibliography_start_page`.
  - **Nivel:** Backend. El JSON final contendrá menciones que en realidad son entradas de la lista de referencias.
  - **Contexto de ejemplo:**
    > Educ. Sci. 2022, 12, 274 18 of 21 Table 14. Descriptive statistics for variables. PEOU PU ATU BIU N

  - **Fallo:** La Referencia `[49]` se marcó como mención en la página 18 (La bibliografía empieza en la pág 18 index=0).
  - **Patrón/Motivo:** Página 18 está en o después de la sección de referencias (Inicia en 18). El backend no descarta correctamente los hallazgos producidos después del `bibliography_start_page`.
  - **Nivel:** Backend. El JSON final contendrá menciones que en realidad son entradas de la lista de referencias.
  - **Contexto de ejemplo:**
    > Educ. Sci. 2022, 12, 274 18 of 21 Table 14. Descriptive statistics for variables. PEOU PU ATU BIU N

  *(... y 5 casos más)*

### 3. Citas inválidas que aún se detectan (Fuera de rango)
- Ningún problema detectado en esta categoría.

### 4 y 5. Problemas de formato y agrupaciones raras
- Ningún problema detectado en esta categoría.

---


## Sobre Problemas de Posicionamiento y Citas No Detectadas
Durante el análisis estático en Backend hemos visto:

- **Casos de menciones no detectadas:** Si el texto es ruidoso (ej. el genérico o Papermage junta texto mal debido a dos columnas, o una ecuación corta el flujo numérico), la regex puede fallar estrepitosamente. Esto es un fallo claro del **Backend (Extractor Genérico)**, que requiere refinar la extracción PDF -> Texto antes de aplicar la Regex.
- **Posicionamiento (Highlights desalineados):** El backend a través de `generic_extractor` sólo calcula índices de párrafo. En producción (con `Papermage` / `Papercraft`), se cruzan cajas de token (bounding boxes) que, si están mal en origen, causan desalineamientos. Esto se considera un fallo híbrido: Backend calcula un área errónea en `_pick_best_text_box` (en `references_data.py`), y el Frontend lo pinta ahí de forma "correcta" pero visualmente equivocada.
