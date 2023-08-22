FROM sourcepole/qwc-uwsgi-base:alpine-v2022.01.26

ADD . /srv/qwc_service

# git: Required for pip with git repos
RUN \
    apk add --no-cache --update --virtual build-deps git && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apk del build-deps

ENV SERVICE_MOUNTPOINT=/ows
ENV UWSGI_PROCESSES=2
ENV UWSGI_THREADS=3
ENV UWSGI_EXTRA="--thunder-lock"
