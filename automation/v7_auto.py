#!/usr/bin/env python3
"""
V7.2 AUTO - results apne aap + agle market ke 8 jodi Telegram par.
Chalta hai GitHub Actions par (.github/workflows/v7_auto.yml). Koi extra package nahi chahiye.

Har run mein:
  1. Is mahine ka chart 2 websites se laata hai (satta-king-fast.com + satta-no-fast.com).
  2. spi_results.json mein sirf MISSING results bharta hai. Purana result kabhi nahi badalta.
     Dono websites alag result dikhayein to kuch nahi bharta, sirf warning bhejta hai.
  3. Jis market se pehle wala result aa gaya ho, uske V7.2 wale 8 jodi Telegram par bhejta hai
     (Gali ke saath BAHAR haruf). Har market aur har din ke liye sirf ek baar.
  4. Subah Desawar ke baad kal ka hisaab (PASS/FAIL, Rs) bhejta hai.

Usage : python3 automation/v7_auto.py [normal|test]
Env   : GITHUB_TOKEN, GITHUB_REPOSITORY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Local : DRY_RUN=1 LOCAL_DIR=<folder with spi_results.json + automation/sent_state.json> [NOW_IST=2026-10-25T18:30]
        Isme kuch bhi bheja ya GitHub par likha nahi jaata; messages sirf print hote hain.
"""
import base64, collections, datetime, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v7_reference as V  # noqa: E402  (V7.2 model, same as the tool)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
D1 = datetime.timedelta(days=1)
MARKETS = ["Desawar", "Faridabad", "Ghaziabad", "Gali"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
RESULTS_PATH, STATE_PATH = "spi_results.json", "automation/sent_state.json"

# When a market's result normally appears (IST, on that result's own date): (earliest, latest) as (hour, minute).
# A website value for a date before 'earliest' is ignored (protects against wrong dates);
# after 'latest' a still-missing result gives ONE alert.  Gali latest 24:15 = 00:15 next day.
RESULT_WINDOW = {"Desawar": ((4, 30), (6, 15)), "Faridabad": ((17, 15), (19, 0)),
                 "Ghaziabad": ((20, 20), (22, 45)), "Gali": ((22, 45), (24, 15))}
DRAW_TEXT = {"Desawar": "subah ~5:00", "Faridabad": "~6:00 PM", "Ghaziabad": "~9:00-10:00 PM", "Gali": "~11:25 PM"}
# No slate is sent after this time (IST, on the target's result date).
CUTOFF = {"Desawar": (4, 40), "Faridabad": (17, 45), "Ghaziabad": (21, 30), "Gali": (23, 10)}
# Result that must be in before a market's slate is final: (market, day offset from the target's result date).
PREREQ = {"Desawar": ("Gali", -1), "Faridabad": ("Desawar", 0), "Ghaziabad": ("Faridabad", 0), "Gali": ("Ghaziabad", 0)}
REPORT_FOR = datetime.timedelta(hours=6)       # PASS/FAIL report only for results younger than this

ENV = os.environ.get
REPO = ENV("GITHUB_REPOSITORY") or "arunk8447ak/spi-pattern-engine"
BRANCH = ENV("BRANCH") or "main"
DRY = ENV("DRY_RUN") == "1"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-IN,en;q=0.9"}


def log(*a):
    print(*a, flush=True)


def at(d, hm):
    """IST datetime for date d at (hour, minute); hour may be >= 24 (next day)."""
    return datetime.datetime(d.year, d.month, d.day, tzinfo=IST) + datetime.timedelta(hours=hm[0], minutes=hm[1])


def fmt_day(d):
    return f"{d.day} {MONTHS[d.month - 1][:3]}"


def inr(x):
    """Indian grouping: 117000 -> 1,17,000"""
    s = str(int(round(abs(x))))
    if len(s) > 3:
        s = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3]) + "," + s[-3:]
    return s


def signed_inr(x):
    return ("+" if x >= 0 else "−") + "₹" + inr(x)


