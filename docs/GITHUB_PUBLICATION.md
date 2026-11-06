# GitHub publication guide

Nothing has been pushed or published. These steps are yours to run when you're ready. The project folder isn't a Git repository yet, and `gh` isn't installed, so the steps use the GitHub website and plain Git.

## 1. Create the repository on GitHub

Go to <https://github.com/new>, then enter:

| Field | Value |
|---|---|
| Repository name | `dataforge-ai-analytics-platform` |
| Description | `An AI-powered data analytics platform for exploring datasets, discovering insights, detecting anomalies, generating visualisations, and creating intelligent reports.` |
| Visibility | **Public**, since the security and privacy review below found no problems. Choose Private if you'd like to look it over on GitHub first; you can change this later. |
| Add a README | **Off** (the project has its own) |
| Add .gitignore | **None** (the project has its own) |
| Choose a license | **None** (the project already has an MIT `LICENSE` file) |

Then choose **Create repository**.

## 2. Add the topics

On the repository page, select the gear icon next to **About**, then add:

`data-analytics`, `artificial-intelligence`, `ai`, `data-science`, `data-visualisation`, `data-analysis`, `business-intelligence`, `anomaly-detection`, `pandas`, `duckdb`, `python`, `fastapi`, `react`, `typescript`, `analytics-dashboard`

`polars` was left out of your suggested list, because the project doesn't use Polars.

## 3. Connect your local project and make the first commit

Open a terminal in the project folder (in VS Code, **Terminal > New Terminal**). Replace `<your-username>` with your GitHub username.

```bash
git init -b main
```

If Git hasn't been configured on this computer, set your name and email first. GitHub shows these publicly on your commits.

```bash
git config user.name "<your name>"
```

```bash
git config user.email "<your email>"
```

Stage everything, then check the list **before** committing:

```bash
git add .
```

```bash
git status
```

The list must **not** include `.env`, `data/`, `.venv/`, `node_modules/`, or `frontend/dist/`. If any appear, stop and investigate.

```bash
git commit -m "Initial commit: DataForge AI v0.9.0"
```

```bash
git remote add origin https://github.com/<your-username>/dataforge-ai-analytics-platform.git
```

## 4. Push the project

```bash
git push -u origin main
```

GitHub may ask you to sign in through your browser.

## 5. Verify the publication

- The README displays with its screenshots, Mermaid diagram, and tables.
- `.env`, `data`, `.venv`, and `node_modules` aren't in the file list.
- `.env.example` shows placeholders only.
- The **Actions** tab shows the CI workflow. This workflow hasn't run before, so watch the first run. If it fails, the log will show why.
- In **Settings > Code security**, turn on **Private vulnerability reporting** (SECURITY.md refers to it), **Secret scanning**, and **Dependabot alerts**.

## 6. Create the pre-release (optional)

```bash
git tag -a v0.9.0 -m "DataForge AI v0.9.0"
```

```bash
git push origin v0.9.0
```

Then go to **Releases > Draft a new release**, choose `v0.9.0`, paste the title and description from [RELEASE_NOTES_v0.9.0.md](RELEASE_NOTES_v0.9.0.md), tick **Set as a pre-release**, and publish.

## Later updates

```bash
git add .
```

```bash
git commit -m "Describe your change"
```

```bash
git push
```

## If a secret is ever committed

Treat it as exposed, even if the repository is private. **Revoke and replace the secret first** at its provider. Removing it from the files isn't enough, because it stays in the Git history. After rotating it, you can clean the history with `git filter-repo`.
