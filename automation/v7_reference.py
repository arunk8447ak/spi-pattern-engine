#!/usr/bin/env python3
"""
V7.3 MODEL - standalone reference implementation (pure Python 3, no extra packages).

V7.3 = V7.2 + Desawar no longer uses the SAME NIGHT's Gali result (Gali lag-0 rules and Gali in the "same-day earlier
       markets" habit set are removed for Desawar). Walk-forward 2017-2026 on cleaned data: more hits (+~20 / 10 years),
       and the Desawar slate is final right after Ghaziabad (~10 pm) instead of after Gali (~11:30 pm).
       Also: load_json() trains straight from the tool's spi_results.json (2013+), so no spreadsheet is needed.

V7.2 = V7.1 + one fix: on the FIRST draw after a market holiday (Faridabad/Ghaziabad/Gali on the 1st, Desawar on the 2nd)
       yesterday is a closed day, so V7.1 lost most of its inputs (2015-2026: 39 hits instead of ~57).  V7.2 then uses the
       last OPEN day's result in place of a closed day (scoring only; the learned rules/adjustments are unchanged) -> 52 hits.
       Applying it on other days does not help, so it is used only on that first draw.

V7.1 = the V7 vote rules + per-market LEARNED operator-habit adjustments (replacing V7's fixed penalties)
       + the andar/bahar digit taken from the vote sums.

What it does
  train       : learn rules + adjustments from the master spreadsheet and write them to v7_logic.json
  predict     : print the 8-number slates (+ andar digit) for a date (Desawar / Faridabad / Ghaziabad / Gali)
  walkforward : strict out-of-sample test - for each year Y everything is re-learned on data BEFORE Y only
  check       : verify that this script reproduces v7_logic.json (the logic embedded in "SPI V7 Engine.html")

Usage
  python3 v7_reference.py train       --json spi_results.json          (or --xlsx Master_All_6_Markets.xlsx)
  python3 v7_reference.py predict     --xlsx Master_All_6_Markets.xlsx --extra recent_results.csv --date 2026-10-18
  python3 v7_reference.py walkforward --xlsx Master_All_6_Markets.xlsx --extra recent_results.csv
  python3 v7_reference.py check       --xlsx Master_All_6_Markets.xlsx --logic v7_logic.json

recent_results.csv (optional): lines "YYYY-MM-DD,Market,Result" for results newer than the spreadsheet.

Model summary (see the handover prompt for the full explanation)
  * Game-day order: Delhi 3:30pm, Shree Ganesh 4:30pm, Faridabad 6pm, Ghaziabad 8:30pm, Gali 11:30pm,
    Desawar 5:30am NEXT morning. Desawar's result dated D closes game day D-1.
  * Closures: Desawar closed on the 1st; Faridabad/Ghaziabad/Gali closed on the last day of each month.
    Rows dated on a closed day are dropped at load time (skip closed days everywhere - also in training).
  * Training pairs are indexed by the TARGET game day: for the window [A, B] only target results inside [A, B] are used
    (input = source market on day G - lag). Nothing after B (or after the midpoint M for half 1) ever enters training.
  * Rule = (source market X, lag 0/1/2 game days, transform). lag 0 only from markets earlier in the day.
  * A rule is kept if its hit rate beats 1% in BOTH halves of the training period and z > 1 (positive),
    or is below 1% in both halves and z < -1 (negative). Weight = hit rate - 1%.
  * ADJUSTMENTS (new in 7.1): 9 "habit sets" built from recent results (own yesterday, its family, yesterday +1..+5,
    own 2-3 days ago, own 4-14 days ago, Desawar morning, its family, other markets yesterday, same-day earlier
    markets). For each set the training data gives hits h vs expected e (= sum of set size / 100). If |z| >= 2 the set
    gets adjustment (h/e - 1) * 0.01 per number (negative = operator avoids, positive = operator repeats).
  * Daily score = sum of rule weights pointing at each number + adjustments of every habit set the number is in.
    Top 8 by score (ties -> smaller number) = the slate. Andar digit = units digit with the largest score sum,
    bahar digit = tens digit with the largest score sum. No V3 bonus, no fixed penalties.
"""
import argparse, collections, datetime, json, math, re, sys, zipfile

VERSION = "7.3"
MARKETS4 = ["Faridabad", "Ghaziabad", "Gali", "Desawar"]          # order matters (lag-0 rule + rule order + habit sets)
TARGETS = ["Desawar", "Faridabad", "Ghaziabad", "Gali"]
EXCLUDE_SAME_DAY = {"Desawar": {"Gali"}}                             # V7.3: target -> same-game-day sources NOT used (lag 0 + habit set)
PROD_TRAIN = (datetime.date(2013, 1, 1), datetime.date(2019, 6, 30), datetime.date(2025, 12, 31))   # A, M, B
ADJ_Z = 2.0                                                          # habit set must be |z| >= 2 on training data
D1 = datetime.timedelta(days=1)

