# Models

- [`manifest.json`](manifest.json): the models sūveryn is validated with: where each comes from, the publisher's
  commit, the file's size and checksum, its licence and, for a language model, llama-server's options.
- [`scripts/presets.py`](scripts/presets.py): writes llama-server's router presets from the manifest, so a model's
  settings are written in one place (suveryn-tracker#133). How to run it: the repository's README, *Run locally*.
