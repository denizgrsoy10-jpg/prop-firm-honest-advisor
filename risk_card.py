"""
risk_card.py — Candor shareable "Risk Card" generator (PIL, headless, no browser).
Produces a 1080x1080 PNG for social sharing.

Fonts are BUNDLED in ./fonts next to this file, so the card looks identical on any
server (Streamlit Cloud included) even with no system fonts. Ship the ./fonts folder.

Usage in Streamlit:
    from risk_card import build_risk_card
    png = build_risk_card(killer_rule=p["killer_rule"],
                          fit_label="Strong fit",
                          n_trades=p["data"]["n_trades"],
                          blocks=None, url="candor.app")
    st.download_button("Download your Risk Card", png,
                       file_name="candor-risk-card.png", mime="image/png")
"""
from __future__ import annotations
import io, os
from PIL import Image, ImageDraw, ImageFont

BG    = (11, 17, 23)
PANEL = (15, 22, 32)
GOLD  = (217, 163, 50)
CREAM = (247, 243, 234)
MUTED = (150, 160, 172)
DARK  = (11, 17, 23)

W = H = 1080
M = 70

_HERE = os.path.dirname(os.path.abspath(__file__))
# Bundled fonts FIRST so the card renders identically everywhere.
_FONT_DIRS = [
    os.path.join(_HERE, "fonts"),
    _HERE,
    "/usr/share/fonts/truetype/google-fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/Library/Fonts", "/System/Library/Fonts",
]

def _find(*names):
    for n in names:
        if os.path.isabs(n) and os.path.exists(n):
            return n
        for d in _FONT_DIRS:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None

def _font(kind, size):
    if kind in ("bold", "semibold"):
        path = _find("Poppins-Bold.ttf", "DejaVuSans-Bold.ttf")
    else:
        path = _find("Poppins-Regular.ttf", "DejaVuSans.ttf")
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)   # PIL >= 10
    except Exception:
        return ImageFont.load_default()

def _w(draw, text, font):
    return draw.textlength(text, font=font)

def _center(draw, y, text, font, fill, spacing=0):
    if spacing:
        total = sum(_w(draw, ch, font) + spacing for ch in text) - spacing
        x = (W - total) / 2
        for ch in text:
            draw.text((x, y), ch, font=font, fill=fill)
            x += _w(draw, ch, font) + spacing
    else:
        x = (W - _w(draw, text, font)) / 2
        draw.text((x, y), text, font=font, fill=fill)

def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if _w(draw, t, font) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = wd
    if cur: lines.append(cur)
    return lines

def build_risk_card(killer_rule="Profit target not reached in window",
                    fit_label="Strong fit",
                    n_trades=292,
                    blocks=None,
                    url="candor.app") -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([M//2, M//2, W-M//2, H-M//2], radius=34, outline=GOLD, width=2)
    d.rectangle([M//2, M//2, W-M//2, M//2+5], fill=GOLD)

    d.text((M+14, M+18), "CANDOR", font=_font("bold", 34), fill=GOLD)
    rc = "RISK CARD"; f = _font("reg", 24)
    d.text((W-M-14-_w(d, rc, f), M+24), rc, font=f, fill=MUTED)
    d.line([M+14, M+82, W-M-14, M+82], fill=(38, 48, 59), width=2)

    _center(d, 250, "MY KILLER RULE", _font("reg", 28), (200, 205, 212), spacing=10)

    fb = _font("bold", 92)
    lines = _wrap(d, killer_rule, fb, W - 2*(M+40))
    if len(lines) > 2:
        fb = _font("bold", 62); lines = _wrap(d, killer_rule, fb, W - 2*(M+40))
    y = 330
    for ln in lines:
        _center(d, y, ln, fb, GOLD); y += fb.size + 6

    y += 22
    _center(d, y, "The rule most likely to end my prop challenge.",
            _font("reg", 30), (183, 192, 203)); y += 52

    chip = (f"Blocks {blocks} rulesets   ·   {n_trades}-trade scan" if blocks
            else f"{n_trades}-trade honest scan")
    cf = _font("reg", 27); cw = _w(d, chip, cf)
    d.rounded_rectangle([(W-cw)/2-30, y+6, (W+cw)/2+30, y+64], radius=29, outline=GOLD, width=2)
    d.text(((W-cw)/2, y+21), chip, font=cf, fill=GOLD); y += 116

    d.rounded_rectangle([M+14, y, W-M-14, y+120], radius=18, fill=PANEL, outline=(51,64,77), width=2)
    lx, ly = M+52, y+40
    d.rounded_rectangle([lx, ly+16, lx+34, ly+52], radius=6, outline=MUTED, width=3)
    d.arc([lx+5, ly-6, lx+29, ly+28], 180, 360, fill=MUTED, width=3)
    d.text((lx+66, y+30), "Best-fit firm   ·   pass-odds   ·   fee burn",
           font=_font("semibold", 30), fill=(199,208,219))
    d.text((lx+66, y+72), "Unlocked in the full report", font=_font("reg", 26), fill=MUTED)
    y += 152

    d.rounded_rectangle([M+14, y, W-M-14, y+98], radius=18, fill=GOLD)
    _center(d, y+18, "What's YOUR killer rule?", _font("bold", 34), DARK)
    _center(d, y+60, f"Run your free RealityCheck    {url}", _font("semibold", 26), DARK)

    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

if __name__ == "__main__":
    open("risk_card_sample.png", "wb").write(build_risk_card())
    print("wrote risk_card_sample.png")