# ------------------------------------------------------------------ data
def load_xlsx(path):
    """Read Sheet1 (Date, Result, Market) without openpyxl. Later duplicate rows overwrite earlier ones."""
    z = zipfile.ZipFile(path)
    ss = []
    if 'xl/sharedStrings.xml' in z.namelist():
        s = z.read('xl/sharedStrings.xml').decode('utf-8')
        ss = [re.sub(r'<[^>]+>', '', m) for m in re.findall(r'<si>(.*?)</si>', s, re.S)]
    x = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
    data = collections.defaultdict(dict)
    for r in re.findall(r'<row [^>]*>(.*?)</row>', x, re.S)[1:]:
        cell = {}
        for ref, t, v in re.findall(r'<c r="([A-Z]+)\d+"(?: [^>]*?t="(\w+)")?[^>]*?>(?:<f>.*?</f>)?(?:<v>(.*?)</v>)?', r, re.S):
            cell[ref] = ss[int(v)] if t == 's' and v else v
        if not cell.get('A') or not cell.get('C') or cell.get('B') in (None, ''):
            continue
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(cell['A'])))
        data[cell['C']][d] = int(float(cell['B'])) % 100
    drop_closed(data)
    return data

def load_json(path):
    """Read the tool's spi_results.json ({market: {"YYYY-MM-DD": result}}; other keys ignored). Closed days dropped."""
    raw = json.load(open(path, encoding='utf-8-sig'))
    data = collections.defaultdict(dict)
    for mk in MARKETS4:
        for ds, v in (raw.get(mk) or {}).items():
            try:
                d = datetime.date.fromisoformat(ds); n = int(str(v).strip())
            except (TypeError, ValueError):
                continue
            if 0 <= n <= 99: data[mk][d] = n
    drop_closed(data)
    return data

def drop_closed(data):
    """Spec rule: skip closed days EVERYWHERE. Rows dated on a closed day (e.g. Desawar on the 1st before 2016) are not used."""
    for mk in data:
        for d in [d for d in data[mk] if closed(mk, d)]: del data[mk][d]

def load_extra(data, path):
    if not path: return
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.lower().startswith('date'): continue
        d, mk, v = [p.strip() for p in line.split(',')[:3]]
        if v.isdigit(): data[mk][datetime.date.fromisoformat(d)] = int(v) % 100
    drop_closed(data)

def closed(mk, d):
    if mk == 'Desawar': return d.day == 1
    if mk in ('Faridabad', 'Ghaziabad', 'Gali'): return (d + D1).month != d.month
    return False

