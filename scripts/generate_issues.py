import json

INPUT_FILE = "example_health_report.json"
OUTPUT_FILE = "issues_to_create.json"

with open(INPUT_FILE, "r") as f:
    data = json.load(f)

issues = []

for example in data:
    status = example["final_status"]

    if status in ["needs_upgrade", "broken"]:
        issue = {
            "title": f"Example issue: {example['name']}",
            "body": f"""
Example **{example['name']}** has status **{status}**.

Declared server: {example['declared_server']}
Declared model: {example['declared_model']}

Latest server: {example['latest_server']}
Latest model: {example['latest_model']}

Maintainer: @{example['maintainer']}
""".strip(),
            "status": status
        }

        issues.append(issue)

with open(OUTPUT_FILE, "w") as f:
    json.dump(issues, f, indent=4)

print(f"{len(issues)} issues written to {OUTPUT_FILE}")