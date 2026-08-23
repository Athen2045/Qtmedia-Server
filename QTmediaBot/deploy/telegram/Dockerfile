FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    HOME=/home/qtmedia \
    XDG_CONFIG_HOME=/home/qtmedia/.config \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        ffmpeg \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv "${VIRTUAL_ENV}"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir ".[impersonation]"

RUN useradd --create-home --home-dir /home/qtmedia --shell /usr/sbin/nologin qtmedia \
    && mkdir -p /app/var /var/lib/qtmedia/telegram_jobs /home/qtmedia/.config \
    && chown -R qtmedia:qtmedia /app/var /var/lib/qtmedia /home/qtmedia

USER qtmedia

ENTRYPOINT ["qtmedia-bot"]
