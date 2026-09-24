"""Local SQLite persistence for the V0 investigation approval loop."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from investigation.models import (
    DECISION_TYPES,
    PROPOSAL_STATUSES,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
    InvestigationRecord,
    apply_human_decision,
)


_DECISION_STATUS = {
    "APPROVE": "APPROVED",
    "DECLINE": "DECLINED",
    "MODIFY": "MODIFIED",
}
_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class DeclineReconsiderationResult:
    """Restart-safe provenance for one successful independent decline replacement."""

    decline_decision_id: str
    replacement_proposal_id: str
    created_at: datetime


class SQLiteInvestigationStore:
    """Persist the approved V0 records in one local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def __enter__(self) -> SQLiteInvestigationStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def add_investigation(self, investigation: InvestigationRecord) -> None:
        try:
            with self._connection:
                self._insert_investigation(investigation)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def add_investigation_with_initial_proposal(
        self,
        investigation: InvestigationRecord,
        proposal: AnalyticalActionProposal,
    ) -> None:
        """Atomically persist one investigation and its initial proposed action."""
        try:
            with self._connection:
                self._insert_investigation(investigation)
                self._insert_proposal(investigation.investigation_id, proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def add_investigation_with_initial_direction_and_proposal(
        self,
        investigation: InvestigationRecord,
        direction: InvestigationDirection,
        proposal: AnalyticalActionProposal,
    ) -> None:
        """Atomically persist the initial V0.5 investigation state."""
        if investigation.objective is None:
            raise ValueError("V0.5 investigation requires an objective")
        if investigation.package_association is None:
            raise ValueError("V0.5 investigation requires a package association")
        if direction.investigation_id != investigation.investigation_id:
            raise ValueError("initial direction must belong to the investigation")
        if direction.version != 1:
            raise ValueError("initial direction must have version 1")
        try:
            with self._connection:
                self._insert_investigation(investigation)
                self._insert_direction(direction)
                self._insert_proposal(investigation.investigation_id, proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def get_investigation(self, investigation_id: str) -> InvestigationRecord:
        row = self._connection.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
        if row is None:
            raise ValueError("investigation does not exist")
        return _investigation_from_row(row)

    def set_package_association_if_missing(
        self, investigation_id: str, package_association: str
    ) -> InvestigationRecord:
        """Persist one explicit safe package association without replacing an existing one."""
        if not isinstance(package_association, str) or not package_association.strip():
            raise ValueError("package_association must be non-empty")
        with self._connection:
            investigation = self.get_investigation(investigation_id)
            if investigation.package_association is not None:
                raise ValueError("investigation already has a package association")
            self._connection.execute(
                "UPDATE investigations SET package_association = ? WHERE investigation_id = ?",
                (package_association, investigation_id),
            )
        return self.get_investigation(investigation_id)

    def add_proposal(
        self, investigation_id: str, proposal: AnalyticalActionProposal
    ) -> None:
        try:
            with self._connection:
                self._insert_proposal(investigation_id, proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def add_direction(self, direction: InvestigationDirection) -> None:
        """Append one immutable V0.5 investigation-direction version."""
        try:
            with self._connection:
                self._insert_direction(direction)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def persist_modify_with_optional_direction(
        self,
        proposal: AnalyticalActionProposal,
        decision: HumanDecision,
        revised_proposal: AnalyticalActionProposal,
        direction: InvestigationDirection | None = None,
    ) -> tuple[AnalyticalActionProposal, ...]:
        """Atomically persist one Modify decision, revision, and optional direction."""
        transitioned = apply_human_decision(proposal, decision, revised_proposal)
        try:
            with self._connection:
                stored = _proposal_from_row(self._proposal_row(proposal.proposal_id))
                if stored != proposal:
                    raise ValueError("stored proposal must match the PROPOSED proposal")
                parent = self._proposal_row(proposal.proposal_id)
                self._connection.execute(
                    "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                    (transitioned[0].status, proposal.proposal_id),
                )
                self._insert_decision(decision)
                if direction is not None:
                    if direction.investigation_id != parent["investigation_id"]:
                        raise ValueError("direction must belong to the proposal investigation")
                    self._require_next_direction_version(direction)
                    self._insert_direction(direction)
                self._insert_proposal(parent["investigation_id"], revised_proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error
        return transitioned

    def add_decline_reconsideration_result(
        self,
        investigation_id: str,
        direction: InvestigationDirection | None,
        proposal: AnalyticalActionProposal,
        result: DeclineReconsiderationResult,
    ) -> None:
        """Atomically persist a decline replacement, optional direction, and its provenance."""
        try:
            with self._connection:
                if direction is not None:
                    if direction.investigation_id != investigation_id:
                        raise ValueError("direction must belong to the investigation")
                    self._require_next_direction_version(direction)
                    self._insert_direction(direction)
                self._insert_proposal(investigation_id, proposal)
                self._insert_decline_reconsideration_result(result, investigation_id)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def get_decline_reconsideration_result(
        self, decline_decision_id: str
    ) -> DeclineReconsiderationResult | None:
        """Return the one successful replacement associated with this decline, if any."""
        row = self._connection.execute(
            "SELECT * FROM decline_reconsideration_results WHERE decline_decision_id = ?",
            (decline_decision_id,),
        ).fetchone()
        if row is None:
            return None
        return DeclineReconsiderationResult(
            row["decline_decision_id"],
            row["replacement_proposal_id"],
            _deserialize_timestamp(row["created_at"]),
        )

    def list_decline_reconsideration_results(
        self, investigation_id: str
    ) -> tuple[DeclineReconsiderationResult, ...]:
        """Return restart-safe decline replacement provenance for one investigation."""
        rows = self._connection.execute(
            """
            SELECT decline_reconsideration_results.*
            FROM decline_reconsideration_results
            JOIN decisions ON decisions.decision_id = decline_reconsideration_results.decline_decision_id
            JOIN proposals ON proposals.proposal_id = decisions.proposal_id
            WHERE proposals.investigation_id = ?
            ORDER BY decline_reconsideration_results.created_at, decline_reconsideration_results.decline_decision_id
            """,
            (investigation_id,),
        ).fetchall()
        return tuple(
            DeclineReconsiderationResult(
                row["decline_decision_id"],
                row["replacement_proposal_id"],
                _deserialize_timestamp(row["created_at"]),
            )
            for row in rows
        )

    def list_investigations(self) -> tuple[InvestigationRecord, ...]:
        """Return investigations in deterministic most-recent-first order."""
        rows = self._connection.execute(
            "SELECT * FROM investigations ORDER BY updated_at DESC, investigation_id"
        ).fetchall()
        return tuple(_investigation_from_row(row) for row in rows)

    def list_directions(self, investigation_id: str) -> tuple[InvestigationDirection, ...]:
        """Return append-only direction history in ascending version order."""
        rows = self._connection.execute(
            "SELECT * FROM investigation_directions "
            "WHERE investigation_id = ? ORDER BY version, direction_id",
            (investigation_id,),
        ).fetchall()
        return tuple(_direction_from_row(row) for row in rows)

    def get_current_direction(
        self, investigation_id: str
    ) -> InvestigationDirection | None:
        """Return the highest persisted direction version, if any."""
        row = self._connection.execute(
            "SELECT * FROM investigation_directions WHERE investigation_id = ? "
            "ORDER BY version DESC, direction_id DESC LIMIT 1",
            (investigation_id,),
        ).fetchone()
        return _direction_from_row(row) if row is not None else None

    def persist_human_decision(
        self,
        proposal: AnalyticalActionProposal,
        decision: HumanDecision,
        revised_proposal: AnalyticalActionProposal | None = None,
    ) -> tuple[AnalyticalActionProposal, ...]:
        """Atomically persist one approved V0 decision lifecycle transition."""
        transitioned_proposals = apply_human_decision(
            proposal, decision, revised_proposal
        )

        try:
            with self._connection:
                stored = _proposal_from_row(self._proposal_row(proposal.proposal_id))
                if stored != proposal:
                    raise ValueError("stored proposal must match the PROPOSED proposal")

                self._connection.execute(
                    "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                    (transitioned_proposals[0].status, proposal.proposal_id),
                )
                self._insert_decision(decision)
                if revised_proposal is not None:
                    parent = self._proposal_row(proposal.proposal_id)
                    self._insert_proposal(parent["investigation_id"], revised_proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

        return transitioned_proposals

    def _insert_proposal(
        self, investigation_id: str, proposal: AnalyticalActionProposal
    ) -> None:
        if proposal.status != "PROPOSED":
            raise ValueError("new proposals must have PROPOSED status")
        if proposal.revised_from_proposal_id is not None:
            parent = self._proposal_row(proposal.revised_from_proposal_id)
            if parent["investigation_id"] != investigation_id:
                raise ValueError("revised proposal must belong to its original investigation")
            if parent["status"] != "MODIFIED":
                raise ValueError("revised proposal requires a MODIFIED original proposal")

        self._connection.execute(
            """
            INSERT INTO proposals (
                proposal_id, investigation_id, action, purpose, why_now,
                data_to_be_used, expected_output, status, created_at,
                revised_from_proposal_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                investigation_id,
                proposal.action,
                proposal.purpose,
                proposal.why_now,
                proposal.data_to_be_used,
                proposal.expected_output,
                proposal.status,
                _serialize_timestamp(proposal.created_at),
                proposal.revised_from_proposal_id,
            ),
        )

    def _insert_investigation(self, investigation: InvestigationRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO investigations (
                investigation_id, case_reference, created_at, updated_at,
                objective, package_association
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                investigation.investigation_id,
                investigation.case_reference,
                _serialize_timestamp(investigation.created_at),
                _serialize_timestamp(investigation.updated_at),
                investigation.objective,
                investigation.package_association,
            ),
        )

    def _insert_direction(self, direction: InvestigationDirection) -> None:
        self._connection.execute(
            """
            INSERT INTO investigation_directions (
                direction_id, investigation_id, version, competing_explanations_json,
                plan_steps_json, created_at, provenance, trigger_reference_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                direction.direction_id,
                direction.investigation_id,
                direction.version,
                json.dumps(direction.competing_explanations),
                json.dumps(direction.plan_steps),
                _serialize_timestamp(direction.created_at),
                direction.provenance,
                direction.trigger_reference_id,
            ),
        )

    def _insert_decision(self, decision: HumanDecision) -> None:
        proposal = self._proposal_row(decision.proposal_id)
        if proposal["status"] != _DECISION_STATUS[decision.decision_type]:
            raise ValueError("decision type must match the persisted proposal status")
        self._connection.execute(
            """
            INSERT INTO decisions (
                decision_id, proposal_id, decision_type, decided_at, instruction_or_reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                decision.proposal_id,
                decision.decision_type,
                _serialize_timestamp(decision.decided_at),
                decision.instruction_or_reason,
            ),
        )

    def _insert_decline_reconsideration_result(
        self,
        result: DeclineReconsiderationResult,
        investigation_id: str,
    ) -> None:
        decision = self._connection.execute(
            """
            SELECT decisions.decision_type, proposals.investigation_id
            FROM decisions JOIN proposals ON proposals.proposal_id = decisions.proposal_id
            WHERE decisions.decision_id = ?
            """,
            (result.decline_decision_id,),
        ).fetchone()
        if decision is None or decision["decision_type"] != "DECLINE":
            raise ValueError("decline reconsideration result requires a DECLINE decision")
        proposal = self._proposal_row(result.replacement_proposal_id)
        if decision["investigation_id"] != investigation_id or proposal["investigation_id"] != investigation_id:
            raise ValueError("decline reconsideration result must remain in one investigation")
        if proposal["status"] != "PROPOSED" or proposal["revised_from_proposal_id"] is not None:
            raise ValueError("decline replacement must be an independent PROPOSED proposal")
        self._connection.execute(
            """
            INSERT INTO decline_reconsideration_results (
                decline_decision_id, replacement_proposal_id, created_at
            ) VALUES (?, ?, ?)
            """,
            (
                result.decline_decision_id,
                result.replacement_proposal_id,
                _serialize_timestamp(result.created_at),
            ),
        )

    def _require_next_direction_version(self, direction: InvestigationDirection) -> None:
        current = self.get_current_direction(direction.investigation_id)
        expected_version = 1 if current is None else current.version + 1
        if direction.version != expected_version:
            raise ValueError("direction version must follow the persisted current direction")

    def list_proposals(self, investigation_id: str) -> tuple[AnalyticalActionProposal, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM proposals
            WHERE investigation_id = ?
            ORDER BY created_at, proposal_id
            """,
            (investigation_id,),
        ).fetchall()
        return tuple(_proposal_from_row(row) for row in rows)

    def list_decisions(self, investigation_id: str) -> tuple[HumanDecision, ...]:
        rows = self._connection.execute(
            """
            SELECT decisions.* FROM decisions
            JOIN proposals ON proposals.proposal_id = decisions.proposal_id
            WHERE proposals.investigation_id = ?
            ORDER BY decided_at, decision_id
            """,
            (investigation_id,),
        ).fetchall()
        return tuple(_decision_from_row(row) for row in rows)

    def list_history(
        self, investigation_id: str
    ) -> tuple[AnalyticalActionProposal | HumanDecision, ...]:
        rows = self._connection.execute(
            """
            SELECT record_type, record_id FROM (
                SELECT 'proposal' AS record_type, proposal_id AS record_id,
                       created_at AS occurred_at, 0 AS record_order
                FROM proposals WHERE investigation_id = ?
                UNION ALL SELECT 'decision' AS record_type, decisions.decision_id AS record_id,
                       decisions.decided_at AS occurred_at, 1 AS record_order
                FROM decisions
                JOIN proposals ON proposals.proposal_id = decisions.proposal_id
                WHERE proposals.investigation_id = ?
            ) ORDER BY occurred_at, record_order, record_id
            """,
            (investigation_id, investigation_id),
        ).fetchall()
        records: list[AnalyticalActionProposal | HumanDecision] = []
        for row in rows:
            if row["record_type"] == "proposal":
                records.append(_proposal_from_row(self._proposal_row(row["record_id"])))
            else:
                decision = self._connection.execute(
                    "SELECT * FROM decisions WHERE decision_id = ?", (row["record_id"],)
                ).fetchone()
                assert decision is not None
                records.append(_decision_from_row(decision))
        return tuple(records)

    def _proposal_row(self, proposal_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise ValueError("proposal does not exist")
        return row

    def _execute(self, statement: str, parameters: tuple[object, ...]) -> None:
        try:
            with self._connection:
                self._connection.execute(statement, parameters)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

    def _create_schema(self) -> None:
        self._connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                case_reference TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                purpose TEXT NOT NULL,
                why_now TEXT NOT NULL,
                data_to_be_used TEXT NOT NULL,
                expected_output TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN {PROPOSAL_STATUSES!r}),
                created_at TEXT NOT NULL,
                revised_from_proposal_id TEXT,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id),
                FOREIGN KEY (revised_from_proposal_id) REFERENCES proposals(proposal_id)
            );

            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                decision_type TEXT NOT NULL CHECK (decision_type IN {DECISION_TYPES!r}),
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
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version > _SCHEMA_VERSION:
            raise ValueError("database schema version is newer than supported")
        investigation_columns = self._table_columns("investigations")
        required_investigation_columns = {
            "investigation_id",
            "case_reference",
            "created_at",
            "updated_at",
        }
        if not required_investigation_columns <= investigation_columns:
            raise ValueError("investigations schema is incomplete")
        with self._connection:
            if "objective" not in investigation_columns:
                self._connection.execute("ALTER TABLE investigations ADD COLUMN objective TEXT")
            if "package_association" not in investigation_columns:
                self._connection.execute(
                    "ALTER TABLE investigations ADD COLUMN package_association TEXT"
                )
            self._ensure_direction_schema()
            self._ensure_decline_reconsideration_schema()
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _ensure_direction_schema(self) -> None:
        direction_columns = self._table_columns("investigation_directions")
        if not direction_columns:
            self._connection.execute(
                """
                CREATE TABLE investigation_directions (
                    direction_id TEXT PRIMARY KEY,
                    investigation_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    competing_explanations_json TEXT NOT NULL,
                    plan_steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provenance TEXT NOT NULL CHECK (
                        provenance IN ('INITIAL', 'MODIFY', 'DECLINE_REDIRECT')
                    ),
                    trigger_reference_id TEXT,
                    UNIQUE (investigation_id, version),
                    FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id)
                )
                """
            )
            return
        required_direction_columns = {
            "direction_id",
            "investigation_id",
            "version",
            "competing_explanations_json",
            "plan_steps_json",
            "created_at",
            "provenance",
            "trigger_reference_id",
        }
        if not required_direction_columns <= direction_columns:
            raise ValueError("investigation directions schema is incomplete")
        unique_version_indexes = (
            row
            for row in self._connection.execute("PRAGMA index_list(investigation_directions)")
            if row["unique"]
        )
        if not any(
            tuple(
                index_column["name"]
                for index_column in self._connection.execute(
                    f"PRAGMA index_info({row['name']})"
                )
            )
            == ("investigation_id", "version")
            for row in unique_version_indexes
        ):
            raise ValueError("investigation directions schema is incomplete")

    def _ensure_decline_reconsideration_schema(self) -> None:
        columns = self._table_columns("decline_reconsideration_results")
        if not columns:
            self._connection.execute(
                """
                CREATE TABLE decline_reconsideration_results (
                    decline_decision_id TEXT PRIMARY KEY,
                    replacement_proposal_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (decline_decision_id) REFERENCES decisions(decision_id),
                    FOREIGN KEY (replacement_proposal_id) REFERENCES proposals(proposal_id)
                )
                """
            )
            return
        required = {"decline_decision_id", "replacement_proposal_id", "created_at"}
        if not required <= columns:
            raise ValueError("decline reconsideration results schema is incomplete")
        unique_columns = {
            tuple(
                index_column["name"]
                for index_column in self._connection.execute(
                    f"PRAGMA index_info({row['name']})"
                )
            )
            for row in self._connection.execute("PRAGMA index_list(decline_reconsideration_results)")
            if row["unique"]
        }
        if not {("decline_decision_id",), ("replacement_proposal_id",)} <= unique_columns:
            raise ValueError("decline reconsideration results schema is incomplete")
        foreign_keys = {
            (row["from"], row["table"], row["to"])
            for row in self._connection.execute(
                "PRAGMA foreign_key_list(decline_reconsideration_results)"
            )
        }
        if not {
            ("decline_decision_id", "decisions", "decision_id"),
            ("replacement_proposal_id", "proposals", "proposal_id"),
        } <= foreign_keys:
            raise ValueError("decline reconsideration results schema is incomplete")

    def _table_columns(self, table_name: str) -> set[str]:
        return {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table_name})")
        }


def _serialize_timestamp(value: datetime) -> str:
    return value.isoformat()


def _deserialize_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _investigation_from_row(row: sqlite3.Row) -> InvestigationRecord:
    return InvestigationRecord(
        row["investigation_id"],
        row["case_reference"],
        _deserialize_timestamp(row["created_at"]),
        _deserialize_timestamp(row["updated_at"]),
        row["objective"],
        row["package_association"],
    )


def _proposal_from_row(row: sqlite3.Row) -> AnalyticalActionProposal:
    return AnalyticalActionProposal(
        row["proposal_id"],
        row["action"],
        row["purpose"],
        row["why_now"],
        row["data_to_be_used"],
        row["expected_output"],
        row["status"],
        _deserialize_timestamp(row["created_at"]),
        row["revised_from_proposal_id"],
    )


def _decision_from_row(row: sqlite3.Row) -> HumanDecision:
    return HumanDecision(
        row["decision_id"],
        row["proposal_id"],
        row["decision_type"],
        _deserialize_timestamp(row["decided_at"]),
        row["instruction_or_reason"],
    )


def _direction_from_row(row: sqlite3.Row) -> InvestigationDirection:
    return InvestigationDirection(
        row["direction_id"],
        row["investigation_id"],
        row["version"],
        tuple(json.loads(row["competing_explanations_json"])),
        tuple(json.loads(row["plan_steps_json"])),
        _deserialize_timestamp(row["created_at"]),
        row["provenance"],
        row["trigger_reference_id"],
    )