# ------------------------------------------------------------------ websites
def http(url, data=None, headers=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(url, post=None):
    hdr, data, err = dict(UA), None, None
    if post:
        data = urllib.parse.urlencode(post).encode()
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    for _ in range(3):
        try:
            return http(url, data, hdr).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(4)
    log(f"  fetch failed: {urllib.parse.urlsplit(url).netloc} ({type(err).__name__} {getattr(err, 'code', '')})")
    return ""


def parse_skf(h):
    """satta-king-fast.com month chart: DATE | DSWR | FRBD | GZBD | GALI  ->  {(market, date): number}"""
    names = {"DSWR": "Desawar", "FRBD": "Faridabad", "GZBD": "Ghaziabad", "GALI": "Gali"}
    m = re.search(r">\s*DATE\s*</td>(.*?)</tr>", h, re.S)
    if not m:
        return {}
    cols = [names.get(c.upper()) for c in re.findall(r"<th[^>]*>\s*([A-Za-z]+)\s*</th>", m.group(1))]
    if sorted(c for c in cols if c) != sorted(MARKETS):
        return {}                                   # layout changed -> trust nothing
    out = {}
    for title, cells in re.findall(r'<td class="day" title="([A-Za-z]+ \d{1,2}, \d{4})"\s*>\s*\d{1,2}\s*</td>'
                                   r'((?:\s*<td class="number">[^<]*</td>)+)', h):
        try:
            d = datetime.datetime.strptime(title, "%B %d, %Y").date()
        except ValueError:
            continue
        for mk, v in zip(cols, re.findall(r'<td class="number">\s*([^<]*?)\s*</td>', cells)):
            if mk and re.fullmatch(r"\d{1,2}", v):
                out[(mk, d)] = int(v)
    return out


def parse_snf(h):
    """satta-no-fast.com chart: title '... Chart of October 2026 ...', columns Dt DS GL DL SG FB GD."""
    names = {"DS": "Desawar", "FB": "Faridabad", "GD": "Ghaziabad", "GL": "Gali"}
    t = re.search(r'id="chartTitle"[^>]*>([^<]*)', h)
    m = re.search(r"Chart of ([A-Za-z]+) (\d{4})", t.group(1)) if t else None
    tb = re.search(r'<table class="chart-table">(.*?)</table>', h, re.S)
    if not m or not tb or m.group(1) not in MONTHS:
        return {}
    year, month = int(m.group(2)), MONTHS.index(m.group(1)) + 1
    cols = [names.get(c.upper()) for c in re.findall(r"<th[^>]*>\s*([A-Za-z]+)\s*</th>", tb.group(1))]
    if sorted(c for c in cols if c) != sorted(MARKETS):
        return {}
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.S):
        cells = re.findall(r"<td[^>]*>\s*([^<]*?)\s*</td>", row)
        if len(cells) != len(cols) or not cells[0].isdigit():
            continue
        try:
            d = datetime.date(year, month, int(cells[0]))
        except ValueError:
            continue
        for mk, v in zip(cols, cells):
            if mk and re.fullmatch(r"\d{1,2}", v):
                out[(mk, d)] = int(v)
    return out


SKF = "https://satta-king-fast.com/chart.php?ResultFor={mn}-{y}&month={m:02d}&year={y}"
SNF = "https://satta-no-fast.com/gali/satta-king-result-chart/gl/"


def fetch_web(today):
    """Both websites, this month (+ last month in the first 3 days). Returns (site A values, site B values)."""
    months = [(today.year, today.month)]
    if today.day <= 3:
        p = today.replace(day=1) - D1
        months.append((p.year, p.month))
    a, b = {}, {}
    for i, (y, m) in enumerate(months):
        a.update(parse_skf(fetch(SKF.format(mn=MONTHS[m - 1], y=y, m=m))))
        b.update(parse_snf(fetch(SNF) if i == 0 else fetch(SNF, {"month": f"{m:02d}", "year": str(y)})))
    if not a:
        a = parse_skf(fetch("https://satta-king-fast.com/"))       # homepage has the same month table
    return a, b


def combine(a, b, now):
    """Agreeing / single-source values -> web; disagreeing -> conflicts. Closed days and 'too early' values dropped."""
    web, conflicts = {}, {}
    for k in set(a) | set(b):
        mk, d = k
        if V.closed(mk, d) or now < at(d, RESULT_WINDOW[mk][0]):
            continue
        va, vb = a.get(k), b.get(k)
        if va is not None and vb is not None and va != vb:
            conflicts[k] = (va, vb)
        else:
            web[k] = va if va is not None else vb
    return web, conflicts


