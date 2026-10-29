from __future__ import annotations

import unittest
import asyncio

from google.adk import Event
from google.adk import Workflow
from google.adk.agents.context import Context
from google.adk.sessions import InMemorySessionService

from api.research_services import AsyncResearchService
from api.research_services import ResearchWorkflowConfig
from api.research_services import ResearchWorkflowRequest
from api.runtimes.mna_dcf_valuation import CreateDcfWorkflowRequest
from api.runtimes.mna_dcf_valuation import DcfValuationRuntime
from api.runtimes.mna_dcf_valuation import RunMonteCarloRequest
from api.runtimes.mna_dcf_valuation import SubmitDcfAssumptionsRequest
from data.sample_data import build_sample_financial_snapshot
from data.sample_data import default_dcf_assumptions
from data.sample_data import default_monte_carlo_distributions
from data.sec_normalizer import build_financial_snapshot as build_sec_financial_snapshot
from valuation.dcf_tool import run_dcf_valuation
from valuation.sensitivity import run_dcf_sensitivity
from valuation.schemas import DCFUserAssumptions
from valuation.schemas import DCFValuationParams
from valuation.schemas import ResolvedCompany


def build_sample_params() -> DCFValuationParams:
    snapshot = build_sample_financial_snapshot()
    assumptions = default_dcf_assumptions(snapshot)
    return DCFValuationParams(
        risk_free_rate=assumptions.risk_free_rate,
        ERP=assumptions.ERP,
        equity_value=assumptions.equity_value,
        debt_value=snapshot.debt_value_book,
        unlevered_beta=assumptions.unlevered_beta,
        terminal_unlevered_beta=assumptions.terminal_unlevered_beta,
        year_beta_begins_to_converge_to_terminal_beta=1,
        current_pretax_cost_of_debt=assumptions.current_pretax_cost_of_debt,
        terminal_pretax_cost_of_debt=assumptions.terminal_pretax_cost_of_debt,
        year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt=3,
        current_effective_tax_rate=snapshot.current_effective_tax_rate,
        marginal_tax_rate=assumptions.marginal_tax_rate,
        year_effective_tax_rate_begin_to_converge_marginal_tax_rate=1,
        revenue_base=snapshot.revenue_base,
        revenue_growth_rate_cycle1_begin=(
            assumptions.revenue_growth_rate_cycle1_begin
        ),
        revenue_growth_rate_cycle1_end=assumptions.revenue_growth_rate_cycle1_end,
        revenue_growth_rate_cycle2_begin=(
            assumptions.revenue_growth_rate_cycle2_begin
        ),
        revenue_growth_rate_cycle2_end=assumptions.revenue_growth_rate_cycle2_end,
        revenue_growth_rate_cycle3_begin=(
            assumptions.revenue_growth_rate_cycle3_begin
        ),
        revenue_growth_rate_cycle3_end=assumptions.revenue_growth_rate_cycle3_end,
        revenue_convergence_periods_cycle1=(
            assumptions.revenue_convergence_periods_cycle1
        ),
        revenue_convergence_periods_cycle2=(
            assumptions.revenue_convergence_periods_cycle2
        ),
        revenue_convergence_periods_cycle3=(
            assumptions.revenue_convergence_periods_cycle3
        ),
        length_of_cycle1=assumptions.length_of_cycle1,
        length_of_cycle2=assumptions.length_of_cycle2,
        length_of_cycle3=assumptions.length_of_cycle3,
        current_sales_to_capital_ratio=assumptions.current_sales_to_capital_ratio,
        terminal_sales_to_capital_ratio=assumptions.terminal_sales_to_capital_ratio,
        year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital=1,
        current_operating_margin=snapshot.current_operating_margin,
        terminal_operating_margin=assumptions.terminal_operating_margin,
        year_operating_margin_begins_to_converge_to_terminal_operating_margin=1,
        additional_return_on_cost_of_capital_in_perpetuity=(
            assumptions.additional_return_on_cost_of_capital_in_perpetuity
        ),
        cash_and_non_operating_asset=snapshot.cash_and_non_operating_asset,
        current_invested_capital=snapshot.current_invested_capital,
    )


