FROM sourcepole/qwc-uwsgi-base:alpine-v2025.01.24

WORKDIR /srv/qwc_service
ADD pyproject.toml uv.lock ./

# git: Required for pip with git repos
RUN \
    apk add --no-cache --update --virtual build-deps git && \
    uv sync --frozen && \
    uv cache clean && \
    apk del build-deps

ADD src /srv/qwc_service/

ENV SERVICE_MOUNTPOINT=/ows
ENV UWSGI_PROCESSES=2
ENV UWSGI_THREADS=3
ENV UWSGI_EXTRA="--thunder-lock"
