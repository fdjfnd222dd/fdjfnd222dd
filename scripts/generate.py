#!/usr/bin/env python3
"""Generate the profile dashboard: assets/window.svg and assets/terminal.svg.

Look: a Windows 95 "Properties" window (repo list + contribution heatmap) and a
matching "MS-DOS Prompt" that types three commands on a loop.

Why SVG: GitHub strips CSS/JS from README markdown, but renders <img src=*.svg>
with inline <style> and SMIL animation intact. Everything is self-contained: no
scripts, no external fonts, no external hrefs.

Why explicit per-glyph x positions in the DOS window: monospace fonts differ by a
fraction of a pixel between systems; absolute x keeps columns and the typing
cursor aligned on whatever font the viewer falls back to. The Win95 window uses
fixed column x positions with short, pre-shortened text for the same reason.

Data: GitHub REST + GraphQL, token from GITHUB_TOKEN (Actions) or `gh auth token`
(local). Every field is independent: if one call fails it renders "n/a" and the
rest still render. This script never raises.

Usage:
  python scripts/generate.py                    # writes assets/*.svg
  python scripts/generate.py --preview DIR      # static terminal frames for PNG review
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
NA = "n/a"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Display order; anything else public follows, newest push first. Forks go last.
ORDER = ["goodix-550c-linux-debian", "ctop-tui", "net-toolkit", "formhand", "jobbot", "pi-robot-cam", "letterstore",
         "study-timer", USER, "spiff-arena"]
# ---- Windows 95 palette (system colours) and fonts
FACE, DK, MID, LT, NAVY, TEAL = "#c0c0c0", "#000000", "#808080", "#ffffff", "#000080", "#008080"
UI = "Tahoma, 'MS Sans Serif', Verdana, 'DejaVu Sans', sans-serif"
MONO = "'Lucida Console', 'Courier New', 'DejaVu Sans Mono', ui-monospace, monospace"
HEAT = ["#e4e4e4", "#99cccc", "#4da6a6", "#008080", "#004848"]  # empty .. busiest


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
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nb-profile-dashboard"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = json.dumps(body).encode() if body is not None else None
    try:
        req = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        print(f"warn: {path}: {e}", file=sys.stderr)
        return None


def parse_ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def short(s, n=46):
    """One-line description: cut at the first natural clause, else at a word."""
    s = " ".join(str(s).split())
    best = s
    for sep in (":", ". ", ", ", " that ", " you ", " for ", " with "):
        if sep in s:
            head = s.split(sep)[0]
            if 12 <= len(head) < len(best):
                best = head
    s = best
    if len(s) > n:
        s = s[: n - 1]
        s = s[: s.rindex(" ")] if " " in s else s
        s = s.rstrip(" ,.;-") + "\u2026"
    return s.rstrip(".")


def collect():
    d = {}
    now = dt.datetime.now(dt.timezone.utc)
    d["now"] = now
    repos = {r["name"]: r for r in (api(f"/users/{USER}/repos?per_page=100&type=owner") or [])}
    rows = []
    for n in list(ORDER) + sorted((k for k in repos if k not in ORDER), key=lambda k: repos[k]["pushed_at"], reverse=True):
        r = repos.get(n)
        if r is None:
            continue
        fork = bool(r.get("fork"))
        rows.append(dict(
            name=n, desc=short(r.get("description") or NA),
            type="Fork" if fork else (r.get("language") or "n/a"),
            stars=r.get("stargazers_count", 0), fork=fork))
    rows.sort(key=lambda x: x["fork"])  # stable: forks last, ORDER kept
    d["rows"] = rows
    d["nrepos"] = len(rows) if rows else NA
    d["forks"] = sum(1 for x in rows if x["fork"])

    # Rolling 365 days (not calendar year). Totals include private contributions
    # when the owner enabled "include private contributions" on their profile.
    d["contrib"], d["active"], d["age"], d["weeks"] = NA, NA, NA, []
    q = api("/graphql", {"query": """query($u:String!,$f:DateTime!,$t:DateTime!){user(login:$u){createdAt
        contributionsCollection(from:$f,to:$t){contributionCalendar{totalContributions
        weeks{contributionDays{date weekday contributionCount}}}}}}""",
        "variables": {"u": USER, "f": (now - dt.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "t": now.strftime("%Y-%m-%dT%H:%M:%SZ")}})
    try:
        u = q["data"]["user"]
        cal = u["contributionsCollection"]["contributionCalendar"]
        d["weeks"] = [w["contributionDays"] for w in cal["weeks"]]
        d["contrib"] = cal["totalContributions"]
        d["active"] = sum(1 for w in d["weeks"] for x in w if x["contributionCount"] > 0)
        mo = (now - parse_ts(u["createdAt"])).days // 30
        d["age"] = f"{mo} months" if mo < 24 else f"{mo // 12} years"
    except Exception as e:
        print(f"warn: contributions: {e}", file=sys.stderr)

    def last_commit():
        for e in api(f"/users/{USER}/events/public?per_page=50") or []:
            if e.get("type") != "PushEvent":
                continue
            repo = e["repo"]["name"]
            msgs = [c["message"] for c in e.get("payload", {}).get("commits", []) if c.get("message")]
            when = e["created_at"]
            if not msgs:  # events often omit commits[]; ask the repo
                cs = api(f"/repos/{repo}/commits?per_page=1")
                if cs:
                    msgs = [cs[0]["commit"]["message"]]
                    when = cs[0]["commit"]["author"]["date"]
            if msgs:
                return (when[:10], repo.split("/")[-1], msgs[-1].splitlines()[0])
    try:
        d["last"] = last_commit() or NA
    except Exception as e:
        print(f"warn: last commit: {e}", file=sys.stderr)
        d["last"] = NA
    return d


# ------------------------------------------------------------------ svg helpers
def clean(s):
    """XML-safe text: drop control chars and non-BMP (emoji), then escape."""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s))
    return escape("".join(c for c in s if ord(c) < 0x10000))


def trunc(s, n):
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    cut = s[: n - 1]
    if " " in cut and s[n - 1] != " ":
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,.:;-") + "\u2026"


def bevel(o, x, y, w, h, raised=True, fill=FACE):
    """Win95 two-pixel bevel. Raised = buttons/panels; sunken = fields."""
    a, b = (LT, DK) if raised else (DK, LT)
    a2, b2 = (FACE, MID) if raised else (MID, FACE)
    cs = 'fill="none" shape-rendering="crispEdges"'
    if fill:
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
    o.append(f'<path d="M{x + .5} {y + h}V{y + .5}H{x + w}" stroke="{a}" {cs}/>')
    o.append(f'<path d="M{x + w - .5} {y}V{y + h - .5}H{x}" stroke="{b}" {cs}/>')
    o.append(f'<path d="M{x + 1.5} {y + h - 1}V{y + 1.5}H{x + w - 1}" stroke="{a2}" {cs}/>')
    o.append(f'<path d="M{x + w - 1.5} {y + 1}V{y + h - 1.5}H{x + 1}" stroke="{b2}" {cs}/>')


def chrome(o, W, H, title):
    """Window frame, navy title bar, three caption buttons. 1px black outline so the
    grey face never bleeds into a light page background."""
    o.append(f'<rect width="{W}" height="{H}" fill="{FACE}"/>')
    bevel(o, 0, 0, W, H)
    o.append(f'<rect x="4" y="4" width="{W - 8}" height="20" fill="{NAVY}"/>')
    o.append(f'<text x="9" y="18" fill="{LT}" font-weight="bold" class="ui">{clean(title)}</text>')
    for i, kind in enumerate(("min", "max", "x")):
        x = W - 6 - (3 - i) * 18 - (2 if i == 2 else 0)
        bevel(o, x, 6, 16, 14)
        if kind == "min":
            o.append(f'<rect x="{x + 4}" y="15" width="7" height="2" fill="{DK}"/>')
        elif kind == "max":
            o.append(f'<rect x="{x + 3.5}" y="8.5" width="9" height="7" fill="none" stroke="{DK}"/>'
                     f'<rect x="{x + 3}" y="8" width="10" height="2" fill="{DK}"/>')
        else:
            o.append(f'<path d="M{x + 4} 8.5L{x + 12} 16.5M{x + 12} 8.5L{x + 4} 16.5" stroke="{DK}" stroke-width="2"/>')
    o.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" fill="none" stroke="{DK}"/>')


def wrap(W, H, body, css, title, desc):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">\n'
            f'<title id="t">{clean(title)}</title><desc id="d">{clean(desc)}</desc>\n<style>{css}</style>\n{body}\n</svg>\n')


UI_CSS = f".ui{{font-family:{UI};font-size:13px}}.sm{{font-family:{UI};font-size:11px}}.num{{font-variant-numeric:tabular-nums}}"


# ------------------------------------------------------------------ window.svg
def level(n, mx):
    if n <= 0:
        return 0
    return min(4, 1 + int(3.999 * (n - 1) / max(mx - 1, 1) * 0.999)) if mx > 1 else 2


def heatmap(o, weeks, x0, y0, pitch=14, cell=11, ramp=HEAT):
    """GitHub-style grid, one column per week, rows Sun..Sat; Mon/Wed/Fri labels."""
    o.append(f'<text x="{x0 - 8}" y="{y0 + 1 * pitch + 9}" text-anchor="end" fill="{DK}" class="sm">Mon</text>')
    o.append(f'<text x="{x0 - 8}" y="{y0 + 3 * pitch + 9}" text-anchor="end" fill="{DK}" class="sm">Wed</text>')
    o.append(f'<text x="{x0 - 8}" y="{y0 + 5 * pitch + 9}" text-anchor="end" fill="{DK}" class="sm">Fri</text>')
    counts = [x["contributionCount"] for w in weeks for x in w]
    mx = max(counts) if counts else 0
    nz = sorted(c for c in counts if c > 0)
    # quartile thresholds over non-empty days, as GitHub does, so one huge day
    # does not flatten everything else
    cuts = [nz[int(len(nz) * f)] for f in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]
    def lv(c):
        return 0 if c <= 0 else 1 + sum(c > t for t in cuts)
    last_label = -10
    for i, w in enumerate(weeks):
        first = dt.date.fromisoformat(w[0]["date"])
        if (i == 0 or first.day <= 7) and i - last_label >= 3 and (i > 0 or first.day <= 14):
            o.append(f'<text x="{x0 + i * pitch}" y="{y0 - 5}" fill="{DK}" class="sm">{first.strftime("%b")}</text>')
            last_label = i
        for x in w:
            r = x["weekday"]
            c = x["contributionCount"]
            o.append(f'<rect x="{x0 + i * pitch}" y="{y0 + r * pitch}" width="{cell}" height="{cell}" fill="{ramp[lv(c)]}"/>')


def window_svg(d, ramp=HEAT):
    W = 860
    rows = d["rows"]
    rowh = 20
    o = []
    chrome(o, W, 10, "nb@github - Properties")  # placeholder height, replaced below
    o.clear()
    listy = 72
    list_h = 22 + rowh * max(len(rows), 1) + 6
    act_y = listy + list_h + 16
    panel_y = act_y + 6
    panel_h = 154
    H = panel_y + panel_h + 14 + 28
    chrome(o, W, H, "nb@github - Properties")
    mx = 12
    for m in ("File", "Edit", "View", "Help"):
        o.append(f'<text x="{mx}" y="44" fill="{DK}" class="ui">{m}</text>')
        mx += 26 + len(m) * 7
    o.append(f'<text x="14" y="{listy - 6}" fill="{DK}" class="ui">Public repositories of @{USER}:</text>')
    lw = W - 28
    bevel(o, 14, listy, lw, list_h, raised=False, fill=LT)
    # Stars column only when at least one repo has stars; otherwise Description widens.
    stars = any(r["stars"] for r in rows)
    # Name column fits "goodix-550c-linux-debian"; Description gives up the width.
    if stars:
        cols = [(18, 190, "Name"), (208, 404, "Description"), (612, 100, "Type"), (712, lw - 712 + 10, "Stars")]
    else:
        cols = [(18, 190, "Name"), (208, 524, "Description"), (732, lw - 732 + 10, "Type")]
    px = cols[2][0] + 6
    for x, w, t in cols:
        bevel(o, x, listy + 3, w, 20)
        o.append(f'<text x="{x + 6}" y="{listy + 17}" fill="{DK}" class="ui">{t}</text>')
    y = listy + 24
    for i, r in enumerate(rows):
        sel = i == 0
        if sel:
            o.append(f'<rect x="18" y="{y}" width="{lw - 8}" height="{rowh}" fill="{NAVY}"/>'
                     f'<rect x="18.5" y="{y + .5}" width="{lw - 9}" height="{rowh - 1}" fill="none" stroke="{LT}" stroke-dasharray="1 1"/>')
        col = LT if sel else DK
        ty = y + 14
        nm = clean(r["name"])
        o.append(f'<text x="24" y="{ty}" fill="{col}" class="ui">{nm}</text>')
        o.append(f'<text x="{cols[1][0] + 6}" y="{ty}" fill="{col}" class="ui">{clean(r["desc"])}</text>')
        o.append(f'<text x="{px}" y="{ty}" fill="{col}" class="ui">{clean(r["type"])}</text>')
        if r["stars"]:
            o.append(f'<text x="{cols[3][0] + 6}" y="{ty}" fill="{col}" class="ui num">{r["stars"]}</text>')
        y += rowh
    o.append(f'<text x="14" y="{act_y}" fill="{DK}" class="ui">Activity:</text>')
    bevel(o, 14, panel_y, lw, panel_h, raised=False, fill=LT)
    weeks = d["weeks"]
    if weeks:
        heatmap(o, weeks, 58, panel_y + 28, ramp=ramp)
        # legend, bottom right of the panel
        lx = 14 + lw - 8 - (34 + 5 * 15 + 34)
        ly = panel_y + panel_h - 22
        o.append(f'<text x="{lx}" y="{ly + 10}" fill="{DK}" class="sm">Less</text>')
        for i, c in enumerate(ramp):
            o.append(f'<rect x="{lx + 30 + i * 15}" y="{ly}" width="11" height="11" fill="{c}"/>')
        o.append(f'<text x="{lx + 30 + 5 * 15 + 3}" y="{ly + 10}" fill="{DK}" class="sm">More</text>')
    else:
        o.append(f'<text x="24" y="{panel_y + 30}" fill="{MID}" class="ui">n/a</text>')
    # status bar
    sy = H - 26
    cells = [(f"{d['contrib']} contributions, last 365 days", 290), (f"{d['active']} active days", 150),
             (f"{d['nrepos']} repos" + (f" ({d['forks']} fork)" if d["forks"] else ""), 150), (f"account age {d['age']}", 0)]
    x = 8
    for t, w in cells:
        w = w or (W - 8 - x)
        bevel(o, x, sy, w, 20, raised=False, fill=None)
        o.append(f'<text x="{x + 6}" y="{sy + 14}" fill="{DK}" class="ui">{clean(t)}</text>')
        x += w + 2
    return wrap(W, H, "\n".join(o), UI_CSS, "nb@github - Properties",
                f"Public repositories of {USER} with a contribution heatmap for the last 365 days.")


# ------------------------------------------------------------------ terminal.svg
CW, LH, TX = 8.4, 19, 24
CYCLE, RESET_AT = 20.0, 19.4
PROMPT = "C:\\GITHUB>"
PX = TX + len(PROMPT) * CW
TOP = 52  # first text baseline
GREY, WHITE = "#c0c0c0", "#ffffff"


def xs(x0, text):
    return " ".join(f"{x0 + i * CW:.2f}" for i in range(len(text)))


def build_script(d):
    rnd = random.Random(7)  # fixed seed -> stable diffs

    def cadence(t, text):
        out = []
        for ch in text:
            t += rnd.uniform(0.055, 0.12) + (0.09 if ch in " ." and rnd.random() < .5 else 0)
            out.append(round(t, 3))
        return out
    ev, line, t = [], 0, 0.7

    def cmd(text):
        nonlocal line, t
        ts = cadence(t, text)
        ev.append(("type", line, text, ts))
        t = ts[-1] + 0.4
        line += 1

    def out(text, tt, color=GREY):
        nonlocal line
        ev.append(("out", line, text, round(tt, 3), color))
        line += 1
    cmd("dir")
    out(" Directory of C:\\GITHUB", t); t += 0.15
    out("", t); t += 0.0
    nw = max([16] + [len(r["name"]) + 2 for r in d["rows"]])
    for r in d["rows"]:
        out(f"{r['name']:<{nw}}{'<DIR>':<8}{r['type']}", t); t += 0.14
    out(f"{len(d['rows']):>8} dir(s)", t)
    t += 1.3
    cmd("type stats.txt")
    stats = [("contributions", f"{d['contrib']}  (last 365 days)"), ("active days", str(d["active"])),
             ("repos", f"{d['nrepos']}" + (f"  ({d['forks']} fork)" if d["forks"] else "")), ("account age", str(d["age"]))]
    for k, v in stats:
        out(f"{k:<16}{v}", t); t += 0.14
    t += 1.2
    cmd("type last.log")
    if isinstance(d["last"], tuple):
        when, repo, msg = d["last"]
        out(trunc(f"{when}  {repo}  {msg}", 92), t)
    else:
        out(NA, t)
    t += 0.9
    ev.append(("prompt", line, "", round(t, 3)))
    return ev, line


def vis_anim(t_on, t_off=RESET_AT):
    return (f'<animate attributeName="visibility" calcMode="discrete" dur="{CYCLE:g}s" repeatCount="indefinite" '
            f'values="hidden;visible;hidden;hidden" keyTimes="0;{t_on / CYCLE:.4f};{t_off / CYCLE:.4f};1"/>')


def terminal_body(d, mode="anim", at=None):
    """Session lines on the black screen. mode: anim (SMIL) | static | frame (snapshot at `at`)."""
    ev, last = build_script(d)
    o = []

    def show(t_on):
        if mode == "anim":
            return ' visibility="hidden"', vis_anim(t_on)
        if mode == "static" or (at is not None and t_on <= at):
            return "", ""
        return ' visibility="hidden"', ""

    def prompt(y):
        return f'<text x="{xs(TX, PROMPT)}" y="{y}" fill="{GREY}">{clean(PROMPT)}</text>'
    for e in ev:
        kind, ln = e[0], e[1]
        y = TOP + ln * LH
        if kind == "type":
            text, times = e[2], e[3]
            attr, child = show(times[0] - 0.12)
            o.append(f'<g{attr}>{child}{prompt(y)}</g>')
            for i, (ch, tt) in enumerate(zip(text, times)):
                if ch != " ":
                    attr, child = show(tt)
                    o.append(f'<text x="{PX + i * CW:.2f}" y="{y}" fill="{WHITE}"{attr}>{child}{clean(ch)}</text>')
            nxt = next(x for x in ev if x[1] == ln + 1)
            t_end = nxt[3] if nxt[0] != "type" else nxt[3][0] - 0.12
            if mode == "anim":
                kt = ";".join(f"{(v / CYCLE):.4f}" for v in [times[0] - 0.12] + times)
                vals = f"{PX:.2f};{PX:.2f};" + ";".join(f"{PX + (i + 1) * CW:.2f}" for i in range(len(text)))
                o.append(f'<rect y="{y - 12}" x="{PX:.2f}" width="{CW}" height="15" fill="{GREY}" visibility="hidden">'
                         f'<animate attributeName="x" calcMode="discrete" dur="{CYCLE:g}s" repeatCount="indefinite" values="{vals}" keyTimes="0;{kt}"/>'
                         f'{vis_anim(times[0] - 0.12, t_end)}</rect>')
            elif mode == "frame" and at is not None and times[0] - 0.12 <= at < t_end:
                k = sum(1 for tt in times if tt <= at)
                o.append(f'<rect x="{PX + k * CW:.2f}" y="{y - 12}" width="{CW}" height="15" fill="{GREY}"/>')
        elif kind == "out":
            if e[2]:
                attr, child = show(e[3])
                o.append(f'<g{attr}>{child}<text x="{xs(TX, e[2])}" y="{y}" fill="{e[4]}" xml:space="preserve">{clean(e[2])}</text></g>')
        elif kind == "prompt":
            attr, child = show(e[3])
            blink = ('<animate attributeName="opacity" dur="1.1s" repeatCount="indefinite" calcMode="discrete" values="1;0" keyTimes="0;.5"/>'
                     if mode == "anim" else "")
            o.append(f'<g{attr}>{child}{prompt(y)}<rect x="{PX:.2f}" y="{y - 12}" width="{CW}" height="15" fill="{GREY}">{blink}</rect></g>')
    return "\n".join(o), last


def terminal_svg(d, mode="reduced", at=None):
    """mode 'reduced': animated group, with a static final frame shown under prefers-reduced-motion.
    mode 'frame': one snapshot at `at` seconds (preview only)."""
    W = 860
    _, last = build_script(d)
    H = TOP + (last + 1) * LH + 22 + 8
    o = []
    chrome(o, W, H, "MS-DOS Prompt")
    sx, sy, sw, sh = 8, 30, W - 16, H - 38
    bevel(o, sx, sy, sw, sh, raised=False, fill=DK)
    body = ""
    css = UI_CSS + f".dos text{{font-family:{MONO};font-size:14px}}"
    screen_y = 0
    if mode == "frame":
        b, _ = terminal_body(d, "frame", at)
        body = f'<g class="dos">{b}</g>'
    else:
        a, _ = terminal_body(d, "anim")
        s, _ = terminal_body(d, "static")
        css += "#s{display:none}@media (prefers-reduced-motion:reduce){#a{display:none}#s{display:inline}}"
        body = f'<g class="dos" id="a">{a}</g><g class="dos" id="s">{s}</g>'
    return wrap(W, H, "\n".join(o) + "\n" + body, css, "MS-DOS Prompt",
                "A looping terminal session: directory listing of the repos, the stats, and the latest commit message.")


def main():
    d = collect()
    printable = {k: v for k, v in d.items() if k not in ("weeks", "now")}
    print(json.dumps(printable, indent=1, default=str), file=sys.stderr)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    outs = {"window.svg": window_svg(d), "terminal.svg": terminal_svg(d)}
    for name, svg in outs.items():
        with open(os.path.join(ROOT, "assets", name), "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote assets/{name} ({len(svg)} bytes)")
    if "--preview" in sys.argv:
        pd = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(pd, exist_ok=True)
        for t in (1.5, 4.0, 7.5, 11.0, 14.0, 18.5):
            with open(os.path.join(pd, f"terminal-t{t:04.1f}.svg"), "w", encoding="utf-8") as f:
                f.write(terminal_svg(d, "frame", t))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never fail the workflow on a render bug
        import traceback
        traceback.print_exc()
        print(f"error: {e}", file=sys.stderr)
        sys.exit(0)
