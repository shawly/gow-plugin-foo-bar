FROM ghcr.io/games-on-whales/steam:edge

RUN <<_PLUGIN_INSTALL
echo "Hello" >> /hello

apt-get update && apt-get install -y jq
_PLUGIN_INSTALL

COPY rootfs/ /

RUN <<_MOAR_LAYERS
  echo "World!" >> /hello
  chmod +x /hello
  chown 1000:1000 /hello
_MOAR_LAYERS
