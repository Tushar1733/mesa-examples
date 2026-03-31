import json


def load_examples(file_path):
    """Load examples list from validation JSON."""
    with open(file_path, "r") as f:
        data = json.load(f)

    if "examples" not in data:
        raise ValueError(f"{file_path} missing 'examples' field")

    return data["examples"]


def env_health(example):
    """Evaluate server and model test."""
    server_ok = example["status"] == "PASS"
    model_ok = example["model_test"]["passed"]

    env_ok = server_ok and model_ok

    return server_ok, model_ok, env_ok


def determine_status(declared_example, latest_example):
    """Determine lifecycle state."""

    _, _, declared_ok = env_health(declared_example)
    _, _, latest_ok = env_health(latest_example)

    if declared_ok and latest_ok:
        return "Active-healthy"

    if declared_ok and not latest_ok:
        return "needs_upgrade"

    if not declared_ok and latest_ok:
        return "Declared-env-invalid"

    return "broken"


def build_report(declared_examples, latest_examples):

    declared_map = {ex["name"]: ex for ex in declared_examples}
    latest_map = {ex["name"]: ex for ex in latest_examples}

    all_examples = sorted(set(declared_map) | set(latest_map))

    report = []
    stats = {
        "Active-healthy": 0,
        "needs_upgrade": 0,
        "Declared-env-invalid": 0,
        "broken": 0
    }

    for name in all_examples:

        declared = declared_map.get(name)
        latest = latest_map.get(name)

        if not declared or not latest:
            final_status = "missing_data"
            maintainer = None
        else:
            final_status = determine_status(declared, latest)

            # maintainer should be same in both envs
            maintainer = declared.get("maintainer") or latest.get("maintainer")

        stats.setdefault(final_status, 0)
        stats[final_status] += 1

        report.append({
            "name": name,
            "maintainer": maintainer,
            "declared_server": declared["status"] if declared else None,
            "declared_model": declared["model_test"]["passed"] if declared else None,
            "latest_server": latest["status"] if latest else None,
            "latest_model": latest["model_test"]["passed"] if latest else None,
            "final_status": final_status
        })

    return report, stats


def save_json(data, file_path):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def main():

    declared_file = "example_validation_results(declared-deps).json"
    latest_file = "example_validation_results(latest-deps).json"

    output_report = "example_health_report.json"
    output_stats = "example_health_stats.json"

    declared_examples = load_examples(declared_file)
    latest_examples = load_examples(latest_file)

    report, stats = build_report(declared_examples, latest_examples)

    save_json(report, output_report)
    save_json(stats, output_stats)

    print("Health report generated:", output_report)
    print("Stats generated:", output_stats)


if __name__ == "__main__":
    main()