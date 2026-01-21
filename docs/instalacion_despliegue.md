# Guía de Instalación y Despliegue

Esta guía detalla los pasos para configurar el entorno de desarrollo completo para CiteCheck, incluyendo el backend Django y el componente frontend en React.

## Requisitos Previos

*   **Python 3.13+** instalado.
*   **Node.js 18+** y **npm** (para el componente frontend).
*   **Git** para control de versiones.
*   **Herramientas de compilación C++** (necesarias para algunas librerías de Python como `numpy` o `torch` en algunos sistemas).

## 1. Configuración del Backend (Django)

### 1.1 Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd tfg_project
```

### 1.2 Crear entorno virtual

Es altamente recomendable usar un entorno virtual para aislar las dependencias.

```bash
python -m venv venv
# Activar en Linux/Mac:
source venv/bin/activate
# Activar en Windows:
.\venv\Scripts\activate
```

### 1.3 Instalar dependencias

El proyecto tiene dependencias específicas, incluyendo PyTorch para CPU (para evitar descargas masivas de CUDA si no se requiere GPU).

```bash
pip install -r requirements-3.13.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

### 1.4 Configuración de la Base de Datos

El proyecto utiliza SQLite por defecto. Aplica las migraciones iniciales:

```bash
python tfg_project/manage.py migrate
```

### 1.5 Crear Superusuario

Para acceder al panel de administración de Django (`/admin`):

```bash
python tfg_project/manage.py createsuperuser
```

### 1.6 Ejecutar el servidor de desarrollo

```bash
python tfg_project/manage.py runserver
```

El servidor estará disponible en `http://127.0.0.1:8000/`.

---

## 2. Configuración del Frontend (Lector PDF)

El componente de lectura de PDFs (`frontend_reader`) es una aplicación React construida con Vite.

### 2.1 Instalar dependencias

Navega al directorio del frontend e instala los paquetes:

```bash
cd frontend_reader
npm install
```

### 2.2 Desarrollo

Para trabajar en el frontend con recarga en caliente (Hot Module Replacement):

```bash
npm run dev
```

### 2.3 Construcción (Build)

Para generar los archivos estáticos que Django servirá en producción (o integración):

```bash
npm run build
```

Esto generará los archivos en `frontend_reader/dist` (o la carpeta configurada en `vite.config.js`). Asegúrate de que Django esté configurado para recolectar estos estáticos si se despliega en producción.

---

## 3. Variables de Entorno y Configuración

El proyecto puede requerir variables de entorno para APIs externas. Crea un archivo `.env` en la raíz si es necesario (o expórtalas en tu shell).

*   `LOG_CITATIONS=1`: Habilita logs detallados para el sistema de extracción de contextos.
*   `INCLUDE_TRACE_IN_RESPONSE=1`: Incluye trazas de depuración en las respuestas JSON de la API (útil para desarrollo).
*   Claves de API (si aplica): `SEMANTIC_SCHOLAR_API_KEY`, etc.

## 4. Pruebas

Para ejecutar la suite de pruebas del backend:

```bash
python tfg_project/manage.py test citations
```

Nota: Para ejecutar las pruebas frontend (si existen), revisa los scripts en `frontend_reader/package.json`.
