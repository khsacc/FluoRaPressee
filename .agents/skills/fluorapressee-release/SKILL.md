---
name: fluorapressee-release
description: Build and release the khsacc/FluoRaPressee Windows installer via GitHub Actions. Use for beta and stable releases, release tags, draft review and publication, and build retries.
---

# FluoRaPressée releases

Verify the checkout root and confirm that the `origin` fetch and push URLs target `khsacc/FluoRaPressee`. Then read the root `AGENTS.md` and `.github/workflows/release.yml`. On macOS, leave app runs and repository tests to Windows CI.

## Choose the commit and version

| Release | Tag target | Example |
| --- | --- | --- |
| Dev prerelease | `origin/__dev` unless the user names another dev branch | `0.1.0b1` → `v0.1.0b1` |
| Stable release | `origin/master` after the release PR is merged and the intended changes are present | `0.1.0` → `v0.1.0` |

1. Fetch `origin` and identify the target commit SHA.
2. Inspect `src/version.py` and `.github/workflows/release.yml` at that SHA with `git show`. Prefix the exact `__version__` value with `v` to form the tag. CI uses PEP 440 to determine prerelease status. If the version or release type differs from the request, land a version fix on the target branch first. For stable releases, use the normal PR workflow and wait for the merge before tagging.
3. Check for the tag locally and on GitHub. For annotated tags, compare the commit each tag points to. Reuse a tag on the same SHA and check its build and release status if it already exists on GitHub. For a different SHA, see [Recovery](#recovery).

## Start the build

- For a tag push or build request, create the annotated tag if needed with `git tag -a "$tag" "$release_commit" -m "FluoRaPressée $version"`. Push only that tag with `git push origin "refs/tags/$tag"`. Only a tag push triggers this release workflow.
- Confirm that GitHub Actions started **Release build** for the tag and SHA. Use `gh run list --repo khsacc/FluoRaPressee --workflow release.yml --branch "$tag" --event push` or the public GitHub REST API if `gh` is unauthenticated.
- For a routine release request, stop once the run starts. Report the version, commit SHA, run URL, current status, and the steps below. Monitor to completion only if explicitly requested.
- A successful Windows CI run tests the app, builds the installer, and creates a draft with `FluoRaPressee-Setup-<version>.exe`. Report build success, draft creation, or publication only after verifying each.

## After a successful build

Share these steps as follow-up. If the user asks to edit or publish the draft after CI, perform the requested steps.

1. Confirm success at the run URL and open the draft for the tag in GitHub Releases. If CI failed, review the logs and see [Recovery](#recovery).
2. Verify the tag, prerelease flag, and `FluoRaPressee-Setup-<version>.exe` attachment.
3. Replace the placeholder under **Changes / 変更点** with the actual release notes and verify the installer on a physical Windows machine.
4. Publish with **Publish release** on GitHub or authenticated `gh release edit "$tag" --repo khsacc/FluoRaPressee --draft=false`. Verify the release URL and installer attachment.

## Recovery

- Retry a transient build failure if no source fix is needed. The rerun uses the original commit.
- An unpublished beta can reuse its version after a fix. Check the existing draft and tag before acting. Delete an old draft or move a tag only if the user explicitly requests that action. After moving a tag, confirm CI runs for the new SHA.
- For fixes to a published release, use a newer version (for example, `0.1.0b1` → `0.1.0b2`) and preserve published tags, including stable tags from `master`.
