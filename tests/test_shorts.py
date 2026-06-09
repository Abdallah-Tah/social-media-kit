import json

import pytest

from agent.shorts import Article, ShortsError, plan_short, validate_plan


def test_shorts_plan_fallback_uses_real_terminal_value(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    article = Article(
        slug="demo",
        title="Deploy Laravel Queues Safely",
        body="""# Deploy Laravel Queues Safely

Use a small command chain and verify each step.

```bash
php artisan queue:restart
php artisan queue:work --tries=3
php artisan horizon:status
```
""",
        url="https://buildwithabdallah.com/tutorials/demo",
    )

    plan = plan_short(article)

    assert plan["short_type"] == "terminal_workflow"
    assert validate_plan(plan) == []
    assert any(scene.get("commands") for scene in plan["scenes"])
    assert plan["scenes"][-1]["kind"] == "cta_card"


def test_shorts_rejects_hype_trailer():
    plan = {
        "short_type": "article_summary_with_practical_takeaway",
        "hook": "Unlock the power of coding",
        "main_idea": "",
        "scenes": [
            {"kind": "cta_card", "title": "Subscribe", "caption": "Click now"},
        ],
        "captions": ["Boost your skills"],
        "voiceover": "This is revolutionary.",
        "cta": "Subscribe",
    }

    issues = validate_plan(plan)

    assert any("hype phrase" in issue for issue in issues)
    assert any("CTA cannot be the first scene" in issue for issue in issues)
    assert any("needs code, terminal commands" in issue for issue in issues)


def test_shorts_plan_writes_json(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / "short_plan.json"
    article = Article(
        slug="code-demo",
        title="Make Config Explicit",
        body="""# Make Config Explicit

```python
def load_config(env):
    return {"queue": env["QUEUE_CONNECTION"]}
```
""",
    )

    plan_short(article, out)

    saved = json.loads(out.read_text())
    assert saved["source"]["slug"] == "code-demo"
    assert saved["short_type"] == "before_after_code"


def test_shorts_plan_raises_when_normalized_plan_has_no_value(monkeypatch):
    from agent import shorts

    monkeypatch.setattr(shorts, "_llm_plan", lambda article: {
        "short_type": "article_summary_with_practical_takeaway",
        "hook": "Generic promo",
        "main_idea": "",
        "scenes": [{"kind": "cta_card", "title": "Read it", "caption": "Click"}],
        "captions": [],
        "voiceover": "Click the article",
        "cta": "Read now",
    })

    with pytest.raises(ShortsError):
        plan_short(Article(slug="bad", title="Bad", body="No useful content"))
