"""The PO-1 real-browser gate. Each test is independently runnable."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.browser.fake_ollama import FakeOllama
from tests.browser.harness import live_application, operation_rows

pytestmark = pytest.mark.real_browser

OBJECTIVE = os.environ.get("QA_OBJECTIVE", "Investigate the deterministic browser scenario.")
DECLINE_GUIDANCE = os.environ.get("QA_DECLINE_GUIDANCE", "Use a relationship-focused direction.")

_TRACK_RUNNING_REFRESH_INTERVAL = """
(() => {
    const nativeSetInterval = window.setInterval.bind(window);
    const nativeClearInterval = window.clearInterval.bind(window);
    const active = new Set();
    window.__qaRunningRefreshIntervals = {active, created: 0, cleared: 0};
    window.setInterval = (callback, delay, ...args) => {
        const timer = nativeSetInterval(callback, delay, ...args);
        if (String(callback).includes("refresh_nonce")) {
            active.add(timer);
            window.__qaRunningRefreshIntervals.created += 1;
        }
        return timer;
    };
    window.clearInterval = (timer) => {
        if (active.delete(timer)) {
            window.__qaRunningRefreshIntervals.cleared += 1;
        }
        return nativeClearInterval(timer);
    };
})();
"""


def _open_new(page: Page, url: str, objective: str = OBJECTIVE) -> None:
    page.goto(url)
    page.get_by_role("button", name="New investigation").click()
    page.get_by_label("Investigation objective").fill(objective)
    page.get_by_role("button", name="Start investigation").click()


def _needs_review(page: Page) -> None:
    expect(page.get_by_role("heading", name="Proposed next analytical action")).to_be_visible(timeout=15_000)


def _initial_proposal(page: Page, app, fake: FakeOllama) -> None:
    _open_new(page, app.url)
    expect(page.get_by_role("heading", name="Preparing investigation approach")).to_be_visible()
    _needs_review(page)
    assert len(fake.generation_calls) == 1


def test_start_completion_refresh_after_back_and_resume(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    try:
        with live_application(evidence_root, "start-back-resume", fake.base_url) as app:
            _initial_proposal(page, app, fake)
            page.get_by_role("button", name="Back to Investigations").click()
            page.get_by_role("button", name="Resume").click()
            _needs_review(page)
            app.evidence.step("resume completed START", "Needs Review without restart", page.locator("body").inner_text())
            app.evidence.snapshot(page, "completed-start-after-resume")
            assert len(fake.generation_calls) == 1
    finally:
        fake.close()


def test_decline_completion_refresh_after_back_and_resume(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    try:
        with live_application(evidence_root, "decline-back-resume", fake.base_url) as app:
            _initial_proposal(page, app, fake)
            guidance = page.get_by_label("Optional decline guidance")
            guidance.fill(DECLINE_GUIDANCE)
            guidance.press("Tab")
            expect(page.get_by_role("button", name="Adjust investigation plan")).to_be_visible()
            page.get_by_role("button", name="Adjust investigation plan").click()
            expect(page.get_by_role("heading", name="Adjusting investigation plan")).to_be_visible()
            _needs_review(page)
            page.get_by_role("button", name="Back to Investigations").click()
            page.get_by_role("button", name="Resume").click()
            _needs_review(page)
            expect(page.get_by_text(DECLINE_GUIDANCE, exact=False).first).to_be_visible()
            app.evidence.step("resume completed DECLINE", "replacement Needs Review", page.locator("body").inner_text())
            assert len(fake.generation_calls) == 2
    finally:
        fake.close()


def test_working_precedes_dispatch_and_refresh_is_safe(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    fake.hold()
    try:
        page.add_init_script(_TRACK_RUNNING_REFRESH_INTERVAL)
        with live_application(evidence_root, "working-refresh", fake.base_url) as app:
            _open_new(page, app.url)
            expect(page.get_by_role("heading", name="Preparing investigation approach")).to_be_visible()
            app.evidence.snapshot(page, "working-before-completion")
            assert fake.request_started.wait(timeout=10)
            assert len(fake.generation_calls) == 1
            page.reload()
            expect(page.get_by_text("Agent Working", exact=False)).to_be_visible()
            page.get_by_role("button", name="Resume").click()
            expect(page.get_by_role("heading", name="Preparing investigation approach")).to_be_visible()
            assert len(fake.generation_calls) == 1
            rows = operation_rows(app.database)
            assert rows[-1]["status"] == "RUNNING"
            page.wait_for_function(
                "() => (window.__qaRunningRefreshIntervals?.created || 0) > 0"
            )
            refresh_frame = page.main_frame
            refresh_state = refresh_frame.evaluate(
                "() => ({"
                "created: window.__qaRunningRefreshIntervals.created, "
                "active: window.__qaRunningRefreshIntervals.active.size"
                "})"
            )
            assert refresh_state["created"] >= 1
            assert refresh_state["active"] == 1
            app.evidence.step(
                "Working before held dispatch completes",
                "visible Working, one RUNNING dispatch, and one active refresh interval",
                {
                    "working_visible": True,
                    "calls": len(fake.generation_calls),
                    "status": rows[-1]["status"],
                    "refresh_interval": refresh_state,
                },
            )
            fake.release()
            _needs_review(page)
            assert len(fake.generation_calls) == 1
            refresh_frame.wait_for_function(
                "() => window.__qaRunningRefreshIntervals.active.size === 0"
            )
            cleaned_refresh_state = refresh_frame.evaluate(
                "() => ({"
                "created: window.__qaRunningRefreshIntervals.created, "
                "cleared: window.__qaRunningRefreshIntervals.cleared, "
                "active: window.__qaRunningRefreshIntervals.active.size"
                "})"
            )
            assert cleaned_refresh_state["cleared"] >= 1
            app.evidence.step(
                "RUNNING refresh and cleanup",
                "one dispatch, visible completion, and no active refresh interval",
                {
                    "status_before_completion": rows[-1]["status"],
                    "calls": len(fake.generation_calls),
                    "refresh_interval": cleaned_refresh_state,
                },
            )
    finally:
        fake.close()


def test_refresh_while_pending_preserves_operation(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    try:
        with live_application(evidence_root, "pending-refresh", fake.base_url) as app:
            from investigation.approval_loop import InvestigatorReadyApprovalLoopService
            from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG
            from investigation.persistence import SQLiteInvestigationStore
            with SQLiteInvestigationStore(app.database) as store:
                service = InvestigatorReadyApprovalLoopService(store, DEFAULT_LOCAL_CASE_CATALOG, object(), object())
                operation = service.prepare_start_investigation("development-case-42", OBJECTIVE)
            page.goto(app.url)
            expect(page.get_by_text("Agent Working", exact=False)).to_be_visible()
            page.reload()
            rows = operation_rows(app.database)
            assert [row["status"] for row in rows] == ["PENDING_RENDER"]
            assert len(fake.generation_calls) == 0
            page.get_by_role("button", name="Resume").click()
            _needs_review(page)
            assert len(fake.generation_calls) == 1
            app.evidence.step(
                "PENDING_RENDER refresh",
                "same pending operation, then one dispatch on Resume",
                {"operation_id": operation.operation_id, "status_before_resume": rows[0]["status"], "calls": 1},
            )
    finally:
        fake.close()


def test_transport_disconnect_is_not_persistence_failure(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    try:
        with live_application(
            evidence_root,
            "transport-disconnect",
            fake.base_url,
            inject_transport_oserror=True,
        ) as app:
            _open_new(page, app.url)
            expect(page.get_by_text("No new proposal was saved", exact=False)).to_be_visible(
                timeout=15_000
            )
            rows = operation_rows(app.database)
            assert rows[-1]["status"] == "FAILED"
            app.evidence.step("disconnect classification", "SERVICE_UNAVAILABLE", rows[-1]["failure_category"])
            assert rows[-1]["failure_category"] == "SERVICE_UNAVAILABLE"
            assert rows[-1]["failure_category"] != "PERSISTENCE_ERROR"
    finally:
        fake.close()


def test_interrupted_operation_requires_explicit_retry(page: Page, evidence_root: Path) -> None:
    fake = FakeOllama().start()
    try:
        with live_application(evidence_root, "interrupted-recovery", fake.base_url) as app:
            # Seed only the durable lifecycle prerequisite; the browser proves recovery presentation.
            from investigation.approval_loop import InvestigatorReadyApprovalLoopService
            from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG
            from investigation.persistence import SQLiteInvestigationStore
            with SQLiteInvestigationStore(app.database) as store:
                service = InvestigatorReadyApprovalLoopService(store, DEFAULT_LOCAL_CASE_CATALOG, object(), object())
                operation = service.prepare_start_investigation("development-case-42", OBJECTIVE)
                assert store.claim_pending_operation(operation.operation_id, "dead-process", operation.updated_at)
            page.goto(app.url)
            page.get_by_role("button", name="Resume").click()
            expect(page.get_by_text("previous processing attempt was interrupted", exact=False)).to_be_visible()
            assert len(fake.generation_calls) == 0
            page.get_by_role("button", name="Try again").click()
            _needs_review(page)
            rows = operation_rows(app.database)
            assert [row["status"] for row in rows] == ["INTERRUPTED", "COMPLETED"]
            assert rows[1]["prior_attempt_operation_id"] == rows[0]["operation_id"]
            assert len(fake.generation_calls) == 1
            app.evidence.step("explicit interrupted retry", ["INTERRUPTED", "COMPLETED"], [row["status"] for row in rows])
    finally:
        fake.close()
