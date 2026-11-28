FROM ghcr.io/nickrunning/wechat-selkies:latest

USER 0
RUN rm /usr/bin/qq && printf '#!/bin/sh\nexec /opt/QQ/qq --force-renderer-accessibility "$@"\n' > /usr/bin/qq && chmod 755 /usr/bin/qq
RUN grep -qx 'export SELKIES_ENABLE_BASIC_AUTH=true' /wechat-container-start \
 && sed -i 's/^export SELKIES_ENABLE_BASIC_AUTH=true$/export SELKIES_ENABLE_BASIC_AUTH=${SELKIES_ENABLE_BASIC_AUTH:-true}/' /wechat-container-start
RUN rm -rf /etc/service/pipewire /etc/service/pipewire-pulse /etc/service/wireplumber

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm xdotool \
 && npm install -g corepack@0.36.0 && corepack enable \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/mc-input
COPY package.json pnpm-lock.yaml mc-input.mjs ./
RUN corepack pnpm install --prod --frozen-lockfile \
 && chmod 755 mc-input.mjs && ln -s /opt/mc-input/mc-input.mjs /usr/local/bin/mc-input
WORKDIR /config
