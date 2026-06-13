FROM docker.io/traefik:v3.7.5

# ACME email is baked into traefik.yml at build time.
# No default here — supplied as a build arg by
# docker-compose.production.yml (a raw `docker build` must pass --build-arg).
ARG TRAEFIK_ACME_EMAIL

RUN mkdir -p /etc/traefik/dynamic /etc/traefik/acme /var/log/traefik \
  && touch /etc/traefik/acme/acme.json \
  && chmod 600 /etc/traefik/acme/acme.json
COPY ./compose/production/traefik/traefik.yml /etc/traefik
COPY ./compose/production/traefik/dynamic.yml /etc/traefik/dynamic
RUN sed -i "s|__ACME_EMAIL__|${TRAEFIK_ACME_EMAIL}|g" /etc/traefik/traefik.yml
