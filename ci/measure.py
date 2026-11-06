import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

root = Path("artifacts")
cases = list(ET.parse(root / "tests.xml").getroot().iter("testcase"))
failures = sum(any(case.find(tag) is not None for tag in ["failure", "error"]) for case in cases)
skipped = sum(case.find("skipped") is not None for case in cases)
coverage = ET.parse(root / "coverage.xml").getroot()
covered, valid = int(coverage.attrib["lines-covered"]), int(coverage.attrib["lines-valid"])
assert len(cases) >= 40 and failures == 0 and skipped == 0
assert covered / valid >= 0.85
e2e = json.loads((root / "e2e-proof.json").read_text())
visual = json.loads((root / "visual-proof.json").read_text())
assert e2e["all_deliveries_sent"] and e2e["browser_errors"] == [] and visual["all_four_sheets_rendered"]
metrics = {"tests": len(cases), "failures": failures, "skipped": skipped, "line_coverage_percent": round(100 * covered / valid, 2),
    "covered_lines": covered, "measured_lines": valid, "e2e_graph_items": e2e["graph_items"], "e2e_notifications": e2e["notifications"],
    "commit": os.environ["GITHUB_SHA"], "run_url": f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'}
(root / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
print(json.dumps(metrics, indent=2))
table = f'| Metric | Measured in CI |\n| --- | ---: |\n| pytest cases | {len(cases)} |\n| Line coverage | {metrics["line_coverage_percent"]:.2f}% ({covered}/{valid}) |\n| Failures / skipped | {failures} / {skipped} |\n'
(root / "metrics.md").write_text(table)
with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
    summary.write(table)
for name in subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True, text=True).stdout.split("\0"):
    if name and Path(name).suffix not in {".png", ".xlsx", ".pdf"}:
        assert chr(0x2014) not in Path(name).read_text(encoding="utf-8"), name
