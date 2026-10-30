#!/usr/bin/env python3
"""
V7.3 AUTO - results apne aap + agle market ke numbers (plan ke hisaab se) Telegram par.
Chalta hai GitHub Actions par (.github/workflows/v7_auto.yml). Koi extra package nahi chahiye.

Har run mein:
  1. Is mahine ka chart 2 websites se laata hai (satta-king-fast.com + satta-no-fast.com).
  2. spi_results.json mein sirf MISSING results bharta hai. Purana result kabhi nahi badalta.
     Dono websites alag result dikhayein to kuch nahi bharta, sirf warning bhejta hai.
  3. Jis market se pehle wala result aa gaya ho, uske V7.3 numbers (v7_plan.json: Gali rank 2-8, Desawar 8, Ghaziabad 8,
     + haruf) Telegram par bhejta hai. Desawar ke numbers Ghaziabad ke baad hi final hain (V7.3). Har market/din ek baar.
  4. Subah Desawar ke baad kal ka hisaab (PASS/FAIL, Rs, 5% commission ke saath) bhejta hai.
  5. 'bhaari 12 34 56 78 90' jaise reply padh kar bhaari-number prayog ka data rakhta hai; 1 Jan ko model dobara train karta hai.

Usage : python3 automation/v7_auto.py [normal|test]
Env   : GITHUB_TOKEN, GITHUB_REPOSITORY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Local : DRY_RUN=1 LOCAL_DIR=<folder with spi_results.json + automation/sent_state.json> [NOW_IST=2026-10-25T18:30]
        Isme kuch bhi bheja ya GitHub par likha nahi jaata; messages sirf print hote hain.
"""
import base64, collections, datetime, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v7_reference as V  # noqa: E402  (V7.3 model, same as the tool)

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
PREREQ = {"Desawar": ("Ghaziabad", -1), "Faridabad": ("Desawar", 0), "Ghaziabad": ("Faridabad", 0), "Gali": ("Ghaziabad", 0)}   # V7.3: Desawar after Ghaziabad
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


# ------------------------------------------------------------------ plan (v7_plan.json: tool + bot dono yahi padhte hain)
DEFAULT_PLAN = {"version": "7.3", "payout": 90, "commission_pct": 5, "heavy_experiment": True,
                "markets": {"Gali": {"play": True, "skip_ranks": [1], "stake": 125, "haruf": {"type": "bahar", "stake": 200}},
                            "Desawar": {"play": True, "skip_ranks": [], "stake": 75, "haruf": {"type": "andar", "stake": 150}},
                            "Ghaziabad": {"play": True, "skip_ranks": [], "stake": 40, "haruf": None},
                            "Faridabad": {"play": False, "skip_ranks": [], "stake": 0, "haruf": None}}}


