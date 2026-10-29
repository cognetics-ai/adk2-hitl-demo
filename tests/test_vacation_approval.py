from __future__ import annotations

import unittest
from datetime import date

from google.adk.sessions import InMemorySessionService

from api.runtimes.vacation_approval import CreateVacationRequest
from api.runtimes.vacation_approval import SubmitManagerDecisionRequest
from api.runtimes.vacation_approval import VacationApprovalRuntime


class VacationApprovalRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def build_runtime(self) -> VacationApprovalRuntime:
        return VacationApprovalRuntime(session_service_factory=InMemorySessionService)

    def build_restarted_runtime(
        self,
        shared_session_service: InMemorySessionService,
    ) -> VacationApprovalRuntime:
        return VacationApprovalRuntime(
            session_service_factory=lambda: shared_session_service
        )

    async def test_one_day_request_is_auto_approved(self) -> None:
        runtime = self.build_runtime()

        record = await runtime.create_request(
            CreateVacationRequest(
                actor_id="rob.white",
                start_date=date(2026, 5, 11),
                end_date=date(2026, 5, 11),
                reason="Personal appointment",
            )
        )

        self.assertEqual(record.status, "approved")
        self.assertIsNone(record.pending_input)
        self.assertEqual(record.final_decision["decision_source"], "auto_policy")
        self.assertEqual(record.final_decision["approved_days"], 1)

    async def test_multi_day_request_waits_for_jason_and_resumes(self) -> None:
        runtime = self.build_runtime()

        record = await runtime.create_request(
            CreateVacationRequest(
                actor_id="rob.white",
                start_date=date(2026, 5, 11),
                end_date=date(2026, 5, 12),
                reason="Family vacation",
            )
        )

        self.assertEqual(record.status, "pending_manager")
        self.assertEqual(record.pending_input["interrupt_id"], f"manager_approval:{record.request_id}")
        self.assertEqual(
            record.pending_input["payload"]["assigned_to"]["id"],
            "jason.brown",
        )

        resumed = await runtime.submit_manager_decision(
            record.request_id,
            SubmitManagerDecisionRequest(
                actor_id="jason.brown",
                approved=True,
                approved_days=2,
                comment="Coverage is arranged.",
            ),
        )

        self.assertEqual(resumed.status, "approved")
        self.assertIsNone(resumed.pending_input)
        self.assertEqual(resumed.final_decision["decision_source"], "manager_review")
        self.assertEqual(resumed.final_decision["node_input"]["decided_by"], "jason.brown")
        self.assertEqual(
            resumed.resume_payloads[-1]["payload"]["parts"][0]["functionResponse"]["id"],
            f"manager_approval:{record.request_id}",
        )

    async def test_employee_cannot_approve_own_manager_request(self) -> None:
        runtime = self.build_runtime()
        record = await runtime.create_request(
            CreateVacationRequest(
                actor_id="rob.white",
                start_date=date(2026, 5, 11),
                end_date=date(2026, 5, 13),
                reason="Vacation",
            )
        )

        with self.assertRaises(PermissionError):
            await runtime.submit_manager_decision(
                record.request_id,
                SubmitManagerDecisionRequest(
                    actor_id="rob.white",
                    approved=True,
                    approved_days=3,
                ),
            )

    async def test_request_materializes_after_runtime_restart(self) -> None:
        shared_session_service = InMemorySessionService()
        runtime = self.build_restarted_runtime(shared_session_service)

        record = await runtime.create_request(
            CreateVacationRequest(
                actor_id="rob.white",
                start_date=date(2026, 5, 11),
                end_date=date(2026, 5, 15),
                reason="Family vacation",
            )
        )

        restarted = self.build_restarted_runtime(shared_session_service)
        await restarted.restart()
        reloaded = await restarted.get_record(record.request_id)
        manager_records = await restarted.visible_records("jason.brown")

        self.assertEqual(reloaded.status, "pending_manager")
        self.assertEqual(reloaded.request["days"], 5)
        self.assertEqual(reloaded.pending_input["payload"]["assigned_to"]["id"], "jason.brown")
        self.assertIn(record.request_id, {item.request_id for item in manager_records})

        approved = await restarted.submit_manager_decision(
            record.request_id,
            SubmitManagerDecisionRequest(
                actor_id="jason.brown",
                approved=True,
                approved_days=5,
                comment="Approved after restart.",
            ),
        )

        restarted_again = self.build_restarted_runtime(shared_session_service)
        finalized = await restarted_again.get_record(record.request_id)

        self.assertEqual(approved.status, "approved")
        self.assertEqual(finalized.status, "approved")
        self.assertIsNone(finalized.pending_input)
        self.assertEqual(finalized.final_decision["approved_days"], 5)
        self.assertEqual(
            finalized.resume_payloads[-1]["payload"]["parts"][0]["functionResponse"]["id"],
            f"manager_approval:{record.request_id}",
        )


if __name__ == "__main__":
    unittest.main()
