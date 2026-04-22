import json, sys
issues = sys.argv[1].splitlines() if sys.argv[1] else []
blocking = sys.argv[2].splitlines() if sys.argv[2] else []
advisory = sys.argv[3].splitlines() if sys.argv[3] else []
print(json.dumps({
    "ok": len(issues) == 0 and len(blocking) == 0,
    "issues": issues,
    "blocking_warnings": blocking,
    "advisory_warnings": advisory
}, indent=2))
