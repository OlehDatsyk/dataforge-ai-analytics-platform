# Contributing

Thanks for your interest in DataForge AI. Before you begin, read [INSTRUCTION.md](INSTRUCTION.md), especially **Rules that must stay true**.

## Workflow

1. **Fork** the repository on GitHub and clone your fork.
2. **Set up** with `setup.bat`, or `./setup.command` on macOS and Linux, then install the test tools:

   ```bash
   .venv\Scripts\python -m pip install -r backend\requirements-dev.txt
   ```

3. **Create a branch** from `main`, with a descriptive name:

   ```bash
   git checkout -b fix/date-inference-for-short-years
   ```

4. **Make your change,** with tests. Changes to calculations need a test comparing against an independent calculation.
5. **Run the checks:**

   ```bash
   cd backend && ..\.venv\Scripts\python -m ruff check app scripts tests && ..\.venv\Scripts\python -m pytest
   ```

   ```bash
   cd frontend && npm run build && npm test && npx playwright test
   ```

6. **Update the documentation** if behaviour changes, and add a line to [CHANGELOG.md](CHANGELOG.md).
7. **Open a pull request** that explains what changed and why, and how you tested it.

## Expectations

- Keep pull requests focused on one change.
- Don't commit secrets, real business data, `.env` files, or generated data. Sample datasets must be synthetic.
- Report what you tested honestly, including anything you couldn't test.
- Discuss large changes in an issue first.

## Reporting problems

Open an issue with steps to reproduce, what you expected, and what happened, along with your operating system and versions. Don't attach private data. Report security problems privately, as described in [SECURITY.md](SECURITY.md).