class DcfValuationToolTest(unittest.TestCase):
    def test_sample_financial_snapshot_includes_operating_flow_fields(self) -> None:
        snapshot = build_sample_financial_snapshot()

        self.assertAlmostEqual(snapshot.gross_profit, 3.759, places=3)
        self.assertAlmostEqual(snapshot.cost_of_revenue, 5.525, places=3)
        self.assertAlmostEqual(snapshot.operating_expenses, 2.3664, places=3)
        self.assertAlmostEqual(snapshot.selling_general_and_admin_expense, 0.832, places=3)
        self.assertAlmostEqual(snapshot.depreciation_amortization, 0.300, places=3)
        self.assertAlmostEqual(snapshot.income_tax_expense, 0.3342, places=3)

    def test_sec_normalizer_derives_operating_flow_fields(self) -> None:
        def usd_fact(value: float) -> dict:
            return {
                "units": {
                    "USD": [
                        {
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2025,
                            "filed": "2026-02-15",
                            "accn": "000-test",
                            "val": value,
                        }
                    ]
                }
            }

        company = ResolvedCompany(
            query="DYN",
            title="Dynamic Test Corp.",
            ticker="DYN",
            cik=123456,
            cik_padded="CIK0000123456",
            data_source="sec",
        )
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": usd_fact(100_000_000_000),
                    "CostOfRevenue": usd_fact(40_000_000_000),
                    "OperatingIncomeLoss": usd_fact(20_000_000_000),
                    "SellingGeneralAndAdministrativeExpense": usd_fact(10_000_000_000),
                    "DepreciationDepletionAndAmortization": usd_fact(2_000_000_000),
                    "IncomeTaxExpenseBenefit": usd_fact(5_000_000_000),
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes": usd_fact(25_000_000_000),
                    "CashAndCashEquivalentsAtCarryingValue": usd_fact(8_000_000_000),
                    "LongTermDebt": usd_fact(12_000_000_000),
                }
            }
        }

        snapshot = build_sec_financial_snapshot(company, facts)

        self.assertEqual(snapshot.ticker, "DYN")
        self.assertAlmostEqual(snapshot.revenue_base, 100.0)
        self.assertAlmostEqual(snapshot.gross_profit, 60.0)
        self.assertAlmostEqual(snapshot.cost_of_revenue, 40.0)
        self.assertAlmostEqual(snapshot.total_costs_and_expenses, 80.0)
        self.assertAlmostEqual(snapshot.operating_expenses, 40.0)
        self.assertAlmostEqual(snapshot.other_operating_expenses, 28.0)
        self.assertAlmostEqual(snapshot.current_effective_tax_rate, 0.20)

    def test_sec_normalizer_anchors_to_latest_10k_period(self) -> None:
        def usd_facts(*rows: dict) -> dict:
            return {"units": {"USD": list(rows)}}

        def annual(
            value: float,
            *,
            start: str | None,
            end: str,
            accn: str = "0000950170-25-087926",
            fy: int = 2025,
            filed: str = "2025-06-18",
        ) -> dict:
            return {
                "form": "10-K",
                "fp": "FY",
                "fy": fy,
                "filed": filed,
                "accn": accn,
                "start": start,
                "end": end,
                "val": value,
            }

        company = ResolvedCompany(
            query="ORCL",
            title="ORACLE CORP",
            ticker="ORCL",
            cik=1341439,
            cik_padded="CIK0001341439",
            data_source="sec",
        )
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "accessionNumber": ["0000950170-25-087926"],
                    "filingDate": ["2025-06-18"],
                    "reportDate": ["2025-05-31"],
                    "primaryDocument": ["orcl-20250531.htm"],
                }
            }
        }
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": usd_facts(
                        annual(49_954_000_000, start="2022-06-01", end="2023-05-31"),
                        annual(52_961_000_000, start="2023-06-01", end="2024-05-31"),
                        annual(57_399_000_000, start="2024-06-01", end="2025-05-31"),
                    ),
                    "OperatingIncomeLoss": usd_facts(
                        annual(13_093_000_000, start="2022-06-01", end="2023-05-31"),
                        annual(15_353_000_000, start="2023-06-01", end="2024-05-31"),
                        annual(17_678_000_000, start="2024-06-01", end="2025-05-31"),
                    ),
                    "GrossProfit": usd_facts(
                        annual(
                            22_410_000_000,
                            start="2015-06-01",
                            end="2016-05-31",
                            accn="0001193125-18-201034",
                            fy=2018,
                            filed="2018-06-22",
                        )
                    ),
                    "CostOfRevenue": usd_facts(
                        annual(
                            880_000_000,
                            start="2009-06-01",
                            end="2010-05-31",
                            accn="0001193125-11-174819",
                            fy=2011,
                            filed="2011-06-28",
                        )
                    ),
                    "CostsAndExpenses": usd_facts(
                        annual(39_721_000_000, start="2024-06-01", end="2025-05-31")
                    ),
                    "SellingAndMarketingExpense": usd_facts(
                        annual(8_651_000_000, start="2024-06-01", end="2025-05-31")
                    ),
                    "GeneralAndAdministrativeExpense": usd_facts(
                        annual(1_602_000_000, start="2024-06-01", end="2025-05-31")
                    ),
                    "IncomeTaxExpenseBenefit": usd_facts(
                        annual(623_000_000, start="2022-06-01", end="2023-05-31"),
                        annual(1_717_000_000, start="2024-06-01", end="2025-05-31"),
                    ),
                    "CashAndCashEquivalentsAtCarryingValue": usd_facts(
                        annual(10_454_000_000, start=None, end="2024-05-31"),
                        annual(10_786_000_000, start=None, end="2025-05-31"),
                    ),
                    "DebtInstrumentCarryingAmount": usd_facts(
                        annual(92_917_000_000, start=None, end="2025-05-31")
                    ),
                    "DebtCurrent": usd_facts(
                        annual(7_271_000_000, start=None, end="2025-05-31")
                    ),
                    "StockholdersEquity": usd_facts(
                        annual(20_451_000_000, start=None, end="2025-05-31")
                    ),
                    "WeightedAverageNumberOfDilutedSharesOutstanding": {
                        "units": {
                            "shares": [
                                annual(
                                    2_866_000_000,
                                    start="2024-06-01",
                                    end="2025-05-31",
                                )
                            ]
                        }
                    },
                }
            }
        }

        snapshot = build_sec_financial_snapshot(company, facts, submissions)

        self.assertEqual(snapshot.fiscal_year, 2025)
        self.assertEqual(snapshot.filing_date.isoformat(), "2025-06-18")
        self.assertAlmostEqual(snapshot.revenue_base, 57.399)
        self.assertAlmostEqual(snapshot.operating_income, 17.678)
        self.assertIsNone(snapshot.gross_profit)
        self.assertIsNone(snapshot.cost_of_revenue)
        self.assertAlmostEqual(snapshot.total_costs_and_expenses, 39.721)
        self.assertAlmostEqual(snapshot.selling_general_and_admin_expense, 8.651)
        self.assertAlmostEqual(snapshot.income_tax_expense, 1.717)
        self.assertAlmostEqual(snapshot.cash_and_non_operating_asset, 10.786)
        self.assertAlmostEqual(snapshot.debt_value_book, 92.917)
        self.assertAlmostEqual(snapshot.current_invested_capital, 20.451)
        self.assertAlmostEqual(snapshot.shares_outstanding, 2.866)
        self.assertTrue(
            any("latest annual filing" in note for note in snapshot.notes)
        )

    def test_user_assumption_convergence_defaults_to_cycle_lengths(self) -> None:
        assumptions = default_dcf_assumptions(build_sample_financial_snapshot())

        self.assertEqual(
            assumptions.revenue_convergence_periods_cycle1,
            assumptions.length_of_cycle1,
        )
        self.assertEqual(
            assumptions.revenue_convergence_periods_cycle2,
            assumptions.length_of_cycle2,
        )
        self.assertEqual(
            assumptions.revenue_convergence_periods_cycle3,
            assumptions.length_of_cycle3,
        )

    def test_user_assumption_accepts_explicit_convergence_periods(self) -> None:
        assumptions = default_dcf_assumptions(build_sample_financial_snapshot())
        explicit = DCFUserAssumptions.model_validate(
            {
                **assumptions.model_dump(mode="json"),
                "revenue_convergence_periods_cycle1": 3,
                "revenue_convergence_periods_cycle2": 4,
                "revenue_convergence_periods_cycle3": 5,
            }
        )

        self.assertEqual(explicit.revenue_convergence_periods_cycle1, 3)
        self.assertEqual(explicit.revenue_convergence_periods_cycle2, 4)
        self.assertEqual(explicit.revenue_convergence_periods_cycle3, 5)

    def test_sample_point_estimate_runs_with_correct_terminal_discounting(self) -> None:
        result = run_dcf_valuation(build_sample_params())

        self.assertEqual(result["status"], "success")
        self.assertAlmostEqual(result["intrinsic_equity_value"], 39.2394, places=3)
        self.assertEqual(len(result["valuation_table"]), 19)
        self.assertEqual(result["valuation_table"][-1]["is_terminal"], True)
        self.assertGreater(result["valuation_table"][-1]["cumWACC"], 1.0)

    def test_terminal_growth_above_risk_free_is_rejected(self) -> None:
        params = build_sample_params().model_copy(
            update={"revenue_growth_rate_cycle3_end": 0.05},
        )
        result = run_dcf_valuation(params.model_dump(mode="json"))

        self.assertEqual(result["status"], "invalid_inputs")

    def test_sensitivity_analysis_runs_key_driver_cases(self) -> None:
        params = build_sample_params()
        base_result = run_dcf_valuation(params)
        result = run_dcf_sensitivity(params, base_result)

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["base_case"]["intrinsic_equity_value"],
            base_result["intrinsic_equity_value"],
        )
        self.assertGreaterEqual(len(result["one_factor_sensitivities"]), 6)
        self.assertGreater(len(result["top_value_drivers"]), 0)
        self.assertEqual(
            result["matrices"][0]["name"],
            "Terminal Growth x Terminal Operating Margin",
        )


class DcfValuationRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def build_runtime(self) -> DcfValuationRuntime:
        return DcfValuationRuntime(session_service_factory=InMemorySessionService)

    async def test_sample_workflow_requests_assumptions_then_runs_dcf(self) -> None:
        runtime = self.build_runtime()
        record = await runtime.create_workflow(
            CreateDcfWorkflowRequest(
                actor_id="sarah.lee",
                company="CMG",
                scenario_name="Base Case",
                data_source="sample",
            )
        )

        self.assertEqual(record.status, "awaiting_assumptions")
        self.assertIsNotNone(record.pending_input)
        self.assertEqual(record.financial_snapshot["revenue_base"], 9.284)

        assumptions = default_dcf_assumptions(build_sample_financial_snapshot())
        completed = await runtime.submit_assumptions(
            record.request_id,
            SubmitDcfAssumptionsRequest(
                actor_id="sarah.lee",
                assumptions=assumptions,
            ),
        )

        self.assertEqual(completed.status, "valuation_complete")
        self.assertIsNone(completed.pending_input)
        self.assertEqual(completed.assumptions["provided_by"], "sarah.lee")
        self.assertAlmostEqual(
            completed.valuation_result["intrinsic_equity_value"],
            39.2394,
            places=3,
        )
        self.assertIsNotNone(completed.sensitivity_result)
        self.assertEqual(completed.sensitivity_result["status"], "success")
        self.assertGreater(len(completed.sensitivity_result["top_value_drivers"]), 0)
        self.assertEqual(
            completed.resume_payloads[-1]["payload"]["parts"][0]["functionResponse"]["id"],
            f"dcf_assumptions:{record.request_id}",
        )

    async def test_monte_carlo_run_is_persisted_on_session_state(self) -> None:
        runtime = self.build_runtime()
        record = await runtime.create_workflow(
            CreateDcfWorkflowRequest(actor_id="sarah.lee", data_source="sample")
        )
        assumptions = default_dcf_assumptions(build_sample_financial_snapshot())
        completed = await runtime.submit_assumptions(
            record.request_id,
            SubmitDcfAssumptionsRequest(
                actor_id="sarah.lee",
                assumptions=assumptions,
            ),
        )

        with_mc = await runtime.run_monte_carlo(
            completed.request_id,
            RunMonteCarloRequest(
                actor_id="sarah.lee",
                sample_size=25,
                seed=11,
                distributions=default_monte_carlo_distributions(assumptions),
            ),
        )

        self.assertEqual(len(with_mc.monte_carlo_runs), 1)
        self.assertEqual(with_mc.monte_carlo_runs[0]["result"]["status"], "success")
        self.assertGreater(
            with_mc.monte_carlo_runs[0]["result"]["successful_samples"],
            0,
        )


