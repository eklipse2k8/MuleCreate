"""Program start with the start animation from the first moment.

Loading the big modules (Qt OpenGL, numpy, USD …) takes long on a first start of the packaged program – Windows
checks every freshly unpacked library. So only Qt and the animation are loaded first: the head of the logo draws
itself and waits with "Loading …", while sketch_machine.app is imported in a background thread (loading libraries
releases the interpreter lock, the animation keeps running). When the import is done, the main window is built here
in the GUI thread and the animation plays on to the end.

Self-test and a switched-off animation take the plain way (app.main)."""
import sys
import threading
import time

from PySide6.QtCore import QTimer

from . import paths, startup


def main():
    if "--selftest" in sys.argv or not startup.enabled():
        from .app import main as plain
        plain()
        return
    t0 = time.monotonic()
    paths.start_log()
    app = startup.make_application()
    anim = startup.StartAnimation()
    if not anim.play():  # animation file missing or unreadable: start without it (the application exists already)
        from . import app as module
        module.show_window(module.make_window(app))
        sys.exit(app.exec())
    result = {}

    def load():
        try:
            from . import app as module
            result["module"] = module
        except BaseException as e:  # noqa: BLE001 – raised again in the GUI thread
            result["error"] = e

    loader = threading.Thread(target=load, name="load-mule", daemon=True)
    loader.start()
    poll = QTimer(interval=30)

    def check():
        if loader.is_alive():
            return
        poll.stop()
        if "error" in result:
            raise result["error"]
        module = result["module"]
        window = module.make_window(app)
        window.start_animation = anim
        print(f"Start: Mule loaded after {time.monotonic() - t0:.1f} s", flush=True)  # mule.log: slow first starts

        def show():
            module.show_window(window)
            print(f"Start: window shown after {time.monotonic() - t0:.1f} s", flush=True)
        anim.loaded(show)

    poll.timeout.connect(check)
    poll.start()
    sys.exit(app.exec())
