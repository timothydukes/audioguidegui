#!/usr/bin/env python3
"""
build_tooltips_v1.py -- audioguidegui Phase 1
Parses docs_v1.79.html + userclasses.py + defaults.py into gui/tooltips.json.

Run from the repo root:  python3 tools/build_tooltips_v1.py

Namespaces in the output JSON:
  options : flat UPPERCASE options   (ground truth: defaults.py assignments)
  tsf, csf, si, d : object kwargs    (ground truth: __init__ signatures in userclasses.py)
  instr, score    : object kwargs    (ground truth: params dicts in userclasses.py)
  spass           : method names + per-method kwargs (ground truth: spass _defaults dicts)

## INTERPRETIVE decisions:
## - Code signatures, not the docs' Appendix 2, are the kwarg ground truth (the
##   appendix is stale: e.g. it lists si(minOnset=...) while the code uses minFrame).
## - d() internal kwargs (origin, neededBy, packagename, simultaneous) are excluded
##   from the GUI-facing list.
## - Tooltip text keeps the full documentation text, incl. code examples (indented)
##   and bullet lists ("- "). The GUI decides about wrapping/truncation.
## - Structured variables (TARGET/CORPUS/SEARCH/SUPERIMPOSE/INSTRUMENTS/
##   CORPUS_GLOBAL_ATTRIBUTES) get pointer text; they are edited in dedicated tabs.
"""
import re, os, sys, json, html

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, 'docs_v1.79.html')
DEFAULTS = os.path.join(REPO, 'audioguide', 'defaults.py')
USERCLASSES = os.path.join(REPO, 'audioguide', 'userclasses.py')
OUT = os.path.join(REPO, 'gui', 'tooltips.json')
NODOC = 'No documentation found.'

doc = open(DOCS, encoding='utf-8').read()
ucsrc = open(USERCLASSES, encoding='utf-8').read()

