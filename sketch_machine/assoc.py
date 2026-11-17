"""File association on Windows: double-clicking a scene (.mule) starts Mule and opens it.

Windows associates by the last extension – "name.sketch.json" would be ".json" and match every JSON file. Hence the
own extension .mule (content unchanged: the same JSON scene; old .sketch.json files still open via File > Open
and can simply be renamed).

Mule registers itself on every start for the logged-in user (HKEY_CURRENT_USER, no administrator rights):
it then opens the Mule that ran last – the installed program or the working copy from the project folder.
Only written if something changed. The scene arrives as the first argument (launch.main)."""
import os
import sys

EXT = ".mule"
OLD_EXT = ".sketch.json"  # up to v0.99.187; still opened
PROGID = "Mule.Scene"
LABEL = "Mule scene"


def with_ext(path):
    """Path for saving: typed without an extension -> append .mule."""
    return path if os.path.splitext(path)[1] else path + EXT


def strip_ext(name):
    """File name without the scene extension (.mule, .sketch.json, .json)."""
    for ext in (EXT, ".json", ".sketch"):
        if name.endswith(ext):
            name = name[:-len(ext)]
    return name


def _root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def command():
    """Command with which Windows opens a scene (%1 = file)."""
    if getattr(sys, "frozen", False):  # finished program
        return f'"{sys.executable}" "%1"'
    # working copy: the same Python without a console window; the project folder goes into the search path (the double click
    # starts in the scene's folder, not in the project)
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = exe if os.path.isfile(exe) else sys.executable
    code = f"import sys; sys.path.insert(0, r'{_root()}'); from sketch_machine.launch import main; main()"
    return f'"{exe}" -c "{code}" "%1"'


def icon():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}",0'
    ico = os.path.join(_root(), "packaging", "mule.ico")
    return f'"{ico}"' if os.path.isfile(ico) else ""


def entries():
    """{key under HKCU\\Software\\Classes: default value}."""
    out = {EXT: PROGID, PROGID: LABEL, PROGID + r"\shell\open\command": command()}
    if icon():
        out[PROGID + r"\DefaultIcon"] = icon()
    return out


def register():
    """Register the association if it is missing or points to another Mule -> True if something was written.
    Windows only; errors (locked registry) have no consequences."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        changed = False
        for key, value in entries().items():
            path = "Software\\Classes\\" + key
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                    if winreg.QueryValueEx(k, "")[0] == value:
                        continue
            except OSError:
                pass
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
            changed = True
        if changed:  # Explorer should know right away (SHCNE_ASSOCCHANGED)
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        return changed
    except Exception:
        return False
