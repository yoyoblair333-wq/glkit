"""Tests for glkit.bundle, glkit.chain and glkit.evidence (no network)."""

import json
import os
from pathlib import Path

import pytest

from glkit import bundle as B
from glkit import chain as C
from glkit import evidence as E

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples" / "quote_check" / "quote_check.src.py"
BUILT = ROOT / "examples" / "quote_check" / "quote_check.py"
FIX = ROOT / "tests" / "fixtures"


class TestBundle:
    def test_committed_bundle_is_up_to_date(self, tmp_path):
        out = tmp_path / "qc.py"
        B.bundle_file(str(SRC), str(out))
        assert out.read_text() == BUILT.read_text(), "run: python -m glkit bundle examples/quote_check/quote_check.src.py examples/quote_check/quote_check.py"

    def test_bundle_inlines_block_with_digest_banner_and_is_idempotent(self):
        once = B.bundle_source(SRC.read_text())
        assert "# glkit:include" not in once
        assert "# ===== glkit.proof (inlined by glkit bundle, sha256:" in once
        assert "def quote_on_page(" in once
        assert B.bundle_source(once) == once

    def test_header_line_is_preserved_first(self):
        assert BUILT.read_text().startswith('# { "Depends": "py-genlayer:')

    def test_unknown_module_and_double_include_rejected(self):
        with pytest.raises(B.BundleError):
            B.bundle_source("# glkit:include nope\n")
        with pytest.raises(B.BundleError):
            B.bundle_source("# glkit:include proof\n# glkit:include proof\n")

    def test_file_without_genvm_header_rejected(self, tmp_path):
        p = tmp_path / "x.py"
        p.write_text("print(1)\n# glkit:include proof\n")
        with pytest.raises(B.BundleError):
            B.bundle_file(str(p), str(tmp_path / "y.py"))


class TestChain:
    def test_clamp_timeunits_into_network_bounds(self):
        out = C.clamp_timeunits({"leaderTimeunitsAllocation": 1500, "validatorTimeunitsAllocation": 5, "x": 1})
        assert out == {"leaderTimeunitsAllocation": 600, "validatorTimeunitsAllocation": 30, "x": 1}
        assert C.clamp_timeunits(None) is None

    @pytest.mark.parametrize("msg,needle", [
        ("Transaction reverted: EVM tx 0xab to consensus contract 0xcd was reverted. FeesDistributionMissing", "fees_for"),
        ("Transaction reverted: EVM tx 0xab to consensus contract 0xcd was reverted. PhaseTimeoutOutOfBounds(1500,30,600)",
         "PhaseTimeoutOutOfBounds(1500,30,600)"),
        ("Transaction failed", "Upgrade genlayer-py"),
    ])
    def test_explain_send_error(self, msg, needle):
        assert needle in C.explain_send_error(Exception(msg))

    def test_send_does_not_retry_fee_errors(self):
        calls = []

        def fn():
            calls.append(1)
            raise Exception("was reverted. FeesDistributionMissing")
        with pytest.raises(RuntimeError, match="fees_for"):
            C.send(fn, attempts=4, delay_s=0, log=lambda *_: None)
        assert len(calls) == 1

    def test_send_retries_transient_then_succeeds(self):
        n = {"i": 0}

        def fn():
            n["i"] += 1
            if n["i"] < 3:
                raise Exception("connection reset")
            return bytes.fromhex("ab" * 32)
        assert C.send(fn, attempts=4, delay_s=0, log=lambda *_: None) == "0x" + "ab" * 32

    def test_summarize_new_fee_aware_shape(self):
        t = json.load(open(FIX / "tx_fee_aware.json"))
        s = C.summarize(t)
        assert s["status"] == "finalized/accepted" and s["result"] == "MAJORITY_AGREE"
        assert s["execution"] == "SUCCESS" and s["votes"].count("agree") == 4
        assert s["fee_paid_wei"] == "100000000000010352"
        assert C.contract_address(t) == "0xb3F7417f8A828f2416427D7760f47C41e2F6d1B7"

    def test_summarize_old_shape_and_tagged_error(self):
        t = {"status_name": "ACCEPTED", "result_name": "MAJORITY_AGREE",
             "consensus_data": {"votes": {"a": "agree"}, "leader_receipt": [{"execution_result": "ERROR",
              "result": "[EXPECTED] already final"}]}}
        s = C.summarize(t)
        assert s["status"] == "ACCEPTED" and s["error"] == "[EXPECTED] already final"


class TestEvidence:
    def test_render_has_tables_links_and_reads(self):
        run = json.load(open(FIX / "run_small.json"))
        md = E.render(run, title="Live evidence: demo")
        assert md.startswith("# Live evidence: demo")
        assert "| deploy | [`0xb3F7417f8A828f2416427D7760f47C41e2F6d1B7`]" in md
        assert "https://explorer-studio.genlayer.com/tx/0x" in md
        assert "agree 4, idle 1" in md
        assert "### check_1" in md and "FOUND" in md

    def test_pipes_in_values_cannot_break_the_table(self):
        run = {"steps": [{"step": "a|b", "tx": "0x1", "status": "x|y"}]}
        md = E.render(run)
        assert "a\\|b" in md and "x\\|y" in md
