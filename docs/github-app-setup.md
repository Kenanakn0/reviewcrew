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

Fill in `GITHUB_APP_CLIENT_ID`, `GITHUB_PRIVATE_KEY_PATH` (forward slashes on Windows),
`GITHUB_WEBHOOK_SECRET` and the LLM settings (`ANTHROPIC_API_KEY`, or
`LLM_PROVIDER=openai_compat` with `OPENAI_COMPAT_BASE_URL` for a local Ollama).

## 5. Run

Terminal 1, the API:

```bash
uv run reviewcrew
```

Terminal 2, the webhook forwarder (requires Node.js):

```bash
npx smee-client --url https://smee.io/<random> --target http://127.0.0.1:8000/webhook
```

## 6. Verify

- Open a pull request in the test repository. After the agents finish (usually well under
  a minute) the bot posts a review: inline comments on problematic lines plus a summary
  table. The review is always a plain comment; the bot never approves or requests changes.
- Draft PRs are skipped until they are marked *Ready for review*.
- In the App's **Advanced** tab, *Recent Deliveries* shows each delivery and lets you
  redeliver it.
