#!/usr/bin/env python3
"""Generate the profile dashboard SVGs (assets/fetch.svg, assets/terminal.svg).

Why SVG: GitHub strips CSS/JS from README markdown, but renders <img src=*.svg>
with inline <style> and SMIL animation intact. So everything here is a
self-contained SVG: no scripts, no external fonts, no external hrefs.

Why explicit per-character x positions: monospace fonts differ by a fraction of
a pixel between systems. Placing every glyph at a computed x keeps the logo,
columns and typing cursor aligned no matter which font the viewer falls back to.

Data: GitHub REST + GraphQL, token from GITHUB_TOKEN (Actions) or `gh auth token`
(local). Unauthenticated works for REST only. Every field is independent: if one
call fails it renders "n/a" and the rest still render. This script never raises.

Usage:
  python scripts/generate.py                 # writes assets/*.svg
  python scripts/generate.py --preview DIR   # also writes static frames of the
                                             # terminal animation to DIR (for PNG review)
"""
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
import textwrap
import urllib.request
from xml.sax.saxutils import escape

USER = os.environ.get("PROFILE_USER", "fdjfnd222dd")
HANDLE = "nb"
DISPLAY = "Nick B"
FEATURED = ["ctop-tui", "formhand", "pi-robot-cam"]
# Used only when the API cannot supply a description (e.g. repo not public yet).
FALLBACK_DESC = {
    "pi-robot-cam": "Raspberry Pi robot you can watch and drive from a phone, with a safety auto-stop",
}
NA = "n/a"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- palette: lifted from ctop's own theme (ctop/app.py) so the two feel related
BG = "#0c0e12"       # ctop screen background
EDGE = "#1c2330"
FG = "#d0d4da"       # ctop body text
DIM = "#7d8590"      # ctop subtitle/dim
ACCENT = "#4ea1ff"   # ctop detail-box accent (the one echoed on the profile)
GREEN, AMBER, ROSE, BLUE = "#5fa86b", "#d9a441", "#c0627a", "#4f8fd6"
CYAN, VIOLET, INK = "#39c5cf", "#a07cc9", "#232a36"
SWATCH = [INK, ROSE, GREEN, AMBER, BLUE, VIOLET, CYAN, FG]
MONO = "ui-monospace, SFMono-Regular, 'DejaVu Sans Mono', Menlo, Consolas, monospace"

LANG_COLORS = {  # GitHub linguist colours, muted slightly by the card background
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#663399", "Shell": "#89e051", "C": "#555555",
    "C++": "#f34b7d", "Go": "#00ADD8", "Rust": "#dea584", "Java": "#b07219",
    "Dockerfile": "#384d54", "Makefile": "#427819", "Lua": "#000080",
}


# ------------------------------------------------------------------ API layer
def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    try:  # local convenience only
        return subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


TOKEN = token()


def api(path, body=None):
    """GET (or GraphQL POST when body given). Returns parsed JSON or None."""
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nb-profile-dashboard"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = json.dumps(body).encode() if body is not None else None
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        print(f"warn: {path}: {e}", file=sys.stderr)
        return None


def safe(fn, default=NA):
    try:
        v = fn()
        return default if v in (None, "") else v
    except Exception as e:
        print(f"warn: {fn.__name__ if hasattr(fn, '__name__') else 'field'}: {e}", file=sys.stderr)
        return default


