from flask import Flask, request, jsonify, send_file
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from io import BytesIO
import os
import re
import unicodedata

app = Flask(__name__)
session = requests.Session()

API_KEY = os.environ.get("API_KEY", "suyash").strip() or "suyash"
INFO_API_URL = os.environ.get("INFO_API_URL", "").strip() or "https://suyashprofileapi.vercel.app/profile"
INFO_SERVER = os.environ.get("INFO_SERVER", "IND").strip() or "IND"
ICON_API_URL = "https://iconapi.wasmer.app/{item_id}"
GITHUB_ASSETS_RAW = "https://raw.githubusercontent.com/pankaj07-ux/ff-assets/main"
TEMPLATE_FILENAME = "profile_template.png"
HTTP_TIMEOUT = 12

# Base template size. Coordinates below are made for this exact image.
BASE_W = 1897
BASE_H = 829

# No external font file is required. The code searches common system fonts.
# You can optionally put your own fonts inside ./fonts/ as:
# fonts/bold.ttf and fonts/regular.ttf
BOLD_FONT_CANDIDATES = [
    "fonts/bold.ttf",
    os.environ.get("FONT_BOLD_PATH", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/system/fonts/Roboto-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "Arial Bold.ttf",
]

REGULAR_FONT_CANDIDATES = [
    "fonts/regular.ttf",
    os.environ.get("FONT_REGULAR_PATH", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/system/fonts/Roboto-Regular.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/Library/Fonts/Arial.ttf",
    "DejaVuSans.ttf",
    "Arial.ttf",
]

SYMBOL_FONT_CANDIDATES = [
    "fonts/symbols.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "C:/Windows/Fonts/seguisym.ttf",
]

CJK_FONT_CANDIDATES = [
    "fonts/cjk.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKJP-Regular.otf",
]

CHEROKEE_FONT_CANDIDATES = [
    "C:/Windows/Fonts/gadugib.ttf",
    "C:/Windows/Fonts/gadugi.ttf",
]

GAME_CJK_SYMBOLS = set("亗乂ツ彡々〆么乄メ卍卐の丶丂乙爪气刁卄ฬ๛۝")

COORDS = {
    "avatar_box": (231, 221, 528, 529),
    "clan_center_x": 1265,
    "clan_y": 50,
    "clan_max_width": 780,

    # Text positions tuned after real output test.
    # These are still based on BASE_W x BASE_H and auto-scale with template size.
    "prefix_x": 650,
    "main_name_x": 900,
    "nickname_y": 168,
    "prefix_max_width": 230,
    "main_name_max_width": 560,
    "full_name_x": 650,
    "full_name_max_width": 830,

    "language_x": 690,
    "language_y": 332,
    "language_max_width": 380,

    "level_x": 205,
    "level_y": 620,
    "level_max_width": 250,

    # Push likes and UID right so they do not overlap the icons.
    "likes_x": 1620,
    "likes_y": 490,
    "likes_max_width": 230,
    "uid_x": 1285,
    "uid_y": 662,
    "uid_max_width": 500,
}


def sx(value, size):
    return int(round(value * size[0] / BASE_W))


def sy(value, size):
    return int(round(value * size[1] / BASE_H))


def sbox(box, size):
    x1, y1, x2, y2 = box
    return sx(x1, size), sy(y1, size), sx(x2, size), sy(y2, size)


class RenderFont:
    def __init__(self, pil_font, requested_size, bitmap_fallback=False):
        self.pil_font = pil_font
        self.requested_size = max(1, int(requested_size))
        self.bitmap_fallback = bitmap_fallback

    @property
    def scale(self):
        # PIL default bitmap font is around 10px. Scale it if no TTF exists.
        return max(1.0, self.requested_size / 10.0) if self.bitmap_fallback else 1.0


def resolve_font_path(candidates):
    base_dir = os.path.dirname(__file__)
    for candidate in candidates:
        if not candidate:
            continue
        # relative path inside project
        local_path = os.path.join(base_dir, candidate)
        if os.path.exists(local_path):
            return local_path
        # absolute path
        if os.path.exists(candidate):
            return candidate
        # font name resolvable by PIL/fontconfig
        try:
            ImageFont.truetype(candidate, size=20)
            return candidate
        except Exception:
            pass
    return None


def load_font(candidates, size):
    font_path = resolve_font_path(candidates)
    if font_path:
        try:
            return RenderFont(ImageFont.truetype(font_path, size=max(1, int(size))), size, bitmap_fallback=False)
        except Exception:
            pass
    # Pillow's sized default font is scalable and stays sharp on Linux deployments.
    try:
        return RenderFont(ImageFont.load_default(size=max(1, int(size))), size, bitmap_fallback=False)
    except TypeError:
        return RenderFont(ImageFont.load_default(), size, bitmap_fallback=True)


def text_bbox(draw, text, render_font, stroke_width=0):
    text = str(text or "")
    bbox = draw.textbbox((0, 0), text, font=render_font.pil_font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if render_font.bitmap_fallback:
        return (0, 0, int(w * render_font.scale), int(h * render_font.scale))
    return bbox


def text_width(draw, text, render_font, stroke_width=0):
    text = str(text or "")
    if "" not in text and not any(is_fallback_character(char) for char in text):
        bbox = text_bbox(draw, text, render_font, stroke_width=stroke_width)
        return bbox[2] - bbox[0]

    total = 0
    symbol_font = None
    cjk_font = None
    cherokee_font = None
    for char in text:
        if char == "":
            total += max(14, int(render_font.requested_size * 0.56))
        elif is_fallback_character(char):
            if is_modifier_letter(char):
                special_font = render_font
            elif is_cherokee_character(char):
                if cherokee_font is None:
                    cherokee_font = load_font(CHEROKEE_FONT_CANDIDATES, render_font.requested_size)
                special_font = cherokee_font
            elif is_cjk_character(char):
                if cjk_font is None:
                    cjk_font = load_font(CJK_FONT_CANDIDATES, render_font.requested_size)
                special_font = cjk_font
            else:
                if symbol_font is None:
                    symbol_font = load_font(SYMBOL_FONT_CANDIDATES, render_font.requested_size)
                special_font = symbol_font
            bbox = text_bbox(draw, char, special_font, stroke_width=stroke_width)
            total += bbox[2] - bbox[0]
        else:
            bbox = text_bbox(draw, char, render_font, stroke_width=stroke_width)
            total += bbox[2] - bbox[0]
    return total


def is_symbol_character(char):
    category = unicodedata.category(char)
    return char in GAME_CJK_SYMBOLS or category in {"Sk", "Sm", "So"}


def is_cjk_character(char):
    codepoint = ord(char)
    return (
        char in GAME_CJK_SYMBOLS
        or 0x2E80 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0xFF00 <= codepoint <= 0xFFEF
    )


def is_cherokee_character(char):
    codepoint = ord(char)
    return 0x13A0 <= codepoint <= 0x13FF or 0xAB70 <= codepoint <= 0xABBF


def is_modifier_letter(char):
    codepoint = ord(char)
    return (
        0x0250 <= codepoint <= 0x02FF
        or 0x1D00 <= codepoint <= 0x1D7F
        or 0x2070 <= codepoint <= 0x209F
    )


def is_fallback_character(char):
    return char == "" or ord(char) > 127 or is_symbol_character(char)


def _draw_basic_text(image, xy, text, render_font, fill, stroke_width=0, stroke_fill=None):
    text = str(text or "")
    x, y = int(xy[0]), int(xy[1])
    if not render_font.bitmap_fallback:
        d = ImageDraw.Draw(image)
        d.text((x, y), text, font=render_font.pil_font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return

    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe)
    raw_bbox = pd.textbbox((0, 0), text, font=render_font.pil_font, stroke_width=stroke_width)
    raw_w = max(1, raw_bbox[2] - raw_bbox[0] + 8)
    raw_h = max(1, raw_bbox[3] - raw_bbox[1] + 8)
    temp = Image.new("RGBA", (raw_w, raw_h), (0, 0, 0, 0))
    td = ImageDraw.Draw(temp)
    td.text((4 - raw_bbox[0], 4 - raw_bbox[1]), text, font=render_font.pil_font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    scale = render_font.scale
    temp = temp.resize((max(1, int(raw_w * scale)), max(1, int(raw_h * scale))), Image.Resampling.NEAREST)
    image.paste(temp, (x, y), temp)


def _draw_apple_logo(image, xy, render_font, fill):
    x, y = int(xy[0]), int(xy[1])
    size = max(18, int(render_font.requested_size * 0.90))
    h = size
    w = int(size * 0.82)
    mask = Image.new("L", (w + 10, h + 10), 0)
    d = ImageDraw.Draw(mask)

    # apple body
    left = 4
    top = int(h * 0.20)
    d.ellipse((left, top + int(h*0.12), left + int(w*0.46), top + int(h*0.58)), fill=255)
    d.ellipse((left + int(w*0.28), top + int(h*0.06), left + int(w*0.76), top + int(h*0.52)), fill=255)
    d.ellipse((left + int(w*0.10), top + int(h*0.28), left + int(w*0.72), top + int(h*0.82)), fill=255)
    # bite
    d.ellipse((left + int(w*0.60), top + int(h*0.16), left + int(w*0.92), top + int(h*0.42)), fill=0)
    # bottom notch
    d.ellipse((left + int(w*0.34), top + int(h*0.62), left + int(w*0.54), top + int(h*0.82)), fill=0)
    # leaf
    d.ellipse((left + int(w*0.40), 2, left + int(w*0.72), int(h*0.24)), fill=255)
    mask = mask.rotate(-18, resample=Image.Resampling.BICUBIC, center=(left + int(w*0.56), int(h*0.12)), fillcolor=0)
    mask = mask.filter(ImageFilter.MinFilter(3))
    temp = Image.new("RGBA", mask.size, fill)
    image.paste(temp, (x, y + max(0, int(render_font.requested_size * 0.02))), mask)
    return w + 3


def draw_text(image, xy, text, render_font, fill, stroke_width=0, stroke_fill=None):
    text = str(text or "")
    if "" not in text and not any(is_fallback_character(char) for char in text):
        _draw_basic_text(image, xy, text, render_font, fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return

    x, y = int(xy[0]), int(xy[1])
    draw = ImageDraw.Draw(image)
    symbol_font = None
    cjk_font = None
    cherokee_font = None
    for char in text:
        if char == "":
            x += _draw_apple_logo(image, (x, y), render_font, fill)
        elif is_fallback_character(char):
            if is_modifier_letter(char):
                special_font = render_font
            elif is_cherokee_character(char):
                if cherokee_font is None:
                    cherokee_font = load_font(CHEROKEE_FONT_CANDIDATES, render_font.requested_size)
                special_font = cherokee_font
            elif is_cjk_character(char):
                if cjk_font is None:
                    cjk_font = load_font(CJK_FONT_CANDIDATES, render_font.requested_size)
                special_font = cjk_font
            else:
                if symbol_font is None:
                    symbol_font = load_font(SYMBOL_FONT_CANDIDATES, render_font.requested_size)
                special_font = symbol_font
            _draw_basic_text(image, (x, y), char, special_font, fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
            x += text_width(draw, char, special_font, stroke_width=stroke_width)
        else:
            _draw_basic_text(image, (x, y), char, render_font, fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
            x += text_width(draw, char, render_font, stroke_width=stroke_width)


def fit_font(draw, text, candidates, max_size, min_size, max_width):
    text = str(text or "")
    for size in range(int(max_size), int(min_size) - 1, -2):
        f = load_font(candidates, size)
        if text_width(draw, text, f) <= max_width:
            return f
    return load_font(candidates, min_size)


def ellipsize(draw, text, render_font, max_width):
    text = str(text or "")
    if not text:
        return ""
    if text_width(draw, text, render_font) <= max_width:
        return text
    ell = "..."
    for i in range(len(text), 0, -1):
        candidate = text[:i].rstrip() + ell
        if text_width(draw, candidate, render_font) <= max_width:
            return candidate
    return ell


def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def clean_display_text(value):
    """Normalize FF separators and placeholder boxes for better rendering."""
    text = str(value or "")
    return (
        text.replace("ㅤ", " ")
            .replace("□", "")
            .replace("▢", "")
            .replace("▯", "")
            .replace("▣", "")
            .replace("▤", "")
            .replace("▥", "")
            .replace("▦", "")
            .replace("▧", "")
            .replace("▨", "")
            .replace("▩", "")
            .replace("◻", "")
            .replace("◼", "")
            .replace("◽", "")
            .replace("◾", "")
            .replace("⬜", "")
            .replace("⬛", "")
            .replace("�", "")
            .replace("​", "")
            .replace("‌", "")
            .replace("‍", "")
            .replace("﻿", "")
            .strip()
    )


def map_language(value):
    if value is None:
        return "English"
    text = str(value).strip()
    mapping = {
        "en": "English",
        "id": "Indonesia",
        "es": "Español",
        "ar": "العربية",
        "fr": "Français",
        "pt": "Português",
        "ru": "Русский",
        "hi": "हिन्दी",
        "bn": "বাংলা",
        "th": "ไทย",
        "vi": "Tiếng Việt",
        "tr": "Türkçe",
        "ms": "Malay",
        "language_en": "English",
        "languageen": "English",
        "language_id": "Indonesia",
        "language_es": "Español",
        "language_ar": "العربية",
        "language_fr": "Français",
        "language_pt": "Português",
        "language_ru": "Русский",
        "language_hi": "हिन्दी",
        "language_bn": "বাংলা",
        "language_bd": "বাংলা",
        "language_th": "ไทย",
        "language_vi": "Tiếng Việt",
        "language_tr": "Türkçe",
        "language_ms": "Malay",
        "language_zh": "中文（繁）",
    }
    key = text.lower()
    return mapping.get(key, text.replace("Language_", "").replace("language_", "").replace("_", " ").title() or "English")


def format_number(value):
    """Likes format:
    < 100000  -> full number
    >= 100000 -> K
    >= 1000000 -> M
    """
    try:
        number = int(value)
    except Exception:
        return str(value or "0")

    def clean(num):
        text = f"{num:.1f}"
        return text[:-2] if text.endswith(".0") else text

    if number < 100000:
        return str(number)
    if number < 1000000:
        return f"{clean(number / 1000)}K"
    return f"{clean(number / 1000000)}M"


def split_nickname(nickname):
    nickname = clean_display_text(nickname)
    if not nickname:
        return "", ""
    parts = re.split(r'[\s\u3164]+', nickname)
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return "", nickname


def fetch_player_info(uid, server=None):
    if not INFO_API_URL:
        print("INFO_API_URL is not configured")
        return None
    try:
        response = session.get(
            INFO_API_URL,
            params={"server": server or INFO_SERVER, "uid": uid},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"Failed to fetch player info: {exc}")
        return None


def fetch_remote_image(url):
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        print(f"Failed to fetch image {url}: {exc}")
        return None


def fetch_first_image(urls):
    for url in urls:
        if not url:
            continue
        image = fetch_remote_image(url)
        if image is not None:
            return image
    return None


def fetch_avatar_asset(head_pic=None, avatar_id=None):
    urls = []
    # Prefer the older icon-style result first because it matched the sample better.
    if head_pic:
        urls.extend([
            ICON_API_URL.format(item_id=head_pic),
            f"{GITHUB_ASSETS_RAW}/avatars/{head_pic}.png",
            f"{GITHUB_ASSETS_RAW}/icons/{head_pic}.png",
        ])
    if avatar_id:
        urls.extend([
            ICON_API_URL.format(item_id=avatar_id),
            f"{GITHUB_ASSETS_RAW}/characters/{avatar_id}.png",
            f"{GITHUB_ASSETS_RAW}/icons/{avatar_id}.png",
        ])
    return fetch_first_image(urls)


def fetch_banner_asset(banner_id=None):
    if not banner_id:
        return None
    urls = [
        f"{GITHUB_ASSETS_RAW}/banners/{banner_id}.png",
        f"{GITHUB_ASSETS_RAW}/icons/{banner_id}.png",
        ICON_API_URL.format(item_id=banner_id),
    ]
    return fetch_first_image(urls)


def extract_profile_fields(data):
    if not isinstance(data, dict):
        return None
    account = data.get("AccountProfile", {}) or data.get("accountprofile", {}) or {}
    if not isinstance(account, dict):
        account = {}
    basic = account.get("basicInfo", {}) or account.get("basicinfo", {}) or data.get("basicinfo", {}) or {}
    profile = account.get("profileInfo", {}) or account.get("profileinfo", {}) or data.get("profileinfo", {}) or {}
    social = account.get("socialInfo", {}) or account.get("socialinfo", {}) or data.get("socialinfo", {}) or {}
    # The current info provider returns these sections at the top level.
    basic = data.get("playerData", {}) or basic
    profile = data.get("profileInfo", {}) or profile
    social = data.get("socialInfo", {}) or social
    if not isinstance(basic, dict):
        basic = {}
    if not isinstance(profile, dict):
        profile = {}
    if not isinstance(social, dict):
        social = {}
    guild_data = ((data.get("GuildInfo") or {}).get("data") or {}) if isinstance(data.get("GuildInfo"), dict) else {}
    if not guild_data:
        guild_data = data.get("guildInfo", {}) or {}
    clan_basic = ((data.get("ClanSummary") or {}).get("clanBasicInfo") or {}) if isinstance(data.get("ClanSummary"), dict) else {}
    clan_basic = clan_basic or data.get("clanbasicinfo", {}) or {}

    # Support both the original nested response and APIs that return fields at the top level.
    nickname = clean_display_text(first_non_empty(
        basic.get("nickname"),
        data.get("nickname"),
        data.get("name"),
        data.get("playerName"),
        "UNKNOWN",
    ))

    prefix, main_name = split_nickname(nickname)
    if not main_name:
        main_name = nickname

    return {
        "uid": first_non_empty(basic.get("accountId"), basic.get("accountid"), data.get("uid"), data.get("accountId"), "UNKNOWN"),
        "nickname": nickname,
        "nickname_prefix": prefix,
        "nickname_main": main_name,
        "language": map_language(first_non_empty(social.get("language"), "English")),
        "level": first_non_empty(basic.get("level"), 0),
        "likes": first_non_empty(basic.get("liked"), 0),
        "head_pic": first_non_empty(basic.get("headPic"), basic.get("headpic")),
        "avatar_id": first_non_empty(profile.get("avatarId"), profile.get("avatarid")),
        "clan_name": clean_display_text(first_non_empty(
            guild_data.get("clanName"),
            guild_data.get("clanname"),
            clan_basic.get("clanName"),
            clan_basic.get("clanname"),
            "",
        )),
    }


def paste_avatar(base, avatar):
    if avatar is None:
        return

    x1, y1, x2, y2 = sbox(COORDS["avatar_box"], base.size)
    width, height = x2 - x1, y2 - y1

    # Keep the avatar exactly as received.
    # Do NOT crop/fill with ImageOps.fit().
    # Instead, scale it down to fit fully inside the box.
    avatar = avatar.convert("RGBA")
    fitted = ImageOps.contain(avatar, (width, height), method=Image.Resampling.LANCZOS)

    # Preserve the full avatar by centering it inside a transparent canvas
    # with the exact box size.
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    paste_x = (width - fitted.width) // 2
    paste_y = (height - fitted.height) // 2
    canvas.paste(fitted, (paste_x, paste_y), fitted)

    base.paste(canvas, (x1, y1), canvas)


def draw_debug(draw, size):
    boxes = [
        sbox(COORDS["avatar_box"], size),
        (sx(COORDS["prefix_x"], size), sy(COORDS["nickname_y"], size), sx(COORDS["prefix_x"] + COORDS["prefix_max_width"], size), sy(COORDS["nickname_y"] + 90, size)),
        (sx(COORDS["main_name_x"], size), sy(COORDS["nickname_y"], size), sx(COORDS["main_name_x"] + COORDS["main_name_max_width"], size), sy(COORDS["nickname_y"] + 90, size)),
        (sx(COORDS["language_x"], size), sy(COORDS["language_y"], size), sx(COORDS["language_x"] + COORDS["language_max_width"], size), sy(COORDS["language_y"] + 70, size)),
        (sx(COORDS["likes_x"], size), sy(COORDS["likes_y"], size), sx(COORDS["likes_x"] + COORDS["likes_max_width"], size), sy(COORDS["likes_y"] + 75, size)),
        (sx(COORDS["uid_x"], size), sy(COORDS["uid_y"], size), sx(COORDS["uid_x"] + COORDS["uid_max_width"], size), sy(COORDS["uid_y"] + 70, size)),
    ]
    for box in boxes:
        draw.rectangle(box, outline=(255, 0, 0, 255), width=max(1, sx(3, size)))


def render_profile_card(fields, debug=False):
    template_path = os.path.join(os.path.dirname(__file__), TEMPLATE_FILENAME)
    image = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Prefer GitHub FF assets for profile avatar, fallback to icon API
    paste_avatar(image, fetch_avatar_asset(fields.get("head_pic"), fields.get("avatar_id")))

    # Clan/Guild
    clan_name = str(fields.get("clan_name") or "")
    if clan_name:
        max_width = sx(COORDS["clan_max_width"], image.size)
        # Keep guild font more consistent across IDs.
        preferred = load_font(BOLD_FONT_CANDIDATES, sx(72, image.size))
        if text_width(draw, clan_name, preferred) <= max_width:
            font = preferred
        else:
            font = fit_font(draw, clan_name, BOLD_FONT_CANDIDATES, sx(72, image.size), sx(40, image.size), max_width)
        clan_text = ellipsize(draw, clan_name, font, max_width)
        w = text_width(draw, clan_text, font)
        x = sx(COORDS["clan_center_x"], image.size) - w // 2
        y = sy(COORDS["clan_y"], image.size)
        draw_text(image, (x, y), clan_text, font, fill=(255, 255, 255, 255))

    # Nickname
    prefix = str(fields.get("nickname_prefix") or "")
    main_name = str(fields.get("nickname_main") or "")
    full_name = str(fields.get("nickname") or "")
    nick_y = sy(COORDS["nickname_y"], image.size)

    if prefix and main_name:
        prefix_limit = sx(COORDS["prefix_max_width"], image.size)
        main_limit = sx(COORDS["main_name_max_width"], image.size)
        common_size = min(
            fit_font(draw, prefix, BOLD_FONT_CANDIDATES, sx(100, image.size), sx(34, image.size), prefix_limit).requested_size,
            fit_font(draw, main_name, BOLD_FONT_CANDIDATES, sx(104, image.size), sx(36, image.size), main_limit).requested_size,
        )
        common_font = load_font(BOLD_FONT_CANDIDATES, common_size)
        prefix_text = ellipsize(draw, prefix, common_font, prefix_limit)
        main_text = ellipsize(draw, main_name, common_font, main_limit)
        draw_text(image, (sx(COORDS["prefix_x"], image.size), nick_y), prefix_text, common_font, fill=(0, 0, 0, 255))
        draw_text(image, (sx(COORDS["main_name_x"], image.size), nick_y), main_text, common_font, fill=(0, 0, 0, 255))
    else:
        full_font = fit_font(draw, full_name, BOLD_FONT_CANDIDATES, sx(98, image.size), sx(34, image.size), sx(COORDS["full_name_max_width"], image.size))
        full_text = ellipsize(draw, full_name, full_font, sx(COORDS["full_name_max_width"], image.size))
        draw_text(image, (sx(COORDS["full_name_x"], image.size), nick_y), full_text, full_font, fill=(0, 0, 0, 255))

    # Language
    language = str(fields.get("language") or "English")
    lang_font = fit_font(draw, language, REGULAR_FONT_CANDIDATES, sx(64, image.size), sx(24, image.size), sx(COORDS["language_max_width"], image.size))
    lang_text = ellipsize(draw, language, lang_font, sx(COORDS["language_max_width"], image.size))
    draw_text(image, (sx(COORDS["language_x"], image.size), sy(COORDS["language_y"], image.size)), lang_text, lang_font, fill=(0, 0, 0, 255))

    # Level
    level_text = f"Lv.{fields.get('level', 0)}"
    level_font = fit_font(draw, level_text, BOLD_FONT_CANDIDATES, sx(78, image.size), sx(28, image.size), sx(COORDS["level_max_width"], image.size))
    draw_text(image, (sx(COORDS["level_x"], image.size), sy(COORDS["level_y"], image.size)), level_text, level_font, fill=(0, 0, 0, 255))

    # Likes
    likes_text = format_number(fields.get("likes", 0))
    likes_font = fit_font(draw, likes_text, BOLD_FONT_CANDIDATES, sx(66, image.size), sx(24, image.size), sx(COORDS["likes_max_width"], image.size))
    likes_text = ellipsize(draw, likes_text, likes_font, sx(COORDS["likes_max_width"], image.size))
    draw_text(image, (sx(COORDS["likes_x"], image.size), sy(COORDS["likes_y"], image.size)), likes_text, likes_font, fill=(0, 0, 0, 255))

    # UID
    uid_text = str(fields.get("uid") or "UNKNOWN")
    uid_font = fit_font(draw, uid_text, BOLD_FONT_CANDIDATES, sx(60, image.size), sx(24, image.size), sx(COORDS["uid_max_width"], image.size))
    uid_text = ellipsize(draw, uid_text, uid_font, sx(COORDS["uid_max_width"], image.size))
    draw_text(
        image,
        (sx(COORDS["uid_x"], image.size), sy(COORDS["uid_y"], image.size)),
        uid_text,
        uid_font,
        fill=(255, 255, 255, 255),
        stroke_width=max(1, sx(2, image.size)),
        stroke_fill=(0, 0, 0, 255),
    )

    if debug:
        draw_debug(ImageDraw.Draw(image), image.size)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "api": "Free Fire Profile Image API",
        "endpoint": "/profile-image?server=SERVER&uid=PLAYER_UID&key=suyash",
        "example": "/profile-image?server=IND&uid=6950878222&key=suyash",
        "credits": {
            "developer": "Pankaj Sah",
            "handle": "pankaj-ux",
            "source": "Origin X Devs",
            "assets": "pankaj07-ux/ff-assets"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/profile-image", methods=["GET"])
def profile_image():
    uid = request.args.get("uid")
    server = request.args.get("server", INFO_SERVER).strip() or INFO_SERVER
    key = request.args.get("key")
    debug = request.args.get("debug") == "1"

    if key != API_KEY:
        return jsonify({"error": "Invalid or missing API key"}), 401
    if not uid:
        return jsonify({"error": "Missing uid parameter"}), 400

    player_data = fetch_player_info(uid, server=server)
    if player_data is None:
        return jsonify({"error": "Failed to fetch player info"}), 500

    fields = extract_profile_fields(player_data)
    if fields is None:
        return jsonify({"error": "Invalid player data returned by info API"}), 500

    try:
        return send_file(render_profile_card(fields, debug=debug), mimetype="image/png")
    except Exception as exc:
        return jsonify({"error": f"Failed to render image: {str(exc)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