# ------------------------------------------------------------------ GitHub files
def gh(method, path, body=None, raw=False):
    url = f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(path)}"
    if method == "GET":
        url += f"?ref={BRANCH}"
    hdr = {"Authorization": "Bearer " + (ENV("GITHUB_TOKEN") or ""), "X-GitHub-Api-Version": "2022-11-28",
           "Accept": "application/vnd.github.v3.raw" if raw else "application/vnd.github+json", "User-Agent": "v7-auto"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    try:
        b = http(url, data, hdr, method, timeout=60)
        return 200, (b if raw else json.loads(b.decode("utf-8") or "{}"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def load_file(path, default):
    """-> (parsed JSON, sha).  DRY_RUN reads LOCAL_DIR instead."""
    if DRY:
        p = os.path.join(ENV("LOCAL_DIR") or ".", path)
        return (json.load(open(p, encoding="utf-8-sig")) if os.path.exists(p) else default), None
    st, j = gh("GET", path)
    if st == 404:
        return default, None
    if st != 200:
        raise RuntimeError(f"GitHub GET {path} -> HTTP {st}")
    content = base64.b64decode(j.get("content") or "") if j.get("encoding") == "base64" else None
    if not content:
        st2, content = gh("GET", path, raw=True)
        if st2 != 200:
            raise RuntimeError(f"GitHub raw GET {path} -> HTTP {st2}")
    return json.loads(content.decode("utf-8-sig")), j.get("sha")


def save_file(path, obj, sha, message):
    """-> True on success, False on sha conflict (someone else wrote first)."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if DRY:
        if ENV("DRY_WRITE") == "1":
            p = os.path.join(ENV("LOCAL_DIR") or ".", path)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            open(p, "w", encoding="utf-8").write(text)
        return True
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode(), "branch": BRANCH}
    if sha:
        body["sha"] = sha
    st, _ = gh("PUT", path, body)
    if st in (200, 201):
        return True
    if st in (409, 422):
        return False
    raise RuntimeError(f"GitHub PUT {path} -> HTTP {st}")


def to_int(v):
    try:
        n = int(str(v).strip())
        return n if 0 <= n <= 99 else None
    except (TypeError, ValueError):
        return None


def merge_results(results, web, today):
    """Fill ONLY missing results. Returns (added list, mismatch list (recent only))."""
    added, mismatch = [], []
    for (mk, d), v in sorted(web.items(), key=lambda kv: (kv[0][1], MARKETS.index(kv[0][0]))):
        if d > today:
            continue
        cur = to_int((results.get(mk) or {}).get(d.isoformat()))
        if cur is None:
            results.setdefault(mk, {})[d.isoformat()] = v
            added.append((mk, d, v))
        elif cur != v and (today - d).days <= 10:
            mismatch.append((mk, d, cur, v))
    return added, mismatch


# ------------------------------------------------------------------ model
class Engine:
    def __init__(self, results):
        self.data = collections.defaultdict(dict)
        for mk in MARKETS:
            for ds, v in (results.get(mk) or {}).items():
                try:
                    d = datetime.date.fromisoformat(ds)
                except (TypeError, ValueError):
                    continue
                n = to_int(v)
                if n is not None and not V.closed(mk, d):
                    self.data[mk][d] = n
        self.m = V.V7(self.data)
        self.logic = json.load(open(os.path.join(HERE, "v7_logic.json"), encoding="utf-8"))["markets"]

    def get(self, mk, d):
        return self.data[mk].get(d)

    def slate(self, T, td):
        return self.m.slate(T, td, self.logic[T])          # (8 numbers, units digit, tens digit)

    def missing_inputs(self, T, td):
        """Results the V7.2 rules read (last 3 game days) that are not closed but missing."""
        G = td - D1 if T == "Desawar" else td
        miss = []
        for lag in (0, 1, 2):
            for X in MARKETS:
                order = ["Faridabad", "Ghaziabad", "Gali", "Desawar"]
                if lag == 0 and order.index(X) >= order.index(T):
                    continue
                rd = G - datetime.timedelta(days=lag) + (D1 if X == "Desawar" else datetime.timedelta(0))
                if not V.closed(X, rd) and self.get(X, rd) is None:
                    miss.append((X, rd))
        return miss


# ------------------------------------------------------------------ messages
def esc(s):
    return html.escape(str(s), quote=False)


def forward_text(T, td, nums, units, cfg):
    stake = cfg["stake_per_jodi"]
    lines = [f"{T.upper()} {fmt_day(td)}", "  ".join(f"{n:02d}" for n in nums), f"har jodi ₹{stake} (8 jodi = ₹{inr(8 * stake)})"]
    if T == "Gali" and cfg.get("gali_haruf_stake", 0) > 0:
        lines.append(f"Bahar (aakhri ank) {units} – ₹{cfg['gali_haruf_stake']}")
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def verdict(eng, T, d):
    v = eng.get(T, d)
    nums, units, _ = eng.slate(T, d)
    return v, v in nums, v % 10 == units


def result_line(eng, mk, d, played, cfg):
    v = eng.get(mk, d)
    if v is None:
        return f"{mk} ({fmt_day(d)}) band tha." if V.closed(mk, d) else f"{mk} ({fmt_day(d)}) ka result abhi nahi mila."
    s = f"{mk} ({fmt_day(d)}) aaya: <b>{v:02d}</b>"
    if mk in played:
        _, hit, hh = verdict(eng, mk, d)
        s += "  ✅ PASS (V7.2 ke 8 mein tha)" if hit else "  ❌ (V7.2 ke 8 mein nahi tha)"
        if mk == "Gali" and cfg.get("gali_haruf_stake", 0) > 0:
            s += " · haruf " + ("✅" if hh else "❌")
    return s


def day_pnl(eng, T, rd, cfg):
    """(played?, hit?, rupees) for one market-day with the configured stake."""
    v = eng.get(T, rd)
    if v is None:
        return False, False, 0
    nums, units, _ = eng.slate(T, rd)
    s = cfg["stake_per_jodi"]
    r = (90 * s if v in nums else 0) - 8 * s
    if T == "Gali" and cfg.get("gali_haruf_stake", 0) > 0:
        h = cfg["gali_haruf_stake"]
        r += (9 * h if v % 10 == units else 0) - h
    return True, v in nums, r


def morning_report(eng, td, played, cfg):
    """After Desawar (result date td): yesterday's game day + month so far."""
    G = td - D1
    parts, tot = [], 0
    for T in played:
        rd = td if T == "Desawar" else G
        ok, hit, r = day_pnl(eng, T, rd, cfg)
        if ok:
            parts.append(f"{T} {'✅' if hit else '❌'}")
            tot += r
    lines = [f"🌅 {result_line(eng, 'Desawar', td, played, cfg)}"]
    if parts:
        lines.append(f"{fmt_day(G)} ka hisaab (₹{cfg['stake_per_jodi']}/jodi): " + " · ".join(parts) + f" → <b>{signed_inr(tot)}</b>")
    hits = n = 0
    mt = 0
    g = G.replace(day=1)
    while g <= G:
        for T in played:
            ok, hit, r = day_pnl(eng, T, g + D1 if T == "Desawar" else g, cfg)
            if ok:
                n += 1
                hits += hit
                mt += r
        g += D1
    if n:
        span = fmt_day(G) if G.day == 1 else f"1–{fmt_day(G)}"
        lines.append(f"Is mahine ({span}): {hits} hit / {n} khel → <b>{signed_inr(mt)}</b>")
    today = td
    shut = [mk for mk in ("Faridabad", "Ghaziabad", "Gali") if V.closed(mk, today)]
    if shut:
        lines.append("Aaj " + ", ".join(shut) + " band hain (mahine ka aakhri din).")
    if V.closed("Desawar", today + D1):
        lines.append("Kal subah Desawar band hai (1 tarikh), to aaj raat Desawar ke numbers nahi aayenge.")
    lines.append("<i>Ye V7.2 ke hisaab se hai (agar har din yahi 8 jodi khele).</i>")
    return "\n".join(lines)


# ------------------------------------------------------------------ one run
def plan_messages(now, eng, state, cfg, mismatch, conflicts, web_ok, mode):
    """Decide what to send. Returns list of (state_key or None, [messages])."""
    today = now.date()
    played = [T for T in ["Ghaziabad", "Gali", "Desawar", "Faridabad"] if T in cfg["markets"]]
    sent = state.setdefault("sent", {})
    out = []

    # A. data warnings (once each)
    warn = []
    for mk, d, cur, v in mismatch:
        k = f"mismatch:{mk}:{d}:{cur}:{v}"
        if k not in sent:
            warn.append((k, f"• {mk} {fmt_day(d)}: aapke tool mein <b>{cur:02d}</b>, website par <b>{v:02d}</b>"))
    for (mk, d), (va, vb) in sorted(conflicts.items(), key=lambda kv: kv[0][1]):
        k = f"conflict:{mk}:{d}"
        if (today - d).days <= 2 and k not in sent and eng.get(mk, d) is None:
            warn.append((k, f"• {mk} {fmt_day(d)}: dono websites alag result dikha rahi hain ({va:02d} / {vb:02d}), isliye maine nahi bhara"))
    if warn:
        msg = ("⚠️ <b>Result check</b>\n" + "\n".join(w for _, w in warn) +
               "\nSahi result tool mein daal do (main purana result khud nahi badalta). Tool mein daalte hi agle numbers usi se banenge.")
        out.append(([k for k, _ in warn], [msg]))

    # B. slates
    for T in played:
        for td in ([today, today + D1] if T == "Desawar" else [today]):
            if V.closed(T, td) or eng.get(T, td) is not None:
                continue
            key = f"slate:{T}:{td}"
            if key in sent and mode != "test":
                continue
            pm, off = PREREQ[T]
            pd = td + datetime.timedelta(days=off)
            have_pre = eng.get(pm, pd) is not None or V.closed(pm, pd)
            cutoff = at(td, CUTOFF[T])
            if mode == "test":
                if not have_pre:                              # not final yet -> no numbers, so nobody plays them by mistake
                    out.append((None, [f"⏳ {T} ({fmt_day(td)}): {pm} ka result aate hi numbers aayenge ({pm} result {DRAW_TEXT[pm]})."]))
                    break
                nums, units, _ = eng.slate(T, td)
                pv = eng.get(pm, pd)
                info = f"🎯 <b>{T.upper()} ({fmt_day(td)})</b> – final numbers ({pm} {'band tha' if pv is None else f'aaya {pv:02d}'})"
                if T == "Gali":
                    info += f"\nHaruf: BAHAR {units} (aakhri ank)"
                out.append((None, [info, forward_text(T, td, nums, units, cfg)]))
                break
            if not have_pre:
                ak = f"alert:{pm}:{pd}"
                if now > at(pd, RESULT_WINDOW[pm][1]) and now < cutoff and ak not in sent:
                    why = "" if web_ok else " (result websites GitHub se nahi khul rahi)"
                    out.append(([ak], [f"⚠️ {pm} ({fmt_day(pd)}) ka result abhi tak nahi mila{why}.\n"
                                       f"{T} ke numbers result milte hi bhej dunga. Jaldi ho to tool mein result daal do ya tool khud dekh lo."]))
                continue
            if now > cutoff:
                continue
            nums, units, _ = eng.slate(T, td)
            when = "subah" if T == "Desawar" else ""
            info = [f"🎯 <b>{T.upper()} ({fmt_day(td)}{' ' + when if when else ''})</b> – V7.2",
                    result_line(eng, pm, pd, played, cfg)]
            keys = [key]
            if pm in played and eng.get(pm, pd) is not None:
                keys.append(f"res:{pm}:{pd}")
            if T == "Gali":
                hs = cfg.get("gali_haruf_stake", 0)
                info.append(f"Haruf: <b>BAHAR {units}</b> (aakhri ank)" + ("" if hs > 0 else " – chaho to ₹200–300"))
            miss = [x for x in eng.missing_inputs(T, td) if x != (pm, pd)]
            if miss:
                info.append("⚠️ Ye results data mein nahi hain, numbers tool se thode alag ho sakte hain: " +
                            ", ".join(f"{x} {fmt_day(d)}" for x, d in miss))
            info.append(f"Neeche wala message khaiwale ko bhejo (tap karke copy). {T} result {DRAW_TEXT[T]}.")
            out.append((keys, ["\n".join(info), forward_text(T, td, nums, units, cfg)]))

    if mode == "test":
        return out

    # C. PASS/FAIL for played results not yet reported (Desawar -> morning report)
    done = {k for keys, _ in out if keys for k in keys}
    for T in played:
        for d in (today - D1, today):
            k = f"res:{T}:{d}"
            if eng.get(T, d) is None or k in sent or k in done:
                continue
            if not (at(d, RESULT_WINDOW[T][0]) <= now <= at(d, RESULT_WINDOW[T][1]) + REPORT_FOR):
                continue
            if T == "Desawar" and cfg.get("send_morning_report", True):
                out.append(([k], [morning_report(eng, d, played, cfg)]))
            else:
                out.append(([k], ["📢 " + result_line(eng, T, d, played, cfg)]))
    return out


def tg_send(text):
    tok, chat = (ENV("TELEGRAM_BOT_TOKEN") or "").strip(), (ENV("TELEGRAM_CHAT_ID") or "").strip()
    if DRY:
        log("----- TELEGRAM -----\n" + text)
        return True
    if not tok or not chat:
        return None                                   # not set up yet
    body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    for _ in range(3):
        try:
            j = json.loads(http(f"https://api.telegram.org/bot{tok}/sendMessage", body, {"Content-Type": "application/json"}).decode())
            if j.get("ok"):
                return True
        except urllib.error.HTTPError as e:
            log(f"  telegram HTTP {e.code}")          # never print the token / URL
            if e.code in (400, 401, 403, 404):
                return False
        except Exception as e:  # noqa: BLE001
            log(f"  telegram error {type(e).__name__}")
        time.sleep(3)
    return False


def now_ist():
    o = ENV("NOW_IST")
    if o:
        return datetime.datetime.fromisoformat(o).replace(tzinfo=IST)
    return datetime.datetime.now(IST)


def prune(sent, today):
    for k in list(sent):
        m = re.search(r"(\d{4}-\d\d-\d\d)", k)
        if m and (today - datetime.date.fromisoformat(m.group(1))).days > 45:
            del sent[k]


def main(mode="normal"):
    now = now_ist()
    today = now.date()
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    log(f"V7.2 auto | mode={mode} | {now:%Y-%m-%d %H:%M} IST | markets={','.join(cfg['markets'])}")

    a, b = fetch_web(today)
    web, conflicts = combine(a, b, now)
    web_ok = bool(a or b)
    log(f"  websites: A={len(a)} values, B={len(b)} values, usable={len(web)}, conflicts={len(conflicts)}")

    # 1. results -> spi_results.json (fill missing only; retry if the tool wrote at the same time)
    for attempt in range(4):
        results, sha = load_file(RESULTS_PATH, {})
        added, mismatch = merge_results(results, web, today)
        if not added:
            break
        what = ", ".join(sorted({f"{mk} {d}" for mk, d, _ in added}))
        if save_file(RESULTS_PATH, results, sha, f"V7 auto: results {what}"):
            log(f"  results added: {len(added)} ({what})")
            break
        log("  results file changed meanwhile, retrying")
        time.sleep(2 + attempt)
    else:
        raise RuntimeError("could not save spi_results.json")

    # 2. decide + send messages
    eng = Engine(results)
    state, ssha = load_file(STATE_PATH, {"sent": {}})
    sent = state.setdefault("sent", {})
    init_now = "init" not in state and mode != "test"
    if init_now:                                         # first run ever: don't flood old PASS/FAIL reports
        state["init"] = now.isoformat(timespec="minutes")
        for T in MARKETS:
            for d in (today - D1, today):
                if eng.get(T, d) is not None:
                    sent[f"res:{T}:{d}"] = "init"
    plan = plan_messages(now, eng, state, cfg, mismatch, conflicts, web_ok, mode)
    if mode == "test":
        head = ("✅ <b>V7.2 Auto chal raha hai!</b>\nTelegram connect ho gaya. Ab har din numbers apne aap aayenge:\n"
                "• Faridabad ke baad → Ghaziabad\n• Ghaziabad ke baad → Gali (+ BAHAR haruf)\n• Gali ke baad → Desawar\n"
                "• Subah → kal ka hisaab\nNeeche abhi ki sthiti hai.")
        waiting = [m[0] for k, m in plan if k is None and len(m) == 1 and m[0].startswith("⏳")]
        plan = [p for p in plan if not (p[0] is None and len(p[1]) == 1 and p[1][0].startswith("⏳"))]
        plan.insert(0, (None, [head + ("\n\n" + "\n".join(waiting) if waiting else "")]))
    changed, failed, not_setup = False, 0, False
    for keys, msgs in plan:
        ok = True
        for t in msgs:
            r = tg_send(t)
            if r is None:
                not_setup = True
                ok = False
                break
            if not r:
                ok = False
                failed += 1
                break
        if ok and keys:
            for k in keys:
                sent[k] = now.isoformat(timespec="minutes")
            changed = True
    log(f"  messages: {len(plan)} planned, {'Telegram not set up yet' if not_setup else f'{failed} failed'}")

    # 3. state
    prune(sent, today)
    if changed or init_now:
        for attempt in range(4):
            if save_file(STATE_PATH, state, ssha, "V7 auto: sent state"):
                break
            fresh, ssha = load_file(STATE_PATH, {"sent": {}})
            fresh.setdefault("sent", {}).update(sent)
            fresh.setdefault("init", state.get("init"))
            state, sent = fresh, fresh["sent"]
        else:
            log("  could not save sent_state.json (will retry next run)")
    if failed or (mode == "test" and (not_setup or not plan)):
        log("  Telegram problem: check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets and send /start to your bot")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("normal", "test") else "normal")
