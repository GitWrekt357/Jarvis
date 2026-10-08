"""Run with: python -m unittest test_code_tool -v
Uses a fake model client and a throwaway workspace. No API calls are made."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import workspace_tool as ws
import code_tool as ct


def fake_response(files, summary="Wrote it.", stop_reason="tool_use"):
    block = SimpleNamespace(type="tool_use", input={"files": files, "summary": summary})
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[block],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


class FakeClient:
    """Returns `response` every time, or each of `responses` in turn (last one repeats)."""
    def __init__(self, response=None, error=None, responses=None):
        self.responses = list(responses) if responses else [response]
        self.error, self.calls = error, []
        self.messages = self

    def create(self, **kwargs):
        # Record a copy of the messages, since the real code builds a new list per call.
        self.calls.append(dict(kwargs, messages=list(kwargs["messages"])))
        if self.error:
            raise self.error
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


def text_only_response():
    block = SimpleNamespace(type="text", text="Here is the code in plain text.")
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[block],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


class CodeToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        patcher = mock.patch.object(ws, "WORKSPACE_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(ct.set_client, None)

    def use(self, **kw):
        client = FakeClient(**kw)
        ct.set_client(client)
        return client

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read()

    def test_saves_new_file(self):
        self.use(response=fake_response([{"path": "hello.py", "content": "print('hi')\n"}]))
        out = ct.write_code("print hello")
        self.assertIn("Saved hello.py", out)
        self.assertTrue(os.path.isfile(self.path("hello.py")))
        self.assertEqual(self.read("hello.py"), "print('hi')\n")

    def test_never_overwrites_existing(self):
        with open(self.path("a.py"), "w") as f:
            f.write("ORIGINAL")
        self.use(response=fake_response([{"path": "a.py", "content": "NEW"}]))
        out = ct.write_code("change it", files=["a.py"])
        self.assertEqual(self.read("a.py"), "ORIGINAL")
        self.assertEqual(self.read("a.proposed.py"), "NEW")
        self.assertIn("a.py already existed", out)
        # A second run must not clobber the first proposal either.
        self.use(response=fake_response([{"path": "a.py", "content": "NEWER"}]))
        ct.write_code("again", files=["a.py"])
        self.assertEqual(self.read("a.proposed.py"), "NEW")
        self.assertEqual(self.read("a.proposed2.py"), "NEWER")

    def test_path_escape_saves_nothing(self):
        self.use(response=fake_response([
            {"path": "ok.py", "content": "x"},
            {"path": "../evil.py", "content": "y"},
        ]))
        out = ct.write_code("do it")
        self.assertIn("outside the workspace", out)
        self.assertFalse(os.path.exists(self.path("ok.py")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "..", "evil.py")))

    def test_absolute_path_rejected(self):
        self.use(response=fake_response([{"path": "/etc/passwd", "content": "x"}]))
        self.assertIn("outside the workspace", ct.write_code("do it"))

    def test_truncated_output_saves_nothing(self):
        self.use(response=fake_response([{"path": "a.py", "content": "x"}], stop_reason="max_tokens"))
        out = ct.write_code("big job")
        self.assertIn("too big", out)
        self.assertFalse(os.path.exists(self.path("a.py")))

    def test_too_many_files(self):
        files = [{"path": f"f{i}.py", "content": "x"} for i in range(ct.MAX_FILES + 1)]
        self.use(response=fake_response(files))
        self.assertIn("more than I save at once", ct.write_code("lots"))
        self.assertEqual(os.listdir(self.root), [])

    def test_text_reply_gets_one_nudge_then_saves(self):
        client = self.use(responses=[
            text_only_response(),
            fake_response([{"path": "n.py", "content": "ok"}]),
        ])
        out = ct.write_code("do it")
        self.assertIn("Saved n.py", out)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("save_files", client.calls[1]["messages"][-1]["content"])

    def test_text_reply_twice_saves_nothing(self):
        client = self.use(responses=[text_only_response(), text_only_response()])
        out = ct.write_code("do it")
        self.assertIn("did not return any files", out)
        self.assertIn("Do not write the code yourself", out)
        self.assertEqual(len(client.calls), 2)  # one retry, never more
        self.assertEqual(os.listdir(self.root), [])

    def test_context_sent_in_full_with_auto_tool_choice(self):
        big = "line\n" * 3000  # 15000 chars, past the normal read tool's 8000 cap
        with open(self.path("big.py"), "w") as f:
            f.write(big)
        client = self.use(response=fake_response([{"path": "out.py", "content": "x"}]))
        ct.write_code("refactor", files=["big.py"], filename="out.py")
        call = client.calls[0]
        self.assertIn(big, call["messages"][0]["content"])
        self.assertIn("Preferred name for the main file: out.py", call["messages"][0]["content"])
        self.assertEqual(call["model"], ct.CODE_MODEL)
        # This model rejects forced tool_choice ("tool" or "any"), so it must stay auto.
        self.assertEqual(call["tool_choice"], {"type": "auto"})

    def test_missing_context_file(self):
        client = self.use(response=fake_response([]))
        out = ct.write_code("x", files=["nope.py"])
        self.assertIn("could not find nope.py", out)
        self.assertEqual(client.calls, [])  # no paid call was made

    def test_context_path_escape(self):
        client = self.use(response=fake_response([]))
        self.assertIn("could not read", ct.write_code("x", files=["../secrets.env"]))
        self.assertEqual(client.calls, [])

    def test_model_error_is_spoken_not_raised(self):
        self.use(error=RuntimeError("boom"))
        self.assertIn("could not reach the coding model", ct.write_code("x"))

    def test_failure_tells_chat_model_not_to_write_code_itself(self):
        self.use(error=RuntimeError("bad key"))
        out = ct.write_code("x")
        self.assertIn("bad key", out)
        self.assertIn("Do not write the code yourself", out)

    def test_empty_task(self):
        client = self.use(response=fake_response([]))
        self.assertIn("what the code should do", ct.write_code("   "))
        self.assertEqual(client.calls, [])

    def test_summary_has_no_dashes(self):
        self.use(response=fake_response(
            [{"path": "a.py", "content": "x"}],
            summary="Done — it renames files - quickly – and safely.",
        ))
        out = ct.write_code("x")
        for ch in ("—", "–", " - "):
            self.assertNotIn(ch, out)

    def test_dispatcher_and_schema(self):
        self.assertEqual(ct.CODE_TOOL_NAMES, {"write_code"})
        self.assertEqual(ct.code_tool_schemas[0]["input_schema"]["required"], ["task"])
        self.use(response=fake_response([{"path": "d.py", "content": "x"}]))
        self.assertIn("Saved d.py", ct.run_code_tool("write_code", {"task": "t"}))
        self.assertIn("Unknown code tool", ct.run_code_tool("nope", {}))


if __name__ == "__main__":
    unittest.main()
