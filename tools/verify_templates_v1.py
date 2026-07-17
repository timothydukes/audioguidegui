#!/usr/bin/env python3
"""
verify_templates_v1.py -- audioguidegui Phase 2
For every template produced by build_templates_v1.py: regenerate an options
.py with codegen, then parse BOTH the original example and the generated file
with audioguide's real user classes (same exec environment as
concatenativeclasses.parse_file) and compare them semantically:

  - structured variables (TARGET/CORPUS/SEARCH/SUPERIMPOSE/INSTRUMENTS)
    compare via the classes' own checksum-based __eq__
  - flat options compare by value

This proves the JSON round-trip preserves meaning without needing to run
analysis/rendering. Run from the repo root:
    python3 tools/verify_templates_v1.py
"""
import os, sys, glob, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from gui import project, codegen
from audioguide.userclasses import (TargetOptionsEntry as tsf,
                                    CorpusOptionsEntry as csf,
                                    SearchPassOptionsEntry as spass,
                                    SuperimpositionOptionsEntry as si,
                                    SingleDescriptor as d,
                                    Instrument as instr, Score as score)


def parse_real(path):
    env = {'tsf': tsf, 'csf': csf, 'spass': spass, 'si': si, 'd': d,
           'instr': instr, 'score': score}
    out = {}
    exec(open(path, encoding='utf-8').read(), env, out)
    return {k: v for k, v in out.items() if k.isupper()}


def spass_eq(a, b):
    # SearchPassOptionsEntry defines no __eq__; compare public attributes,
    # descending into SingleDescriptor lists (which do define __eq__)
    ka = {k: v for k, v in vars(a).items() if not k.startswith('_')}
    kb = {k: v for k, v in vars(b).items() if not k.startswith('_')}
    return ka.keys() == kb.keys() and all(ka[k] == kb[k] for k in ka)


def compare(orig, gen):
    problems = []
    for k in sorted(set(orig) | set(gen)):
        if k not in orig or k not in gen:
            problems.append('%s present in only one file' % k)
            continue
        a, b = orig[k], gen[k]
        if k in ('CORPUS',):
            ok = len(a) == len(b) and all(x == y for x, y in zip(a, b))
        elif k == 'SEARCH':
            ok = len(a) == len(b) and all(spass_eq(x, y) for x, y in zip(a, b))
        else:
            ok = a == b
        if not ok:
            problems.append('%s differs' % k)
    return problems


tpl_glob = os.path.join(REPO, 'gui', 'templates', '*.agproj.json')
templates = sorted(glob.glob(tpl_glob))
if not templates:
    sys.exit('no templates found -- run tools/build_templates_v1.py first')

failed = 0
for tpath in templates:
    prj = project.load(tpath)
    origname = prj['name'] + '.py'
    origpath = os.path.join(REPO, 'examples', origname)
    genpath = os.path.join(REPO, 'examples', '_gen_' + origname)
    codegen.write(prj, genpath)
    try:
        problems = compare(parse_real(origpath), parse_real(genpath))
    except Exception as e:
        problems = ['exception: %r' % e]
    if problems:
        failed += 1
        print('FAIL %-30s %s' % (origname, '; '.join(problems)))
    else:
        print('PASS %-30s' % origname)
    os.remove(genpath)

print('%d/%d passed' % (len(templates) - failed, len(templates)))
sys.exit(1 if failed else 0)
