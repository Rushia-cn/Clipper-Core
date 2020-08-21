FROM python:3.8.5-buster
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && mkdir /usr/src && cd /usr/src
    && git clone https://github.com/Rushia-cn/Clipper-Core.git