def parse_ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def collect():
    d = {}
    repos = api(f"/users/{USER}/repos?per_page=100&type=owner") or []
    own = [r for r in repos if not r.get("fork") and r["name"].lower() != USER.lower()]
    d["repos"] = safe(lambda: len(own) if repos else None)

    def langs():
        tot = {}
        for r in own:
            for k, v in (api(f"/repos/{USER}/{r['name']}/languages") or {}).items():
                tot[k] = tot.get(k, 0) + v
        s = sum(tot.values())
        return [(k, v / s) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])] if s else None
    d["langs"] = safe(langs)

    now = dt.datetime.now(dt.timezone.utc)
    year = now.year

    # Commits come from the public repos' own commit lists (author=USER), so the
    # numbers match what visitors can verify. The GraphQL contributionsCollection
    # also counts private/org work, which would not match the repos shown here;
    # it is only the fallback when the REST listing fails entirely.
    dates = []
    ok = bool(own)
    for r in own:
        page = 1
        while page <= 5:
            cs = api(f"/repos/{USER}/{r['name']}/commits?per_page=100&page={page}&since={year}-01-01T00:00:00Z")
            if cs is None:
                ok = False
                break
            dates += [c["commit"]["author"]["date"][:10] for c in cs]
            if len(cs) < 100:
                break
            page += 1
    if ok:
        d["commits"] = f"{len(dates)} in {year}"
        days = sorted(set(dates))
        best = run = 0
        prev = None
        for x in days:
            cur = dt.date.fromisoformat(x)
            run = run + 1 if prev and (cur - prev).days == 1 else 1
            best, prev = max(best, run), cur
        d["streak"] = f"{len(days)} active day{'s' if len(days) != 1 else ''}, best streak {best}"
    else:
        g = api("/graphql", {"query": "query($u:String!,$f:DateTime!){user(login:$u){contributionsCollection(from:$f){totalCommitContributions}}}",
                             "variables": {"u": USER, "f": f"{year}-01-01T00:00:00Z"}})
        d["commits"] = safe(lambda: f"{g['data']['user']['contributionsCollection']['totalCommitContributions']} in {year}")
        d["streak"] = NA

    firsts = sorted(r["created_at"] for r in own)
    d["since"] = safe(lambda: firsts[0][:4])
    d["uptime_days"] = safe(lambda: (now - parse_ts(firsts[0])).days)

    cnt = [0]

    def release():
        best = None
        for r in own:
            rel = api(f"/repos/{USER}/{r['name']}/releases/latest")
            if rel and rel.get("tag_name"):
                cnt[0] += 1
                t = rel.get("published_at") or rel.get("created_at")
                if best is None or t > best[0]:
                    best = (t, f"{r['name']}@{rel['tag_name']}")
        return best[1] if best else None
    d["release"] = safe(release)
    d["relcount"] = f"{cnt[0]} tagged" if d["release"] != NA else NA

    def topics():
        c = {}
        for r in own:
            for t in r.get("topics") or []:
                c[t] = c.get(t, 0) + 1
        top = []
        for t in sorted(c, key=lambda t: (-c[t], t))[:4]:  # up to 4, as many as fit the card
            if len(" \u00b7 ".join(top + [t])) <= 40:
                top.append(t)
        return " \u00b7 ".join(top) if top else None
    d["topics"] = safe(topics)

    by = {r["name"]: r for r in repos}
    d["featured"] = []
    for n in FEATURED:
        desc = (by.get(n) or {}).get("description") or FALLBACK_DESC.get(n) or NA
        d["featured"].append((n, desc))

    def last_commit():
        ev = api(f"/users/{USER}/events/public?per_page=50") or []
        for e in ev:
            if e.get("type") != "PushEvent":
                continue
            repo = e["repo"]["name"]
            msgs = [c["message"] for c in e.get("payload", {}).get("commits", []) if c.get("message")]
            when = e["created_at"]
            if not msgs:  # GitHub often omits commits[] from events; ask the repo
                cs = api(f"/repos/{repo}/commits?per_page=1")
                if cs:
                    msgs = [cs[0]["commit"]["message"]]
                    when = cs[0]["commit"]["author"]["date"]
            if msgs:
                return (when[:10] + " " + when[11:16], repo.split("/")[-1], msgs[-1].splitlines()[0])
        return None
    d["last"] = safe(last_commit)
    d["updated"] = now.strftime("%Y-%m-%d")
    return d


# ------------------------------------------------------------------ helpers
def clean(s):
    """XML-safe text: drop control chars and non-BMP (emoji) then escape."""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s))
    s = "".join(c for c in s if ord(c) < 0x10000)
    return escape(s)


def trunc(s, n):
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    cut = s[: n - 1]
    if " " in cut and s[n - 1] != " ":  # prefer a word boundary over a mid-word cut
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,.:;-") + "\u2026"


def xs(x0, text, cw):
    return " ".join(f"{x0 + i * cw:.2f}" for i in range(len(text)))


