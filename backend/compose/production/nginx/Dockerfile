# Media-only edge for the local (FileSystemStorage) media backend.
# Static files are served by WhiteNoise from inside Django; this nginx serves
# ONLY /media/ from the production_django_media volume shared with Django.
# Used only when bootstrap.py was run with media=local (the aws variant serves
# media from S3 and never builds this image).
FROM docker.io/nginx:1.27-alpine

COPY ./compose/production/nginx/default.conf /etc/nginx/conf.d/default.conf
