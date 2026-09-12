from guardian import guardian_check
from rule_filter import rule_filter
from controlled_tests import tests


def run_comparison():

    normal_correct = 0
    rule_correct = 0
    guardian_correct = 0

    total = len(tests)

    print("=" * 80)
    print("THREE-WAY SAFETY COMPARISON")
    print("=" * 80)

    for test in tests:

        sql = test["sql"]
        expected = test["expected"]

        normal_decision = "ALLOW"

        rule_decision = rule_filter(sql)

        guardian_result = guardian_check(
            test["request"],
            sql,
            known_intent=test["intent"]
        )

        guardian_decision = guardian_result["risk"]["decision"]

        if normal_decision == expected:
            normal_correct += 1

        if rule_decision == expected:
            rule_correct += 1

        if guardian_decision == expected:
            guardian_correct += 1

        print()
        print("-" * 80)
        print("TEST:", test["name"])
        print("CATEGORY:", test["category"])
        print("EXPECTED:", expected)
        print("NORMAL AGENT:", normal_decision)
        print("RULE FILTER:", rule_decision)
        print("GUARDIANAGENT:", guardian_decision)

    print()
    print("=" * 80)
    print("FINAL COMPARISON")
    print("=" * 80)

    normal_accuracy = (normal_correct / total) * 100
    rule_accuracy = (rule_correct / total) * 100
    guardian_accuracy = (guardian_correct / total) * 100

    print()
    print("System              Correct       Accuracy")
    print("-" * 50)
    print(
        f"Normal Agent        "
        f"{normal_correct}/{total}          "
        f"{normal_accuracy:.1f}%"
    )
    print(
        f"Rule Filter         "
        f"{rule_correct}/{total}          "
        f"{rule_accuracy:.1f}%"
    )
    print(
        f"GuardianAgent       "
        f"{guardian_correct}/{total}          "
        f"{guardian_accuracy:.1f}%"
    )


if __name__ == "__main__":
    run_comparison()