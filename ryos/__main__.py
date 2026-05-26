"""Entry point — `python -m ryos` or imported by script_runner.py shim."""
from .ui.app import RYOSApp


def main():
    app = RYOSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
