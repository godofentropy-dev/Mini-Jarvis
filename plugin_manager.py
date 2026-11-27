"""
Plugin manager for JARVIS (phase 1 of the self-extending design).

A plugin is one file in plugins/ that defines:

    META = {"name": "...", "description": "...",
            "triggers": [r"regex that matches the spoken command", ...],
            "permissions": ["phone", "phone_unlock"]}

    def run(ctx, command, match):      # returns the sentence JARVIS should speak (or None)
        ...

Why this design:
  * voice.py never changes when a feature is added: it only calls this manager.
  * a plugin only reaches the outside world through `ctx`, and ctx refuses anything the plugin
    did not declare in META["permissions"]. That is a speed bump against accidents and a clear place to
    review, NOT a hardened sandbox: plugins run inside JARVIS's own process. Only load code you have read.
  * a broken plugin can never crash JARVIS: errors are caught, logged, and after 3 failures in a row
    the plugin switches itself off for the session.

NOTE: load_one() executes the file to read its META. That is fine for plugins you wrote or reviewed.
Before generated code is ever loaded (phase 2), it must pass an ast check and your approval first.
"""
import ast
import importlib.util
import os
import re
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(BASE, "plugins")
DATA_DIR = os.path.join(BASE, "plugins_data")
LOG_FILE = os.path.join(BASE, "plugins.log")

KNOWN_PERMISSIONS = {"phone", "phone_unlock"}      # grows as JARVIS gains safe helpers
MAX_FAILURES = 3
SAFE_PLUGIN_IMPORTS = {"re", "json", "math", "time", "datetime", "collections", "typing"}


def _validate_plugin_source(path):
    """Reject top-level executable plugin code before importing the module."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            source = stream.read()
        tree = ast.parse(source, filename=path)
    except (OSError, SyntaxError, UnicodeError) as exc:
        return False, f"could not parse plugin: {exc}"

    for node in tree.body:
        # Module docstring.
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
            if any(name not in SAFE_PLUGIN_IMPORTS for name in names):
                return False, "top-level imports must use the safe standard-library allowlist"
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in SAFE_PLUGIN_IMPORTS:
                return False, "top-level imports must use the safe standard-library allowlist"
            continue
        if isinstance(node, ast.Assign):
            if not all(isinstance(target, ast.Name) and target.id.isupper() for target in node.targets):
                return False, "top-level assignments must use uppercase constant names"
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                return False, "top-level assignments must contain literal data only"
            continue
        if isinstance(node, ast.AnnAssign):
            if (not isinstance(node.target, ast.Name) or not node.target.id.isupper()
                    or node.value is None):
                return False, "top-level assignments must use uppercase constants with literal values"
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                return False, "top-level assignments must contain literal data only"
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list or node.returns or any(
                    arg.annotation for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs):
                return False, "plugin functions cannot use import-time decorators or annotations"
            try:
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is not None:
                        ast.literal_eval(default)
            except (ValueError, TypeError, SyntaxError):
                return False, "plugin function defaults must be literal values"
            continue
        return False, f"unsupported top-level statement: {type(node).__name__}"

    return True, ""


class PluginContext:
    """The only door a plugin has to the rest of JARVIS. `host` is a dict of callables supplied by voice.py."""

    def __init__(self, plugin, host):
        self._plugin = plugin
        self._host = host

    def _need(self, perm):
        if perm not in self._plugin.permissions:
            raise PermissionError(f"plugin '{self._plugin.name}' did not declare the '{perm}' permission")

    # ---- always allowed
    def speak(self, text):
        self._host["speak"](text)

    def confirm(self, question):
        """Spoken yes/no. Returns True/False."""
        return bool(self._host["confirm"](question))

    @property
    def cancelled(self):
        ev = self._host.get("cancel")
        return bool(ev is not None and ev.is_set())

    def data_path(self, filename):
        """A private folder for this plugin's own files."""
        folder = os.path.join(DATA_DIR, self._plugin.name)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, os.path.basename(filename))

    # ---- permission "phone"
    def phone_connected(self):
        self._need("phone")
        phone = self._host["get_phone"]()
        return bool(phone and phone.connected)

    def adb(self, *args, timeout=10):
        """Runs `adb <args>` on the connected phone. Returns (returncode, output text)."""
        self._need("phone")
        phone = self._host["get_phone"]()
        if not (phone and phone.connected):
            return 1, ""
        return phone._run(*args, timeout=timeout)

    # ---- permission "phone_unlock"
    def unlock_phone(self):
        """Uses JARVIS's existing unlock flow (PIN after a spoken yes, or waits for your fingerprint).
        The plugin never sees the PIN. Returns the sentence the unlock flow wants spoken."""
        self._need("phone_unlock")
        return self._host["unlock_phone"]()


