# ---- stage 1: build the Flutter web app ----
FROM ghcr.io/cirruslabs/flutter:stable AS web
# pubspec needs Dart ^3.13.5; the image's stable channel can lag behind,
# so pin the SDK the app is developed and tested with.
ARG FLUTTER_VERSION=3.47.6
RUN git clone --depth 1 -b ${FLUTTER_VERSION} https://github.com/flutter/flutter.git /opt/flutter && /opt/flutter/bin/flutter precache --web
ENV PATH=/opt/flutter/bin:$PATH
WORKDIR /src/app
COPY app/pubspec.yaml app/pubspec.lock ./
RUN flutter pub get
COPY app/ ./
RUN flutter build web --release --no-web-resources-cdn \
 && flutter build web --release --no-web-resources-cdn -t lib/console/main.dart \
      --base-href /console/ -o build/console

# ---- stage 2: API + static web on one origin ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WEB_DIR=/srv/web CONSOLE_DIR=/srv/console DB_PATH=/data/bolo.db \
    PROMETHEUS_MULTIPROC_DIR=/tmp/bolo-prometheus
WORKDIR /srv
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY api/ api/
COPY data/ data/
COPY model/ model/
COPY ml/ ml/
COPY --from=web /src/app/build/web /srv/web
COPY --from=web /src/app/build/console /srv/console
RUN mkdir -p /data && rm -f data/bolo.db
WORKDIR /srv/api
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
# gunicorn with WEB_CONCURRENCY uvicorn workers (default: one per CPU), sharing
# the SQLite file in WAL mode; see api/gunicorn.conf.py and docs/SCALE.md
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
