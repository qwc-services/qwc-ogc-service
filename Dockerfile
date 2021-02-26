# WSGI service environment

FROM sourcepole/qwc-uwsgi-base:alpine-latest

# Required for pip with git repos
RUN apk add --no-cache --update git

# maybe set locale here if needed

ADD . /srv/qwc_service
RUN pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt
RUN pip3 install --no-cache-dir flask_cors

ENV UWSGI_PROCESSES=2
ENV UWSGI_THREADS=3
ENV UWSGI_EXTRA="--thunder-lock"
