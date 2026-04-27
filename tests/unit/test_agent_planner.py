from argus_py.llm.parser import extract_json


def test_extract_json_from_markdown_block():
    data = extract_json("```json\n{\"action\": \"screenshot\"}\n```")

    assert data["action"] == "screenshot"
