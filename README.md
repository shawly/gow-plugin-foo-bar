# Games-on-Whales Plugin Foo Bar

This is just an example idea of a future plugin implementation for [Games-on-Whales](https://github.com/games-on-whales/gow).

# Example for how this could be used in the future

## Building the plugin image

```
docker build -t gow-plugin-foo-bar:edge .
```

## Extracting the plugin layers

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r .github/workflows/requirements.txt
python .github/workflows/extract_delta_layers.py \
  ghcr.io/games-on-whales/steam:edge \
  gow-plugin-foo-bar:edge \
  --verbose --output-dir ./gow-plugin-foo-bar@edge
```

Looks like this:

```
 $ tree gow-plugin-foo-bar@edge
gow-plugin-foo-bar@edge
|____extraction_report.json
|____layers
| |____01_blobs_sha256_81952e8a70f0fbc1007e34553b3a1c840a07f6356065dad26d5bc4a1ba316d34.tar
| |____03_blobs_sha256_bac336f3a117cd070cae0216bb445ac69d5228cdb3a13e9b8ba0f02329b102a1.tar
| |____02_blobs_sha256_83de25e2825f88b8305800f703d2e8b0c7b9c26ab9f993f06e3336b0cd7a9e3f.tar
```

## Using the plugin layers in a Wolf image

```Dockerfile
# Dockerfile

FROM ghcr.io/games-on-whales/steam:edge

# gow-plugin-foo-bar@edge
ADD gow-plugin-foo-bar@edge/layers/01_blobs_sha256_81952e8a70f0fbc1007e34553b3a1c840a07f6356065dad26d5bc4a1ba316d34.tar /
ADD gow-plugin-foo-bar@edge/layers/02_blobs_sha256_83de25e2825f88b8305800f703d2e8b0c7b9c26ab9f993f06e3336b0cd7a9e3f.tar /
ADD gow-plugin-foo-bar@edge/layers/03_blobs_sha256_bac336f3a117cd070cae0216bb445ac69d5228cdb3a13e9b8ba0f02329b102a1.tar /
```

This would need to be done by Wolf itself when building the final image with all selected plugins.
