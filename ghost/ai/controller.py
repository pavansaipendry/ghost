#!/usr/bin/env python3
"""Ghost menu-bar controller — Phase A of "make Ghost a real app".

A tiny, always-on 👻 menu-bar app whose only job is to Start / Stop the real
Ghost AI process (``python -m ghost.ai.entry``) without a terminal. It runs over
the repo's existing venv, so there's nothing to bundle and no new dependency —
just AppKit/Foundation, already used everywhere in Ghost.

Launch it by double-clicking ``Ghost.app`` (a thin bundle that execs this module)
or directly for testing::

    venv/bin/python -m ghost.ai.controller

Menu:
    • Start — BlackHole (both voices) / Interviewer only / Microphone
      (these mirror ``run_ghost.sh`` exactly)
    • Stop Ghost           — sends SIGTERM so entry.py restores your audio output
    • Open Logs            — the captured stdout/stderr of the running Ghost
    • Open Session Folder  — the newest sessions/<ts> transcript folder
    • Launch Ghost at Login — install/remove a LaunchAgent
    • Quit Ghost Controller

Stopping matters: entry.py switches your system output to the "Ghost Audio"
device in BlackHole mode and only restores it on a clean quit. We therefore stop
with SIGTERM (handled in entry.py) and fall back to SIGKILL only if it hangs.
"""

import os
import signal
import subprocess
import threading
import plistlib

import objc
from AppKit import (
    NSObject,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSAlert,
    NSWorkspace,
)
from Foundation import NSTimer, NSURL
from PyObjCTools import AppHelper


# --- Paths (resolved relative to this file so it works on every synced Mac) ----
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENV_PYTHON = os.path.join(REPO_ROOT, "venv", "bin", "python")
LOGS_DIR = os.path.join(REPO_ROOT, "logs")
GHOST_LOG = os.path.join(LOGS_DIR, "ghost.log")
CONTROLLER_LOG = os.path.join(LOGS_DIR, "controller.log")
SESSIONS_DIR = os.path.join(REPO_ROOT, "sessions")
PID_LOCK = os.path.join(LOGS_DIR, "controller.pid")

LAUNCH_AGENT_LABEL = "com.ghost.controller"
LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist"
)

# Appended to every launch. --parakeet is the README-recommended on-device engine
# (`./run_ghost.sh --parakeet`); the role context matches run_ghost.sh's default.
COMMON_ARGS = ["--parakeet", "--context", "./contexts/ml_engineer"]

# Launch modes — mirror run_ghost.sh. Key -> (menu label, entry.py args).
LAUNCH_MODES = {
    "blackhole": ("Start — BlackHole (both voices)", ["--blackhole"]),
    "interviewer": ("Start — Interviewer only", ["--blackhole", "--interviewer-only"]),
    "mic": ("Start — Microphone", ["--mic"]),
}

STOP_GRACE_SECONDS = 8  # give entry.py time to restore audio before SIGKILL


# --- Single-instance lock -----------------------------------------------------
def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_single_instance():
    """Return True if we're the only controller; False if another is already up.

    launch-at-login + a manual double-click can both fire, and two 👻 icons that
    each spawn their own Ghost is a mess — so we guard with a PID lockfile.
    """
    os.makedirs(LOGS_DIR, exist_ok=True)
    try:
        if os.path.exists(PID_LOCK):
            with open(PID_LOCK) as f:
                existing = int((f.read() or "0").strip() or 0)
            if existing and existing != os.getpid() and _pid_alive(existing):
                return False
        with open(PID_LOCK, "w") as f:
            f.write(str(os.getpid()))
    except (OSError, ValueError):
        pass  # a flaky lock shouldn't stop the app from running
    return True


def release_single_instance():
    try:
        if os.path.exists(PID_LOCK):
            with open(PID_LOCK) as f:
                if (f.read() or "").strip() == str(os.getpid()):
                    os.remove(PID_LOCK)
    except OSError:
        pass


# --- LaunchAgent (launch at login) -------------------------------------------
def login_item_installed():
    return os.path.exists(LAUNCH_AGENT_PLIST)


def install_login_item():
    """Write the LaunchAgent so the controller starts at the NEXT login.

    We deliberately do NOT ``launchctl load`` it now — this controller is already
    running, and loading a RunAtLoad agent would immediately spawn a duplicate.
    launchd loads ~/Library/LaunchAgents at login on its own.
    """
    os.makedirs(os.path.dirname(LAUNCH_AGENT_PLIST), exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [VENV_PYTHON, "-m", "ghost.ai.controller"],
        "WorkingDirectory": REPO_ROOT,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "StandardOutPath": CONTROLLER_LOG,
        "StandardErrorPath": CONTROLLER_LOG,
    }
    with open(LAUNCH_AGENT_PLIST, "wb") as f:
        plistlib.dump(plist, f)


def remove_login_item():
    """Remove the LaunchAgent and unload it if it happens to be loaded."""
    try:
        uid = os.getuid()
        subprocess.run(
            ["/bin/launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"],
            capture_output=True,
        )
    except OSError:
        pass
    try:
        if os.path.exists(LAUNCH_AGENT_PLIST):
            os.remove(LAUNCH_AGENT_PLIST)
    except OSError:
        pass