class ResearchWorkflowServiceTest(unittest.IsolatedAsyncioTestCase):
    def build_service(self) -> AsyncResearchService:
        def company_node(ctx: Context, node_input: ResearchWorkflowRequest) -> Event:
            ctx.state["title"] = node_input.title
            markdown = f"# Company Background: {node_input.title}"
            ctx.state["company_background_markdown"] = f"```markdown\n{markdown}\n```"
            return Event(message=markdown, output=markdown)

        def comps_node(ctx: Context, node_input: ResearchWorkflowRequest) -> Event:
            ctx.state["title"] = node_input.title
            markdown = f"# Comparable Companies: {node_input.title}\n\n| Company | Ticker |\n|---|---|"
            ctx.state["comparables_markdown"] = f"```markdown\n{markdown}\n```"
            return Event(message=markdown, output=markdown)

        return AsyncResearchService(
            session_service_factory=InMemorySessionService,
            configs=(
                ResearchWorkflowConfig(
                    workflow_type="company_background",
                    source_agent="company_details_research_agent",
                    final_agent_name="company_node",
                    app_name="test_company_details",
                    root_agent=Workflow(
                        name="test_company_details",
                        edges=[("START", company_node)],
                    ),
                    output_key="company_background_markdown",
                    job_prefix="company-bg",
                ),
                ResearchWorkflowConfig(
                    workflow_type="comparables",
                    source_agent="comps_agent",
                    final_agent_name="comps_node",
                    app_name="test_comps",
                    root_agent=Workflow(
                        name="test_comps",
                        edges=[("START", comps_node)],
                    ),
                    output_key="comparables_markdown",
                    job_prefix="comps",
                ),
            ),
        )

    async def _wait_for_completion(
        self,
        service: AsyncResearchService,
        job_id: str,
    ):
        for _ in range(20):
            record = service.get_job(job_id)
            if record.status in {"completed", "failed"}:
                return record
            await asyncio.sleep(0.05)
        self.fail(f"Research workflow {job_id} did not finish")

    async def test_company_background_workflow_generates_markdown(self) -> None:
        service = self.build_service()
        record = service.start_company_background(
            ResearchWorkflowRequest(
                company="MSFT",
                title="Microsoft Corporation",
                ticker="MSFT",
                scenario_name="Base Case",
            )
        )

        completed = await self._wait_for_completion(service, record.job_id)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.source_agent, "company_details_research_agent")
        self.assertEqual(completed.title, "Microsoft Corporation")
        self.assertIn("# Company Background", completed.markdown)
        self.assertIn("Microsoft Corporation", completed.markdown)
        self.assertNotIn("Chipotle", completed.markdown)
        self.assertNotIn("```", completed.markdown)
        self.assertTrue(
            all("# Company Background" not in str(event.get("message")) for event in completed.events)
        )

    async def test_comparables_workflow_generates_markdown(self) -> None:
        service = self.build_service()
        record = service.start_comparables(
            ResearchWorkflowRequest(
                company="MSFT",
                title="Microsoft Corporation",
                ticker="MSFT",
                scenario_name="Base Case",
            )
        )

        completed = await self._wait_for_completion(service, record.job_id)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.source_agent, "comps_agent")
        self.assertEqual(completed.title, "Microsoft Corporation")
        self.assertIn("# Comparable Companies", completed.markdown)
        self.assertIn("| Company | Ticker |", completed.markdown)
        self.assertIn("Microsoft Corporation", completed.markdown)
        self.assertNotIn("Chipotle", completed.markdown)
        self.assertNotIn("```", completed.markdown)
        self.assertTrue(
            all("# Comparable Companies" not in str(event.get("message")) for event in completed.events)
        )


if __name__ == "__main__":
    unittest.main()