# ------------------------------------------------------------------ transforms
def rashi(d): return (d + 5) % 10
def palti(n): return (n % 10) * 10 + n // 10
def fullR(n): return rashi(n // 10) * 10 + rashi(n % 10)
def innerR(n): return rashi(n // 10) * 10 + (n % 10)
def outerR(n): return (n // 10) * 10 + rashi(n % 10)
def fam(n): return {n, palti(n), fullR(n), innerR(n), outerR(n)}
TRANS = collections.OrderedDict([
    ("x", lambda x: x), ("x+1", lambda x: (x + 1) % 100), ("x-1", lambda x: (x - 1) % 100), ("x+2", lambda x: (x + 2) % 100),
    ("x-2", lambda x: (x - 2) % 100), ("x+5", lambda x: (x + 5) % 100), ("x-5", lambda x: (x - 5) % 100),
    ("x+10", lambda x: (x + 10) % 100), ("x-10", lambda x: (x - 10) % 100), ("x+11", lambda x: (x + 11) % 100),
    ("x-11", lambda x: (x - 11) % 100), ("x+50", lambda x: (x + 50) % 100), ("palti", palti), ("full", fullR),
    ("inner", innerR), ("outer", outerR), ("palti(full)", lambda x: palti(fullR(x))), ("100-x", lambda x: (100 - x) % 100),
    ("99-x", lambda x: 99 - x), ("2x", lambda x: (2 * x) % 100), ("jod11", lambda x: ((x // 10 + x % 10) % 10) * 11),
    ("TT", lambda x: (x // 10) * 11), ("UU", lambda x: (x % 10) * 11)])

# ------------------------------------------------------------------ model
class V7:
    def __init__(self, data): self.data = data
    def val(self, mk, G):
        """Result of market mk on GAME day G (Desawar's 5:30am result belongs to the previous game day)."""
        return self.data["Desawar"].get(G + D1) if mk == "Desawar" else self.data[mk].get(G)

    # ---- rules (unchanged from V7)
    def learn_rules(self, target, A, M, B):
        sources = [(X, lag) for lag in (0, 1, 2) for X in MARKETS4
                   if not (lag == 0 and (MARKETS4.index(X) >= MARKETS4.index(target) or X in EXCLUDE_SAME_DAY.get(target, ())))]
        def pairs(X, lag, a, b):
            """Pairs indexed by the TARGET game day G in [a, b]: input = X on day G - lag. No target result outside [a, b] is used."""
            P = []; G = a
            while G <= b:
                x = self.val(X, G - datetime.timedelta(days=lag)); y = self.val(target, G)
                if x is not None and y is not None: P.append((x, y))
                G += D1
            return P
        pos, neg = [], []
        for X, lag in sources:
            P1 = pairs(X, lag, A, M); P2 = pairs(X, lag, M + D1, B)
            if len(P1) < 300 or len(P2) < 300: continue
            for name, f in TRANS.items():
                h1 = sum(f(x) == y for x, y in P1); h2 = sum(f(x) == y for x, y in P2); n = len(P1) + len(P2); h = h1 + h2
                z = (h - n / 100) / math.sqrt(n * .0099); w = h / n - 0.01
                if h1 / len(P1) > .01 and h2 / len(P2) > .01 and z > 1.0: pos.append([X, lag, name, w])
                if h1 / len(P1) < .01 and h2 / len(P2) < .01 and z < -1.0: neg.append([X, lag, name, w])
        return pos + neg

    # ---- habit sets + learned adjustments (new in 7.1)
    def val_fb(self, mk, G):
        """V7.2: like val(), but a CLOSED day of mk is replaced by the day before it (used only on the first draw after a holiday)."""
        x = self.val(mk, G)
        if x is None and closed(mk, G + D1 if mk == "Desawar" else G): return self.val(mk, G - D1)
        return x
    def habit_sets(self, target, G, fb=False):
        """Ordered dict name -> set of numbers, built only from results known before the target is drawn on game day G."""
        val = self.val_fb if fb else self.val
        S = collections.OrderedDict()
        def add(name, nums):
            s = {v for v in nums if v is not None}
            if s: S[name] = s
        y = val(target, G - D1)
        if y is not None:
            add("own yesterday", [y]); add("own yesterday family", fam(y) - {y}); add("own yesterday +1..+5", [(y + k) % 100 for k in range(1, 6)])
        add("own 2-3 days ago", [val(target, G - datetime.timedelta(days=k)) for k in (2, 3)])
        add("own 4-14 days ago", [val(target, G - datetime.timedelta(days=k)) for k in range(4, 15)])
        if target != "Desawar":
            x = val("Desawar", G - D1)                                  # this morning's Desawar
            if x is not None: add("Desawar morning", [x]); add("Desawar morning family", fam(x) - {x})
        add("other markets yesterday", [val(X, G - D1) for X in MARKETS4 if X not in (target, "Desawar")])
        add("same-day earlier markets", [val(X, G) for X in MARKETS4
                                         if MARKETS4.index(X) < MARKETS4.index(target) and X not in EXCLUDE_SAME_DAY.get(target, ())])
        return S
    def learn_adjust(self, target, A, B):
        h = collections.Counter(); e = collections.Counter(); n = collections.Counter(); G = A
        while G <= B:
            a = self.val(target, G)
            if a is not None:
                for k, s in self.habit_sets(target, G).items(): h[k] += a in s; e[k] += len(s) / 100; n[k] += 1
            G += D1
        adj = {}
        for k in e:
            z = (h[k] - e[k]) / math.sqrt(e[k] * (1 - e[k] / n[k]))
            if abs(z) >= ADJ_Z: adj[k] = (h[k] / e[k] - 1) * 0.01
        return adj
    def learn(self, target, A, M, B):
        return {"rules": self.learn_rules(target, A, M, B), "adjust": self.learn_adjust(target, A, B)}

    # ---- scoring
    def scores(self, target, G, logic):
        s = collections.defaultdict(float)
        rd = G + D1 if target == "Desawar" else G               # result date of the target
        fb = closed(target, rd - D1)                             # V7.2: first draw after this market's holiday
        val = self.val_fb if fb else self.val
        for X, lag, name, w in logic["rules"]:
            v = val(X, G - datetime.timedelta(days=lag))
            if v is not None: s[TRANS[name](v)] += w
        for k, st in self.habit_sets(target, G, fb).items():
            a = logic["adjust"].get(k)
            if a:
                for n in st: s[n] += a
        return s
    def slate(self, target, result_date, logic):
        G = result_date - D1 if target == "Desawar" else result_date
        s = self.scores(target, G, logic)
        order = sorted(range(100), key=lambda n: -s.get(n, 0))       # stable sort -> ties go to the smaller number
        tens = [0.0] * 10; units = [0.0] * 10
        for n in range(100): tens[n // 10] += s.get(n, 0); units[n % 10] += s.get(n, 0)
        return order[:8], max(range(10), key=lambda i: units[i]), max(range(10), key=lambda i: tens[i])

# ------------------------------------------------------------------ commands
def cmd_train(m, out):
    A, M, B = PROD_TRAIN
    logic = {"version": VERSION, "markets": {T: m.learn(T, A, M, B) for T in TARGETS}}
    json.dump(logic, open(out, 'w'))
    for T in TARGETS:
        L = logic["markets"][T]
        print(f"{T:10} {sum(1 for r in L['rules'] if r[3] > 0)} positive, {sum(1 for r in L['rules'] if r[3] < 0)} negative rules, "
              f"{len(L['adjust'])} habit adjustments: " + ", ".join(f"{k} {v:+.4f}" for k, v in L['adjust'].items()))
    print("written", out)

def cmd_predict(m, logic, date):
    print(f"V{logic.get('version', '?')} slates for {date}  (enter earlier same-day results first: they are inputs)")
    for T in TARGETS:
        if closed(T, date): print(f"  {T:10} closed today"); continue
        s, andar, bahar = m.slate(T, date, logic["markets"][T])
        print(f"  {T:10} " + " ".join(f"{n:02d}" for n in s) + f"   andar(units) {andar}  bahar(tens) {bahar}" + ("   <- andar digit played" if T == "Gali" else ""))

def cmd_walkforward(m, last_year):
    print("Strict walk-forward: rules AND adjustments for year Y learned only on 2013..Y-1. 8 numbers. Random = 8.00%, break-even = 8.89%")
    tot = collections.Counter()
    for Y in range(2017, last_year + 1):
        A, B = datetime.date(2013, 1, 1), datetime.date(Y - 1, 12, 31); M = A + (B - A) / 2
        line = []
        for T in TARGETS:
            logic = m.learn(T, A, M, B); n = h = ha = 0; d = datetime.date(Y, 1, 1)
            while d <= datetime.date(Y, 12, 31):
                a = m.data[T].get(d)
                if a is not None and not closed(T, d):
                    s, andar, bahar = m.slate(T, d, logic); n += 1; h += a in s; ha += a % 10 == andar
                d += D1
            if n: line.append(f"{T} {h:3d}/{n} {100*h/n:5.2f}% andar {100*ha/n:4.1f}%"); tot[(T, 'n')] += n; tot[(T, 'h')] += h; tot[(T, 'a')] += ha
        print(f"  {Y}: " + "  ".join(line), flush=True)
    print("  ALL : " + "  ".join(f"{T} {tot[(T,'h')]}/{tot[(T,'n')]} {100*tot[(T,'h')]/tot[(T,'n')]:5.2f}% andar {100*tot[(T,'a')]/tot[(T,'n')]:4.1f}%" for T in TARGETS if tot[(T, 'n')]))

def cmd_check(m, logic_path):
    A, M, B = PROD_TRAIN
    ref = json.load(open(logic_path)); ok = True
    print(f"  logic file version {ref.get('version')}, script version {VERSION}")
    for T in TARGETS:
        mine = m.learn(T, A, M, B); R = ref["markets"][T]
        same_r = mine["rules"] == R["rules"]; same_a = mine["adjust"] == R["adjust"]; ok &= same_r and same_a
        print(f"  {T:10} rules {len(mine['rules']):3d} vs file {len(R['rules']):3d} -> {'IDENTICAL' if same_r else 'DIFFERENT'};  "
              f"adjustments {len(mine['adjust'])} vs file {len(R['adjust'])} -> {'IDENTICAL' if same_a else 'DIFFERENT'}")
    print("RESULT:", "this script reproduces the V7 logic (rules + adjustments) exactly" if ok else "MISMATCH - check data / implementation")

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['train', 'predict', 'walkforward', 'check'])
    ap.add_argument('--xlsx'); ap.add_argument('--json', help='spi_results.json (alternative to --xlsx)'); ap.add_argument('--extra'); ap.add_argument('--logic', default='v7_logic.json')
    ap.add_argument('--date'); ap.add_argument('--out', default='v7_logic.json'); ap.add_argument('--last-year', type=int, default=2026)
    a = ap.parse_args()
    if not a.xlsx and not a.json: ap.error('give --xlsx or --json')
    data = load_json(a.json) if a.json else load_xlsx(a.xlsx); load_extra(data, a.extra); m = V7(data)
    if a.cmd == 'train': cmd_train(m, a.out)
    elif a.cmd == 'predict':
        logic = json.load(open(a.logic)); cmd_predict(m, logic, datetime.date.fromisoformat(a.date) if a.date else datetime.date.today())
    elif a.cmd == 'walkforward': cmd_walkforward(m, a.last_year)
    else: cmd_check(m, a.logic)