class GhostController(NSObject):
    """NSStatusItem supervisor for the Ghost AI process."""

    def init(self):
        self = objc.super(GhostController, self).init()
        if self is None:
            return None
        self._proc = None
        self._stopping = False
        self._status_item = None
        self._rendered_state = None
        return self

    # -- lifecycle -------------------------------------------------------------
    def setup(self):
        bar = NSStatusBar.systemStatusBar()
        self._status_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self._status_item.button().setTitle_("👻")
        self._rebuild_menu()

        # Poll the child so a crash or an in-app quit flips the menu back to Stopped.
        self._poll_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            1.0, True, lambda _t: self._poll()
        )

    @objc.python_method
    def _state(self):
        if self._proc is None:
            return "stopped"
        return "stopping" if self._stopping else "running"

    @objc.python_method
    def _poll(self):
        if self._proc is not None and self._proc.poll() is not None:
            # The child exited (crash, in-app Ctrl+Shift+Q, or our SIGTERM landed).
            self._proc = None
            self._stopping = False
        state = self._state()
        if state != self._rendered_state:
            self._rebuild_menu()

    # -- menu ------------------------------------------------------------------
    @objc.python_method
    def _rebuild_menu(self):
        state = self._state()
        self._rendered_state = state
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        header = {
            "running": "Ghost — Running",
            "stopping": "Ghost — Stopping…",
            "stopped": "Ghost — Stopped",
        }[state]
        head = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(header, None, "")
        head.setEnabled_(False)
        menu.addItem_(head)
        menu.addItem_(NSMenuItem.separatorItem())

        if state == "stopped":
            for key, (label, _args) in LAUNCH_MODES.items():
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    label, "startMode:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(key)
                menu.addItem_(item)
        elif state == "running":
            stop = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Stop Ghost", "stopGhost:", ""
            )
            stop.setTarget_(self)
            menu.addItem_(stop)
        else:  # stopping
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Stopping…", None, ""
            )
            item.setEnabled_(False)
            menu.addItem_(item)

        menu.addItem_(NSMenuItem.separatorItem())

        logs = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Logs", "openLogs:", ""
        )
        logs.setTarget_(self)
        menu.addItem_(logs)

        sess = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Session Folder", "openSessions:", ""
        )
        sess.setTarget_(self)
        menu.addItem_(sess)

        menu.addItem_(NSMenuItem.separatorItem())

        login = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Launch Ghost at Login", "toggleLoginItem:", ""
        )
        login.setTarget_(self)
        login.setState_(1 if login_item_installed() else 0)
        menu.addItem_(login)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Ghost Controller", "quitController:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        self._status_item.setMenu_(menu)

    # -- actions ---------------------------------------------------------------
    @objc.IBAction
    def startMode_(self, sender):
        key = sender.representedObject()
        mode = LAUNCH_MODES.get(str(key))
        if not mode:
            return
        self._start(mode[1])

    @objc.python_method
    def _start(self, mode_args):
        if self._proc is not None:
            return
        os.makedirs(LOGS_DIR, exist_ok=True)
        try:
            logf = open(GHOST_LOG, "a", buffering=1)
            logf.write("\n" + "=" * 70 + "\n[controller] starting: "
                       + " ".join(["ghost.ai.entry"] + mode_args + COMMON_ARGS) + "\n")
            logf.flush()
        except OSError:
            logf = subprocess.DEVNULL

        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [VENV_PYTHON, "-m", "ghost.ai.entry"] + mode_args + COMMON_ARGS
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,  # detach from the controller's session
            )
        except OSError as e:
            self._proc = None
            self._alert("Couldn't start Ghost", f"{e}\n\nCommand:\n{' '.join(cmd)}")
            return
        self._stopping = False
        self._rebuild_menu()

    @objc.IBAction
    def stopGhost_(self, sender):
        proc = self._proc
        if proc is None:
            return
        self._stopping = True
        self._rebuild_menu()

        def _worker():
            try:
                proc.terminate()  # SIGTERM -> entry.py cleans up + restores audio
                try:
                    proc.wait(timeout=STOP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    proc.kill()  # last resort; audio may need manual reset
            except OSError:
                pass
            # The poll timer notices the exit and flips the menu back to Stopped.

        threading.Thread(target=_worker, daemon=True).start()

    @objc.IBAction
    def openLogs_(self, sender):
        if not os.path.exists(GHOST_LOG):
            os.makedirs(LOGS_DIR, exist_ok=True)
            open(GHOST_LOG, "a").close()
        self._open_path(GHOST_LOG)

    @objc.IBAction
    def openSessions_(self, sender):
        target = SESSIONS_DIR
        try:
            subdirs = [
                os.path.join(SESSIONS_DIR, d)
                for d in os.listdir(SESSIONS_DIR)
                if os.path.isdir(os.path.join(SESSIONS_DIR, d))
            ]
            if subdirs:
                target = max(subdirs, key=os.path.getmtime)
        except OSError:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
        self._open_path(target)

    @objc.IBAction
    def toggleLoginItem_(self, sender):
        if login_item_installed():
            remove_login_item()
        else:
            install_login_item()
        self._rebuild_menu()

    @objc.IBAction
    def quitController_(self, sender):
        # Take the running Ghost down with us so we don't orphan it (and leave the
        # audio output on 'Ghost Audio'). Block briefly for the clean shutdown.
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=STOP_GRACE_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        release_single_instance()
        NSApplication.sharedApplication().terminate_(None)

    # -- helpers ---------------------------------------------------------------
    @objc.python_method
    def _open_path(self, path):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(path))

    @objc.python_method
    def _alert(self, title, message):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.runModal()


_controller = None  # module-level strong ref so ARC doesn't collect it


def main():
    if not acquire_single_instance():
        # Another controller already owns the menu bar — surface it and bail.
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Ghost controller is already running")
        alert.setInformativeText_("Look for the 👻 in your menu bar.")
        alert.runModal()
        return

    global _controller
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _controller = GhostController.alloc().init()
    _controller.setup()
    try:
        AppHelper.runEventLoop(installInterrupt=True)
    finally:
        release_single_instance()


if __name__ == "__main__":
    main()
