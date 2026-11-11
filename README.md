# cli-anything-squoosh

Agent-friendly, stateful CLI for **Squoosh** image compression. Every image is
encoded by Squoosh's own WebAssembly codecs (MozJPEG, WebP, AVIF, JPEG XL, OxiPNG,
QOI, …) running in Node. Nothing is reimplemented in Python.

## Install

```bash
# 1. Requirements: Node.js 18+ and the Squoosh source tree (contains prebuilt codecs/)
brew install node
git clone https://github.com/GoogleChromeLabs/squoosh.git
export SQUOOSH_ROOT="$PWD/squoosh"

# 2. The CLI, straight from GitHub
pip install "git+https://github.com/Marcdaou/cli-anything-squoosh.git"
cli-anything-squoosh doctor
```

## Quick start

```bash
cli-anything-squoosh compress photo.png -e webp -q 75 -w 1280 -o photo.webp
```

Full reference: [`cli_anything/squoosh/README.md`](cli_anything/squoosh/README.md).
Agent skill: [`skills/cli-anything-squoosh/SKILL.md`](skills/cli-anything-squoosh/SKILL.md).

Built with the [CLI-Anything](https://github.com/HKUDS/CLI-Anything) methodology. MIT licensed.
