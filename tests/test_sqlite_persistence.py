import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from investigation.models import (
    AgentOperation,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
    InvestigationRecord,
)
from investigation.persistence import SQLiteInvestigationStore
from investigation.persistence import DeclineReconsiderationResult


BASE_TIME = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def _investigation() -> InvestigationRecord:
    return InvestigationRecord(
        "investigation-001",
        "development-case-42",
        BASE_TIME,
        BASE_TIME + timedelta(minutes=5),
    )


def _v05_investigation(
    investigation_id: str = "investigation-001",
    *,
    objective: str = "Investigate the reported suspicious activity.",
    package_association: str = "development-case-42",
    updated_at: datetime = BASE_TIME + timedelta(minutes=5),
) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id,
        "development-case-42",
        BASE_TIME,
        updated_at,
        objective,
        package_association,
    )


def _direction(
    direction_id: str = "direction-001",
    *,
    investigation_id: str = "investigation-001",
    version: int = 1,
    provenance: str = "INITIAL",
    trigger_reference_id: str | None = None,
) -> InvestigationDirection:
    return InvestigationDirection(
        direction_id,
        investigation_id,
        version,
        (
            "The activity may reflect coordinated account takeover.",
            "The activity may reflect legitimate shared access.",
        ),
        (
            "Review visible login and transfer records.",
            "Compare available relationship evidence.",
        ),
        BASE_TIME + timedelta(minutes=version),
        provenance,
        trigger_reference_id,
    )


