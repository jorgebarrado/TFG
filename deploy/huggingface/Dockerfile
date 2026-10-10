# Demo pública de CiteCheck en Hugging Face Spaces (SDK Docker, plan gratuito).
# El Space solo contiene este Dockerfile y el README.md de esta carpeta: el código
# se clona de GitHub. Tras un push a main, usa "Factory rebuild" en el Space para
# que no reutilice la capa cacheada del clone.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ALLOWED_HOSTS=.hf.space \
    CSRF_TRUSTED_ORIGINS=https://*.hf.space \
    LOG_CITATIONS=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Spaces ejecuta el contenedor con el uid 1000.
RUN useradd -m -u 1000 user
USER user
ENV PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user

RUN git clone --depth 1 https://github.com/jorgebarrado/TFG.git app
WORKDIR /home/user/app/tfg_project

RUN pip install --user -r ../requirements-demo.txt \
    && pip install --user --no-deps "papermage @ git+https://github.com/allenai/papermage.git@3781ae08a787f1b2e755a9eff69ec029a6749a8c"

EXPOSE 7860

# Un solo worker: la caché (LocMemCache) y la SECRET_KEY autogenerada viven en el proceso.
# Timeout alto porque la extracción de PDFs es síncrona.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:7860 --workers 1 --threads 4 --timeout 300"]
