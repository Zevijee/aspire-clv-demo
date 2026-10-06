"""Open every report in a headless browser and say what is broken.

    python tools/site_audit.py                  # every report and tab
    python tools/site_audit.py --only /mds      # reports whose path starts with /mds
    python tools/site_audit.py --show           # watch it run in a real window

From Git Bash, prefix --only runs with MSYS_NO_PATHCONV=1, or Bash rewrites
"/mds" into a Windows path and nothing matches.

Needs the API and the Vite dev server running, and Playwright:
    python -m pip install playwright && python -m playwright install chromium

It signs in through the page's own form as admin, with ADMIN_PASSWORD from the
root .env, so it sees exactly what a person does. Then for each report in the
navigation -- read from the features' reports.ts, so new reports are included --
and each of its tabs, it waits for loading to finish and records:

- JavaScript errors and console errors (a crash, a module that failed to load)
- API requests that failed or returned 4xx/5xx
- error panels the page shows (role="alert")
- a page that rendered nothing at all

A screenshot of every view goes to the --out folder. Exit code 1 if anything
was found, so it can gate a script.
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def report_paths():
    """Report paths in navigation order, from each feature's reports.ts."""
    paths = []
    for feature in ('adt', 'census', 'mds'):
        source = (ROOT / 'frontend' / 'src' / 'features' / feature / 'reports.ts').read_text(encoding='utf-8')
        paths += re.findall(r"path:\s*'([^']+)'", source)
    return paths


def admin_password():
    password = os.getenv('ADMIN_PASSWORD')
    if not password and (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
            if line.startswith('ADMIN_PASSWORD='):
                password = line.split('=', 1)[1].strip().strip('"\'')
    if not password:
        sys.exit('Set ADMIN_PASSWORD in the root .env or the environment.')
    return password


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # localhost, not 127.0.0.1: the Vite dev server listens on IPv6 [::1] only.
    parser.add_argument('--base', default='http://localhost:5173', help='Frontend address.')
    parser.add_argument('--only', default='', help='Audit only report paths starting with this.')
    parser.add_argument('--out', default=str(Path(tempfile.gettempdir()) / 'clearview-audit'),
        help='Folder for screenshots.')
    parser.add_argument('--show', action='store_true', help='Open a visible browser window.')
    parser.add_argument('--timeout', type=int, default=30, help='Seconds to wait for a view to finish loading.')
    args = parser.parse_args()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright
    except ImportError:
        sys.exit('Install Playwright: python -m pip install playwright && python -m playwright install chromium')

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = [path for path in report_paths() if path.startswith(args.only)]
    findings = {}  # view label -> list of problems

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.show)
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        current = {'problems': None}

        def note(message):
            if current['problems'] is not None and message not in current['problems']:
                current['problems'].append(message)

        page.on('pageerror', lambda error: note(f'JavaScript error: {error}'))
        page.on('console', lambda message: message.type == 'error' and note(f'Console error: {message.text[:300]}'))
        # ERR_ABORTED is the page cancelling its own request -- on reload,
        # navigation, or React's development double-run of effects -- not a failure.
        page.on('requestfailed', lambda request: '/api/' in request.url
            and 'ERR_ABORTED' not in (request.failure or '')
            and note(f'Request failed: {request.method} {request.url.split("/api/", 1)[1][:120]} '
                f'({request.failure})'))
        page.on('response', lambda response: '/api/' in response.url and response.status >= 400
            and note(f'API {response.status}: {response.request.method} {response.url.split("/api/", 1)[1][:140]}'))

        # Sign in through the form, as a person would.
        try:
            page.goto(args.base, wait_until='domcontentloaded')
        except Exception as error:  # Playwright raises its own Error for a refused connection.
            sys.exit(f'Could not open {args.base} ({str(error).splitlines()[0]}). Is the dev server running '
                '(npm --prefix frontend run dev)?')
        username = page.locator('input[name="username"]')
        try:
            username.wait_for(timeout=5000)
            username.fill('admin')
            page.locator('input[name="password"]').fill(admin_password())
            page.locator('button[type="submit"]').click()
            username.wait_for(state='detached', timeout=15000)
        except PlaywrightTimeout:
            if username.count():
                sys.exit('Sign-in did not complete: check ADMIN_PASSWORD and that the API is running.')

        def settle():
            """Wait until no loading spinner is left, then a moment for late errors."""
            try:
                page.wait_for_function("!document.querySelector('.data-state__spinner')",
                    timeout=args.timeout * 1000)
            except PlaywrightTimeout:
                note(f'Still loading after {args.timeout} s')
            page.wait_for_timeout(500)

        def inspect(label):
            for alert in page.locator('[role="alert"]').all():
                text = alert.inner_text().strip()
                if text:
                    note(f'Error shown on page: {text[:200]}')
            main = page.locator('main, .main-panel').first
            if not main.count() or len(main.inner_text().strip()) < 20:
                note('Page rendered nothing (likely a crash)')
            # Content wider than the report area: the panel clips it, so header
            # controls, scrollbars or text end up off-screen without any error.
            overflow = page.evaluate("""() => {
                const area = document.querySelector('.report-content')
                return area ? area.scrollWidth - area.clientWidth : 0
            }""")
            if overflow > 2:
                note(f'Content is {overflow}px wider than the page: something is pushed off-screen')
            name = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')
            page.screenshot(path=str(out / f'{name}.png'))

        for path in paths:
            label = path
            current['problems'] = findings.setdefault(label, [])
            page.goto(args.base + path, wait_until='domcontentloaded')
            settle()
            inspect(label)
            # Every other tab of this report, by its visible name.
            tabs = page.locator('.report-tabs button, .report-tabs a, .report-tabs [role="tab"]')
            names = [tab.inner_text().strip() for tab in tabs.all()]
            for name in names[1:]:
                label = f'{path} > {name}'
                current['problems'] = findings.setdefault(label, [])
                page.locator('.report-tabs').get_by_text(name, exact=True).first.click()
                settle()
                inspect(label)
            print(f'  checked {path}' + (f' ({len(names)} tabs)' if len(names) > 1 else ''), flush=True)
        browser.close()

    broken = {label: problems for label, problems in findings.items() if problems}
    print(f'\n{len(findings)} views checked, {len(broken)} with problems. Screenshots: {out}\n')
    for label, problems in broken.items():
        print(label)
        for problem in problems:
            print(f'  - {problem}')
    return 1 if broken else 0


if __name__ == '__main__':
    raise SystemExit(main())
