#!/usr/bin/env python3
"""
runner.py -- audioguidegui Phase 3 (delivered as runner_v1.py)
Launches audioguide CLI scripts as a subprocess, parses the AGGUI progress
protocol from stderr, and supports hard cancellation via process-group kill.

Pure stdlib, no wx import -- usable headless and from the GUI (which will
wrap callbacks in wx.CallAfter).

Protocol events (JSON, one per stderr line), emitted by the ## AGGUI patches
in audioguide/userinterface.py and audioguide/util.py:
  {"ev":"bar_start","label":str,"total":int}
  {"ev":"bar_incr","label":str,"incr":int}
  {"ev":"bar_close","txt":str}
  {"ev":"section","text":str}
  {"ev":"log","text":str}
  {"ev":"error","tag":str,"msg":str}
The runner synthesizes two additional events:
  {"ev":"stdout","text":str}    every stdout line (csound output, warnings...)
  {"ev":"exit","code":int}      process termination

## INTERPRETIVE: stderr lines that are not valid JSON (e.g. python tracebacks)
## are forwarded as {"ev":"stderr","text":...} rather than dropped -- the GUI
## log should show crashes verbatim.
"""
import os, sys, json, signal, threading, subprocess


class Runner(object):
    def __init__(self, repo_root, python_exe=None):
        self.repo_root = os.path.abspath(repo_root)
        self.python_exe = python_exe or sys.executable
        self.proc = None
        self._threads = []

    # ------------------------------------------------------------------ run
    def run(self, script, args, on_event):
        """Start `python3 <script> <args...>` inside repo_root.
        script is relative to the repo root (e.g. 'agConcatenate.py').
        on_event(dict) is called from reader threads for every event.
        Returns immediately; use wait() or poll()."""
        if self.proc is not None and self.proc.poll() is None:
            raise RuntimeError('a process is already running')
        env = dict(os.environ, AGGUI_PROGRESS='1')
        cmd = [self.python_exe, os.path.join(self.repo_root, script)] + list(args)
        self.proc = subprocess.Popen(
            cmd, cwd=self.repo_root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            start_new_session=True)          # own process group -> killable tree
        self._threads = [
            threading.Thread(target=self._read_stderr, args=(on_event,), daemon=True),
            threading.Thread(target=self._read_stdout, args=(on_event,), daemon=True),
        ]
        for t in self._threads:
            t.start()
        threading.Thread(target=self._reap, args=(on_event,), daemon=True).start()

    def _read_stderr(self, on_event):
        for line in self.proc.stderr:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                if not isinstance(ev, dict) or 'ev' not in ev:
                    raise ValueError
            except ValueError:
                ev = {'ev': 'stderr', 'text': line}
            on_event(ev)

    def _read_stdout(self, on_event):
        for line in self.proc.stdout:
            line = line.rstrip('\n')
            if line.strip():
                on_event({'ev': 'stdout', 'text': line})

    def _reap(self, on_event):
        code = self.proc.wait()
        for t in self._threads:
            t.join(timeout=2)
        on_event({'ev': 'exit', 'code': code})

    # -------------------------------------------------------------- control
    def cancel(self, grace_sec=1.0):
        """SIGTERM the whole process group (python + csound children); SIGKILL
        anything still alive after grace_sec."""
        if self.proc is None or self.proc.poll() is not None:
            return
        pgid = os.getpgid(self.proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=grace_sec)
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)

    def poll(self):
        return None if self.proc is None else self.proc.poll()

    def wait(self):
        return None if self.proc is None else self.proc.wait()


# ---------------------------------------------------------------- aggregation
class ProgressState(object):
    """Folds raw events into a display state the GUI can bind to:
    .upper (bar label), .lower (item label), .fraction (0..1 or None for
    indeterminate), .sections (list), .done, .exit_code, .error."""
    def __init__(self):
        self.upper = ''
        self.lower = ''
        self.total = None
        self.count = 0
        self.sections = []
        self.done = False
        self.exit_code = None
        self.error = None

    @property
    def fraction(self):
        if not self.total:
            return None
        return min(1.0, self.count / float(self.total))

    def feed(self, ev):
        e = ev.get('ev')
        if e == 'bar_start':
            self.upper, self.total, self.count, self.lower = ev.get('label', ''), ev.get('total') or None, 0, ''
        elif e == 'bar_incr':
            self.count += ev.get('incr', 1)
            if ev.get('label'):
                self.lower = ev['label']
        elif e == 'bar_close':
            if self.total:
                self.count = self.total
            self.lower = ev.get('txt', '')
        elif e == 'section':
            self.sections.append(ev.get('text', ''))
            self.upper, self.lower, self.total, self.count = ev.get('text', ''), '', None, 0
        elif e == 'error':
            self.error = '%s: %s' % (ev.get('tag', 'ERROR'), ev.get('msg', ''))
        elif e == 'exit':
            self.done, self.exit_code = True, ev.get('code')
        return self
