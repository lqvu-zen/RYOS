"""Entry point — `uv run ryos` or `python -m ryos`."""
from .ui.app import RYOSApp


def main():
    app = RYOSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
