import json

with open("example_health_report.json") as f:
    data = json.load(f)

issues = []

for example in data:
    status = example["final_status"]

    if status in ["needs_upgrade", "broken"]:
        issues.append({
            "title": f"Example issue: {example['name']}",
            "body": f"""
Example **{example['name']}** has status **{status}**.

Declared server: {example['declared_server']}
Declared model: {example['declared_model']}

Latest server: {example['latest_server']}
Latest model: {example['latest_model']}

Maintainer: @{example['maintainer']}
"""
        })

with open("issues_to_create.json", "w") as f:
    json.dump(issues, f, indent=2)