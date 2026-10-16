# GitHub App setup (local development)

ReviewCrew runs as a GitHub App. This guide registers a private App for your account,
forwards its webhooks to your machine with [smee.io](https://smee.io), and verifies the
round trip on a test repository.

## 1. Create a webhook proxy channel

Open <https://smee.io/new> and copy the channel URL (`https://smee.io/<random>`).
Anyone who knows this URL can read the deliveries sent to it, so treat it as private.

## 2. Generate a webhook secret

```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Register the App

GitHub → **Settings** → **Developer settings** → **GitHub Apps** → **New GitHub App**.

| Field | Value |
|---|---|
| GitHub App name | Globally unique, e.g. `reviewcrew-<your-username>` |
| Homepage URL | Your repository URL (any valid URL works) |
| Webhook → Active | ✅ |
| Webhook URL | The smee channel URL from step 1 |
| Webhook secret | The value from step 2 |
| Repository permissions → **Pull requests** | Read and write |
| Repository permissions → **Contents** | Read-only |
| Repository permissions → **Metadata** | Read-only (mandatory, preselected) |
| Subscribe to events | ✅ **Pull request** |
| Where can this GitHub App be installed? | Only on this account |

Leave every other permission at **No access**.

After **Create GitHub App**:

1. Copy the **Client ID** from the App's *General* page.
2. Under **Private keys**, click **Generate a private key**. A `.pem` file downloads.
   Move it **outside the repository** (for example `~/.reviewcrew/`).
3. **Install App** → choose your account → **Only select repositories** → pick a test
   repository.

## 4. Configure ReviewCrew

```bash
cp .env.example .env
```

Fill in `GITHUB_APP_CLIENT_ID`, `GITHUB_PRIVATE_KEY_PATH` (forward slashes on Windows) and
`GITHUB_WEBHOOK_SECRET`. The LLM settings already target a local Ollama; set it up with
[local-llm.md](local-llm.md). To use Claude instead, set `LLM_PROVIDER=anthropic` and
`ANTHROPIC_API_KEY`.

## 5. Run

**With Docker** (API, worker and Redis together):

```bash
docker compose up --build
```

`GITHUB_PRIVATE_KEY_PATH` stays the key's path on your machine; Compose mounts the file into
the containers as a secret. On Linux hosts the containers run as UID 10001, so the key file
must be readable by that user (for example `chmod 644` on a key kept in a private
directory). Then start the webhook forwarder below.

**Without Docker,** ReviewCrew has two processes: the API receives webhooks and queues work in Redis, and the
worker performs the reviews. Start Redis first (Docker shown; any Redis 6.2+ works):

```bash
docker run -d --name reviewcrew-redis -p 127.0.0.1:6379:6379 redis:8.10-alpine
```

Terminal 1, the API:

```bash
uv run reviewcrew
```

Terminal 2, the worker:

```bash
uv run reviewcrew-worker
```

Terminal 3, the webhook forwarder (requires Node.js):

```bash
npx smee-client --url https://smee.io/<random> --target http://127.0.0.1:8000/webhook
```

## 6. Verify

- Open a pull request in the test repository. After the agents finish (usually well under
  a minute) the bot posts a review: inline comments on problematic lines plus a summary
  table. The review is always a plain comment; the bot never approves or requests changes.
- Draft PRs are skipped until they are marked *Ready for review*.
- Each commit is reviewed once: redelivering the webhook or reopening the PR without new
  commits does not produce a second review. Push a new commit to get a fresh one.
- To tune the review per repository, add a `.reviewcrew.yml` to the default branch
  (see [configuration.md](configuration.md)).
- In the App's **Advanced** tab, *Recent Deliveries* shows each delivery and lets you
  redeliver it.
