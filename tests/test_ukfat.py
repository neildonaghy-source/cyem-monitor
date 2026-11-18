"""UKFAT parsing must free each page as it goes: kept, pdfplumber's page caches took the 2026 PDF to 1.3 GB, past the
container's 1 GB, and the app was killed and restarted in a loop (18 Nov 2026). With page.close() the peak was 52 MB."""
import sys
import types
from pathlib import Path


class _Page:
    def __init__(self, n, log):
        self.n, self.log = n, log

    def extract_tables(self):
        self.log.append(("used", self.n))
        if self.n == 14:
            return [[["Frequency band", "Allocation", "PR/SE", "Footnotes"], ["100 – 200 kHz", "FIXED", "PR", "UK1"]]]
        return []

    def extract_text(self):
        self.log.append(("used", self.n))
        return "SOMETHING  Something here\n300 – 400 kHz MOBILE PR UK2" if self.n == 15 else ""

    def close(self):
        self.log.append(("closed", self.n))


class _Pdf:
    def __init__(self, log):
        self.pages = [_Page(n, log) for n in range(1, 21)]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_every_page_used_is_closed(monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=lambda p: _Pdf(log)))
    from app.ukfat import parse_pdf
    data = parse_pdf(Path("unused.pdf"))
    used = {n for what, n in log if what == "used"}
    closed = {n for what, n in log if what == "closed"}
    assert used and used <= closed                       # nothing left holding its layout cache
    assert [e["band"] for e in data["entries"]] == ["100 – 200 kHz", "300 – 400 kHz"]   # parsing itself unchanged