# ---------------------------------------------------------------- html -> text
def clean(fragment):
    s = fragment
    s = re.sub(r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>',
               lambda m: '\n' + '\n'.join('    ' + ln.strip()
                   for ln in re.sub(r'<[^>]+>', '', m.group(1)).strip().splitlines()) + '\n',
               s, flags=re.S)
    s = re.sub(r'<li[^>]*>', '\n- ', s)
    s = re.sub(r'</?(ul|ol|p|br)[^>]*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

# --------------------------------------------- code ground truth: signatures
def parse_init_kwargs(classname):
    m = re.search(r'class %s\(object\):\s*\n\tdef __init__\(self,([^)]*)\)' % classname, ucsrc)
    if not m:
        sys.exit('cannot find __init__ for ' + classname)
    body = m.group(1)
    out = {}
    for kw, dflt in re.findall(r'(\w+)\s*=\s*((?:\([^()]*\)|\{[^{}]*\}|\[[^\[\]]*\]|[^,])+)', body):
        out[kw.strip()] = dflt.strip()
    return out

def parse_params_dict(classname):
    m = re.search(r'class %s\(object\):.*?self\.params = \{(.*?)\n\t\t\}' % classname, ucsrc, re.S)
    if not m:
        sys.exit('cannot find params dict for ' + classname)
    out = {}
    for kw, dflt in re.findall(r"^\s*'(\w+)'\s*:\s*([^,\n]+(?:\([^()]*\))?[^,\n]*),", m.group(1), re.M):
        out[kw] = dflt.strip()
    return out

sig = {
    'tsf': parse_init_kwargs('TargetOptionsEntry'),
    'csf': parse_init_kwargs('CorpusOptionsEntry'),
    'si':  parse_init_kwargs('SuperimpositionOptionsEntry'),
    'd':   parse_init_kwargs('SingleDescriptor'),
    'instr': parse_params_dict('Instrument'),
    'score': parse_params_dict('Score'),
}
# trailing "# comment" text on kwarg lines serves as fallback doc text
code_comments = {}
for line in ucsrc.splitlines():
    m = re.match(r"\s*(?:self\.)?['\"]?(\w+)['\"]?\s*[:=][^#]*#\s*(.+)$", line)
    if m and len(m.group(2).strip()) > 3:
        code_comments.setdefault(m.group(1), m.group(2).strip())

sig['tsf'].pop('filename', None)
sig['csf'].pop('name', None)
for internal in ('simultaneous', 'origin', 'neededBy', 'packagename'):
    sig['d'].pop(internal, None)

# spass: per-method kwarg defaults, read from the three _defaults dicts
spass_defaults = re.findall(r"_defaults = \{([^}]*)\}", ucsrc)
spass_kw = {}
for grp in spass_defaults:
    for kw, dflt in re.findall(r"'(\w+)'\s*:\s*([^,]+)", grp):
        spass_kw.setdefault(kw.strip(), dflt.strip())

# ------------------------------------------------- flat UPPERCASE options
flat_re = re.compile(
    r'<p><b>([A-Z][A-Z0-9_]+)</b>\s*\(type=<span[^>]*>(.*?)</span>,\s*'
    r'default=<span[^>]*>(.*?)</span>\)\s*(.*?)</p>', re.S)

options = {}
matches = list(flat_re.finditer(doc))
for k, m in enumerate(matches):
    name, typ, dflt, body = m.group(1), clean(m.group(2)), clean(m.group(3)), m.group(4)
    tail = doc[m.end(): matches[k + 1].start() if k + 1 < len(matches) else m.end()]
    tail = re.split(r'<h[1-4]|<section|</section', tail)[0]
    keep = ''
    tm = re.match(r'\s*((?:<ul>.*?</ul>|<pre.*?</pre>)\s*)+', tail, re.S)
    if tm:
        keep = tm.group(0)
    options[name] = {'type': typ, 'default': dflt, 'doc': clean(body + keep)}

STRUCTURED = {
    'TARGET': 'Structured variable: the target soundfile, a tsf() object. Edited in the Target tab.',
    'CORPUS': 'Structured variable: a list of csf() objects. Edited in the Corpus tab.',
    'SEARCH': 'Structured variable: a list of spass() objects. Edited in the Search tab.',
    'SUPERIMPOSE': 'Structured variable: an si() object. Edited in the Superimpose tab.',
    'INSTRUMENTS': 'Structured variable: a score() of instr() objects. Edited as raw Python in the Instruments tab.',
    'CORPUS_GLOBAL_ATTRIBUTES': 'A dict of csf() keywords applied to every corpus entry (per-entry values win). See the Corpus tab.',
}
gt_options = sorted(set(re.findall(r'^([A-Z][A-Z0-9_]+)\s*=', open(DEFAULTS, encoding='utf-8').read(), re.M)))
for name in gt_options:
    if name in STRUCTURED:
        options[name] = {'type': 'structured', 'default': '', 'doc': STRUCTURED[name]}
    else:
        options.setdefault(name, {'type': '', 'default': '', 'doc': NODOC})

# ------------------------------------------------- object-keyword doc text
def span(start_pat, end_pat):
    a = re.search(start_pat, doc)
    b = re.search(end_pat, doc[a.end():])
    return doc[a.end(): a.end() + b.start()]

sections = {
    'tsf':   span(r'<h3>The TARGET Variable and tsf\(\) object</h3>', r'<h3>The CORPUS Variable'),
    'csf':   span(r'<h3>The CORPUS Variable and csf\(\) object</h3>', r'Normalization</h2>'),
    'd':     span(r'<h3>Descriptors and the d\(\) object</h3>', r'<h3>SEARCH variable'),
    'spass': span(r'<h3>SEARCH variable and spass\(\) object</h3>', r'<h3>The SUPERIMPOSE variable'),
    'si':    span(r'<h3>The SUPERIMPOSE variable and si\(\) object</h3>', r'<h4>Concatenation Output Files'),
    'instr': span(r'<h4>score\(\) and instr\(\)</h4>', r'<h3>Other Options</h3>'),
}
sections['score'] = sections['instr']

# entries look like <li><b>name</b> - ...; allow an <a id=..></a> anchor inside
# the <b> and a trailing asterisk on the name
li_re = re.compile(
    r"<li>\s*<b>\s*(?:<a[^>]*>\s*</a>\s*)?([&#\w'\u2018\u2019 ]+?)\*?\s*</b>\s*"
    r"(?:-|&ndash;|&mdash;|\u2013|\u2014)\s*", re.S)

def harvest(seg):
    found = {}
    ms = list(li_re.finditer(seg))
    for k, m in enumerate(ms):
        name = html.unescape(m.group(1)).strip().strip("'\u2018\u2019")
        end = ms[k + 1].start() if k + 1 < len(ms) else len(seg)
        chunk = re.split(r'</ul>\s*<p>|<h[1-4]', seg[m.end(): end])[0]
        found.setdefault(name, clean(chunk))
    return found

result = {'_meta': {'source': os.path.basename(DOCS),
                    'generator': os.path.basename(__file__)},
          'options': options}

for obj in ('tsf', 'csf', 'si', 'd', 'instr', 'score'):
    raw = harvest(sections[obj])
    plain = clean(sections[obj])
    ns = {}
    for kw, dflt in sig[obj].items():
        if kw in raw:
            ns[kw] = {'default': dflt, 'doc': raw[kw], 'src': 'docs'}
        elif kw in code_comments:
            ns[kw] = {'default': dflt, 'doc': code_comments[kw], 'src': 'code-comment'}
        else:
            # skip sentences that are just the object signature (they mention
            # many kwargs at once) -- not useful as a tooltip
            def usable(s):
                if not re.search(r'\b%s\b' % re.escape(kw), s):
                    return False
                others = sum(1 for k2 in sig[obj] if k2 != kw and re.search(r'\b%s\b' % re.escape(k2), s))
                return others <= 3
            sent = next((s.strip() for s in re.split(r'(?<=[.!?])\s+', plain) if usable(s)), None)
            if sent:
                ns[kw] = {'default': dflt, 'doc': sent, 'src': 'prose'}
            else:
                ns[kw] = {'default': dflt, 'doc': NODOC, 'src': 'none'}
    result[obj] = ns

raw = harvest(sections['spass'])
ns = {}
for meth in ('closest', 'farthest', 'closest_percent', 'farthest_percent',
             'ratio_limit', 'parser', 'target_partial_filter'):
    ns['method:' + meth] = {'default': '', 'doc': raw.get(meth, NODOC)}
plain = clean(sections['spass'])
for kw, dflt in spass_kw.items():
    if kw in raw:
        ns[kw] = {'default': dflt, 'doc': raw[kw], 'src': 'docs'}
    else:
        sent = next((s.strip() for s in re.split(r'(?<=[.!?])\s+', plain)
                     if re.search(r'\b%s\b' % re.escape(kw), s)), None)
        ns[kw] = {'default': dflt, 'doc': sent or NODOC, 'src': 'prose' if sent else 'none'}
result['spass'] = ns

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(result, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

# ------------------------------------------------------------------ coverage
print('wrote', OUT)
for nsname in ('options', 'tsf', 'csf', 'si', 'd', 'spass', 'instr', 'score'):
    ns = result[nsname]
    good = sum(1 for v in ns.values() if v['doc'] != NODOC)
    print('%-8s: %d/%d documented' % (nsname, good, len(ns)))
    miss = [k for k, v in ns.items() if v['doc'] == NODOC]
    if miss:
        print('   undocumented:', ', '.join(miss))