def load_plan():
    for p in ([os.path.join(ENV("LOCAL_DIR") or ".", "v7_plan.json")] if DRY else [os.path.join(HERE, "..", "v7_plan.json")]):
        try:
            j = json.load(open(p, encoding="utf-8-sig"))
            if j.get("markets"):
                return j
        except (OSError, ValueError):
            pass
    try:                                                   # fallback: GitHub raw
        j = json.loads(http(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/v7_plan.json?t={int(time.time())}", headers=UA).decode("utf-8-sig"))
        if j.get("markets"):
            return j
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_PLAN


def mplan(plan, T):
    p = (plan.get("markets") or {}).get(T)
    return p if p and p.get("play", True) and p.get("stake", 0) > 0 else None


def plan_nums(p, slate8):
    skip = set(p.get("skip_ranks") or [])
    return [n for i, n in enumerate(slate8) if (i + 1) not in skip]


def haruf_of(p, units, tens):
    """-> (label, digit, stake) or None"""
    h = p.get("haruf") if p else None
    if not h or not h.get("stake"):
        return None
    return ("ANDAR (pehla ank)", tens, h["stake"]) if h.get("type") == "andar" else ("BAHAR (aakhri ank)", units, h["stake"])


# ------------------------------------------------------------------ model
class Engine:
    def __init__(self, results, logic=None):
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
        L = logic or json.load(open(os.path.join(HERE, "v7_logic.json"), encoding="utf-8"))
        self.logic = L["markets"]
        self.version = L.get("version", "?")
        ex = L.get("exclude_same_day") or {}
        V.EXCLUDE_SAME_DAY.clear()
        V.EXCLUDE_SAME_DAY.update({k: set(v) for k, v in ex.items()})

    def get(self, mk, d):
        return self.data[mk].get(d)

    def slate(self, T, td):
        return self.m.slate(T, td, self.logic[T])          # (8 numbers, units digit, tens digit)

    def needs(self, T, td):
        """Same-day inputs a market's slate depends on: [(market, result date)]."""
        ex = V.EXCLUDE_SAME_DAY.get(T, set())
        if T == "Desawar":
            return [(X, td - D1) for X in ("Faridabad", "Ghaziabad", "Gali") if X not in ex]
        if T == "Faridabad":
            return [("Desawar", td)]
        if T == "Ghaziabad":
            return [("Faridabad", td)]
        if T == "Gali":
            return [("Faridabad", td), ("Ghaziabad", td)]
        return []

    def missing_inputs(self, T, td):
        """Results the rules read (last 3 game days) that are not closed but missing."""
        G = td - D1 if T == "Desawar" else td
        order = ["Faridabad", "Ghaziabad", "Gali", "Desawar"]
        ex = V.EXCLUDE_SAME_DAY.get(T, set())
        miss = []
        for lag in (0, 1, 2):
            for X in MARKETS:
                if lag == 0 and (order.index(X) >= order.index(T) or X in ex):
                    continue
                rd = G - datetime.timedelta(days=lag) + (D1 if X == "Desawar" else datetime.timedelta(0))
                if not V.closed(X, rd) and self.get(X, rd) is None:
                    miss.append((X, rd))
        return miss


# ------------------------------------------------------------------ messages
def esc(s):
    return html.escape(str(s), quote=False)


def forward_text(T, td, p, slate8, units, tens):
    nums = plan_nums(p, slate8)
    st = p["stake"]
    lines = [f"{T.upper()} {fmt_day(td)}" + (" (subah)" if T == "Desawar" else ""), "  ".join(f"{n:02d}" for n in nums),
             f"har jodi ₹{st} ({len(nums)} jodi = ₹{inr(len(nums) * st)})"]
    h = haruf_of(p, units, tens)
    if h:
        lines.append(f"{h[0].split(' ')[0].title()} ({h[0].split('(')[1]} {h[1]} – ₹{h[2]}")
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def day_pnl(eng, plan, T, rd):
    """(played?, jodi hit?, haruf hit or None, rupees incl. commission) for one market-day under the plan."""
    p = mplan(plan, T)
    v = eng.get(T, rd)
    if not p or v is None:
        return False, False, None, 0
    slate8, units, tens = eng.slate(T, rd)
    nums = plan_nums(p, slate8)
    comm = (plan.get("commission_pct") or 0) / 100
    pay = plan.get("payout") or 90
    stake = len(nums) * p["stake"]
    r = (pay * p["stake"] if v in nums else 0) - stake + comm * stake
    hh = None
    h = haruf_of(p, units, tens)
    if h:
        dig = v // 10 if h[0].startswith("ANDAR") else v % 10
        hh = dig == h[1]
        r += (9 * h[2] if hh else 0) - h[2] + comm * h[2]
    return True, v in nums, hh, r


def result_line(eng, plan, mk, d):
    v = eng.get(mk, d)
    if v is None:
        return f"{mk} ({fmt_day(d)}) band tha." if V.closed(mk, d) else f"{mk} ({fmt_day(d)}) ka result abhi nahi mila."
    s = f"{mk} ({fmt_day(d)}) aaya: <b>{v:02d}</b>"
    played, hit, hh, r = day_pnl(eng, plan, mk, d)
    if played:
        s += "  ✅ PASS" if hit else "  ❌"
        if hh is not None:
            s += " · haruf " + ("✅" if hh else "❌")
        s += f" ({signed_inr(r)})"
    return s


def heavy_stats(eng, state):
    """Heavy-number experiment: how often did the khaiwala's 'bhaari' numbers come?"""
    n = h = 0; e = 0.0
    for k, nums in (state.get("heavy") or {}).items():
        ds, mk = k.split(":")
        v = eng.get(mk, datetime.date.fromisoformat(ds))
        if v is None or not nums:
            continue
        n += 1; e += len(set(nums)) / 100; h += v in nums
    return n, h, e


def morning_report(eng, plan, td, played, state):
    """After Desawar (result date td): yesterday's game day + month so far (plan + commission)."""
    G = td - D1
    parts, tot = [], 0
    for T in played:
        rd = td if T == "Desawar" else G
        ok, hit, hh, r = day_pnl(eng, plan, T, rd)
        if ok:
            parts.append(f"{T} {'✅' if hit else '❌'}" + ("" if hh is None else ("✅" if hh else "❌")))
            tot += r
    lines = [f"🌅 {result_line(eng, plan, 'Desawar', td)}"]
    if parts:
        lines.append(f"{fmt_day(G)} ka hisaab: " + " · ".join(parts) + f" → <b>{signed_inr(tot)}</b>")
    hits = n = 0; mt = 0
    g = G.replace(day=1)
    while g <= G:
        for T in played:
            ok, hit, hh, r = day_pnl(eng, plan, T, g + D1 if T == "Desawar" else g)
            if ok:
                n += 1; hits += hit; mt += r
        g += D1
    if n:
        span = fmt_day(G) if G.day == 1 else f"1–{fmt_day(G)}"
        lines.append(f"Is mahine ({span}): {hits} hit / {n} khel → <b>{signed_inr(mt)}</b> ({plan.get('commission_pct', 0)}% commission ke saath)")
    hn, hh_, he = heavy_stats(eng, state)
    if hn:
        lines.append(f"🧪 Bhaari-number prayog: {hn} din, bhaari numbers {hh_} baar aaye (andaaze se {he:.1f})")
    shut = [mk for mk in ("Faridabad", "Ghaziabad", "Gali") if V.closed(mk, td)]
    if shut:
        lines.append("Aaj " + ", ".join(shut) + " band hain (mahine ka aakhri din).")
    if V.closed("Desawar", td + D1):
        lines.append("Kal subah Desawar band hai (1 tarikh), to aaj raat Desawar ke numbers nahi aayenge.")
    lines.append(f"<i>V{eng.version} plan ke hisaab se.</i>")
    return "\n".join(lines)


# ------------------------------------------------------------------ one run
def plan_messages(now, eng, plan, state, mismatch, conflicts, web_ok, mode):
    """Decide what to send. Returns list of (state_keys or None, [messages])."""
    today = now.date()
    played = [T for T in ["Ghaziabad", "Gali", "Desawar", "Faridabad"] if mplan(plan, T)]
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
        p = mplan(plan, T)
        for td in ([today, today + D1] if T == "Desawar" else [today]):
            if V.closed(T, td) or eng.get(T, td) is not None:
                continue
            key = f"slate:{T}:{td}"
            if key in sent and mode != "test":
                continue
            pm, off = PREREQ[T]
            pd = td + datetime.timedelta(days=off)
            have_pre = all(eng.get(X, xd) is not None or V.closed(X, xd) for X, xd in eng.needs(T, td))
            cutoff = at(td, CUTOFF[T])
            if mode == "test":
                if not have_pre:
                    out.append((None, [f"⏳ {T} ({fmt_day(td)}): {pm} ka result aate hi numbers aayenge ({pm} result {DRAW_TEXT[pm]})."]))
                    break
                slate8, units, tens = eng.slate(T, td)
                pv = eng.get(pm, pd)
                info = f"🎯 <b>{T.upper()} ({fmt_day(td)})</b> – final numbers ({pm} {'band tha' if pv is None else f'aaya {pv:02d}'})"
                out.append((None, [info, forward_text(T, td, p, slate8, units, tens)]))
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
            slate8, units, tens = eng.slate(T, td)
            nums = plan_nums(p, slate8)
            info = [f"🎯 <b>{T.upper()} ({fmt_day(td)}{' subah' if T == 'Desawar' else ''})</b> – V{eng.version}",
                    result_line(eng, plan, pm, pd)]
            keys = [key]
            if pm in played and eng.get(pm, pd) is not None:
                keys.append(f"res:{pm}:{pd}")
            skipped = [n for n in slate8 if n not in nums]
            if skipped:
                info.append("✕ MAIN " + " ".join(f"{n:02d}" for n in skipped) + " nahi khelna (rank 1 kamzor hai), baaki " + str(len(nums)) + " khelo")
            h = haruf_of(p, units, tens)
            if h:
                info.append(f"Haruf: <b>{h[0]} {h[1]}</b> ₹{h[2]}")
            miss = [x for x in eng.missing_inputs(T, td) if x != (pm, pd)]
            if miss:
                info.append("⚠️ Ye results data mein nahi hain, numbers tool se thode alag ho sakte hain: " +
                            ", ".join(f"{x} {fmt_day(d)}" for x, d in miss))
            info.append(f"Neeche wala message khaiwale ko bhejo (tap karke copy). {T} result {DRAW_TEXT[T]}.")
            msgs = ["\n".join(info), forward_text(T, td, p, slate8, units, tens)]
            if T == "Gali" and plan.get("heavy_experiment", True):
                msgs.append("🧪 Prayog: khaiwale se poochho aaj Gali mein sabse BHAARI 5 number kaunse hain (jahan sabse zyada paisa laga hai), "
                            "aur mujhe reply karo:\n<code>bhaari 12 34 56 78 90</code>\nMain jaanchunga ki operator unhe bachata hai ya nahi.")
            out.append((keys, msgs))

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
            if T == "Desawar":
                out.append(([k], [morning_report(eng, plan, d, played, state)]))
            else:
                out.append(([k], ["📢 " + result_line(eng, plan, T, d)]))
    return out


# ------------------------------------------------------------------ telegram
def tg_api(method, body):
    tok = (ENV("TELEGRAM_BOT_TOKEN") or "").strip()
    if not tok:
        return None
    try:
        j = json.loads(http(f"https://api.telegram.org/bot{tok}/{method}", json.dumps(body).encode(), {"Content-Type": "application/json"}).decode())
        return j if j.get("ok") else False
    except urllib.error.HTTPError as e:
        log(f"  telegram {method} HTTP {e.code}")          # never print the token / URL
        return False
    except Exception as e:  # noqa: BLE001
        log(f"  telegram {method} error {type(e).__name__}")
        return False


def tg_send(text):
    tok, chat = (ENV("TELEGRAM_BOT_TOKEN") or "").strip(), (ENV("TELEGRAM_CHAT_ID") or "").strip()
    if DRY:
        log("----- TELEGRAM -----\n" + text)
        return True
    if not tok or not chat:
        return None                                   # not set up yet
    for _ in range(3):
        r = tg_api("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        if r:
            return True
        time.sleep(3)
    return False


HEAVY_RE = re.compile(r"^\s*(?:bhaari|bhari|heavy|भारी)\s*(gali|desawar|ghaziabad|faridabad)?\s*[:\-]?\s*([\d][\d\s,./]*)$", re.I)


def read_heavy_replies(state, now):
    """Poll Telegram for 'bhaari 12 34 56 78 90' replies from the user; store under result date + market."""
    chat = (ENV("TELEGRAM_CHAT_ID") or "").strip()
    if DRY or not chat:
        return []
    body = {"timeout": 0, "allowed_updates": ["message"]}
    if state.get("tg_offset"):
        body["offset"] = state["tg_offset"]
    r = tg_api("getUpdates", body)
    if not r:
        return []
    acks = []
    for u in r.get("result", []):
        state["tg_offset"] = max(state.get("tg_offset") or 0, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat:
            continue
        m = HEAVY_RE.match(msg.get("text") or "")
        if not m:
            continue
        nums = sorted({int(x) for x in re.findall(r"\d{1,2}", m.group(2)) if 0 <= int(x) <= 99})
        if not nums:
            continue
        mk = (m.group(1) or "Gali").capitalize()
        t = datetime.datetime.fromtimestamp(msg.get("date", now.timestamp()), IST)
        rd = t.date()
        if mk == "Desawar" and t.hour >= 12:
            rd += D1                                   # evening reply is about next morning's Desawar
        state.setdefault("heavy", {})[f"{rd}:{mk}"] = nums
        acks.append(f"✅ Note kar liya: {mk} {fmt_day(rd)} bhaari = " + " ".join(f"{n:02d}" for n in nums))
    return acks


# ------------------------------------------------------------------ yearly retrain (1 Jan)
def retrain(results, year, state):
    """Train V7 on 2013..(year-1) from spi_results.json, write automation/v7_logic.json + v7_logic.json (root)."""
    eng = Engine(results)
    A, B = datetime.date(2013, 1, 1), datetime.date(year - 1, 12, 31)
    M = A + (B - A) / 2
    new = {"version": eng.version, "trained_on": f"{A}..{B} (spi_results.json, auto {year}-01-01)",
           "engine_note": "auto-retrained; same V7.3 method", "exclude_same_day": {k: sorted(v) for k, v in V.EXCLUDE_SAME_DAY.items()},
           "markets": {T: eng.m.learn(T, A, M, B) for T in V.TARGETS}}
    ok = all(20 <= len(new["markets"][T]["rules"]) <= 400 and new["markets"][T]["adjust"] for T in V.TARGETS)
    # last year: old vs new logic (new is in-sample for that year, so only a sanity check)
    old_h = new_h = n = 0
    for T in V.TARGETS:
        d = datetime.date(year - 1, 1, 1)
        while d <= B:
            a = eng.get(T, d)
            if a is not None and not V.closed(T, d):
                n += 1
                old_h += a in eng.m.slate(T, d, eng.logic[T])[0]
                new_h += a in eng.m.slate(T, d, new["markets"][T])[0]
            d += D1
    summary = (f"🧠 <b>Saal {year}: V7 dobara train</b>\nData 2013–{year - 1}. Rules: " +
               ", ".join(f"{T[:3]} {len(new['markets'][T]['rules'])}" for T in V.TARGETS) +
               f"\n{year - 1} par: purana logic {old_h}/{n} hit, naya {new_h}/{n} (naya usi saal par seekha hai, isliye thoda zyada dikhega).")
    if not ok:
        return summary + "\n❌ Sanity check fail – purana logic hi rahega."
    text = json.dumps(new)
    for path in ("automation/v7_logic.json", "v7_logic.json"):
        for attempt in range(3):
            _, sha = load_file(path, {})
            if save_file(path, new, sha, f"V7 auto: yearly retrain {year}"):
                break
            time.sleep(2)
    return summary + "\n✅ Naya logic GitHub par likh diya; tool aur bot ab yahi use karenge."


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
    plan = load_plan()
    log(f"V7 auto | mode={mode} | {now:%Y-%m-%d %H:%M} IST | plan v{plan.get('version')} markets=" +
        ",".join(T for T in MARKETS if mplan(plan, T)))

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

    # 2. state + yearly retrain + heavy replies
    state, ssha = load_file(STATE_PATH, {"sent": {}})
    sent = state.setdefault("sent", {})
    changed = False
    if mode == "normal" and today.month == 1 and today.day == 1 and f"retrain:{today.year}" not in sent:
        try:
            msg = retrain(results, today.year, state)
        except Exception as e:  # noqa: BLE001
            msg = f"🧠 Saal {today.year} retrain fail: {type(e).__name__}. Purana logic chalta rahega."
        if tg_send(msg):
            sent[f"retrain:{today.year}"] = now.isoformat(timespec="minutes"); changed = True
    eng = Engine(results)
    init_now = "init" not in state and mode != "test"
    if init_now:                                         # first run ever: don't flood old PASS/FAIL reports
        state["init"] = now.isoformat(timespec="minutes")
        for T in MARKETS:
            for d in (today - D1, today):
                if eng.get(T, d) is not None:
                    sent[f"res:{T}:{d}"] = "init"
    acks = read_heavy_replies(state, now)
    if acks:
        changed = True
        for t in acks:
            tg_send(t)
    plan_ = plan_messages(now, eng, plan, state, mismatch, conflicts, web_ok, mode)
    if mode == "test":
        head = (f"✅ <b>V{eng.version} Auto chal raha hai!</b>\nTelegram connect ho gaya. Ab har din numbers apne aap aayenge:\n"
                "• Faridabad ke baad → Ghaziabad\n• Ghaziabad ke baad → Gali (+ BAHAR haruf) aur Desawar (+ ANDAR haruf)\n"
                "• Subah → kal ka hisaab\nPlan: Gali 7 jodi × ₹125 (MAIN chhod kar), Desawar 8 × ₹75, Ghaziabad 8 × ₹40.\nNeeche abhi ki sthiti hai.")
        waiting = [m[0] for k, m in plan_ if k is None and len(m) == 1 and m[0].startswith("⏳")]
        plan_ = [p for p in plan_ if not (p[0] is None and len(p[1]) == 1 and p[1][0].startswith("⏳"))]
        plan_.insert(0, (None, [head + ("\n\n" + "\n".join(waiting) if waiting else "")]))
    failed, not_setup = 0, False
    for keys, msgs in plan_:
        ok = True
        for t in msgs:
            r = tg_send(t)
            if r is None:
                not_setup = True; ok = False
                break
            if not r:
                ok = False; failed += 1
                break
        if ok and keys:
            for k in keys:
                sent[k] = now.isoformat(timespec="minutes")
            changed = True
    log(f"  messages: {len(plan_)} planned, {'Telegram not set up yet' if not_setup else f'{failed} failed'}")

    # 3. state
    prune(sent, today)
    if changed or init_now:
        for attempt in range(4):
            if save_file(STATE_PATH, state, ssha, "V7 auto: sent state"):
                break
            fresh, ssha = load_file(STATE_PATH, {"sent": {}})
            fresh.setdefault("sent", {}).update(sent)
            for k in ("init", "tg_offset", "heavy"):
                if k in state and k not in fresh:
                    fresh[k] = state[k]
            if "heavy" in state:
                fresh.setdefault("heavy", {}).update(state["heavy"])
            state, sent = fresh, fresh["sent"]
        else:
            log("  could not save sent_state.json (will retry next run)")
    if failed or (mode == "test" and (not_setup or not plan_)):
        log("  Telegram problem: check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets and send /start to your bot")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("normal", "test") else "normal")
