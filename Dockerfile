ARG BASE_TAG=latest
FROM sourcepole/qwc-uwsgi-base:alpine-$BASE_TAG

ARG UPDATE_DEPS=false

WORKDIR /srv/qwc_service

COPY pyproject.toml uv.lock ./

# git: Required for pip with git repos
# postgresql-dev g++ python3-dev: Required for psycopg2
RUN \
    apk add --no-cache --update --virtual runtime-deps postgresql-libs musl-locales musl-locales-lang && \
    apk add --no-cache --update --virtual build-deps git postgresql-dev g++ python3-dev && \
    if [ "${UPDATE_DEPS}" = "true" ]; then \
        uv lock --upgrade; \
    fi && \
    uv sync --frozen && \
    uv cache clean && \
    apk del build-deps

COPY src /srv/qwc_service/

ENV SERVICE_MOUNTPOINT=/ows
ENV UWSGI_PROCESSES=2
ENV UWSGI_THREADS=3
ENV UWSGI_EXTRA="--thunder-lock"
ENV MUSL_LOCPATH=/usr/share/i18n/locales/musl
