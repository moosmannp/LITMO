"""Tests for the measurement scripts in tools/."""
import json
import sys

sys.path.insert(0, "tools")
import lost_pairs as LP  # noqa: E402
from helpers import base  # noqa: E402


def test_compare_runs_counts_the_plans_exclusions_before_and_after_decisions_131():
    import compare_runs as CR
    # before 131: only protected exclusions reviewed, the others directly in "excluded" (VA 4a)
    old = {"reviewed": 7, "excluded": ["a"] * 11, "completion_excluded": 1, "review_kept": ["x"], "earlier_decisions": 0}
    assert CR._plan_excluded(old) == 16
    # since 131: every exclusion reviewed, reassignments counted apart
    new = {"reviewed": 30, "reviewed_protected": 12, "excluded": ["a"] * 9, "review_kept": ["a"] * 9,
           "accounted_as": ["b", "c"], "completion_excluded": 0, "earlier_decisions": 0}
    assert CR._plan_excluded(new) == 32
    assert CR._plan_excluded({}) is None


def test_lost_pairs_are_reconstructed_and_seeded_into_a_copy(tmp_path):
    before = {"ontology": base()}
    before["ontology"]["properties"].append({"name": "usesSample", "type": "ObjectProperty", "domain": "LowLevelTask",
                                             "range": "Dataset"})
    before["ontology"]["properties"].append({"name": "usesGone", "type": "ObjectProperty", "domain": "Task",
                                             "range": "RemovedClass"})                  # its class is gone: no pair
    after = {"ontology": base(), "title": "VA"}
    assert LP.lost_pairs(before, after) == [{"property": "usesSample", "into": None, "type": "ObjectProperty",
                                             "domain": "LowLevelTask", "range": "Dataset"}]
    src, out, old = tmp_path / "va.project.json", tmp_path / "copy.project.json", tmp_path / "before.json"
    src.write_text(json.dumps({"format": LP.PROJECT_FORMAT, "version": 1, "project": after}), encoding="utf-8")
    old.write_text(json.dumps(before), encoding="utf-8")
    LP.main(["seed", str(old), str(src), str(out)])
    copy = json.loads(out.read_text(encoding="utf-8"))["project"]
    assert copy["title"] == "VA (class restrictions)" and copy["merge_records"][0]["property"] == "usesSample"
