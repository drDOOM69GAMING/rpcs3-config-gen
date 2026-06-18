# RPCS3 Config Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automatically generate RPCS3 per-game configuration files from wiki settings. Scans your installed games, builds a database from saved RPCS3 wiki pages, and produces `config_SERIAL.yml` files with correct resolution scaling — no manual tinkering.

## How it works

```
┌─────────────┐    ┌──────────┐    ┌───────────────────┐
│  wiki_pages/ │───▶│  Scan   │───▶│  rpcs3_configs.json│
│  (HTML files)│    │         │    │  (settings DB)    │
└─────────────┘    └────┬─────┘    └────────┬──────────┘
                        │                   │
┌─────────────┐         │                   │
│Installed_   │─────────┘                   │
│within_rpcs3 │                             │
│(game list)  │                             ▼
└─────────────┘                   ┌───────────────────┐
                                 │  Generate         │
                                 │  config_SERIAL.yml │
                                 └───────────────────┘
```

## Quick start

### Requirements
- Linux with Python 3.12+
- RPCS3 installed with games

### Run the AppImage

[Download the AppImage](../../releases) and place it alongside:

```
your-folder/
├── RPCS3_Config_Generator-x86_64.AppImage
├── wiki_pages/            ← saved wiki HTML files
└── Installed_within_rpcs3  ← your game list
```

**Both `wiki_pages/` and `Installed_within_rpcs3` must be in the same directory as the AppImage.** The tool auto-detects them from the AppImage's location.

Double-click the AppImage — it shows an interactive menu.

### Run from source

```bash
git clone https://github.com/YOUR_USER/rpcs3-config-gen
cd rpcs3-config-gen

pip install -r requirements.txt
python3 rpcs3-config-generator.py --scan-only --local-wiki wiki_pages --installed-list Installed_within_rpcs3
python3 rpcs3-config-generator.py --generate --installed-list Installed_within_rpcs3
```

## Usage

```
Flags:  --scan-only  --generate  --list  --force  --missing  --local-wiki <dir>  --installed-list <file>  --help

Examples:
  # Interactive menu (double-click AppImage or no args)
  ./RPCS3_Config_Generator-x86_64.AppImage

  # Show game/DB/config status
  ./RPCS3_Config_Generator-x86_64.AppImage --list --installed-list Installed_within_rpcs3

  # Full run
  ./RPCS3_Config_Generator-x86_64.AppImage --scan-only --local-wiki wiki_pages --installed-list Installed_within_rpcs3
  ./RPCS3_Config_Generator-x86_64.AppImage --generate --installed-list Installed_within_rpcs3
```

## Wiki data

Each file is named `SERIAL.html` (e.g. `BCUS98114.html`). The script matches by serial — no title guessing.

Expected settings are parsed from `<table class="wikitable">` on the RPCS3 wiki.

## Resolution scaling

The tool reads `(Can Upscale)` / `(Cant Upscale)` from your game list and sets the resolution accordingly:

- **Can Upscale** → `Resolution Scale: 150` (1920×1080)
- **Cant Upscale** → `Resolution Scale: 100` (1280×720)

## Output

Configs are written to `~/.config/rpcs3/custom_configs/config_SERIAL.yml`.

Each config starts from RPCS3 factory defaults, overlays wiki-recommended settings, and applies the resolution scale from your game list.

## Building the AppImage

```bash
pip install pyinstaller
pyinstaller --onefile --name rpcs3-config-generator rpcs3-config-gui.py
# Then wrap with appimagetool
```
<img width="818" height="620" alt="Screenshot from 2026-06-18 12-45-23" src="https://github.com/user-attachments/assets/405798f9-4626-4f08-aafe-51d34f06bb94" />
