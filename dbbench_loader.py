import json
import os


# dbbench_loader.py lives in the project root; AgentBenchData is a sibling.
_FILE_DIR = os.path.dirname(os.path.abspath(__file__))

# Support both cases:
# 1. File is in project root → AgentBenchData is a sibling directory.
# 2. File is in a subdirectory → AgentBenchData may be one level up.
def _find_base_dir():
    for candidate in [_FILE_DIR, os.path.dirname(_FILE_DIR)]:
        if os.path.isdir(os.path.join(candidate, "AgentBenchData")):
            return candidate
    return _FILE_DIR  # fallback


BASE_DIR = _find_base_dir()

DBBENCH_FILE = os.path.join(
    BASE_DIR,
    "AgentBenchData",
    "data",
    "dbbench",
    "dev.jsonl"
)


def load_dbbench():
    """
    Load the official AgentBench DBBench dev split.

    Important:
    - READ-style tasks use `label` as the ground truth.
    - INSERT/UPDATE/DELETE tasks use `answer_md5` as the
      ground-truth database-state hash.
    - For write tasks, the reference SQL is stored in label[0].
    """

    if not os.path.exists(DBBENCH_FILE):
        raise FileNotFoundError(
            f"DBBench dataset not found:\n{DBBENCH_FILE}"
        )

    tasks = []

    with open(
        DBBENCH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for index, line in enumerate(
            file,
            start=1
        ):

            line = line.strip()

            if not line:
                continue

            raw = json.loads(line)

            task_type = raw.get(
                "type",
                ["UNKNOWN"]
            )

            if isinstance(task_type, str):
                task_type = [task_type]

            primary_type = (
                task_type[0]
                if task_type
                else "UNKNOWN"
            )

            is_write_operation = (
                primary_type
                in {
                    "INSERT",
                    "UPDATE",
                    "DELETE"
                }
            )

            # -------------------------------------------------
            # Reference SQL
            # -------------------------------------------------

            sql_data = raw.get(
                "sql",
                ""
            )

            if is_write_operation:

                # Official DBBench write records do not normally
                # contain a `sql` field.
                #
                # label[0] contains the reference SQL.
                label = raw.get(
                    "label",
                    []
                )

                if (
                    isinstance(label, list)
                    and label
                ):
                    reference_sql = label[0]
                else:
                    reference_sql = ""

            elif isinstance(
                sql_data,
                dict
            ):

                reference_sql = (
                    sql_data.get(
                        "query",
                        ""
                    )
                )

            else:

                reference_sql = sql_data

            # -------------------------------------------------
            # Normalize answer_md5
            # -------------------------------------------------

            answer_md5 = raw.get(
                "answer_md5"
            )

            # -------------------------------------------------
            # Preserve original fields
            # -------------------------------------------------

            task = {
                "case_id": index,

                "description": raw.get(
                    "description",
                    ""
                ),

                "label": raw.get(
                    "label",
                    []
                ),

                "answer_md5": answer_md5,

                "reference_sql": (
                    reference_sql
                ),

                "table": raw.get(
                    "table",
                    {}
                ),

                "create": raw.get(
                    "create",
                    {}
                ),

                "evaluation": raw.get(
                    "evaluation",
                    ""
                ),

                "type": task_type,

                "source": raw.get(
                    "source",
                    ""
                ),

                # Preserve optional DBBench fields.
                "evidence": raw.get(
                    "evidence",
                    ""
                ),

                "add_description": raw.get(
                    "add_description",
                    ""
                ),

                "user_sqlite": raw.get(
                    "user_sqlite",
                    False
                ),

                # Keep original SQL object if present.
                "sql": raw.get(
                    "sql"
                ),
            }

            tasks.append(task)

    return tasks


if __name__ == "__main__":

    tasks = load_dbbench()

    print(
        f"Loaded DBBench tasks: {len(tasks)}"
    )

    if tasks:

        first = tasks[0]

        print(
            "First case:",
            first["case_id"]
        )

        print(
            "Type:",
            first["type"]
        )

        print(
            "Reference SQL:",
            first["reference_sql"]
        )