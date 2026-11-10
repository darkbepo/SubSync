# Parked: GitHub community files (on hold, waiting for the owner's go-ahead)

Drafted for GitHub's "community standards" checklist. The owner reviewed them and chose to **wait**. Don't add them until the owner says so. `CONTRIBUTING.md` was explicitly declined. A code of conduct was not recommended, because the standard templates require publishing a contact email.

When approved:

1. Set the repository **description, topics and website** (repository settings, or `PATCH /repos/{owner}/{repo}` and `PUT /repos/{owner}/{repo}/topics`).
2. Add the three issue-template files and `SECURITY.md` below, in one commit.
3. Ask the owner to enable **Settings → Security → Private vulnerability reporting**; the security links depend on it.

## 1. Description, topics, website

- Description: `Line-by-line subtitle sync from the video's own audio. Drag-and-drop Windows app + CLI, GPU-accelerated, for whole seasons.`
- Topics: `subtitles` `subtitle-sync` `srt` `whisper` `speech-recognition` `windows` `jellyfin` `plex`
- Website: `https://github.com/darkbepo/SubSync/releases/latest`

## 2. `.github/ISSUE_TEMPLATE/bug_report.yml`

```yaml
name: Bug report
description: Something doesn't work or a subtitle came out wrong
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for reporting! The log files in SubSync's `logs` folder are usually what's needed to find the cause.
  - type: input
    id: version
    attributes:
      label: SubSync version
      description: Run `subsync-cli version`, or see the release you downloaded.
      placeholder: "1.1.0"
    validations:
      required: true
  - type: dropdown
    id: frontend
    attributes:
      label: Which part?
      options:
        - The window (SubSync.exe)
        - The command line (subsync-cli.exe)
        - First-time setup / repair
    validations:
      required: true
  - type: input
    id: windows
    attributes:
      label: Windows version
      placeholder: "Windows 11 24H2"
  - type: input
    id: gpu
    attributes:
      label: Graphics card
      description: Shown in the top-right corner of SubSync's window.
      placeholder: "NVIDIA GeForce RTX 3050 / no NVIDIA card"
  - type: textarea
    id: what
    attributes:
      label: What happened?
      description: Include any error message, and what you expected instead.
    validations:
      required: true
  - type: textarea
    id: files
    attributes:
      label: About the video and subtitle (if it's a sync problem)
      description: |
        Video type (mkv/mp4…), audio language, subtitle format, and roughly where it goes wrong
        (e.g. "fine until 22:00, then 3 s late"). Hovering over the result in SubSync shows the details.
        Please don't attach videos or full subtitle files.
  - type: textarea
    id: logs
    attributes:
      label: Logs
      description: |
        From the `logs` folder next to SubSync.exe: `app.log`, `worker.log`, `setup.log` and/or `cli.log`
        (the last part is usually enough). Logs contain file and folder paths, so replace anything you consider private.
      render: text
  - type: checkboxes
    id: privacy
    attributes:
      label: Privacy
      options:
        - label: I checked the logs above for personal information (names in folder paths, etc.)
          required: true
```

## 3. `.github/ISSUE_TEMPLATE/feature_request.yml`

```yaml
name: Feature request
description: Suggest an idea or improvement
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: What would you like SubSync to do?
      description: Describe the situation or problem first, then your idea.
    validations:
      required: true
  - type: textarea
    id: example
    attributes:
      label: Example
      description: A concrete case where this would help (file types, languages, workflow…).
```

## 4. `.github/ISSUE_TEMPLATE/config.yml`

```yaml
blank_issues_enabled: false
contact_links:
  - name: Report a security problem privately
    url: https://github.com/darkbepo/SubSync/security/advisories/new
    about: Please don't report security issues as public issues.
```

## 5. `SECURITY.md`

```markdown
# Security policy

## Supported versions

Only the [latest release](https://github.com/darkbepo/SubSync/releases/latest) receives fixes.

## Reporting a problem

Please **don't** open a public issue for security problems.
Report them privately through GitHub instead:
**[Report a vulnerability](https://github.com/darkbepo/SubSync/security/advisories/new)**

Helpful details: what the problem is, how to reproduce it, which version, and what an attacker could do with it.

SubSync is maintained in spare time, so there is no fixed response time, but every report will be read
and confirmed fixes will be published as a new release with a note in the release description.

## What's especially relevant

SubSync downloads and runs software during setup and repair, so these areas matter most:

- **Downloads:** Python packages and NVIDIA libraries are checked against SHA-256 hashes fixed at build time;
  AI models are pinned to an exact revision and hash on first install; Python itself is fetched over HTTPS.
- **`sources.json`:** lets a user add their own download locations; package and model files are still hash-checked.
- **Process handling:** everything SubSync starts runs inside a Windows job object and is ended when SubSync closes.

Everything else runs locally; videos and subtitles never leave your computer.
```
