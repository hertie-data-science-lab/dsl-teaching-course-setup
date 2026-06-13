"""Minimal autograder: run the assignment's tests, write result.json (the C50-style
contract for later score collection) and a GitHub Actions score summary. Exits 0 - the
score is the signal (a failing submission just scores low). Swap pytest for
Otter/nbgrader without changing the calling workflow."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/", "--junitxml=report.xml"])

root = ET.parse("report.xml").getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
cases = [
    {"name": tc.get("name"), "passed": tc.find("failure") is None and tc.find("error") is None}
    for tc in suite.findall("testcase")
]
passed = sum(c["passed"] for c in cases)

with open("result.json", "w") as f:
    json.dump({"score": passed, "max": len(cases), "tests": cases}, f, indent=2)

lines = ["## Autograder", "", f"**Score: {passed}/{len(cases)}**", ""]
lines += [f"- {'✅' if c['passed'] else '❌'} `{c['name']}`" for c in cases]
report = "\n".join(lines)
print(report)

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write(report + "\n")
