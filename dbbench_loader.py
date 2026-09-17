import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DBBENCH_FILE = os.path.join(
    BASE_DIR,
    "AgentBenchData",
    "data",
    "dbbench",
    "dev.jsonl"
)


def load_dbbench():

    tasks = []

    with open(
        DBBENCH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for index, line in enumerate(file, start=1):

            line = line.strip()

            if not line:
                continue

            task = json.loads(line)

            # -----------------------------------------
            # Identify task type
            # -----------------------------------------

            task_type = task.get(
                "type",
                ["UNKNOWN"]
            )

            if not task_type:
                task_type = ["UNKNOWN"]

            is_write_op = (
                task_type[0]
                in ("INSERT", "UPDATE", "DELETE")
            )

            # -----------------------------------------
            # Get SQL information
            # -----------------------------------------

            sql_data = task.get(
                "sql",
                ""
            )

            # -----------------------------------------
            # Determine reference SQL
            # -----------------------------------------

            if is_write_op:

                # DBBench write operations store the
                # reference SQL inside label[0].
                #
                # The actual correctness ground truth
                # for write operations is answer_md5.

                label_field = task.get(
                    "label",
                    []
                )

                if isinstance(label_field, list):

                    reference_sql = (
                        label_field[0]
                        if label_field
                        else ""
                    )

                else:

                    reference_sql = str(
                        label_field
                    )

            elif isinstance(sql_data, dict):

                reference_sql = sql_data.get(
                    "query",
                    ""
                )

            else:

                reference_sql = sql_data

            # -----------------------------------------
            # Add task
            # -----------------------------------------

            tasks.append({

                "case_id": index,

                "description": task.get(
                    "description",
                    ""
                ),

                "label": task.get(
                    "label",
                    []
                ),

                # Important:
                # Used for INSERT / UPDATE / DELETE
                # correctness evaluation.
                "answer_md5": task.get(
                    "answer_md5",
                    None
                ),

                "reference_sql": reference_sql,

                "table": task.get(
                    "table",
                    {}
                ),

                "create": task.get(
                    "create",
                    {}
                ),

                "evaluation": task.get(
                    "evaluation",
                    ""
                ),

                "type": task.get(
                    "type",
                    []
                ),

                "source": task.get(
                    "source",
                    ""
                )
            })

    return tasks