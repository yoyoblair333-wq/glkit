"""Direct-mode tests for the bundled example contract (real GenVM SDK, web mocked)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = str(ROOT / "examples" / "quote_check" / "quote_check.py")
URL = "https://rules.example.org/payouts"
PAGE = ("<html><head><script>var tracking=1</script></head><body><h1>Payout rules</h1>"
        "<div hidden><p>Payouts are processed within 14 calendar days of a valid request.</p></div>"
        + "<p>General terms and background.</p>" * 40 + "</body></html>")


def page(vm, body=PAGE, status=200, ctype="text/html; charset=utf-8", url=URL):
    vm.mock_web("^" + url.replace(".", r"\.") + "$", {"method": "GET", "response": {
        "status": status, "headers": {"content-type": ctype.encode()}, "body": body.encode()}})


@pytest.fixture
def qc(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    return direct_deploy(CONTRACT)


def test_found_in_collapsed_section_and_stored(qc, direct_vm):
    page(direct_vm)
    r = qc.check(URL, "processed within 14 calendar days")
    assert r["status"] == "FOUND" and r["page_size"] == "medium" and r["id"] == 1
    assert qc.get_check(1)["quote"] == "processed within 14 calendar days" and qc.count() == 1


def test_invented_quote_is_not_found(qc, direct_vm):
    page(direct_vm)
    assert qc.check(URL, "processed within 3 calendar days")["status"] == "NOT_FOUND"


def test_script_text_does_not_count_as_page_text(qc, direct_vm):
    page(direct_vm)
    assert qc.check(URL, "var tracking=1 payout")["status"] == "NOT_FOUND"


def test_unreadable_page(qc, direct_vm):
    page(direct_vm, status=404)
    assert qc.check(URL, "processed within 14 calendar days")["status"] == "UNREADABLE"


@pytest.mark.parametrize("url", ["http://rules.example.org/", "https://127.0.0.1/", "https://u:p@rules.example.org/"])
def test_bad_urls_rejected_before_any_fetch(qc, direct_vm, url):
    with direct_vm.expect_revert("[EXPECTED]"):
        qc.check(url, "processed within 14 calendar days")


def test_quote_length_bounds(qc, direct_vm):
    with direct_vm.expect_revert("quote must be"):
        qc.check(URL, "too short")


def test_validator_agrees_when_it_reads_the_same_page(qc, direct_vm):
    page(direct_vm)
    qc.check(URL, "processed within 14 calendar days")
    assert direct_vm.run_validator() is True


def test_validator_disagrees_when_its_page_says_otherwise(qc, direct_vm):
    page(direct_vm)
    qc.check(URL, "processed within 14 calendar days")
    direct_vm.clear_mocks()
    page(direct_vm, body=PAGE.replace("14 calendar days", "30 calendar days"))
    assert direct_vm.run_validator() is False
