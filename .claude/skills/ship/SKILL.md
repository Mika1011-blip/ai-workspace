\---

name: ship

description: Branch, test, commit, push and open a pull request for the current changes.

disable-model-invocation: true

allowed-tools: Bash(git:\*), Bash(gh pr:\*), Bash(pytest:\*)

\---

Ship the current changes as a pull request. Extra notes from me: $ARGUMENTS



1\. Run `git status`. If there are no changes, say so and stop.

2\. If on `main`, create a branch named `feat/<short-topic>` or `fix/<short-topic>` based on the changes.

3\. Run `pytest`. If anything fails, stop and show me the failures. Do not commit.

4\. Stage the changes and commit with a short message: what changed and why. Never commit `.env` files.

5\. Push with `git push -u origin <branch>`.

6\. Open the PR with `gh pr create`: a title, then a body with "What", "Why" and "How I tested".

7\. Reply with the PR link and a two-line summary.

