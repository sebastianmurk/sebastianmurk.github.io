from pathlib import Path
import os

OUTPUT_DIR = Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR", "docs"))
SITE = "https://sebastianmurk.com"
PAGES = ("research", "publications", "news", "talks", "travels", "photos")


def clean_text(text: str) -> str:
    """Replace /index.html URL variants with clean trailing-slash URLs."""

    # Absolute homepage URL
    text = text.replace(f"{SITE}/index.html", f"{SITE}/")

    # Homepage links
    text = text.replace('href="/index.html"', 'href="/"')
    text = text.replace('href="index.html"', 'href="/"')
    text = text.replace('href="../index.html"', 'href="/"')

    # Section URLs
    for page in PAGES:
        text = text.replace(f"{SITE}/{page}/index.html", f"{SITE}/{page}/")

        text = text.replace(
            f'href="/{page}/index.html"',
            f'href="/{page}/"',
        )
        text = text.replace(
            f'href="{page}/index.html"',
            f'href="/{page}/"',
        )
        text = text.replace(
            f'href="../{page}/index.html"',
            f'href="/{page}/"',
        )

        # Catches redirect files and other generated references.
        text = text.replace(
            f"{page}/index.html",
            f"{page}/",
        )

    return text


def main() -> None:
    if not OUTPUT_DIR.exists():
        raise SystemExit(f"Output directory not found: {OUTPUT_DIR}")

    files_to_clean = []

    sitemap = OUTPUT_DIR / "sitemap.xml"
    if sitemap.exists():
        files_to_clean.append(sitemap)

    files_to_clean.extend(OUTPUT_DIR.rglob("*.html"))

    changed = []

    for path in files_to_clean:
        text = path.read_text(encoding="utf-8")
        updated = clean_text(text)

        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)

    if changed:
        for path in changed:
            print(f"Cleaned URLs in {path}")
    else:
        print("No URL cleanup changes needed.")


if __name__ == "__main__":
    main()
