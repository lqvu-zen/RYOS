"""``ryos mcp`` end to end: a real MCP client (the official SDK) starts the
real server as a child process -- the way Claude Code or Claude Desktop does
-- on a throwaway data folder, and uses every tool.

Skipped when the MCP SDK is not installed (``uv run --with mcp ...``); CI
installs it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAVE_MCP = True
except ImportError:                     # pragma: no cover - depends on the env
    HAVE_MCP = False

from ryos.db import ScriptDB  # noqa: E402


def _data(result) -> object:
    """A tool result's value, from its structured content (SDK 2.x names it
    ``structured_content``; a list comes wrapped as ``{"result": [...]}``)."""
    structured = getattr(result, "structured_content", None)
    if structured is None:
        return json.loads(result.content[0].text)
    return structured["result"] if set(structured) == {"result"} else structured


@unittest.skipUnless(HAVE_MCP, "the MCP SDK is not installed")
class TestMcpServer(unittest.TestCase):
    def setUp(self):
        self.appdata = Path(tempfile.mkdtemp())
        folder = self.appdata / "RYOS"
        folder.mkdir()
        db = ScriptDB(folder / "scripts.db")
        db.create_group("Tools")
        hello = folder / "hello.py"
        hello.write_text("import sys\nprint('hello', *sys.argv[1:])\n", encoding="utf-8")
        sid = db.add("hello", str(hello), "--world", sys.executable, "Tools")
        db.replace_param_presets(sid, [("loud", "--loud")])
        db.set_agent_exposed("script", sid, True)
        db.add("secret", str(hello), "", sys.executable, "Tools")      # not available

    def call(self, steps):
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "ryos", "mcp"], cwd=str(ROOT),
            env={**os.environ, "APPDATA": str(self.appdata), "RYOS_NO_REGISTRY": "1",
                 "RYOS_NO_TOASTS": "1", "PYTHONPATH": str(ROOT)})

        async def session():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    return await steps(client)
        return asyncio.run(asyncio.wait_for(session(), 60))

    def test_the_tools(self):
        async def steps(client):
            tools = sorted(t.name for t in (await client.list_tools()).tools)
            scripts = _data(await client.call_tool("list_scripts", {}))
            started = _data(await client.call_tool(
                "run_script", {"script": "Tools/hello", "preset": "loud"}))
            done = _data(await client.call_tool(
                "get_run", {"run_id": started["run_id"], "wait_seconds": 20}))
            while not done["done"]:
                done = _data(await client.call_tool(
                    "get_run", {"run_id": started["run_id"], "wait_seconds": 5}))
            refused = await client.call_tool("run_script", {"script": "secret"})
            return tools, scripts, done, refused

        tools, scripts, done, refused = self.call(steps)
        self.assertEqual(tools, ["get_run", "list_pipelines", "list_scripts",
                                 "run_pipeline", "run_script", "stop_run"])
        self.assertEqual([s["ref"] for s in scripts], ["Tools/hello"])
        self.assertEqual(scripts[0]["presets"], ["loud"])
        self.assertEqual((done["status"], done["exit_code"]), ("ok", 0))
        self.assertEqual(done["lines"][0], "hello --loud")
        self.assertTrue(refused.is_error)
        self.assertIn("available to agents", refused.content[0].text)


if __name__ == "__main__":
    unittest.main()
