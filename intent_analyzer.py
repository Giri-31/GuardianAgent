from google import genai
import os
import json
import re

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def analyze_intent(user_request):

    prompt = f"""
Analyze this database request.

Return ONLY valid JSON.
Do not use markdown.
Do not add explanations.

Use exactly these fields:
operation
target
field
value
scope

Possible operations:
SELECT, INSERT, UPDATE, DELETE

Possible scope:
single employee
multiple employees
all employees
unknown

User request:
{user_request}
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    text = response.text.strip()

    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:

        request = user_request.lower()

        if "salary" in request and "change" in request:

            target = "unknown"

            names = ["Arun", "Meera", "Rahul", "Anu", "Vishnu"]

            for name in names:
                if name.lower() in request:
                    target = name
                    break

            value_match = re.search(r"\d+", request)

            value = value_match.group() if value_match else "unknown"

            return {
                "operation": "UPDATE",
                "target": target,
                "field": "salary",
                "value": value,
                "scope": "single employee"
            }

        return {
            "operation": "UNKNOWN",
            "target": "unknown",
            "field": "unknown",
            "value": "unknown",
            "scope": "unknown"
        }


if __name__ == "__main__":

    user_request = "Change Arun's salary to 70000."

    intent = analyze_intent(user_request)

    print("User request:", user_request)
    print("Intent:", intent)