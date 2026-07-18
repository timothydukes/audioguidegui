#!/usr/bin/env python3
"""
test_runner_v3.py -- audioguidegui Phase 3 (v2: full-run mode also prints stderr and, on failure, the stdout tail)
Headless verification of the AGGUI progress protocol and the subprocess runner.

Run from the repo root:

  python3 tools/test_runner_v3.py --selftest
      Exercises the patched printer/util through a synthetic child process and
      tests cancellation. Needs no soundfiles, csound, or ircamdescriptor.

  python3 tools/test_runner_v3.py
      Full test: regenerates an options file from the 01-simplest template and
      runs the real agConcatenate.py through the runner, printing a live
      progress readout. Requires a working audioguide install (your machine).
"""
import os, sys, time, argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from gui.runner import Runner, ProgressState

CHILD = r'''
import sys, time, os
sys.path.insert(0, %(repo)r)
from audioguide import userinterface, util
p = userinterface.printer(2, '.', None)
p.middleprint('SYNTHETIC SECTION ONE')
p.startPercentageBar(upperLabel='Fake work', total=20)
for i in range(20):
    p.percentageBarNext(lowerLabel='item %%i' %% i)
    time.sleep(0.03)
p.percentageBarClose(txt='Read 20/20 fake items')
p.pprint('a log line')
p.printProgramInfo('X.XX')
p.printDict('DICT HEADER', {'a': 1, 'b': 2})
p.printListLikeHistogram('HIST HEADER', ['x', 'x', 'y'])
print('plain stdout line')
p.middleprint('SYNTHETIC SECTION TWO')
if os.environ.get('CHILD_HANG') == '1':
    time.sleep(600)     # for the cancel test
if os.environ.get('CHILD_ERROR') == '1':
    util.error('fake', 'synthetic failure')
'''


def collect(events):
    def cb(ev):
        events.append(ev)
    return cb


def selftest():
    childpath = os.path.join(REPO, '_aggui_child.py')
    open(childpath, 'w').write(CHILD % {'repo': REPO})
    failures = []
    try:
        # --- 1. protocol emission + parsing
        events = []
        r = Runner(REPO)
        r.run('_aggui_child.py', [], collect(events))
        code = r.wait(); time.sleep(0.3)
        kinds = [e['ev'] for e in events]
        st = ProgressState()
        for e in events:
            st.feed(e)
        checks = [
            ('exit 0', code == 0),
            ('bar_start seen', 'bar_start' in kinds),
            ('20 bar_incr', kinds.count('bar_incr') == 20),
            ('bar_close seen', 'bar_close' in kinds),
            ('4 sections', kinds.count('section') == 4),
            ('programinfo/dict/histogram as log events', kinds.count('log') >= 6),
            ('log event seen', 'log' in kinds),
            ('stdout captured', any(e['ev'] == 'stdout' and 'plain stdout' in e['text'] for e in events)),
            ('state folded', st.done and st.exit_code == 0 and len(st.sections) == 4),
        ]
        for name, ok in checks:
            print('  %s %s' % ('PASS' if ok else 'FAIL', name))
            if not ok:
                failures.append(name)

        # --- 2. error event
        events = []
        os.environ['CHILD_ERROR'] = '1'
        r = Runner(REPO)
        r.run('_aggui_child.py', [], collect(events))
        r.wait(); time.sleep(0.3)
        del os.environ['CHILD_ERROR']
        ok = any(e['ev'] == 'error' and e.get('tag') == 'fake' for e in events)
        print('  %s error event emitted' % ('PASS' if ok else 'FAIL'))
        if not ok:
            failures.append('error event')

        # --- 3. cancel kills the process group promptly
        events = []
        os.environ['CHILD_HANG'] = '1'
        r = Runner(REPO)
        r.run('_aggui_child.py', [], collect(events))
        while not any(e['ev'] == 'bar_close' for e in events):
            time.sleep(0.05)
        t0 = time.time()
        r.cancel()
        r.wait()
        elapsed = time.time() - t0
        del os.environ['CHILD_HANG']
        ok = elapsed < 5
        print('  %s cancel terminated hung child in %.2fs' % ('PASS' if ok else 'FAIL', elapsed))
        if not ok:
            failures.append('cancel')
    finally:
        os.remove(childpath)
    print('%s (%d failures)' % ('OK' if not failures else 'FAILED', len(failures)))
    return 1 if failures else 0


def fullrun():
    from gui import project, codegen
    genpath = os.path.join(REPO, 'examples', '_aggui_run.py')
    codegen.write(project.load(os.path.join(REPO, 'gui', 'templates', '01-simplest.agproj.json')), genpath)
    st = ProgressState()

    stdout_tail = []

    def cb(ev):
        st.feed(ev)
        if ev['ev'] in ('bar_start', 'section'):
            print('\n== %s' % st.upper)
        elif ev['ev'] == 'bar_incr':
            frac = st.fraction
            sys.stdout.write('\r  %3d%%  %-50s' % ((frac or 0) * 100, st.lower[:50]))
            sys.stdout.flush()
        elif ev['ev'] == 'bar_close':
            print('\n  done: %s' % st.lower)
        elif ev['ev'] == 'error':
            print('\nERROR: %s' % st.error)
        elif ev['ev'] == 'stderr':
            print('\n[stderr] %s' % ev['text'])
        elif ev['ev'] == 'stdout':
            stdout_tail.append(ev['text'])
            del stdout_tail[:-30]
    r = Runner(REPO)
    r.run('agConcatenate.py', [genpath], cb)
    code = r.wait()
    os.remove(genpath)
    if code != 0 and stdout_tail:
        print('\n--- last stdout lines ---')
        for ln in stdout_tail:
            print('  ' + ln)
    print('\nexit code:', code)
    return code


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else fullrun())
