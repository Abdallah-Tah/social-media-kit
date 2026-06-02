# Commercial License & Resale Terms

The source code in this repository is released under the **MIT License** (see
[`LICENSE`](../LICENSE)), which already permits commercial use, modification,
and resale. This document clarifies terms for buyers who purchase the product
on Gumroad (or similar) and explains what a typical end-user license covers.

> This is a plain-language template, not legal advice. Adapt it to your
> jurisdiction and consider a lawyer for anything high-stakes.

## What a buyer gets

A non-exclusive, perpetual license to:

- Use the Social Media Agent for personal or commercial projects.
- Modify the source and configure it for their own brands/clients.
- Run it for clients as part of a service (agency / freelance use).

## What a buyer may not do

- Resell or redistribute the product **as-is** as a competing template/kit.
- Claim original authorship of the kit.
- Remove attribution from the source files.

(Under MIT these are courtesy terms; enforceable restrictions on a sold product
are typically set out in the Gumroad product EULA you attach at checkout.)

## Suggested Gumroad EULA snippet

> By purchasing, you receive a non-exclusive, non-transferable license to use
> and modify the Social Media Agent for unlimited personal and client projects.
> You may not resell or redistribute the unmodified product as a competing
> product. The software is provided "as is", without warranty of any kind. You
> are responsible for complying with the terms of service of every platform you
> publish to and every model provider you use.

## Third-party responsibilities (tell your buyers)

- **API costs**: Claude/OpenAI usage is billed by the provider. Ollama is free
  and local.
- **Platform rules**: Each network (X, LinkedIn, Meta, Slack, etc.) has its own
  automation and rate-limit policies. The buyer must comply with them.
- **Keys & data**: All credentials stay in the buyer's `config/secrets.env`.
  Neither the author nor any server sees them.

## Recommended product page checklist

- [ ] Requirements listed (Python 3.10+, an LLM key *or* local Ollama).
- [ ] "What's included" = agent + 9 channels + scheduling + profiles + skill.
- [ ] Screenshot/GIF of a `--dry-run`.
- [ ] Link to your support channel.
- [ ] This EULA snippet attached as the product's license.
