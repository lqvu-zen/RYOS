"""Writes a timestamped report into reports/ -- a pipeline step with a
result you can see."""
import datetime
import pathlib

folder = pathlib.Path(__file__).resolve().parent / "reports"
folder.mkdir(exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
path = folder / f"report_{stamp}.txt"
path.write_text(f"Report written at {stamp}\n", encoding="utf-8")
print("wrote", path)
