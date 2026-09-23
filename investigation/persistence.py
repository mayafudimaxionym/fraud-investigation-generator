"""Local SQLite persistence for the V0 investigation approval loop."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from investigation.models import (
    DECISION_TYPES,
    PROPOSAL_STATUSES,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationRecord,
    apply_human_decision,
)


_DECISION_STATUS = {
    "APPROVE": "APPROVED",
    "DECLINE": "DECLINED",
    "MODIFY": "MODIFIED",
}


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

    def get_investigation(self, investigation_id: str) -> InvestigationRecord:
        row = self._connection.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
        if row is None:
            raise ValueError("investigation does not exist")
        return _investigation_from_row(row)

    def add_proposal(
        self, investigation_id: str, proposal: AnalyticalActionProposal
    ) -> None:
        try:
            with self._connection:
                self._insert_proposal(investigation_id, proposal)
        except sqlite3.IntegrityError as error:
            raise ValueError("persistence integrity constraint failed") from error

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
                investigation_id, case_reference, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                investigation.investigation_id,
                investigation.case_reference,
                _serialize_timestamp(investigation.created_at),
                _serialize_timestamp(investigation.updated_at),
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
