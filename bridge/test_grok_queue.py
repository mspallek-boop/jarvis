import json
import tempfile
import unittest
from pathlib import Path

from grok_queue import enqueue_task, list_inbox, read_result, write_result, queue_dirs


class GrokQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        queue_dirs(self.tmp)

    def test_enqueue_and_list(self):
        out = enqueue_task("hello", root=self.tmp)
        self.assertFalse(out["dry_run_acked"])
        jobs = list_inbox(self.tmp)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["task"], "hello")
        self.assertEqual(set(jobs[0]), {"id", "task", "target", "priority", "dry_run", "enqueued_at"})

    def test_dry_run_acks_immediately(self):
        out = enqueue_task("ping", dry_run=True, root=self.tmp)
        self.assertTrue(out["dry_run_acked"])
        job_id = out["task"]["id"]
        self.assertEqual(list_inbox(self.tmp), [])
        result = read_result(job_id, root=self.tmp)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["dry_run"])
        self.assertEqual(set(result) >= {"id", "status", "summary", "result"}, True)

    def test_write_and_read_result(self):
        out = enqueue_task("work", root=self.tmp)
        job_id = out["task"]["id"]
        write_result(job_id, "ok", "done", {"n": 1}, root=self.tmp)
        result = read_result(job_id, root=self.tmp)
        self.assertEqual(result["summary"], "done")
        self.assertEqual(result["result"], {"n": 1})


if __name__ == "__main__":
    unittest.main()
