#!/tmp/rpcs3_venv/bin/python3
"""
RPCS3 Game Config Generator — v2
  Two-phase: scan wiki → save DB → generate configs from DB.

Project folder: ~/rpcs3-config-generator/
  wiki_pages/       ← save HTML files here (Right-click → Save as → "Webpage, HTML only")
  rpcs3_configs.json  ← local DB (auto-generated, stored in ~/.config/rpcs3/)

Usage:
  # Save wiki pages to wiki_pages/ first, then:
  python3 rpcs3-config-generator.py --scan-only --local-wiki wiki_pages

  # Generate configs from the database:
  python3 rpcs3-config-generator.py --generate

  # Scan + generate in one go (tries online, use --local-wiki for local):
  python3 rpcs3-config-generator.py

  # Other flags:
  python3 rpcs3-config-generator.py --list            # Show game/DB/config status
  python3 rpcs3-config-generator.py --force BLUS30109  # Re-scan specific game
  python3 rpcs3-config-generator.py --missing          # Process new games only
"""

import os
import re
import sys
import time
import random
import json
import struct
from copy import deepcopy
from urllib.parse import quote, unquote
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lxml import html

"""
Usage:
  # With user's installed list (REQUIRED for full coverage):
  python3 rpcs3-config-generator.py --scan-only --local-wiki wiki_pages --installed-list Installed_within_rpcs3
  python3 rpcs3-config-generator.py --generate --installed-list Installed_within_rpcs3
  python3 rpcs3-config-generator.py --list --installed-list Installed_within_rpcs3
  python3 rpcs3-config-generator.py --local-wiki wiki_pages --installed-list Installed_within_rpcs3 --force
"""

# ─── Paths ───────────────────────────────────────────────────────────────────
RPCS3_CONFIG_DIR = os.path.expanduser("~/.config/rpcs3")
CUSTOM_CONFIGS_DIR = os.path.join(RPCS3_CONFIG_DIR, "custom_configs")
GAMES_YML = os.path.join(RPCS3_CONFIG_DIR, "games.yml")
DEV_HDD0_GAME = os.path.join(RPCS3_CONFIG_DIR, "dev_hdd0", "game")
DB_PATH = os.path.join(RPCS3_CONFIG_DIR, "rpcs3_configs.json")

# ─── URLs ────────────────────────────────────────────────────────────────────
LIVE_WIKI_URL = "https://wiki.rpcs3.net/index.php?title={title}"
WAYBACK_URL = "https://web.archive.org/web/20260618000000/https://wiki.rpcs3.net/index.php?title={title}"
WAYBACK_URL_2025 = "https://web.archive.org/web/2025/https://wiki.rpcs3.net/index.php?title={title}"

# ─── Special character substitutions for game titles ─────────────────────────
TITLE_SUBSTITUTIONS = {
    "Σ": "Sigma", "σ": "Sigma", "Δ": "Delta", "δ": "Delta",
    "Ω": "Omega", "ω": "Omega", "α": "Alpha", "β": "Beta",
    "Γ": "Gamma", "γ": "Gamma", "vs.": "Vs.", "vs": "Vs.",
    "Ⅳ": "IV", "Ⅲ": "III", "Ⅱ": "II",
}

