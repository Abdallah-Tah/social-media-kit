# Contributing

Thanks for improving the Social Media Agent.

## Dev setup

```bash
pip install -r requirements.txt
pip install -e ".[dev]"     # installs pytest
```

## Run the tests

```bash
python -m pytest -q
```

CI runs the suite on Python 3.10–3.12 for every PR (`.github/workflows/ci.yml`).

## Adding a publishing channel

1. Add `scripts/<channel>_poster.py` with a `post(...)`/`post_message(...)`
   function that catches `requests.RequestException` and returns a truthy value
   on success.
2. Register a tool schema + handler in `agent/tools.py`, add the channel to
   `PLATFORM_TOOLS` in `agent/prompts.py`, and to the `doctor` checks in
   `agent/cli.py`.
3. Add credentials to `config/secrets.env.example` and a setup section in
   `docs/PLATFORM_SETUP.md`.
4. Add a test in `tests/`.

## Conventions

- Standard library + `requests` + `PyYAML` + `Pillow` only — avoid new deps.
- Keep secrets out of the repo; never commit `config/secrets.env`.
- Match the surrounding code style (small functions, clear names, docstrings).
