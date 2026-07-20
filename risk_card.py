"""
risk_card.py — Candor shareable "Risk Card" generator (PIL, headless).
Produces a 1080x1080 PNG for social sharing. No browser needed.

Usage in Streamlit:
    from risk_card import build_risk_card
    png = build_risk_card(killer_rule=p["killer_rule"],
                          fit_label="Strong fit",
                          n_trades=p["data"]["n_trades"],
                          blocks="5 of 9",
                          url="candor.app")
    st.download_button("Download your Risk Card", png,
                       file_name="candor-risk-card.png", mime="image/png")
"""
from __future__ import annotations
import io, os
from PIL import Image, ImageDraw, ImageFont

# ---- brand palette ----
BG     = (11, 17, 23)      # #0B1117
PANEL  = (15, 22, 32)      # #0F1620
GOLD   = (217, 163, 50)    # #D9A332
CREAM  = (247, 243, 234)   # #F7F3EA
MUTED  = (150, 160, 172)
FAINT  = (110, 120, 132)
DARK   = (11, 17, 23)

W = H = 1080
M = 70  # frame margin

_FONT_DIRS = [
    "/usr/share/fonts/truetype/google-fonts",
    "/usr/share/fonts/truetype/poppins",
    "/usr/share/fonts/truetype/lato",
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
    if kind == "bold":
        path = _find("Poppins-Bold.ttf", "DejaVuSans-Bold.ttf")
    elif kind == "semibold":
        path = _find("Poppins-SemiBold.ttf", "Lato-Semibold.ttf", "DejaVuSans-Bold.ttf")
    elif kind == "mono":
        path = _find("DejaVuSansMono.ttf")
    else:
        path = _find("Lato-Regular.ttf", "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
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

def build_risk_card(killer_rule="Profit target not reached",
                    fit_label="Strong fit",
                    n_trades=292,
                    blocks="5 of 9",
                    url="candor.app") -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # frame
    d.rounded_rectangle([M//2, M//2, W-M//2, H-M//2], radius=34,
                        outline=GOLD, width=2)
    d.rectangle([M//2, M//2, W-M//2, M//2+5], fill=GOLD)

    # header
    d.text((M+14, M+18), "CANDOR", font=_font("bold", 30), fill=GOLD)
    rc = "RISK CARD"; f = _font("mono", 22)
    d.text((W-M-14-_w(d, rc, f), M+24), rc, font=f, fill=MUTED)
    d.line([M+14, M+78, W-M-14, M+78], fill=(38, 48, 59), width=2)

    # label
    _center(d, 250, "MY KILLER RULE", _font("mono", 26), (200, 205, 212), spacing=10)

    # killer rule (big, wrapped)
    fb = _font("bold", 92)
    lines = _wrap(d, killer_rule, fb, W - 2*(M+40))
    if len(lines) > 2:  # shrink if too long
        fb = _font("bold", 68)
        lines = _wrap(d, killer_rule, fb, W - 2*(M+40))
    y = 330
    for ln in lines:
        _center(d, y, ln, fb, GOLD)
        y += fb.size + 8

    y += 20
    _center(d, y, "The rule most likely to end my prop challenge.",
            _font("reg", 30), (183, 192, 203)); y += 46

    # stat chip
    chip = (f"Blocks {blocks} rulesets  ·  {n_trades}-trade scan" if blocks
            else f"{n_trades}-trade honest scan")
    cf = _font("mono", 26); cw = _w(d, chip, cf)
    cx0 = (W-cw)/2 - 28; cx1 = (W+cw)/2 + 28
    d.rounded_rectangle([cx0, y+8, cx1, y+62], radius=27, outline=GOLD, width=2)
    d.text(((W-cw)/2, y+22), chip, font=cf, fill=GOLD); y += 110

    # locked strip
    d.rounded_rectangle([M+14, y, W-M-14, y+118], radius=18, fill=PANEL,
                        outline=(51, 64, 77), width=2)
    # padlock
    lx, ly = M+52, y+40
    d.rounded_rectangle([lx, ly+16, lx+34, ly+52], radius=6, outline=MUTED, width=3)
    d.arc([lx+5, ly-6, lx+29, ly+28], 180, 360, fill=MUTED, width=3)
    d.text((lx+64, y+30), "Best-fit firm  ·  pass-odds  ·  fee burn",
           font=_font("semibold", 30), fill=(199, 208, 219))
    d.text((lx+64, y+72), "Unlocked in the full report",
           font=_font("reg", 26), fill=MUTED)
    y += 150

    # CTA
    d.rounded_rectangle([M+14, y, W-M-14, y+96], radius=18, fill=GOLD)
    _center(d, y+18, "What's YOUR killer rule?", _font("bold", 32), DARK)
    _center(d, y+58, f"Run your free RealityCheck  →  {url}",
            _font("semibold", 26), DARK)

    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

if __name__ == "__main__":
    png = build_risk_card()
    open("risk_card_sample.png", "wb").write(png)
    print("wrote risk_card_sample.png", len(png), "bytes")
