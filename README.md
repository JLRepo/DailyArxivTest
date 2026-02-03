# daily_arxiv_paper

Fetch the latest arXiv cs.CV papers in the last 24 hours, filter by keywords, and push to Slack. Also supports starring papers locally for later search.

## Setup

1. Create `.env` with your Slack webhook URL:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

2. Adjust `config.json` if needed:

- `category`: arXiv category (default `cs.CV`)
- `keywords`: keyword list (case-insensitive, any match)
- `max_results`: fetch limit from arXiv
- `abstract_max_chars`: abstract snippet length
- `use_proxy`: whether to honor system proxy settings (default `false`)

## Run

Fetch and send to Slack (last 24 hours):

```bash
python -m daily_arxiv_paper fetch
```

Dry run (no Slack):

```bash
python -m daily_arxiv_paper fetch --dry-run
```

## Star (收藏)

Star a paper by arXiv id:

```bash
python -m daily_arxiv_paper star 2401.01234
```

List starred papers:

```bash
python -m daily_arxiv_paper list
```

Search starred papers:

```bash
python -m daily_arxiv_paper search retrieval
```

## Schedule (Beijing 09:00)

Using cron with China Standard Time:

```bash
TZ=Asia/Shanghai
0 9 * * * cd /Users/xujilan/Desktop/skills/daily_arxiv_paper && /usr/bin/python3 -m daily_arxiv_paper fetch
```

If you want, I can also set up a Codex automation to run this daily at 09:00 Beijing time.

## GitHub Actions (always-on)

1. Push this repo to GitHub.
2. In GitHub repo settings, add a secret:

- Name: `SLACK_WEBHOOK_URL`
- Value: your Slack Incoming Webhook URL

3. The workflow is in `.github/workflows/daily_arxiv.yml`.
4. It runs every day at 09:00 China Standard Time (01:00 UTC). You can also run it manually via `workflow_dispatch`.
