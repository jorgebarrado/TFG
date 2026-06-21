FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
ARG TARGETARCH
RUN python - <<'PY'
import os
from pathlib import Path

raw = Path("/tmp/requirements.txt").read_bytes()
for enc in ("utf-8-sig", "utf-16", "utf-16-le"):
    try:
        text = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
else:
    text = raw.decode("latin-1")

target_arch = os.environ.get("TARGETARCH", "")
lines = []
for line in text.splitlines():
    stripped = line.strip()
    lower = stripped.lower()
    if lower.startswith("pywin32=="):
        continue
    # PyTorch's ARM Linux index omits the +cpu local tag for some companion wheels.
    if target_arch == "arm64" and stripped.endswith("+cpu"):
        if lower.startswith("torchaudio==") or lower.startswith("torchvision=="):
            line = line.replace("+cpu", "")
    lines.append(line)

Path("/tmp/requirements.linux.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)
PY

RUN pip install --upgrade pip \
    && pip install --no-deps --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements.linux.txt

COPY . /app

EXPOSE 8000

WORKDIR /app/tfg_project
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
