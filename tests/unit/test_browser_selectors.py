from argus_py.browser.selectors import SelectorQuery
from argus_py.browser.snapshot import InteractiveElement, PageSnapshot


def test_parse_jquery_contains_button_as_role_selector():
    query = SelectorQuery.parse("button:contains('登录')")

    assert query.strategy == "role"
    assert query.value == "button"
    assert query.name == "登录"


def test_parse_prefixed_contains_button_as_role_selector():
    query = SelectorQuery.parse('css: button:contains("登录")')

    assert query.strategy == "role"
    assert query.value == "button"
    assert query.name == "登录"


def test_parse_selector_hint_prefix():
    query = SelectorQuery.parse('selector=role=button[name="登录"]')

    assert query.strategy == "role"
    assert query.value == "button"
    assert query.name == "登录"


def test_parse_jquery_contains_link_as_role_selector():
    query = SelectorQuery.parse("a:contains('提交')")

    assert query.strategy == "role"
    assert query.value == "link"
    assert query.name == "提交"


def test_page_snapshot_includes_selector_hints():
    snapshot = PageSnapshot(
        url="https://example.com/login",
        title="登录",
        text="登录",
        interactive_elements=[
            InteractiveElement(index=0, tag="input", placeholder="用户名", name="username"),
            InteractiveElement(index=1, tag="button", text="登录"),
        ],
    )

    prompt_text = snapshot.to_prompt_text()

    assert 'selector=css=[name="username"]' in prompt_text
    assert 'selector=role=button[name="登录"]' in prompt_text


def test_password_input_selector_hint_uses_type_when_no_name():
    element = InteractiveElement(index=0, tag="input", element_type="password")

    assert element.selector_hint() == 'css=input[type="password"]'
