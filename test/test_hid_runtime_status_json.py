import json
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_C = os.path.join(ROOT, "bridge", "device", "hid-activity-diagnostic", "runtime-status.c")


class HidRuntimeStatusJsonTests(unittest.TestCase):
    def test_status_fragment_is_valid_inside_diagnostic_object(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("C compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "probe.c")
            binary = os.path.join(directory, "probe")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write(r'''#include "runtime-status.h"
#include <stdio.h>
int main(void) {
  mc_runtime_status status = { true, 1, 0 };
  fputs("{\"ready\":true,\"events\":1,", stdout);
  mc_runtime_status_write_json(stdout, &status);
  fputs(",\"rootTypes\":{},\"teardownErrors\":0}", stdout);
  return 0;
}
''')
            subprocess.run([compiler, source, STATUS_C, "-I", os.path.dirname(STATUS_C),
                            "-o", binary], check=True, capture_output=True)
            result = subprocess.run([binary], check=True, capture_output=True, text=True)
            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["events"], 1)
            self.assertTrue(parsed["hidEventMonitorEntitlement"])
            self.assertEqual(parsed["rootTypes"], {})


if __name__ == "__main__":
    unittest.main()