class Plugin:
    def __init__(self, name, description, triggers, permissions, module, path):
        self.name, self.description = name, description
        self.triggers, self.permissions = triggers, permissions
        self.module, self.path = module, path
        self.failures = 0
        self.disabled = False


class PluginManager:
    def __init__(self, host):
        self.host = host
        self.plugins = {}
        os.makedirs(PLUGIN_DIR, exist_ok=True)

    # ------------------------------------------------------------------ logging
    @staticmethod
    def _log(text):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ loading
    def load_one(self, path):
        """Loads (or hot-reloads) one plugin file. Returns (ok, name_or_reason)."""
        stem = os.path.splitext(os.path.basename(path))[0]
        modname = f"jarvis_plugin_{stem}"
        sys.modules.pop(modname, None)                    # forget the old copy so edits take effect
        try:
            root = os.path.realpath(PLUGIN_DIR)
            real_path = os.path.realpath(path)
            if os.path.commonpath([root, real_path]) != root or not os.path.isfile(real_path):
                return False, "plugin path is outside the plugins folder"
            valid, reason = _validate_plugin_source(real_path)
            if not valid:
                return False, reason
            spec = importlib.util.spec_from_file_location(modname, real_path)
            if spec is None or spec.loader is None:
                return False, "could not create a plugin loader"
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            meta = getattr(mod, "META", None)
            if not isinstance(meta, dict):
                return False, "no META dict"
            if not callable(getattr(mod, "run", None)):
                return False, "no run(ctx, command, match) function"
            triggers = [re.compile(t, re.I) for t in meta.get("triggers", [])]
            if not triggers:
                return False, "META has no triggers"
            perms = set(meta.get("permissions", []))
            if perms - KNOWN_PERMISSIONS:
                return False, f"unknown permissions: {sorted(perms - KNOWN_PERMISSIONS)}"
            name = str(meta.get("name") or stem)
        except Exception as e:
            self._log(f"load failed for {stem}:\n{traceback.format_exc()}")
            return False, f"{type(e).__name__}: {e}"
        self.plugins[name] = Plugin(name, meta.get("description", ""), triggers, perms, mod, real_path)
        return True, name

    def reload_all(self):
        """Re-reads every plugins/*.py. Returns a short sentence to speak."""
        self.plugins.clear()
        ok = bad = 0
        files = sorted(os.listdir(PLUGIN_DIR))
        self._log(f"reload_all: looking in {PLUGIN_DIR}, found {files}")
        if not any(fn.endswith(".py") and not fn.startswith("_") for fn in files):
            return "I found no plugin files. Check the plugins log for the folder I looked in."
        for fn in sorted(files):
            if fn.endswith(".py") and not fn.startswith("_"):
                good, info = self.load_one(os.path.join(PLUGIN_DIR, fn))
                ok += good
                bad += not good
                if not good:
                    self._log(f"{fn} skipped: {info}")
        return f"Loaded {ok} plugin{'s' if ok != 1 else ''}." + (f" {bad} failed, see the plugins log." if bad else "")

    # ------------------------------------------------------------------ running
    def match(self, command):
        """First enabled plugin whose trigger matches -> (plugin, match object), else None."""
        for p in self.plugins.values():
            if p.disabled:
                continue
            for t in p.triggers:
                m = t.search(command)
                if m:
                    return p, m
        return None

    def run(self, plugin, command, match):
        """Runs a plugin safely. Returns the sentence to speak (or None). Never raises."""
        ctx = PluginContext(plugin, self.host)
        try:
            out = plugin.module.run(ctx, command, match)
            plugin.failures = 0
            return out if isinstance(out, str) and out.strip() else None
        except PermissionError as e:
            self._log(f"{plugin.name}: blocked: {e}")
            return f"The {plugin.name.replace('_', ' ')} plugin tried something it has no permission for, so I stopped it."
        except Exception:
            plugin.failures += 1
            self._log(f"{plugin.name} crashed ({plugin.failures}/{MAX_FAILURES}):\n{traceback.format_exc()}")
            if plugin.failures >= MAX_FAILURES:
                plugin.disabled = True
                return f"The {plugin.name.replace('_', ' ')} plugin keeps failing, so I've switched it off until you reload plugins."
            return f"The {plugin.name.replace('_', ' ')} plugin hit an error. The details are in the plugins log."