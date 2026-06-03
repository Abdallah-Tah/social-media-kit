# Security

## Reporting a vulnerability

Email **security@buildwithabdallah.com** (or open a private security advisory on
GitHub). Please don't file public issues for security reports. We aim to
acknowledge within 72 hours.

## How the kit handles your secrets

- All credentials live in `config/secrets.env`, which is **gitignored**.
- Tokens are read from environment variables / that local file only — never
  transmitted anywhere except the official platform/provider APIs you configure.
- The release builder (`scripts/make_release.sh`) packages from `git archive`
  and **aborts if a real `secrets.env` would be included**.
- `smkit doctor` warns when a credential looks truncated (a common copy-paste
  failure that leaks confusing errors, not keys).

## Built-in safety guardrails

- **Dry-run mode** simulates every publish/post with zero side effects.
- **Profile allowlist** is enforced at execution: the agent can only post to
  channels the active brand profile enables.
- **Draft reads are sandboxed** to `content/drafts/` — model output can't make
  the agent read arbitrary local files.
- **Per-provider base URLs** are isolated so one provider's endpoint can't
  redirect another's traffic.
- The scheduled GitHub workflow passes user inputs via the environment, not
  inline shell, to avoid script injection.

## Your responsibilities

You are responsible for complying with the Terms of Service and automation
policies of every platform you publish to and every model provider you use.