# ─── Setting Mapping ─────────────────────────────────────────────────────────
SETTING_MAP = {
    "SPU xfloat accuracy": {"section": "Core", "key": "SPU XFloat Accuracy",
        "transform": lambda v: "Approximate" if v.strip().lower() == "relaxed" else v.strip()},
    "SPU block size": {"section": "Core", "key": "SPU Block Size",
        "transform": lambda v: v.strip()},
    "ZCULL accuracy": {"section": "Video", "key": "Relaxed ZCULL Sync",
        "transform": lambda v: v.strip().lower() == "relaxed",
        "side_effects": lambda cfg, v: cfg.setdefault("Video", {}).__setitem__(
            "Accurate ZCULL stats", v.strip().lower() != "relaxed")},
    "Resolution scale threshold": {"section": "Video", "key": "Minimum Scalable Dimension",
        "transform": lambda v: int(v.split("x")[0]) if "x" in v else int(v)},
    "Multithreaded RSX": {"section": "Video", "key": "Multithreaded RSX",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Asynchronous texture streaming": {"section": "Video", "subkey": "Vulkan",
        "key": "Asynchronous Texture Streaming",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Asynchronous Texture Streaming": {"section": "Video", "subkey": "Vulkan",
        "key": "Asynchronous Texture Streaming",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Sleep timers accuracy": {"section": "Core", "key": "Sleep Timers Accuracy",
        "transform": lambda v: v.strip()},
    "RSX FIFO accuracy": {"section": "Core", "key": "RSX FIFO Fetch Accuracy",
        "transform": lambda v: v.strip()},
    "Disable ZCull occlusion queries": {"section": "Video", "key": "Disable ZCull Occlusion Queries",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "PPU Decoder": {"section": "Core", "key": "PPU Decoder",
        "transform": lambda v: v.strip()},
    "SPU Decoder": {"section": "Core", "key": "SPU Decoder",
        "transform": lambda v: v.strip()},
    "SPU Cache": {"section": "Core", "key": "SPU Cache",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Preferred SPU Threads": {"section": "Core", "key": "Preferred SPU Threads",
        "transform": lambda v: int(v.strip().split()[0].split("-")[0].strip())},
    "Thread Scheduler Mode": {"section": "Core", "key": "Thread Scheduler Mode",
        "transform": lambda v: v.strip()},
    "Enable PPU LLVM Greedy Mode": {"section": "Core", "key": "PPU LLVM Greedy Mode",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Driver Wake-Up Delay": {"section": "Video", "key": "Driver Wake-Up Delay",
        "transform": lambda v: int(v.strip())},
    "Read Color Buffers": {"section": "Video", "key": "Read Color Buffers",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Write Color Buffers": {"section": "Video", "key": "Write Color Buffers",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Shader Mode": {"section": "Video", "key": "Shader Mode",
        "transform": lambda v: v.strip()},
    "Resolution Scale": {"section": "Video", "key": "Resolution Scale",
        "transform": lambda v: int(v.strip().rstrip("%"))},
    "Frame Limit": {"section": "Video", "key": "Frame limit",
        "transform": lambda v: v.strip()},
    "Anisotropic Filter Override": {"section": "Video", "key": "Anisotropic Filter Override",
        "transform": lambda v: int(v.strip()) if v.strip().isdigit() else 0},
    "VSync Mode": {"section": "Video", "key": "VSync Mode",
        "transform": lambda v: v.strip()},
    "Shader Compiler Threads": {"section": "Video", "key": "Shader Compiler Threads",
        "transform": lambda v: int(v.strip())},
    "PPU LLVM Greedy Mode": {"section": "Core", "key": "PPU LLVM Greedy Mode",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Relaxed ZCULL Sync": {"section": "Video", "key": "Relaxed ZCULL Sync",
        "transform": lambda v: v.strip().lower() in ("on", "true", "relaxed"),
        "side_effects": lambda cfg, v: cfg.setdefault("Video", {}).__setitem__(
            "Accurate ZCULL stats", v.strip().lower() not in ("on", "true", "relaxed"))},
    "Maximum SPURS threads": {"section": "Core", "key": "Max SPURS Threads",
        "transform": lambda v: int(v.strip())},
    "Enable thread scheduler": {"section": "Core", "key": "Thread Scheduler Mode",
        "transform": lambda v: v.strip()},
    "Strict Rendering Mode": {"section": "Video", "key": "Strict Rendering Mode",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "GPU Texture Scaling": {"section": "Video", "key": "Use GPU texture scaling",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Resolution": {"section": "Video", "key": "Resolution",
        "transform": lambda v: v.strip()},
    "ZCULL Occlusion Query Accuracy": {"section": "Video", "key": "Accurate ZCULL stats",
        "transform": lambda v: v.strip().lower() not in ("relaxed", "off", "false")},
    "Framelimit": {"section": "Video", "key": "Frame limit",
        "transform": lambda v: v.strip()},
    "Accurate RSX reservation access": {"section": "Core", "key": "Accurate RSX reservation access",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
    "Anti-aliasing": {"section": "Video", "key": "MSAA",
        "transform": lambda v: v.strip()},
    "Anisotropic filter": {"section": "Video", "key": "Anisotropic Filter Override",
        "transform": lambda v: int(v.strip().rstrip("x").strip())},
    "Read color buffers": {"section": "Video", "key": "Read Color Buffers",
        "transform": lambda v: v.strip().lower() in ("on", "true")},
}
SETTING_MAP_CI = {k.lower(): v for k, v in SETTING_MAP.items()}

# ─── Default Config Template ────────────────────────────────────────────────
DEFAULT_OVERRIDES = {
    "Core": {
        "SPU XFloat Accuracy": "Approximate",
        "SPU Block Size": "Safe",
        "Sleep Timers Accuracy": "As Host",
        "RSX FIFO Fetch Accuracy": "Atomic",
        "PPU Decoder": "Recompiler (LLVM)",
        "SPU Decoder": "Recompiler (LLVM)",
        "SPU Cache": True,
        "Preferred SPU Threads": 0,
        "Thread Scheduler Mode": "Operating System",
        "PPU LLVM Greedy Mode": False,
        "Accurate Cache Line Stores": False,
        "Accurate PPU 128-byte Reservation Op Max Length": 0,
        "Accurate RSX reservation access": False,
        "Accurate SPU DMA": False,
        "Accurate SPU Reservations": True,
        "Allow RSX CPU Preemptions": True,
        "Clocks scale": 100,
        "LLVM Precompilation": True,
        "Max SPURS Threads": 6,
        "PPU Accurate Non-Java Mode": False,
        "PPU Accurate Vector NaN Values": False,
        "PPU Threads": 2,
        "PPU Vector NaN Handling": True,
        "SPU delay penalty": 3,
        "SPU loop detection": False,
        "SPU Verification": True,
        "Set DAZ and FTZ": False,
        "Use Accurate DFMA": True,
    },
    "Video": {
        "Accurate ZCULL stats": True,
        "Relaxed ZCULL Sync": False,
        "Disable ZCull Occlusion Queries": False,
        "Multithreaded RSX": False,
        "Minimum Scalable Dimension": 16,
        "Resolution Scale": 150,
        "Resolution": "1920x1080",
        "Frame limit": "Auto",
        "Anisotropic Filter Override": 0,
        "VSync Mode": "Full",
        "Shader Mode": "Async Recompiler (multi-threaded)",
        "Shader Compiler Threads": 0,
        "Read Color Buffers": False,
        "Write Color Buffers": False,
        "Vblank Rate": 60,
        "Strict Rendering Mode": False,
        "Force High Precision Z buffer": False,
        "Output Scaling Mode": "Bilinear",
        "Aspect ratio": "16:9",
        "MSAA": "Auto",
        "Driver Wake-Up Delay": 0,
        "Vulkan": {
            "Asynchronous Texture Streaming": False,
            "Asynchronous Queue Scheduler": "Safe",
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  PARAM.SFO parser
# ═══════════════════════════════════════════════════════════════════════════════

def parse_psf(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[0:4] != b'\x00PSF':
        raise ValueError("Bad PSF magic")
    key_table_off = struct.unpack_from("<I", data, 8)[0]
    data_table_off = struct.unpack_from("<I", data, 12)[0]
    num_entries = struct.unpack_from("<H", data, 16)[0]
    result = {}
    for i in range(num_entries):
        off = 20 + i * 16
        ed = data[off:off+16]
        key_off = struct.unpack_from("<H", ed, 0)[0]
        data_type = ed[3]
        data_len = struct.unpack_from("<I", ed, 4)[0]
        data_start = struct.unpack_from("<I", ed, 12)[0]
        key_end = data.index(b'\0', key_table_off + key_off)
        key_name = data[key_table_off + key_off:key_end].decode('ascii')
        raw = data[data_table_off + data_start : data_table_off + data_start + data_len]
        if data_type == 2:
            value = raw.rstrip(b'\0').decode('utf-8', errors='replace')
        elif data_type == 4:
            value = struct.unpack_from("<I", raw, 0)[0]
        else:
            value = raw.hex()
        result[key_name] = value
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Session / HTTP helpers
# ═══════════════════════════════════════════════════════════════════════════════

def make_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    })
    return session

_session = None
_last_request_time = 0

def rate_limited_get(url, **kwargs):
    global _session, _last_request_time
    if _session is None:
        _session = make_session()
    elapsed = time.time() - _last_request_time
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed + random.uniform(0.1, 0.5))
    _last_request_time = time.time()
    return _session.get(url, timeout=30, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
#  Game scanning
# ═══════════════════════════════════════════════════════════════════════════════

def load_installed_list(path):
    """Parse user's game list file (format: Title [SERIAL] (Playable) (Can Upscale)).
    Returns dict: serial -> {name, can_upscale: bool, status: str}"""
    games = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.search(r'\[([A-Z0-9_-]{4,15})\]', line)
            if not m:
                continue
            serial = m.group(1)
            title = line[:m.start()].strip().rstrip()
            can_upscale = "(Can Upscale)" in line
            status_m = re.search(r'\((Playable|Ingame)\)', line, re.I)
            status = status_m.group(1) if status_m else ""
            games[serial] = {"name": title, "can_upscale": can_upscale, "status": status}
    return games

def load_installed_games(installed_list_path=None):
    """Return {serial: name} for all installed games.
    If installed_list_path is given, use that as authoritative source.
    Otherwise scan dev_hdd0/game/ via PARAM.SFO."""
    if installed_list_path:
        result = {}
        for serial, info in load_installed_list(installed_list_path).items():
            result[serial] = info["name"]
        return result
    games = {}
    if not os.path.isdir(DEV_HDD0_GAME):
        return games
    for serial in sorted(os.listdir(DEV_HDD0_GAME)):
        if serial.startswith("$") or serial in ("NPIA00001", "NPIA00025"):
            continue
        param_path = os.path.join(DEV_HDD0_GAME, serial, "PARAM.SFO")
        if not os.path.exists(param_path):
            continue
        try:
            psf = parse_psf(param_path)
            title = psf.get("TITLE", "").strip()
            title = " ".join(title.splitlines())
            if title:
                games[serial] = title
        except (ValueError, OSError, IndexError):
            continue
    return games


# ═══════════════════════════════════════════════════════════════════════════════
#  Database (JSON) helpers
# ═══════════════════════════════════════════════════════════════════════════════

def load_db():
    if not os.path.exists(DB_PATH):
        return {}
    with open(DB_PATH) as f:
        return json.load(f)

def save_db(db):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def db_entry_exists(db, serial):
    return serial in db and db[serial].get("settings") is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Wiki scraping — live + Wayback Machine fallback
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_game_title(game_name):
    small_words = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by"}
    words = game_name.split()
    result_words = []
    for i, w in enumerate(words):
        stripped = w.rstrip(".,:;!?")
        is_upper = stripped.isupper() and len(stripped) > 1
        if is_upper:
            w = stripped.title()
        elif w.lower() in small_words and i > 0:
            w = w.lower()
        else:
            w = stripped.capitalize() if stripped.istitle() or stripped.islower() else stripped
        result_words.append(w)
    result = " ".join(result_words)
    result = re.sub(r' (\d+) ([A-Z])', r' \1: \2', result)
    return result

def wiki_title_variants(game_name):
    variants = []
    # Strip Unicode symbols first
    clean = game_name.replace("\u2122", "").replace("\u00ae", "")
    # Original
    variants.append(clean)
    # Strip parentheticals and trailing qualifiers
    for v in list(variants):
        # Substitution variants
        for old, new in TITLE_SUBSTITUTIONS.items():
            if old in v:
                subbed = v.replace(old, new)
                subbed = re.sub(r'\s+', ' ', subbed).strip()
                if subbed not in variants:
                    variants.append(subbed)
    # Normalized
    norm = normalize_game_title(clean)
    if norm not in variants:
        variants.append(norm)
    # Title case
    tc = clean.title()
    if tc not in variants:
        variants.append(tc)
    # Proper case (all-caps words -> capitalized)
    words = clean.split()
    proper = [w.capitalize() if w == w.upper() else w for w in words]
    pc = " ".join(proper)
    if pc not in variants:
        variants.append(pc)
    # Strip parentheticals like "(Trial Version)", "(Update Data)"
    for v in list(variants):
        clean_v = re.sub(r'\s*\(.*?\)\s*', ' ', v).strip()
        clean_v = re.sub(r'\s+', ' ', clean_v)
        if clean_v and clean_v not in variants:
            variants.append(clean_v)
        # Strip trailing qualifiers
        for suffix in ["Update", "DLC", "Additional Content", "Patches", "Patch",
                       "Update Data", "Trial Version", "Trial", "Demo",
                       "Unlock Key", "Digital"]:
            clean_s = re.sub(rf'\s+{re.escape(suffix)}\s*$', '', clean_v, flags=re.I).strip()
            if clean_s and clean_s != clean_v and clean_s not in variants:
                variants.append(clean_s)
    return variants


def extract_snapshot_date(response):
    memento = response.headers.get("memento-datetime", "")
    if memento:
        try:
            return datetime.strptime(memento, "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            pass
    url_date = re.search(r'/web/(\d{14})/', response.url)
    if url_date:
        try:
            return datetime.strptime(url_date.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def is_cloudflare_blocked(text):
    checks = [
        "Just a moment" in text,
        "challenge" in text.lower()[:500],
        "Checking your browser" in text[:500],
        "attention required" in text.lower()[:500],
        "cf-browser-verification" in text,
    ]
    return any(checks)


def parse_config_tables(html_content):
    tree = html.fromstring(html_content)
    tables = tree.cssselect("table.wikitable")
    settings = {}
    for table in tables:
        prev = table.getprevious()
        section_name = ""
        while prev is not None:
            if prev.tag in ("h2", "h3", "h4"):
                section_name = prev.text_content().strip()
                break
            prev = prev.getprevious()
        rows = table.cssselect("tr")
        if not rows:
            continue
        headers = [h.text_content().strip().lower() for h in rows[0].cssselect("th,td")]
        if "setting" not in headers or "option" not in headers:
            continue
        for row in rows[1:]:
            cells = row.cssselect("td")
            if len(cells) >= 2:
                setting = cells[0].text_content().strip()
                option = cells[1].text_content().strip()
                notes = cells[2].text_content().strip() if len(cells) > 2 else ""
                if setting and option and option.lower() != "n/a":
                    settings[setting] = {
                        "value": option,
                        "notes": notes,
                        "section": section_name,
                    }
    return settings


def fetch_wiki_page(title_variant, use_wayback=False):
    """Try to fetch a wiki page. Returns (html_content, source_label, snapshot_date) or raises."""
    try:
        if use_wayback:
            # Try latest first, then 2025 fallback
            url = WAYBACK_URL.replace("{title}", quote(title_variant.replace(" ", "_"), safe="_'()"))
            resp = rate_limited_get(url)
            if resp.status_code != 200:
                url = WAYBACK_URL_2025.replace("{title}", quote(title_variant.replace(" ", "_"), safe="_'()"))
                resp = rate_limited_get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code} (Wayback)")
            if "There is currently no text in this page" in resp.text:
                raise RuntimeError("Empty wiki page")
            return resp.content, "wayback", extract_snapshot_date(resp) or datetime.now()
        else:
            url = LIVE_WIKI_URL.replace("{title}", quote(title_variant.replace(" ", "_"), safe="_'()"))
            resp = rate_limited_get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code} (live)")
            if is_cloudflare_blocked(resp.text):
                raise RuntimeError("Cloudflare blocked")
            if "There is currently no text in this page" in resp.text:
                raise RuntimeError("Empty wiki page")
            return resp.content, "live", datetime.now()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Connection refused: {e}")
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"Timeout: {e}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")


def fetch_config_from_wiki(game_name):
    """Try live wiki first, then Wayback Machine."""
    variants = wiki_title_variants(game_name)
    last_error = None
    source = "none"
    snapshot_date = None

    for variant in variants:
        # Try live first
        try:
            html_content, src, snap = fetch_wiki_page(variant, use_wayback=False)
            settings = parse_config_tables(html_content)
            if settings:
                return settings, src, snap
            else:
                last_error = "No config tables found"
        except RuntimeError as e:
            last_error = str(e)

        # If live failed, try Wayback Machine
        try:
            html_content, src, snap = fetch_wiki_page(variant, use_wayback=True)
            settings = parse_config_tables(html_content)
            if settings:
                return settings, src, snap
        except RuntimeError as e:
            last_error = str(e)

    return None, last_error or "No wiki page found", None


def extract_html_from_viewsource(content):
    """Convert Firefox view-source format back to parseable HTML."""
    try:
        text = content.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return content
    # Check if it's view-source format
    if 'id="viewsource"' not in text:
        return content
    # Extract everything between <body> and </body>, stripping Firefox annotations
    body_match = re.search(r'<body[^>]*>(.*?)</body>', text, re.DOTALL | re.I)
    if not body_match:
        return content
    body = body_match.group(1)
    # Remove all HTML tags (the view-source spans/divs) to get the raw text
    raw_text = re.sub(r'<[^>]+>', '', body)
    # The view-source format double-escapes HTML entities (&amp; -> &amp;amp;)
    # Need to unescape multiple passes until stable
    for _ in range(5):
        prev = raw_text
        raw_text = raw_text.replace('&lt;', '<').replace('&gt;', '>')
        raw_text = raw_text.replace('&amp;', '&').replace('&quot;', '"')
        raw_text = raw_text.replace('&apos;', "'").replace('&#39;', "'")
        if raw_text == prev:
            break
    return raw_text.encode("utf-8")


def build_local_wiki_index(local_dir):
    """Scan all .html files in local_dir, parse page titles, and return a dict
    of normalized_title -> (html_content, filename).
    Also builds a serial-based index from filenames like BCUS98114.html."""
    index = {}
    serial_index = {}
    if not os.path.isdir(local_dir):
        return index, serial_index
    for fname in os.listdir(local_dir):
        if not fname.endswith((".html", ".htm")):
            continue
        fpath = os.path.join(local_dir, fname)
        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            # Check for serial in filename: e.g. "BCUS98114.html" or "BCUS98114 - Gran Turismo 5.html"
            serial_match = re.match(r'^([A-Z]{2,4}\d{4,6})', fname)
            if serial_match:
                content = extract_html_from_viewsource(raw)
                serial_index[serial_match.group(1)] = (content, fname)
                continue  # Don't add to title index if serial-named

            # Convert view-source format if needed
            content = extract_html_from_viewsource(raw)
            text = content.decode("utf-8", errors="replace")
            # Extract page title
            m = re.search(r'<title>([^<]+?)\s*[-–—|]\s*RPCS3', text, re.I)
            if not m:
                m = re.search(r'class="firstHeading"[^>]*>([^<]+)', text, re.I)
            if not m:
                m = re.search(r'<title>([^<]+)</title', text, re.I)
            if m:
                page_title = m.group(1).strip()
            else:
                base = os.path.splitext(fname)[0]
                fb = re.sub(r'^https___wiki\.rpcs3\.net_index\.php_title=', '', base)
                fb = fb.replace("__", ":").replace("_", " ")
                page_title = fb
            norm = page_title.lower().replace("\u2122", "").replace("\u00ae", "").strip()
            norm = re.sub(r'\s+', ' ', norm)
            index[norm] = (content, fname)
        except (OSError, UnicodeDecodeError):
            continue
    return index, serial_index


def scan_from_local(local_dir, game_name, serial, wiki_index=None, serial_index=None):
    """Scan locally saved wiki HTML files for a game's config settings."""
    # Try serial match first (user named the file BCUS98114.html)
    if serial_index and serial in serial_index:
        content, fname = serial_index[serial]
        settings = parse_config_tables(content)
        if settings:
            return settings, f"local:{fname}", datetime.now()

    if wiki_index is None or serial_index is None:
        wiki_index, serial_index = build_local_wiki_index(local_dir)
    if not wiki_index and not serial_index:
        return None, "No HTML files found in " + local_dir, None

    # Normalize game name for matching
    clean = game_name.replace("\u2122", "").replace("\u00ae", "").strip()
    variants = wiki_title_variants(clean)

    # Try exact title variant match only — no fuzzy matching to avoid
    # one game getting another game's settings
    for variant in variants:
        norm = variant.lower().strip()
        for key in (norm, norm.replace(":", ""), norm.replace(":", " ")):
            if key in wiki_index:
                content, fname = wiki_index[key]
                settings = parse_config_tables(content)
                if settings:
                    return settings, f"local:{fname}", datetime.now()

    return None, "No local file found for " + game_name, None


# ═══════════════════════════════════════════════════════════════════════════════
#  Config generation
# ═══════════════════════════════════════════════════════════════════════════════

def load_base_config():
    config_path = os.path.join(RPCS3_CONFIG_DIR, "config.yml")
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found.")
        sys.exit(1)
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f)

def create_default_config(base_config):
    cfg = deepcopy(base_config) if base_config else {}
    for section, settings in DEFAULT_OVERRIDES.items():
        if section not in cfg:
            cfg[section] = {}
        for key, value in settings.items():
            if isinstance(value, dict):
                if key not in cfg[section]:
                    cfg[section][key] = {}
                for subkey, subval in value.items():
                    cfg[section][key][subkey] = subval
                continue
            cfg[section][key] = value
    return cfg

def apply_settings_to_config(cfg, settings):
    applied_count = 0
    for setting_name, setting_info in settings.items():
        value = setting_info["value"]
        mapping = SETTING_MAP_CI.get(setting_name.lower())
        if mapping is None:
            continue
        section = mapping["section"]
        key = mapping["key"]
        subkey = mapping.get("subkey")
        try:
            transformed = mapping["transform"](value)
        except (ValueError, TypeError):
            continue
        if subkey:
            if subkey not in cfg[section]:
                cfg[section][subkey] = {}
            cfg[section][subkey][key] = transformed
        else:
            cfg[section][key] = transformed
        if "side_effects" in mapping:
            mapping["side_effects"](cfg, value)
        applied_count += 1
    return cfg, applied_count

def sanitize_config(cfg):
    required_sections = [
        "Audio", "Core", "Input/Output", "Log", "Miscellaneous",
        "Net", "Savestate", "System", "VFS", "Video",
    ]
    for section in required_sections:
        if section not in cfg:
            cfg[section] = {}
    return cfg

def custom_config_path(serial):
    return os.path.join(CUSTOM_CONFIGS_DIR, f"config_{serial}.yml")

def game_already_has_config(serial):
    return os.path.exists(custom_config_path(serial))

def write_custom_config(serial, cfg):
    import yaml
    path = custom_config_path(serial)
    os.makedirs(CUSTOM_CONFIGS_DIR, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, width=4096)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
#  Main — subcommand dispatch
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_list(installed_list_path=None):
    games = load_installed_games(installed_list_path)
    db = load_db()
    print(f"\nFound {len(games)} installed games:")
    for serial, name in sorted(games.items()):
        in_db = "✓" if db_entry_exists(db, serial) else " "
        has_cfg = "✓" if game_already_has_config(serial) else " "
        print(f"  [{in_db}|{has_cfg}] {serial}: {name}")
    print(f"\nDatabase: {len([s for s in db if db_entry_exists(db, s)])} games in DB")
    print(f"Configs:  {sum(1 for s in games if game_already_has_config(s))} files generated")


def cmd_scan(force_serials=None, local_dir=None, installed_list_path=None):
    games = load_installed_games(installed_list_path)
    db = load_db()

    if not games:
        print("No installed games found.")
        return

    # Build local wiki index once if using local files
    wiki_index = None
    serial_index = None
    if local_dir:
        wiki_index, serial_index = build_local_wiki_index(local_dir)
        total = (len(wiki_index) if wiki_index else 0) + (len(serial_index) if serial_index else 0)
        if total:
            print(f"Found {total} wiki HTML files in {local_dir} ({len(serial_index or [])} serial-named)")
        else:
            print(f"No .html files found in {local_dir}")

    # Filter if specific serials given
    if force_serials:
        games = {s: n for s, n in games.items() if s in force_serials}
        missing = set(force_serials) - set(games.keys())
        for s in missing:
            print(f"  Serial {s} not found installed")

    to_scan = {}
    for serial, name in games.items():
        if force_serials or not db_entry_exists(db, serial):
            to_scan[serial] = name

    if not to_scan:
        print("All games already in database (use --force to re-scan).")
        return

    print(f"\nScanning {len(to_scan)} game(s)...\n")

    success = 0
    failed = 0

    for serial, name in sorted(to_scan.items()):
        # Check if DB already has a manual entry (user-edited)
        if serial in db and db[serial].get("settings") is not None and not force_serials:
            print(f"  ⏭  [{serial}] {name} - already in DB")
            continue

        print(f"  [{serial}] {name}...", end=" ", flush=True)
        try:
            if local_dir:
                settings, source, snapshot_date = scan_from_local(local_dir, name, serial, wiki_index, serial_index)
            else:
                settings, source, snapshot_date = fetch_config_from_wiki(name)
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            db[serial] = {"name": name, "status": "error", "error": str(e),
                          "source": "none", "settings": {}}
            failed += 1
            save_db(db)
            continue

        if settings is None:
            print(f"❌ {source}")
            db[serial] = {"name": name, "status": "not_found", "error": str(source),
                          "source": "none", "settings": {}}
            failed += 1
            save_db(db)
            continue

        count = len(settings)
        date_str = snapshot_date.strftime("%Y-%m-%d") if snapshot_date else "?"
        print(f"✅ {count} settings from {source} ({date_str})")
        db[serial] = {
            "name": name,
            "status": "found",
            "source": source,
            "snapshot_date": date_str,
            "settings": settings,
        }
        success += 1
        save_db(db)

    print(f"\n{'='*50}")
    print(f"Scan done: {success} found, {failed} not found")
    print(f"Database: {DB_PATH}")


def cmd_generate(force=False, only_missing=False, specific_serials=None, installed_list_path=None):
    games = load_installed_games(installed_list_path)
    db = load_db()
    upscale_info = load_installed_list(installed_list_path) if installed_list_path else {}

    if not games:
        print("No installed games found.")
        return

    # Load base config
    base_config = load_base_config()
    default_config = create_default_config(base_config)

    # Filter games
    to_process = {}
    for serial, name in games.items():
        if specific_serials and serial not in specific_serials:
            continue
        if not force and game_already_has_config(serial):
            continue
        if only_missing and game_already_has_config(serial):
            continue
        to_process[serial] = name

    if not to_process:
        print("No games to generate configs for (use --force to overwrite).")
        return

    print(f"\nGenerating configs for {len(to_process)} game(s)...\n")

    success = 0
    skipped = 0
    failed = 0

    for serial, name in sorted(to_process.items()):
        if not db_entry_exists(db, serial):
            print(f"  ⏭  [{serial}] {name} - not in database (run --scan first)")
            skipped += 1
            continue

        entry = db[serial]
        wiki_settings = entry.get("settings", {})
        config = deepcopy(default_config)
        config = sanitize_config(config)

        if wiki_settings:
            config, applied = apply_settings_to_config(config, wiki_settings)
        else:
            applied = 0

        # Apply Resolution Scale based on upscale capability
        info = upscale_info.get(serial, {})
        if info.get("can_upscale") is False:
            if "Video" not in config:
                config["Video"] = {}
            config["Video"]["Resolution Scale"] = 100
            config["Video"]["Resolution"] = "1280x720"

        out_path = write_custom_config(serial, config)
        src = entry.get("source", "none")
        date_str = entry.get("snapshot_date", "?")
        print(f"  ✅ [{serial}] {name} ({applied} settings, src: {src} {date_str}) → {os.path.basename(out_path)}")
        success += 1

    print(f"\n{'='*50}")
    print(f"Generate done: {success} generated, {skipped} skipped, {failed} failed")
    print(f"Configs in: {CUSTOM_CONFIGS_DIR}")


def pause():
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

def print_usage():
    print("RPCS3 Config Generator")
    print("=" * 40)
    print("Usage:")
    print("  --scan-only --local-wiki <dir> --installed-list <file>")
    print("  --generate --installed-list <file>")
    print("  --list --installed-list <file>")
    print("  --local-wiki <dir> --installed-list <file>  (scan + generate)")
    print()
    print("Examples:")
    print("  rpcs3-config-generator --list --installed-list Installed_within_rpcs3")
    print("  rpcs3-config-generator --scan-only --local-wiki wiki_pages --installed-list Installed_within_rpcs3")
    print("  rpcs3-config-generator --generate --installed-list Installed_within_rpcs3")
    print()
    print("Flags:  --force  --missing  --help")

def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print_usage()
        return

    force = "--force" in args
    only_missing = "--missing" in args
    list_only = "--list" in args
    scan_only = "--scan-only" in args
    gen_only = "--generate" in args
    local_wiki = None
    installed_list = None

    # Parse parameterized flags
    clean = []
    i = 0
    while i < len(args):
        if args[i] == "--local-wiki" and i + 1 < len(args):
            local_wiki = os.path.expanduser(args[i + 1])
            i += 2
        elif args[i] == "--installed-list" and i + 1 < len(args):
            installed_list = os.path.expanduser(args[i + 1])
            i += 2
        else:
            clean.append(args[i])
            i += 1
    args = clean

    specific = [a for a in args if not a.startswith("--")]

    if not args or not (list_only or scan_only or gen_only or force or only_missing):
        # Interactive menu mode (shown when double-clicked)
        print("RPCS3 Config Generator")
        print("=" * 40)
        # Find files relative to AppImage location or CWD
        search_dirs = [os.getcwd()]
        appimage = os.environ.get("APPIMAGE", "")
        if appimage:
            search_dirs.append(os.path.dirname(os.path.abspath(appimage)))
        search_dirs.append(os.path.expanduser("~/rpcs3-config-generator"))
        wiki_dir = local_wiki or ""
        inst_file = installed_list or ""
        if not wiki_dir:
            for d in search_dirs:
                p = os.path.join(d, "wiki_pages")
                if os.path.isdir(p):
                    wiki_dir = p
                    break
        if not inst_file:
            for d in search_dirs:
                p = os.path.join(d, "Installed_within_rpcs3")
                if os.path.isfile(p):
                    inst_file = p
                    break
        if wiki_dir:
            print(f"  📁 Wiki folder:  {wiki_dir}")
        else:
            print(f"  📁 Wiki folder:  NOT FOUND (press M to set manually)")
        if inst_file:
            print(f"  📄 Games list:   {inst_file}")
        else:
            print(f"  📄 Games list:   NOT FOUND (press M to set manually)")
        print()
        print("  1. Scan wiki → database")
        print("  2. Generate configs")
        print("  3. Scan + Generate (full)")
        print("  4. Show game list")
        print("  M. Set paths manually")
        print("  0. Exit")
        print()
        try:
            choice = input("Choose [0-4/M]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "0"
        if choice == "m":
            try:
                entered = input("Wiki folder path: ").strip()
                if entered:
                    wiki_dir = os.path.expanduser(entered)
                entered = input("Games list file: ").strip()
                if entered:
                    inst_file = os.path.expanduser(entered)
            except (EOFError, KeyboardInterrupt):
                pass
            if wiki_dir and inst_file:
                print("\n--- Scan ---")
                cmd_scan(force_serials=True, local_dir=wiki_dir, installed_list_path=inst_file)
                print("\n--- Generate ---")
                cmd_generate(force=True, installed_list_path=inst_file)
            else:
                print("Paths not provided, skipping.")
        elif choice == "1":
            cmd_scan(force_serials=True, local_dir=wiki_dir or None, installed_list_path=inst_file or None)
        elif choice == "2":
            cmd_generate(force=True, installed_list_path=inst_file or None)
        elif choice == "3":
            cmd_scan(force_serials=True, local_dir=wiki_dir or None, installed_list_path=inst_file or None)
            cmd_generate(force=True, installed_list_path=inst_file or None)
        elif choice == "4":
            cmd_list(installed_list_path=inst_file or None)
        print("\nDone. Press Enter to exit...", end="")
        pause()
        return

    if list_only:
        cmd_list(installed_list_path=installed_list)
        print("\nPress Enter to exit...", end="")
        pause()
        return

    if scan_only:
        cmd_scan(force_serials=specific if force else None, local_dir=local_wiki, installed_list_path=installed_list)
        print("\nPress Enter to exit...", end="")
        pause()
        return

    if gen_only:
        cmd_generate(force=force, only_missing=only_missing, specific_serials=specific, installed_list_path=installed_list)
        print("\nPress Enter to exit...", end="")
        pause()
        return

    # Default: scan then generate
    cmd_scan(force_serials=specific if force else None, local_dir=local_wiki, installed_list_path=installed_list)
    cmd_generate(force=force, only_missing=only_missing, specific_serials=specific, installed_list_path=installed_list)
    print("\nDone. Press Enter to exit...", end="")
    pause()


if __name__ == "__main__":
    main()