def gtext(x0, y, text, cw, cls="", fill=None):
    """One <text> with an explicit x per glyph (font-independent columns)."""
    f = f' fill="{fill}"' if fill else ""
    c = f' class="{cls}"' if cls else ""
    return f'<text x="{xs(x0, text, cw)}" y="{y}"{c}{f} xml:space="preserve">{clean(text)}</text>'


def card(w, h, body, extra_css="", title="", desc=""):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">
<title id="t">{clean(title)}</title><desc id="d">{clean(desc)}</desc>
<style>
text{{font-family:{MONO};font-size:14px;fill:{FG}}}
.dim{{fill:{DIM}}} .k{{fill:{ACCENT};font-weight:bold}} .g{{fill:{GREEN}}} .a{{fill:{AMBER}}}
{extra_css}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="{BG}" stroke="{EDGE}"/>
{body}
</svg>
'''


# ------------------------------------------------------------------ fetch.svg
# 12-col glyphs, 3-col vertical strokes, ~1-row horizontal strokes, chamfered corners.
N = ["", "",
     "███" + "▄" * 8,
     "███" + "▀" * 6 + "███",
     "███      ███", "███      ███", "███      ███", "███      ███", "███      ███", "███      ███"]
B = ["███", "███",
     "███" + "▄" * 8,
     "███" + "▀" * 6 + "███",
     "███      ███", "███      ███", "███      ███", "███      ███", "███      ███",
     "███████████▀"]
LOGO = [a.ljust(14) + b.ljust(12) for a, b in zip(N, B)]
# top-to-bottom accent ramp, same hue family as ctop's blues
RAMP = ["#8cc4ff", "#7bb9ff", "#6aaeff", "#5ea6ff", "#4ea1ff", "#4a9af2", "#4a92e6", "#4f8fd6", "#4f8fd6", "#4a84c4"]


def fetch_svg(d):
    W, H = 860, 392
    cw = 9.6
    lx = 26
    ix, iw = 340, 8.4
    row = 23
    top = 62
    out = []
    # The logo is drawn as pixel runs rather than font glyphs: block characters
    # (█ ▄ ▀) fall back to different fonts on different systems and leave seams
    # between rows. Rects are identical everywhere. A soft offset shadow gives the
    # "ANSI Shadow" feel. Source text lives in LOGO so the art stays editable.
    cwp, rh = 11, 9  # px per column, px per half-row
    ly = top - 14 + (9 * row - len(LOGO) * 2 * rh) // 2 + 4
    def runs(i, line):
        j = 0
        while j < len(line):
            c = line[j]
            if c == " ":
                j += 1
                continue
            k = j
            while k < len(line) and line[k] == c:
                k += 1
            y0 = ly + i * 2 * rh + (rh if c == "\u2584" else 0)
            h = rh if c in "\u2584\u2580" else 2 * rh
            yield lx + j * cwp, y0, (k - j) * cwp, h
            j = k
    shadow, front = [], []
    for i, line in enumerate(LOGO):
        for x, y0, w, h in runs(i, line):
            shadow.append(f'<rect x="{x + 3}" y="{y0 + 3}" width="{w}" height="{h}"/>')
            front.append(f'<rect x="{x}" y="{y0}" width="{w}" height="{h}" fill="{RAMP[i]}"/>')
    out.append(f'<g fill="{INK}" shape-rendering="crispEdges">' + "".join(shadow) + "</g>")
    out.append('<g shape-rendering="crispEdges">' + "".join(front) + "</g>")

    y = top
    out.append(gtext(ix, y, f"{HANDLE}@github", iw, "k"))
    out.append(f'<text x="{ix}" y="{y}" dx="{len(HANDLE + "@github") * iw + 12:.1f}" class="dim">{clean(DISPLAY)}</text>')
    out.append(f'<text x="{ix + 440}" y="{y}" text-anchor="end" class="dim" style="font-size:12px">@{USER}</text>')
    y += 10
    out.append(f'<rect x="{ix}" y="{y}" width="440" height="1" fill="{EDGE}"/>')
    y += row - 4

    langs = d["langs"] if isinstance(d["langs"], list) else None
    lang_txt = "  ".join(f"{k} {v * 100:.0f}%" for k, v in langs[:3]) if langs else NA
    rows = [
        ("repos", f"{d['repos']} public"),
        ("langs", lang_txt),
        ("commits", d["commits"]),
        ("release", d["release"] if d["release"] == NA else f"{d['release']} \u00b7 {d['relcount']}"),
        ("topics", d["topics"]),
        ("featured", " · ".join(FEATURED)),
        ("updated", f"{d['updated']} by action"),
    ]
    vx = ix + 10 * iw
    for k, v in rows:
        out.append(gtext(ix, y, k, iw, "k"))
        out.append(gtext(vx, y, trunc(v, 54), iw, "na dim" if v == NA else ""))
        y += row
    # classic fastfetch language strip (proportional, rounded ends)
    y += 2
    bw = 440
    out.append(f'<clipPath id="bar"><rect x="{ix}" y="{y}" width="{bw}" height="12" rx="6"/></clipPath><g clip-path="url(#bar)">')
    if langs:
        x = float(ix)
        shown = [(k, v) for k, v in langs if v >= 0.01]
        tot = sum(v for _, v in shown)
        for k, v in shown:
            w = bw * v / tot
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{w + 0.6:.1f}" height="12" fill="{LANG_COLORS.get(k, DIM)}"/>')
            x += w
    else:
        out.append(f'<rect x="{ix}" y="{y}" width="{bw}" height="12" fill="{INK}"/>')
    out.append("</g>")
    # signature fastfetch swatch row
    y += 26
    for i, c in enumerate(SWATCH):
        out.append(f'<rect x="{ix + i * 34}" y="{y}" width="30" height="16" rx="3" fill="{c}"/>')
    css = ""
    return card(W, H, "\n".join(out), css, f"{HANDLE}@github",
                f"GitHub activity summary for {USER}, rendered as a system-info card.")


# ------------------------------------------------------------------ terminal.svg
CW, LH, TX, T0 = 8.4, 24, 28, 58
CYCLE = 20.0
RESET_AT = 19.4


def build_script(d):
    """Return list of ('type', line, text, start, [char times]) / ('out', line, [(text,cls,dx)], t)."""
    rnd = random.Random(7)  # fixed seed -> stable diffs between runs

    def cadence(t, text):
        times = []
        for ch in text:
            t += rnd.uniform(0.055, 0.12) + (0.09 if ch in " /-." and rnd.random() < .5 else 0)
            times.append(round(t, 3))
        return times
    ev = []
    t = 0.7
    cmds = [
        ("ls projects/", 0),
        ("uptime", 0),
        ("tail -1 activity.log", 0),
    ]
    line = 0
    # 1) ls projects/
    ev.append(("type", line, cmds[0][0], cadence(t, cmds[0][0])))
    t = ev[-1][3][-1] + 0.45
    line += 1
    nm = max(len(n) for n, _ in d["featured"]) + 3
    for n, desc in d["featured"]:
        avail = 90 - nm - 1
        ws = textwrap.wrap(desc, avail) or [desc]
        if len(ws) > 2:  # keep it to two lines; ellipsis only if still too long
            ws = [ws[0], trunc(" ".join(ws[1:]), avail)]
        for k, w in enumerate(ws):
            parts = [(n + "/", "k", 0)] if k == 0 else []
            ev.append(("out", line, parts + [(w, "dim", nm)], round(t, 3)))
            line += 1
        t += 0.28
    # 2) uptime
    t += 1.0
    ev.append(("type", line, cmds[1][0], cadence(t, cmds[1][0])))
    t = ev[-1][3][-1] + 0.4
    line += 1
    days = d["uptime_days"]
    up = f"up {days} day{'s' if days != 1 else ''} since first commit, {d['repos']} public repos" if days != NA else f"up {NA} since first commit, {d['repos']} public repos"
    ev.append(("out", line, [(up, "", 0)], round(t, 3)))
    line += 1
    # 3) tail -1 activity.log
    t += 1.2
    ev.append(("type", line, cmds[2][0], cadence(t, cmds[2][0])))
    t = ev[-1][3][-1] + 0.5
    line += 1
    if isinstance(d["last"], tuple):
        when, repo, msg = d["last"]
        parts = [(when, "dim", 0), (repo, "k", 17), (trunc(msg, 90 - 17 - len(repo) - 2), "", 17 + len(repo) + 2)]
    else:
        parts = [(NA, "dim", 0)]
    ev.append(("out", line, parts, round(t, 3)))
    line += 1
    t += 0.9
    ev.append(("prompt", line, "", round(t, 3)))  # idle prompt with blinking cursor
    return ev, line


PROMPT = "nb@github"
PROMPT_TAIL = ":~$ "
PX = TX + (len(PROMPT) + len(PROMPT_TAIL)) * CW


def prompt_markup(y, vis=None):
    a = vis or ""
    return (f'<g {a}><text x="{xs(TX, PROMPT, CW)}" y="{y}" class="g">{PROMPT}</text>'
            f'<text x="{xs(TX + len(PROMPT) * CW, PROMPT_TAIL.strip(), CW)}" y="{y}" class="dim">{PROMPT_TAIL.strip()}</text></g>')


def vis_anim(t_on, t_off=RESET_AT):
    """Hidden -> visible at t_on -> hidden at reset; loops with the document."""
    a, b = t_on / CYCLE, t_off / CYCLE
    return (f'<animate attributeName="visibility" calcMode="discrete" dur="{CYCLE:g}s" repeatCount="indefinite" '
            f'values="hidden;visible;hidden;hidden" keyTimes="0;{a:.4f};{b:.4f};1"/>')


def terminal_svg(d, mode="anim", at=None):
    """mode: anim (SMIL) | static (final frame) | frame (snapshot at `at` seconds)."""
    ev, last_line = build_script(d)
    W = 860
    H = T0 + (last_line + 1) * LH + 22
    out = []
    # window chrome: three muted dots + path title, no branding
    out.append(f'<circle cx="26" cy="22" r="5" fill="{ROSE}" opacity=".7"/><circle cx="44" cy="22" r="5" fill="{AMBER}" opacity=".7"/>'
               f'<circle cx="62" cy="22" r="5" fill="{GREEN}" opacity=".7"/>')
    out.append(f'<text x="{W / 2 - 60:.0f}" y="26" class="dim" style="font-size:12px">nb@github: ~</text>')
    out.append(f'<rect x="1" y="38" width="{W - 2}" height="1" fill="{EDGE}"/>')

    def show(t_on):
        """Return (attr, child) visibility pieces for an element appearing at t_on."""
        if mode == "anim":
            return ' visibility="hidden"', vis_anim(t_on)
        if mode == "static" or (at is not None and t_on <= at):
            return "", ""
        return ' visibility="hidden"', ""

    for e in ev:
        kind, ln = e[0], e[1]
        y = T0 + ln * LH
        if kind in ("type", "out"):
            pass
        if kind == "type":
            text, times = e[2], e[3]
            attr, child = show(times[0] - 0.12)
            out.append(f'<g{attr}>{child}<text x="{xs(TX, PROMPT, CW)}" y="{y}" class="g">{PROMPT}</text>'
                       f'<text x="{xs(TX + len(PROMPT) * CW, PROMPT_TAIL.strip(), CW)}" y="{y}" class="dim">{PROMPT_TAIL.strip()}</text></g>')
            for i, (ch, tt) in enumerate(zip(text, times)):
                if ch == " ":
                    continue
                attr, child = show(tt)
                out.append(f'<text x="{PX + i * CW:.2f}" y="{y}"{attr}>{child}{clean(ch)}</text>')
            # cursor block follows the last typed char, then disappears when the output lands
            nxt = next(x for x in ev if x[1] == ln + 1)
            t_end = nxt[3] if nxt[0] != "type" else nxt[3][0] - 0.12
            if mode == "anim":
                xv = ";".join(f"{PX + i * CW:.2f}" for i in range(len(text) + 1))
                kt = ";".join(f"{(t0 / CYCLE):.4f}" for t0 in [times[0] - 0.12] + times)
                # appear at first key, step along the text, hide after output lands
                vals = f"{PX:.2f};" + ";".join(f"{PX + (i + 1) * CW:.2f}" for i in range(len(text)))
                out.append(f'<rect y="{y - 12}" width="{CW:.2f}" height="16" fill="{ACCENT}" opacity=".85" visibility="hidden" x="{PX:.2f}">'
                           f'<animate attributeName="x" calcMode="discrete" dur="{CYCLE:g}s" repeatCount="indefinite" values="{PX:.2f};{vals}" keyTimes="0;{kt}"/>'
                           f'{vis_anim(times[0] - 0.12, t_end)}</rect>')
            elif mode == "frame" and at is not None and times[0] - 0.12 <= at < t_end:
                k = sum(1 for tt in times if tt <= at)
                out.append(f'<rect x="{PX + k * CW:.2f}" y="{y - 12}" width="{CW}" height="16" fill="{ACCENT}" opacity=".85"/>')
        elif kind == "out":
            attr, child = show(e[3])
            segs = "".join(
                f'<text x="{xs(TX + dx * CW, txt, CW)}" y="{y}"{(" class=%s" % chr(34) + cls + chr(34)) if cls else ""}>{clean(txt)}</text>'
                for txt, cls, dx in e[2])
            out.append(f'<g{attr}>{child}{segs}</g>')
        elif kind == "prompt":
            attr, child = show(e[3])
            out.append(f'<g{attr}>{child}<text x="{xs(TX, PROMPT, CW)}" y="{y}" class="g">{PROMPT}</text>'
                       f'<text x="{xs(TX + len(PROMPT) * CW, PROMPT_TAIL.strip(), CW)}" y="{y}" class="dim">{PROMPT_TAIL.strip()}</text>'
                       f'<rect x="{PX:.2f}" y="{y - 12}" width="{CW}" height="16" fill="{ACCENT}" opacity=".85">'
                       + ('<animate attributeName="opacity" dur="1.1s" repeatCount="indefinite" calcMode="discrete" values=".85;0" keyTimes="0;.5"/>' if mode == "anim" else "")
                       + '</rect></g>')
    body = "\n".join(out)
    return card(W, H, body, "", f"{HANDLE}@github terminal",
                "A looping terminal session listing projects, uptime since the first commit, and the latest commit message.")


def terminal_with_reduced_motion(d):
    """Animated group by default; static final frame replaces it under prefers-reduced-motion."""
    anim = terminal_svg(d, "anim")
    stat = terminal_svg(d, "static")
    grab = lambda s: s[s.index('<rect x="1" y="38"'):s.rindex("</svg>")].split("\n", 1)[1]
    # reuse the chrome from anim; swap only the session body
    head_end = anim.index('<rect x="1" y="38"')
    css = ("#s{display:none}@media (prefers-reduced-motion:reduce){#a{display:none}#s{display:inline}}")
    anim_body = anim[head_end:anim.rindex("</svg>")].split("\n", 1)[1]
    stat_body = stat[stat.index('<rect x="1" y="38"'):stat.rindex("</svg>")].split("\n", 1)[1]
    pre = anim[:head_end].replace("</style>", css + "\n</style>", 1)
    return pre + anim_body.join(['<rect x="1" y="38" width="858" height="1" fill="%s"/>\n<g id="a">' % EDGE, "</g>\n"]) + \
        '<g id="s">' + stat_body + "</g>\n</svg>\n"


def main():
    d = collect()
    print(json.dumps({k: v for k, v in d.items()}, indent=1, default=str), file=sys.stderr)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    for name, svg in (("fetch.svg", fetch_svg(d)), ("terminal.svg", terminal_with_reduced_motion(d))):
        with open(os.path.join(ROOT, "assets", name), "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote assets/{name} ({len(svg)} bytes)")
    if "--preview" in sys.argv:
        pd = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(pd, exist_ok=True)
        for t in (1.5, 3.0, 6.0, 9.5, 12.0):
            with open(os.path.join(pd, f"terminal-t{t:04.1f}.svg"), "w", encoding="utf-8") as f:
                f.write(terminal_svg(d, "frame", t))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # last-resort: never fail the workflow on a render bug
        print(f"error: {e}", file=sys.stderr)
        sys.exit(0)
