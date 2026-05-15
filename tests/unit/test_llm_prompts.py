from argus_py.llm.prompts import (
    load_prompt,
    load_prompt_template,
    render_prompt,
    resolve_prompt_path,
)


def test_load_builtin_planner_prompt():
    content = load_prompt("blackbox_planner.md")

    assert content.startswith("你是 Argus 黑盒测试规划器")
    assert "## 业务扩展" in content


def test_load_builtin_evaluator_prompt():
    content = load_prompt("blackbox_evaluator.md")

    assert content.startswith("你是 Argus 黑盒测试结果评估器")
    assert "## 业务扩展" in content


def test_load_prompt_template_contains_source(tmp_path):
    template = load_prompt_template("blackbox_planner.md")

    assert template.name == "blackbox_planner.md"
    assert template.source.endswith("blackbox_planner.md")


def test_explicit_prompt_path_has_highest_priority(tmp_path):
    explicit_path = tmp_path / "explicit.md"
    explicit_path.write_text("显式路径 {{ value }}", encoding="utf-8")

    resolved = resolve_prompt_path(str(explicit_path))
    rendered = render_prompt(str(explicit_path), value="优先")

    assert resolved == explicit_path
    assert rendered == "显式路径 优先"
