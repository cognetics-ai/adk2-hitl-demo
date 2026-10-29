from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from agents.company_details_research_agent import agent as company_details_agent
from agents.comps_agent import agent as comps_agent
from api.research_services import _latest_event_error
from api.research_services import _latest_event_text
from api.research_services import _latest_state_delta_text
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types


SEC_LOOKUP_RESPONSE = {
    "status": "success",
    "query": "MSFT",
    "best_match": {
        "ticker": "MSFT",
        "title": "MICROSOFT CORP",
        "cik": 789019,
        "cik_padded": "CIK0000789019",
        "data_source": "sec",
    },
    "matches": [],
}


class ResearchPayloadTest(unittest.TestCase):
    def test_company_details_payload_resolves_ticker_to_company_title(self) -> None:
        with patch(
            "agents.research_payload.lookup_company",
            return_value=SEC_LOOKUP_RESPONSE,
        ):
            payload = company_details_agent._payload_from_input("MSFT")

        self.assertEqual(payload["company"], "MSFT")
        self.assertEqual(payload["title"], "MICROSOFT CORP")
        self.assertEqual(payload["client_name"], "MICROSOFT CORP")
        self.assertEqual(payload["ticker"], "MSFT")

    def test_comps_payload_resolves_ticker_to_company_title(self) -> None:
        with patch(
            "agents.research_payload.lookup_company",
            return_value=SEC_LOOKUP_RESPONSE,
        ):
            payload = comps_agent._payload_from_input('{"company": "MSFT"}')

        self.assertEqual(payload["company"], "MSFT")
        self.assertEqual(payload["title"], "MICROSOFT CORP")
        self.assertEqual(payload["client_name"], "MICROSOFT CORP")
        self.assertEqual(payload["ticker"], "MSFT")

    def test_payload_uses_supplied_title_without_sec_lookup(self) -> None:
        with patch("agents.research_payload.lookup_company") as lookup:
            payload = company_details_agent._payload_from_input(
                {
                    "company": "MSFT",
                    "title": "Microsoft Corporation",
                    "ticker": "MSFT",
                }
            )

        lookup.assert_not_called()
        self.assertEqual(payload["title"], "Microsoft Corporation")
        self.assertEqual(payload["ticker"], "MSFT")

    def test_comps_payload_reads_adk_content_text_part(self) -> None:
        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    text='{"company": "NFLX", "title": "NETFLIX INC", "ticker": "NFLX"}'
                )
            ],
        )

        payload = comps_agent._payload_from_input(content)

        self.assertEqual(payload["company"], "NFLX")
        self.assertEqual(payload["title"], "NETFLIX INC")
        self.assertEqual(payload["ticker"], "NFLX")


class ResearchOutputExtractionTest(unittest.TestCase):
    def test_latest_event_text_matches_final_agent_node_path(self) -> None:
        markdown = _latest_event_text(
            [
                {
                    "author": "comps_research_workflow",
                    "node_path": "comps_research_workflow@1/comm_agent@1",
                    "message": "# Comparable Companies\n\n| Company | Ticker |",
                    "output": None,
                }
            ],
            final_agent_name="comm_agent",
            output_key="comparables_markdown",
        )

        self.assertEqual(markdown, "# Comparable Companies\n\n| Company | Ticker |")

    def test_latest_state_delta_text_reads_output_key(self) -> None:
        markdown = _latest_state_delta_text(
            [
                {
                    "state_delta": {
                        "comparables_markdown": "```markdown\n# Comps\n```",
                    }
                }
            ],
            output_key="comparables_markdown",
        )

        self.assertEqual(markdown, "```markdown\n# Comps\n```")

    def test_latest_event_error_surfaces_adk_error(self) -> None:
        message = _latest_event_error(
            [
                {
                    "error_code": "ValueError",
                    "error_message": "No API key was provided.",
                }
            ]
        )

        self.assertEqual(message, "ValueError: No API key was provided.")


class CompsSkillIntegrationTest(unittest.TestCase):
    def test_comps_skill_uses_adk_filesystem_layout(self) -> None:
        skill_dir = (
            Path(comps_agent.__file__).resolve().parent / "skills" / "comps-analysis"
        )

        skill = load_skill_from_dir(skill_dir)

        self.assertEqual(skill.name, "comps-analysis")
        self.assertIn("Human-In-The-Loop Gate", skill.instructions)

    def test_peer_selection_agent_registers_adk_skill_toolset(self) -> None:
        self.assertTrue(
            any(
                isinstance(tool, SkillToolset)
                for tool in comps_agent.peer_selection_agent.tools
            )
        )

    def test_peer_selection_agent_does_not_mix_output_schema_with_skills(self) -> None:
        self.assertIsNone(comps_agent.peer_selection_agent.output_schema)

    def test_peer_proposal_json_text_is_validated_after_skill_agent(self) -> None:
        proposal = comps_agent._coerce_peer_proposal(
            """
            ```json
            {
              "target_company": "Netflix, Inc.",
              "target_ticker": "NFLX",
              "as_of_date": "2026-05-16",
              "selection_methodology": "Streaming and media public comps.",
              "suggested_peers": [
                {
                  "company_name": "Walt Disney Company",
                  "ticker": "DIS",
                  "exchange": "NYSE",
                  "country": "US",
                  "peer_category": "core",
                  "rationale": "Large subscription streaming and content portfolio.",
                  "key_differences": "More diversified parks and linear networks."
                }
              ],
              "excluded_peers": [],
              "data_limitations": []
            }
            ```
            """
        )

        self.assertEqual(proposal.target_ticker, "NFLX")
        self.assertEqual(proposal.suggested_peers[0].ticker, "DIS")

    def test_peer_proposal_normalizes_common_model_schema_drift(self) -> None:
        proposal = comps_agent._coerce_peer_proposal(
            {
                "target_company": "Netflix, Inc.",
                "target_ticker": "NFLX",
                "as_of_date": "2026-05-16",
                "selection_methodology": "Streaming and media public comps.",
                "suggested_peers": [
                    {
                        "company_name": "Walt Disney Company",
                        "ticker": "DIS",
                        "exchange": "NYSE",
                        "country": "US",
                        "peer_category": "primary",
                        "rationale": "Large subscription streaming and content portfolio.",
                        "key_differences": "More diversified parks and linear networks.",
                    }
                ],
                "excluded_peers": [
                    {
                        "company_name": "Spotify Technology S.A.",
                        "ticker": "SPOT",
                        "exchange": "NYSE",
                        "country": "LU",
                        "peer_category": "excluded",
                        "rationale": "Subscription media but primarily audio.",
                        "key_differences": "Audio-first economics differ from video streaming.",
                    },
                    {
                        "company_name": "Roblox Corporation",
                        "ticker": "RBLX",
                        "exchange": "NYSE",
                        "country": "US",
                        "peer_category": "n/a",
                        "rationale": "Digital entertainment but not a video streaming comp.",
                        "key_differences": "User-generated gaming platform economics.",
                    }
                ],
                "data_limitations": "This proposal requires human review and approval.",
            }
        )

        self.assertEqual(proposal.suggested_peers[0].peer_category, "core")
        self.assertEqual(proposal.excluded_peers[0].peer_category, "broader_reference")
        self.assertEqual(proposal.excluded_peers[1].peer_category, "broader_reference")
        self.assertEqual(
            proposal.data_limitations,
            ["This proposal requires human review and approval."],
        )


if __name__ == "__main__":
    unittest.main()
