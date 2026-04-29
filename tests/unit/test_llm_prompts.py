from argus_py.llm.prompts import load_prompt, load_prompt_template, render_prompt, resolve_prompt_path


def test_load_prompt_falls_back_to_builtin_when_user_template_missing(tmp_path):
    content = load_prompt("llm_connection_check.md", prompts_dir=tmp_path / "missing")

    assert content.strip() == "Reply only: ok"


def test_user_prompt_overrides_builtin_prompt(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    prompt_path = prompts_dir / "llm_connection_check.md"
    prompt_path.write_text("用户覆盖模板", encoding="utf-8")

    template = load_prompt_template("llm_connection_check.md", prompts_dir=prompts_dir)

    assert template.content == "用户覆盖模板"
    assert template.source == str(prompt_path)


def test_explicit_prompt_path_has_highest_priority(tmp_path):
    user_dir = tmp_path / "prompts"
    user_dir.mkdir()
    (user_dir / "demo.md").write_text("用户模板", encoding="utf-8")
    explicit_path = tmp_path / "explicit.md"
    explicit_path.write_text("显式路径 {{ value }}", encoding="utf-8")

    resolved = resolve_prompt_path(str(explicit_path), prompts_dir=user_dir)
    rendered = render_prompt(str(explicit_path), prompts_dir=user_dir, value="优先")

    assert resolved == explicit_path
    assert rendered == "显式路径 优先"
