"""The Qt (PySide6) front-end, built alongside the Tk one.

`ryos/ui/` stays the shipping UI until this reaches parity; `__main__` flips
over only then. See docs/plans/qt-migration.md.

Nothing here is imported by the rest of the package, and PySide6 is an
optional dependency, so the Tk app and the test suite run without Qt
installed.
"""