def _create_v0_database(database_path: Path) -> None:
    """Create the accepted pre-V0.5 SQLite schema without V0.5 columns."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY,
                case_reference TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE proposals (
                proposal_id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                purpose TEXT NOT NULL,
                why_now TEXT NOT NULL,
                data_to_be_used TEXT NOT NULL,
                expected_output TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('PROPOSED', 'APPROVED', 'DECLINED', 'MODIFIED')),
                created_at TEXT NOT NULL,
                revised_from_proposal_id TEXT,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id),
                FOREIGN KEY (revised_from_proposal_id) REFERENCES proposals(proposal_id)
            );
            CREATE TABLE decisions (
                decision_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                decision_type TEXT NOT NULL CHECK (decision_type IN ('APPROVE', 'MODIFY', 'DECLINE')),
                decided_at TEXT NOT NULL,
                instruction_or_reason TEXT,
                FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id),
                CHECK (
                    (decision_type = 'APPROVE' AND instruction_or_reason IS NULL)
                    OR (decision_type = 'MODIFY' AND instruction_or_reason IS NOT NULL)
                    OR decision_type = 'DECLINE'
                )
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def _schema_version(database_path: Path) -> int:
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _proposal(
    proposal_id: str = "proposal-001", *, created_at: datetime = BASE_TIME
) -> AnalyticalActionProposal:
    return AnalyticalActionProposal(
        proposal_id,
        "Compare login and transfer sequences.",
        "Assess the visible sequence.",
        "The investigator requested an initial review.",
        "investigation request and visible_events.csv inventory",
        "A bounded sequence-comparison result.",
        "PROPOSED",
        created_at,
    )


def _decision(
    decision_type: str,
    *,
    proposal_id: str = "proposal-001",
    decision_id: str = "decision-001",
    instruction_or_reason: str | None = None,
    decided_at: datetime = BASE_TIME + timedelta(minutes=1),
) -> HumanDecision:
    return HumanDecision(
        decision_id,
        proposal_id,
        decision_type,
        decided_at,
        instruction_or_reason,
    )


def _operation(
    operation_id: str = "operation-001",
    *,
    investigation_id: str = "investigation-001",
    operation_type: str = "START",
    status: str = "PENDING_RENDER",
    triggering_proposal_id: str | None = None,
    triggering_decision_id: str | None = None,
    prior_attempt_operation_id: str | None = None,
    runner_instance_id: str | None = None,
    updated_at: datetime = BASE_TIME,
) -> AgentOperation:
    return AgentOperation(
        operation_id,
        investigation_id,
        operation_type,
        status,
        BASE_TIME,
        updated_at,
        triggering_proposal_id,
        triggering_decision_id,
        prior_attempt_operation_id,
        runner_instance_id,
    )


def test_store_reloads_investigation_across_a_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = _investigation()

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)

    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.get_investigation(investigation.investigation_id) == investigation


def test_fresh_database_creates_v05_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"

    with SQLiteInvestigationStore(database_path):
        pass

    connection = sqlite3.connect(database_path)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(investigations)")
        }
        direction_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'investigation_directions'"
        ).fetchone()
        result_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'decline_reconsideration_results'"
        ).fetchone()
        operation_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agent_operations'"
        ).fetchone()
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert {"objective", "package_association"} <= columns
    assert direction_table is not None
    assert result_table is not None
    assert operation_table is not None
    assert schema_version == 3


def test_v0_schema_migrates_idempotently_without_losing_history(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite"
    _create_v0_database(database_path)
    legacy = _investigation()
    original = _proposal()
    decision = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = AnalyticalActionProposal(
        "proposal-002",
        "Compare only visible login and transfer events.",
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        "PROPOSED",
        BASE_TIME + timedelta(minutes=2),
        original.proposal_id,
    )
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO investigations VALUES (?, ?, ?, ?)",
            (
                legacy.investigation_id,
                legacy.case_reference,
                legacy.created_at.isoformat(),
                legacy.updated_at.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                original.proposal_id,
                legacy.investigation_id,
                original.action,
                original.purpose,
                original.why_now,
                original.data_to_be_used,
                original.expected_output,
                "MODIFIED",
                original.created_at.isoformat(),
                None,
            ),
        )
        connection.execute(
            "INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revised.proposal_id,
                legacy.investigation_id,
                revised.action,
                revised.purpose,
                revised.why_now,
                revised.data_to_be_used,
                revised.expected_output,
                revised.status,
                revised.created_at.isoformat(),
                revised.revised_from_proposal_id,
            ),
        )
        connection.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
            (
                decision.decision_id,
                decision.proposal_id,
                decision.decision_type,
                decision.decided_at.isoformat(),
                decision.instruction_or_reason,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with SQLiteInvestigationStore(database_path) as migrated:
        migrated_legacy = migrated.get_investigation(legacy.investigation_id)
        assert migrated_legacy == legacy
        assert migrated_legacy.objective is None
        assert migrated_legacy.package_association is None
        assert migrated.list_proposals(legacy.investigation_id) == (
            AnalyticalActionProposal(
                original.proposal_id,
                original.action,
                original.purpose,
                original.why_now,
                original.data_to_be_used,
                original.expected_output,
                "MODIFIED",
                original.created_at,
            ),
            revised,
        )
        assert migrated.list_decisions(legacy.investigation_id) == (decision,)
        assert migrated.get_current_direction(legacy.investigation_id) is None
    assert _schema_version(database_path) == 3

    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.get_investigation(legacy.investigation_id) == legacy
        assert reopened.list_proposals(legacy.investigation_id)[1] == revised
    assert _schema_version(database_path) == 3


def test_misleading_current_user_version_repairs_a_v0_shaped_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "misleading-version.sqlite"
    _create_v0_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()

    with SQLiteInvestigationStore(database_path) as store:
        assert store.get_current_direction("investigation-missing") is None

    connection = sqlite3.connect(database_path)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(investigations)")
        }
        direction_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'investigation_directions'"
        ).fetchone()
    finally:
        connection.close()

    assert {"objective", "package_association"} <= columns
    assert direction_table is not None
    assert _schema_version(database_path) == 3


def test_failed_migration_does_not_advance_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "failed-migration.sqlite"
    _create_v0_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "CREATE TABLE investigation_directions (direction_id TEXT PRIMARY KEY)"
        )
        connection.commit()
    finally:
        connection.close()

    try:
        SQLiteInvestigationStore(database_path)
    except ValueError as error:
        assert "directions schema is incomplete" in str(error)
    else:
        raise AssertionError("an incomplete directions table must reject migration")

    assert _schema_version(database_path) == 0


def test_store_reloads_all_proposal_fields_and_final_status(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()
    decision = _decision("APPROVE")

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", proposal)
        (approved,) = store.persist_human_decision(proposal, decision)

        assert store.list_proposals("investigation-001") == (approved,)


def test_store_reloads_human_decisions(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()
    decision = _decision(
        "DECLINE", instruction_or_reason="Review customer correspondence first."
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", proposal)
        (declined,) = store.persist_human_decision(proposal, decision)

        assert store.list_decisions("investigation-001") == (decision,)


def test_store_preserves_modify_lineage_and_restart_state(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    original = _proposal()
    decision = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = AnalyticalActionProposal(
        "proposal-002",
        "Compare only visible login and transfer events.",
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        "PROPOSED",
        BASE_TIME + timedelta(minutes=2),
        original.proposal_id,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", original)
        modified_original, proposed_revision = store.persist_human_decision(
            original, decision, revised
        )

    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.list_proposals("investigation-001") == (
            modified_original,
            proposed_revision,
        )
        assert reopened.list_decisions("investigation-001") == (decision,)
        assert reopened.list_history("investigation-001") == (
            modified_original,
            decision,
            proposed_revision,
        )


def test_history_is_deterministically_ordered_by_timestamp_then_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    later = _proposal("proposal-later", created_at=BASE_TIME + timedelta(minutes=2))
    earlier = _proposal("proposal-earlier", created_at=BASE_TIME)

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", later)
        store.add_proposal("investigation-001", earlier)

        assert store.list_proposals("investigation-001") == (earlier, later)
        assert store.list_history("investigation-001") == (earlier, later)


def test_store_rejects_proposals_without_a_persisted_investigation(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()

    with SQLiteInvestigationStore(database_path) as store:
        try:
            store.add_proposal("investigation-001", proposal)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("proposals require a persisted investigation")


def test_initial_investigation_and_proposal_write_rolls_back_on_proposal_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    target_investigation = _investigation()
    duplicate_proposal = _proposal("proposal-duplicate")
    target_proposal = _proposal("proposal-duplicate")
    existing_investigation = InvestigationRecord(
        "investigation-existing",
        "other-case",
        BASE_TIME,
        BASE_TIME,
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(existing_investigation)
        store.add_proposal(existing_investigation.investigation_id, duplicate_proposal)

        try:
            store.add_investigation_with_initial_proposal(
                target_investigation, target_proposal
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate initial proposal IDs must fail inside the transaction")

        try:
            store.get_investigation(target_investigation.investigation_id)
        except ValueError as error:
            assert "does not exist" in str(error)
        else:
            raise AssertionError("investigation insertion must roll back with proposal failure")
        assert store.list_proposals(target_investigation.investigation_id) == ()


def test_final_decision_writes_roll_back_when_decision_insert_fails(tmp_path: Path) -> None:
    for decision_type in ("APPROVE", "DECLINE"):
        database_path = tmp_path / f"{decision_type.lower()}.sqlite"
        existing_proposal = _proposal(f"proposal-existing-{decision_type}")
        existing_decision = _decision(
            decision_type,
            proposal_id=existing_proposal.proposal_id,
            decision_id="decision-duplicate",
        )
        target_proposal = _proposal(f"proposal-target-{decision_type}")
        duplicate_decision = _decision(
            decision_type,
            proposal_id=target_proposal.proposal_id,
            decision_id="decision-duplicate",
        )

        with SQLiteInvestigationStore(database_path) as store:
            store.add_investigation(_investigation())
            store.add_proposal("investigation-001", existing_proposal)
            store.persist_human_decision(existing_proposal, existing_decision)
            store.add_proposal("investigation-001", target_proposal)

            try:
                store.persist_human_decision(target_proposal, duplicate_decision)
            except ValueError as error:
                assert "integrity" in str(error)
            else:
                raise AssertionError("duplicate decision IDs must fail inside the transaction")

            statuses = {
                proposal.proposal_id: proposal.status
                for proposal in store.list_proposals("investigation-001")
            }
            assert statuses[target_proposal.proposal_id] == "PROPOSED"
            assert store.list_decisions("investigation-001") == (existing_decision,)


def test_modify_writes_roll_back_when_revised_proposal_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "modify.sqlite"
    original = _proposal()
    duplicate = _proposal("proposal-duplicate")
    decision = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = AnalyticalActionProposal(
        duplicate.proposal_id,
        "Compare only visible login and transfer events.",
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        "PROPOSED",
        BASE_TIME + timedelta(minutes=2),
        original.proposal_id,
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", original)
        store.add_proposal("investigation-001", duplicate)
        try:
            store.persist_human_decision(original, decision, revised)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate revised proposal IDs must fail inside the transaction")

        statuses = {
            proposal.proposal_id: proposal.status
            for proposal in store.list_proposals("investigation-001")
        }
        assert statuses == {
            original.proposal_id: "PROPOSED",
            duplicate.proposal_id: "PROPOSED",
        }
        assert store.list_decisions("investigation-001") == ()


def test_v05_metadata_preserves_blank_objective_and_safe_package_association(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = _v05_investigation(objective="", package_association="case-opaque-42")

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        assert store.get_investigation(investigation.investigation_id) == investigation


def test_store_associates_an_unassociated_investigation_without_changing_objective(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = InvestigationRecord(
        "investigation-001",
        "development-case-42",
        BASE_TIME,
        BASE_TIME,
        "",
        None,
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        associated = store.set_package_association_if_missing(
            investigation.investigation_id, "development-case-42"
        )

        assert associated.objective == ""
        assert associated.package_association == "development-case-42"


def test_store_rejects_blank_or_replaced_package_associations(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = _v05_investigation(package_association=None)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        for association in ("", "   "):
            try:
                store.set_package_association_if_missing(
                    investigation.investigation_id, association
                )
            except ValueError as error:
                assert "package_association" in str(error)
            else:
                raise AssertionError("blank package associations must be rejected")

        store.set_package_association_if_missing(
            investigation.investigation_id, "development-case-42"
        )
        try:
            store.set_package_association_if_missing(
                investigation.investigation_id, "other-case"
            )
        except ValueError as error:
            assert "already has" in str(error)
        else:
            raise AssertionError("package associations must not be silently replaced")


def test_store_sets_legacy_objective_once_without_changing_other_history(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    legacy = InvestigationRecord("legacy", "development-case-42", BASE_TIME, BASE_TIME, None, "case-42")
    proposal = AnalyticalActionProposal("proposal", "Review events.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(legacy)
        store.add_proposal(legacy.investigation_id, proposal)
        before_proposals = store.list_proposals(legacy.investigation_id)
        recovered = store.set_objective_if_missing(legacy.investigation_id, "")
        assert recovered.objective == ""
        assert recovered.case_reference == legacy.case_reference
        assert recovered.package_association == legacy.package_association
        assert recovered.created_at == legacy.created_at
        assert store.list_proposals(legacy.investigation_id) == before_proposals
        assert store.list_directions(legacy.investigation_id) == ()
        assert store.list_decisions(legacy.investigation_id) == ()
        for value in ("replacement", ""):
            with pytest.raises(ValueError, match="already established"):
                store.set_objective_if_missing(legacy.investigation_id, value)
        with pytest.raises(ValueError, match="does not exist"):
            store.set_objective_if_missing("unknown", "objective")
    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.get_investigation(legacy.investigation_id).objective == ""


def test_direction_history_preserves_version_and_text_order(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    first = _direction()
    second = InvestigationDirection(
        "direction-002",
        first.investigation_id,
        2,
        (
            "The shared device may be legitimate.",
            "The activity may be coordinated.",
        ),
        (
            "Review visible relationships.",
            "Compare visible event timing.",
        ),
        BASE_TIME + timedelta(minutes=3),
        "MODIFY",
        "proposal-001",
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_v05_investigation())
        store.add_direction(second)
        store.add_direction(first)

        assert store.list_directions(first.investigation_id) == (first, second)
        assert store.get_current_direction(first.investigation_id) == second


def test_direction_rejects_duplicate_version_and_missing_investigation(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    first = _direction()
    duplicate_version = _direction("direction-duplicate")
    missing = _direction("direction-missing", investigation_id="investigation-missing")

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_v05_investigation())
        store.add_direction(first)
        for direction in (duplicate_version, missing):
            try:
                store.add_direction(direction)
            except ValueError as error:
                assert "integrity" in str(error)
            else:
                raise AssertionError("invalid direction persistence must be rejected")


def test_initial_v05_write_persists_investigation_direction_and_proposal_atomically(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = _v05_investigation()
    direction = _direction()
    proposal = _proposal()

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation_with_initial_direction_and_proposal(
            investigation, direction, proposal
        )
        assert store.get_investigation(investigation.investigation_id) == investigation
        assert store.get_current_direction(investigation.investigation_id) == direction
        assert store.list_proposals(investigation.investigation_id) == (proposal,)


def test_initial_v05_write_rolls_back_when_direction_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "directions.sqlite"
    existing = _v05_investigation("investigation-existing")
    duplicate_direction = _direction(
        "direction-duplicate", investigation_id=existing.investigation_id
    )
    target = _v05_investigation("investigation-target")
    target_direction = _direction(
        "direction-duplicate", investigation_id=target.investigation_id
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(existing)
        store.add_direction(duplicate_direction)
        try:
            store.add_investigation_with_initial_direction_and_proposal(
                target, target_direction, _proposal("proposal-target")
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate direction IDs must fail inside the transaction")

        try:
            store.get_investigation(target.investigation_id)
        except ValueError:
            pass
        else:
            raise AssertionError("investigation insertion must roll back with direction failure")
        assert store.get_current_direction(target.investigation_id) is None


def test_initial_v05_write_rolls_back_when_proposal_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "proposals.sqlite"
    existing = _v05_investigation("investigation-existing")
    target = _v05_investigation("investigation-target")
    duplicate_proposal = _proposal("proposal-duplicate")

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(existing)
        store.add_proposal(existing.investigation_id, duplicate_proposal)
        try:
            store.add_investigation_with_initial_direction_and_proposal(
                target,
                _direction("direction-target", investigation_id=target.investigation_id),
                _proposal("proposal-duplicate"),
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate proposal IDs must fail inside the transaction")

        try:
            store.get_investigation(target.investigation_id)
        except ValueError:
            pass
        else:
            raise AssertionError("investigation insertion must roll back with proposal failure")
        assert store.get_current_direction(target.investigation_id) is None


def test_investigation_listing_is_deterministically_most_recent_first(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    later = _v05_investigation(
        "investigation-later", updated_at=BASE_TIME + timedelta(minutes=2)
    )
    earlier = _v05_investigation("investigation-earlier", updated_at=BASE_TIME)

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(earlier)
        store.add_investigation(later)

        assert store.list_investigations() == (later, earlier)


def test_v05_modify_direction_and_revision_are_one_atomic_write(tmp_path: Path) -> None:
    database_path = tmp_path / "modify-direction.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    duplicate = _proposal("proposal-duplicate")
    decision = _decision("MODIFY", instruction_or_reason="Focus on visible events.")
    direction = _direction("direction-002", version=2, provenance="MODIFY", trigger_reference_id=decision.decision_id)
    revised = AnalyticalActionProposal(
        duplicate.proposal_id, "Revised action.", original.purpose, original.why_now,
        original.data_to_be_used, original.expected_output, "PROPOSED",
        BASE_TIME + timedelta(minutes=4), original.proposal_id,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        store.add_proposal(investigation.investigation_id, duplicate)
        try:
            store.persist_modify_with_optional_direction(original, decision, revised, direction)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate revision ID must fail inside the transaction")
        assert store.list_proposals(investigation.investigation_id)[0].status == "PROPOSED"
        assert store.list_decisions(investigation.investigation_id) == ()
        assert store.list_directions(investigation.investigation_id) == (_direction(),)


def test_v05_reconsideration_direction_proposal_and_result_are_one_atomic_write(tmp_path: Path) -> None:
    database_path = tmp_path / "reconsideration.sqlite"
    investigation = _v05_investigation()
    existing = _proposal("proposal-existing")
    replacement = _proposal("proposal-existing")
    direction = _direction("direction-002", version=2, provenance="DECLINE_REDIRECT", trigger_reference_id="decision-001")
    decision = _decision(
        "DECLINE", proposal_id=existing.proposal_id,
        instruction_or_reason="Use a different approach.",
    )
    result = DeclineReconsiderationResult(
        decision.decision_id, replacement.proposal_id, BASE_TIME + timedelta(minutes=3)
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, existing)
        store.persist_human_decision(existing, decision)
        try:
            store.add_decline_reconsideration_result(
                investigation.investigation_id, direction, replacement, result
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate replacement ID must fail inside the transaction")
        assert store.list_directions(investigation.investigation_id) == (_direction(),)
        assert store.list_proposals(investigation.investigation_id) == (
            AnalyticalActionProposal(
                existing.proposal_id, existing.action, existing.purpose, existing.why_now,
                existing.data_to_be_used, existing.expected_output, "DECLINED", existing.created_at,
            ),
        )
        assert store.get_decline_reconsideration_result(decision.decision_id) is None


def test_v05_modify_direction_must_belong_to_the_proposal_investigation(tmp_path: Path) -> None:
    database_path = tmp_path / "modify-wrong-direction.sqlite"
    investigation = _v05_investigation()
    other = _v05_investigation("investigation-other")
    original = _proposal()
    decision = _decision("MODIFY", instruction_or_reason="Focus on visible events.")
    revised = AnalyticalActionProposal(
        "proposal-revised", "Revised action.", original.purpose, original.why_now,
        original.data_to_be_used, original.expected_output, "PROPOSED",
        BASE_TIME + timedelta(minutes=4), original.proposal_id,
    )
    wrong_direction = _direction(
        "direction-other", investigation_id=other.investigation_id, version=1,
        provenance="MODIFY", trigger_reference_id=decision.decision_id,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_investigation(other)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        try:
            store.persist_modify_with_optional_direction(original, decision, revised, wrong_direction)
        except ValueError as error:
            assert "proposal investigation" in str(error)
        else:
            raise AssertionError("a Modify direction must belong to the proposal investigation")
        assert store.list_proposals(investigation.investigation_id) == (original,)
        assert store.list_decisions(investigation.investigation_id) == ()


def test_decline_reconsideration_result_requires_decline_and_independent_same_case_replacement(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "result-integrity.sqlite"
    investigation = _v05_investigation()
    source = _proposal("proposal-source")
    decision = _decision("APPROVE", proposal_id=source.proposal_id)
    replacement = _proposal("proposal-replacement")
    result = DeclineReconsiderationResult(decision.decision_id, replacement.proposal_id, BASE_TIME)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_proposal(investigation.investigation_id, source)
        store.persist_human_decision(source, decision)
        try:
            store.add_decline_reconsideration_result(investigation.investigation_id, None, replacement, result)
        except ValueError as error:
            assert "DECLINE" in str(error)
        else:
            raise AssertionError("only a DECLINE decision may produce a reconsideration result")
        assert store.list_proposals(investigation.investigation_id) == (
            AnalyticalActionProposal(
                source.proposal_id, source.action, source.purpose, source.why_now,
                source.data_to_be_used, source.expected_output, "APPROVED", source.created_at,
            ),
        )
        assert store.get_decline_reconsideration_result(decision.decision_id) is None


def test_decline_reconsideration_result_is_unique_by_decision_and_replacement(tmp_path: Path) -> None:
    database_path = tmp_path / "result-unique.sqlite"
    investigation = _v05_investigation()
    first = _proposal("proposal-first")
    second = _proposal("proposal-second")
    first_decision = _decision("DECLINE", proposal_id=first.proposal_id, decision_id="decision-first")
    second_decision = _decision("DECLINE", proposal_id=second.proposal_id, decision_id="decision-second")
    replacement = _proposal("proposal-replacement")
    result = DeclineReconsiderationResult(first_decision.decision_id, replacement.proposal_id, BASE_TIME)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_proposal(investigation.investigation_id, first)
        store.persist_human_decision(first, first_decision)
        store.add_proposal(investigation.investigation_id, second)
        store.persist_human_decision(second, second_decision)
        store.add_decline_reconsideration_result(investigation.investigation_id, None, replacement, result)
        another = _proposal("proposal-another")
        duplicate_decision = DeclineReconsiderationResult(first_decision.decision_id, another.proposal_id, BASE_TIME)
        try:
            store.add_decline_reconsideration_result(investigation.investigation_id, None, another, duplicate_decision)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("one decline decision must have at most one replacement")
        assert all(proposal.proposal_id != another.proposal_id for proposal in store.list_proposals(investigation.investigation_id))
        try:
            with store._connection:
                store._connection.execute(
                    "INSERT INTO decline_reconsideration_results VALUES (?, ?, ?)",
                    (second_decision.decision_id, replacement.proposal_id, BASE_TIME.isoformat()),
                )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("one replacement proposal must have at most one decline result")


def test_pending_operation_claim_is_atomic_and_terminal_operations_cannot_be_reclaimed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operations.sqlite"
    investigation = _v05_investigation()
    operation = _operation()
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_pending_operation(operation)
        assert store.claim_pending_operation(
            operation.operation_id, "runner-001", BASE_TIME + timedelta(seconds=1)
        )
        assert not store.claim_pending_operation(
            operation.operation_id, "runner-002", BASE_TIME + timedelta(seconds=2)
        )
        failed = store.mark_operation_failed(
            operation.operation_id, "runner-001", BASE_TIME + timedelta(seconds=3)
        )
        assert failed.status == "FAILED"
        assert not store.claim_pending_operation(
            operation.operation_id, "runner-001", BASE_TIME + timedelta(seconds=4)
        )


def test_retry_operation_preserves_terminal_prior_attempt_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "operation-retry.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    decision = _decision("DECLINE", instruction_or_reason="Use a different approach.")
    first = _operation(
        "operation-first",
        operation_type="DECLINE_REDIRECT",
        triggering_proposal_id=original.proposal_id,
        triggering_decision_id=decision.decision_id,
    )
    retry = _operation(
        "operation-retry",
        operation_type="DECLINE_REDIRECT",
        triggering_proposal_id=original.proposal_id,
        triggering_decision_id=decision.decision_id,
        prior_attempt_operation_id=first.operation_id,
        updated_at=BASE_TIME + timedelta(minutes=2),
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_proposal(investigation.investigation_id, original)
        store.persist_decline_with_pending_operation(original, decision, first)
        assert store.claim_pending_operation(first.operation_id, "runner-001", BASE_TIME + timedelta(seconds=1))
        store.mark_operation_interrupted(first.operation_id, "runner-001", BASE_TIME + timedelta(seconds=2))
        store.add_pending_operation(retry)
        assert store.list_agent_operations(investigation.investigation_id) == (
            store.get_agent_operation(first.operation_id), retry,
        )


def test_previous_process_running_operations_become_interrupted(tmp_path: Path) -> None:
    database_path = tmp_path / "interrupted.sqlite"
    investigation = _v05_investigation()
    operation = _operation()
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_pending_operation(operation)
        assert store.claim_pending_operation(operation.operation_id, "previous-process", BASE_TIME)
        interrupted = store.interrupt_operations_from_previous_process(
            "current-process", BASE_TIME + timedelta(minutes=1)
        )
        assert interrupted == (
            store.get_agent_operation(operation.operation_id),
        )
        assert interrupted[0].status == "INTERRUPTED"


def test_start_result_and_completion_are_atomic(tmp_path: Path) -> None:
    database_path = tmp_path / "start-completion.sqlite"
    target = _v05_investigation("investigation-target")
    other = _v05_investigation("investigation-other")
    duplicate = _proposal("proposal-duplicate")
    operation = _operation("operation-start", investigation_id=target.investigation_id)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(other)
        store.add_proposal(other.investigation_id, duplicate)
        store.add_investigation(target)
        store.add_pending_operation(operation)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        try:
            store.complete_start_operation(
                operation.operation_id,
                "runner-001",
                _direction("direction-target", investigation_id=target.investigation_id),
                _proposal("proposal-duplicate"),
                BASE_TIME + timedelta(minutes=1),
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate generated proposal must fail inside completion transaction")
        assert store.get_current_direction(target.investigation_id) is None
        assert store.list_proposals(target.investigation_id) == ()
        assert store.get_agent_operation(operation.operation_id).status == "RUNNING"


def test_successful_start_result_and_completion_are_one_persisted_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "start-success.sqlite"
    investigation = _v05_investigation()
    operation = _operation("operation-start")
    direction = _direction()
    proposal = _proposal()
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation_with_pending_start_operation(investigation, operation)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        store.complete_start_operation(
            operation.operation_id, "runner-001", direction, proposal,
            BASE_TIME + timedelta(minutes=1),
        )
        assert store.list_directions(investigation.investigation_id) == (direction,)
        assert store.list_proposals(investigation.investigation_id) == (proposal,)
        assert store.get_agent_operation(operation.operation_id).status == "COMPLETED"


def test_modify_result_completion_is_atomic_and_preserves_prior_human_decision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "modify-completion.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    decision = _decision("MODIFY", instruction_or_reason="Focus on transfers.")
    operation = _operation(
        "operation-modify", operation_type="MODIFY", triggering_proposal_id=original.proposal_id,
        triggering_decision_id=decision.decision_id,
    )
    duplicate = _proposal("proposal-duplicate")
    revised = AnalyticalActionProposal(
        duplicate.proposal_id, "Revised action.", original.purpose, original.why_now,
        original.data_to_be_used, original.expected_output, "PROPOSED",
        BASE_TIME + timedelta(minutes=2), original.proposal_id,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        store.persist_modify_with_pending_operation(original, decision, operation)
        store.add_investigation(_v05_investigation("investigation-other"))
        store.add_proposal("investigation-other", duplicate)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        try:
            store.complete_modify_operation(
                operation.operation_id, "runner-001", revised,
                _direction("direction-002", version=2, provenance="MODIFY", trigger_reference_id=decision.decision_id),
                BASE_TIME + timedelta(minutes=3),
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate revision must roll back completion")
        assert store.list_decisions(investigation.investigation_id) == (decision,)
        assert store.list_proposals(investigation.investigation_id)[0].status == "MODIFIED"
        assert store.list_directions(investigation.investigation_id) == (_direction(),)
        assert store.get_agent_operation(operation.operation_id).status == "RUNNING"


def test_successful_modify_result_and_completion_are_one_persisted_transaction(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "modify-success.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    decision = _decision("MODIFY", instruction_or_reason="Focus on transfers.")
    operation = _operation(
        "operation-modify", operation_type="MODIFY", triggering_proposal_id=original.proposal_id,
        triggering_decision_id=decision.decision_id,
    )
    revised = AnalyticalActionProposal(
        "proposal-revised", "Revised action.", original.purpose, original.why_now,
        original.data_to_be_used, original.expected_output, "PROPOSED",
        BASE_TIME + timedelta(minutes=2), original.proposal_id,
    )
    direction = _direction(
        "direction-002", version=2, provenance="MODIFY", trigger_reference_id=decision.decision_id
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        store.persist_modify_with_pending_operation(original, decision, operation)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        store.complete_modify_operation(
            operation.operation_id, "runner-001", revised, direction,
            BASE_TIME + timedelta(minutes=3),
        )
        assert store.list_proposals(investigation.investigation_id)[-1] == revised
        assert store.list_directions(investigation.investigation_id)[-1] == direction
        assert store.get_agent_operation(operation.operation_id).status == "COMPLETED"


def test_decline_reconsideration_completion_is_atomic_and_preserves_decline(tmp_path: Path) -> None:
    database_path = tmp_path / "decline-completion.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    decision = _decision("DECLINE", instruction_or_reason="Use a different approach.")
    operation = _operation(
        "operation-decline", operation_type="DECLINE_REDIRECT",
        triggering_proposal_id=original.proposal_id, triggering_decision_id=decision.decision_id,
    )
    duplicate = _proposal("proposal-duplicate")
    result = DeclineReconsiderationResult(decision.decision_id, duplicate.proposal_id, BASE_TIME)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        store.persist_decline_with_pending_operation(original, decision, operation)
        store.add_investigation(_v05_investigation("investigation-other"))
        store.add_proposal("investigation-other", duplicate)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        try:
            store.complete_decline_reconsideration_operation(
                operation.operation_id, "runner-001", _proposal("proposal-duplicate"),
                _direction("direction-002", version=2, provenance="DECLINE_REDIRECT", trigger_reference_id=decision.decision_id),
                result, BASE_TIME + timedelta(minutes=1),
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate replacement must roll back completion")
        assert store.list_decisions(investigation.investigation_id) == (decision,)
        assert store.list_proposals(investigation.investigation_id)[0].status == "DECLINED"
        assert store.list_directions(investigation.investigation_id) == (_direction(),)
        assert store.get_decline_reconsideration_result(decision.decision_id) is None
        assert store.get_agent_operation(operation.operation_id).status == "RUNNING"


def test_successful_decline_reconsideration_result_and_completion_are_atomic(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "decline-success.sqlite"
    investigation = _v05_investigation()
    original = _proposal()
    decision = _decision("DECLINE", instruction_or_reason="Use a different approach.")
    operation = _operation(
        "operation-decline", operation_type="DECLINE_REDIRECT",
        triggering_proposal_id=original.proposal_id, triggering_decision_id=decision.decision_id,
    )
    replacement = _proposal("proposal-replacement", created_at=BASE_TIME + timedelta(minutes=2))
    direction = _direction(
        "direction-002", version=2, provenance="DECLINE_REDIRECT", trigger_reference_id=decision.decision_id
    )
    result = DeclineReconsiderationResult(decision.decision_id, replacement.proposal_id, BASE_TIME)
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, original)
        store.persist_decline_with_pending_operation(original, decision, operation)
        assert store.claim_pending_operation(operation.operation_id, "runner-001", BASE_TIME)
        store.complete_decline_reconsideration_operation(
            operation.operation_id, "runner-001", replacement, direction, result,
            BASE_TIME + timedelta(minutes=3),
        )
        assert store.list_proposals(investigation.investigation_id)[-1] == replacement
        assert store.list_directions(investigation.investigation_id)[-1] == direction
        assert store.get_decline_reconsideration_result(decision.decision_id) == result
        assert store.get_agent_operation(operation.operation_id).status == "COMPLETED"
