# Encoding Baseline

This repository should use `UTF-8` consistently.

## Rules

- Source files, templates, scripts, docs, JSON, CSS, and JS should be saved as `UTF-8`.
- Text files should use `LF` line endings by default.
- Windows shell scripts such as `*.bat` and `*.ps1` may use `CRLF`.
- Python code that reads or writes text files should explicitly set `encoding="utf-8"` whenever practical.

## Repository Guards

- [`.gitattributes`](/E:/JianYingApi/VideoFactory/.gitattributes) forces UTF-8 working-tree encoding for key file types.
- [`.editorconfig`](/E:/JianYingApi/VideoFactory/.editorconfig) keeps editors aligned on charset, line endings, and whitespace.
- [`scripts/check_encoding.py`](/E:/JianYingApi/VideoFactory/scripts/check_encoding.py) can be used as a lightweight scan for suspicious mojibake characters.

## Recommended Checks

Run a focused scan on active user-facing pages:

```powershell
venv\Scripts\python.exe scripts\check_encoding.py app\templates\user app\views
```

Run a broader scan on the front-end and docs:

```powershell
venv\Scripts\python.exe scripts\check_encoding.py frontend docs
```

Run a broader Windows-friendly scan with UTF-8 console output:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_encoding_all.ps1
```

## Notes

- A terminal can still display garbled Chinese even when the file itself is valid UTF-8.
- On Windows, prefer running the PowerShell helper script above before judging whether a file is actually broken.
- Fix active files first. Do not attempt a whole-repo encoding rewrite in one pass.
