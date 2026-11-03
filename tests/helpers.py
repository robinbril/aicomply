import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMEWORKS = os.path.join(ROOT, "frameworks")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

MINI = """framework: "Test framework"
reference: "TEST 1:2026"
short: "Test"
kind: "iso"
source: "test"
scope: "test scope"
controls:
  - id: "T-CRIT"
    title: "Critical"
    part: "Part A"
    clause: "1"
    requirement: "r"
    applies_when: "always"
    severity: critical
    weight: 5
    check: "c"
    evidence: "e"
    advice: "fix crit"
    owner: "CISO"
  - id: "T-HIGH"
    title: "High"
    part: "Part A"
    clause: "2"
    requirement: "r"
    applies_when: "always"
    severity: high
    weight: 3
    check: "c"
    evidence: "e"
    advice: "fix high"
    owner: "DPO"
  - id: "T-MED"
    title: "Medium"
    part: "Part B"
    clause: "3"
    requirement: "r"
    applies_when: "always"
    severity: medium
    weight: 2
    check: "c"
    evidence: "e"
    advice: "fix med"
    owner: "DPO"
  - id: "T-LOW"
    title: "Low"
    part: "Part B"
    clause: "4"
    requirement: "r"
    applies_when: "sometimes"
    severity: low
    weight: 1
    check: "c"
    evidence: "e"
    advice: "fix low"
    owner: "CISO"
"""
