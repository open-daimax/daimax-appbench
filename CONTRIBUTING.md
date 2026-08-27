# Contributing to daimax-appbench

Thank you for your interest in contributing to **daimax-appbench**! We welcome
contributions of all kinds — bug reports, feature requests, documentation
improvements, and code. This guide will help you get started and make the
contribution process smooth for everyone.

## How to Contribute

We follow a standard GitHub workflow:

1. **Open an Issue** — Before starting significant work, please
   [open an issue](../../issues) to describe the bug you found or the feature
   you would like to add. This lets us discuss the approach and avoid
   duplicated effort.
2. **Fork the repository** — Create your own fork of the project.
3. **Create a branch** — Base your work on `main` and use a descriptive branch
   name, e.g. `fix/scoring-edge-case` or `feat/new-metric`.
4. **Make your changes** — Keep commits focused and write clear commit messages.
5. **Open a Pull Request** — Push your branch to your fork and open a PR against
   the upstream `main` branch. Reference the related issue in the PR
   description.

## Development Setup

Clone your fork and install the project in editable mode with development
dependencies:

```bash
pip install -e ".[dev]"
```

This installs the package along with the tools needed for testing and linting.

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) for all Python code.
- **Type hints are required** for all function signatures and public
  interfaces.
- Public APIs must include **docstrings written in English** that describe the
  purpose, parameters, and return values.
- Keep functions small and focused; prefer readability over cleverness.

## Testing

- **All new features must include tests.** Bug fixes should include a
  regression test that fails before the fix and passes after.
- Run the full test suite before submitting your changes:

  ```bash
  pytest
  ```

- Ensure all tests pass locally. PRs with failing tests will not be merged.

## Pull Request Guidelines

- Use a **descriptive title** that summarizes the change.
- **Link to the related issue** (e.g. `Closes #123`) in the description.
- Prefer **small, focused changes** — large PRs are harder to review and slower
  to merge. Split unrelated changes into separate PRs.
- Update documentation when your change affects user-facing behavior.
- Make sure your branch is up to date with `main` before requesting review.

## Code of Conduct

We are committed to providing a welcoming and respectful environment for
everyone. Please communicate constructively, assume good intent, and treat all
contributors with courtesy. Harassment or disrespectful behavior of any kind
will not be tolerated.

Thank you for helping make daimax-appbench better!
