# Keep Mancebo Voice Studio current

The **VoiceStudio upstream drift** action compares this fork's `main` with
`debpalash/VoiceStudio:main` every Monday. It can also run on demand from
**Actions**. A failed comparison with a commit count means upstream changes
are waiting for review. The run summary links to the exact upstream diff.

## Prepare a sync pull request

Fetch both histories in a clean, full clone. Start from the current Mancebo
branch and merge upstream into a review branch.

```bash
git fetch --no-tags origin main
git fetch --no-tags https://github.com/debpalash/VoiceStudio.git main
upstream=$(git rev-parse FETCH_HEAD)
git rev-list --left-right --count origin/main..."$upstream"
git switch -c sync/voicestudio-YYYY-MM-DD origin/main
git merge --no-ff "$upstream"
```

Review the net changes against `origin/main`, including files Git merged
cleanly. Preserve Mancebo branding, sign-in and workspace boundaries, the
managed API and MCP contracts, licensed model choices, and the fork's dubbing
and deployment behavior. Review changes to publishing workflows, external
endpoints and dependency locks. Resolve conflicts by combining compatible
behavior. Keep the fork's behavior where an upstream change would break a
Mancebo contract, and record that decision in the pull request.

Open the pull request against `jvelezc/mancebo.voicestudio:main`. Record the
upstream commit, the conflict resolutions, and the checks used to verify the
affected Mancebo behavior. Follow the review and CI gates in
[`AGENTS.md`](../AGENTS.md). Use GitHub's **Create a merge commit** option so
both histories remain visible and the weekly check recognizes the sync.
Feature pull requests can then merge the refreshed fork `main` and rerun
their checks. Releases follow the Mancebo deployment process.
