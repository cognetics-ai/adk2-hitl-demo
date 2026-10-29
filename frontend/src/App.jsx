import {
  BarChart3,
  Building2,
  CheckCircle2,
  Database,
  Download,
  FileText,
  LineChart,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  SlidersHorizontal,
  Table2,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const DEFAULT_ACTOR_ID = "sarah.lee";

const WORKFLOW_FORM = {
  company: "CMG",
  scenario_name: "Base Case",
  data_source: "sample",
};

const TABS = [
  { id: "company", label: "Company Background", icon: Building2 },
  { id: "dcf", label: "DCF Evaluation Workbench", icon: BarChart3 },
  { id: "comparables", label: "Comparables", icon: Table2 },
];

const ASSUMPTION_GROUPS = [
  {
    title: "Market and WACC",
    fields: [
      ["risk_free_rate", "Risk-free rate", "percent"],
      ["ERP", "Equity risk premium", "percent"],
      ["equity_value", "Current equity value", "currency"],
      ["unlevered_beta", "Unlevered beta", "multiple"],
      ["terminal_unlevered_beta", "Terminal beta", "multiple"],
      ["current_pretax_cost_of_debt", "Pre-tax cost of debt", "percent"],
      ["terminal_pretax_cost_of_debt", "Terminal cost of debt", "percent"],
      ["marginal_tax_rate", "Marginal tax rate", "percent"],
    ],
  },
  {
    title: "Revenue Phases",
    fields: [
      ["revenue_growth_rate_cycle1_begin", "Cycle 1 growth start", "percent"],
      ["revenue_growth_rate_cycle1_end", "Cycle 1 growth end", "percent"],
      ["length_of_cycle1", "Cycle 1 years", "integer"],
      ["revenue_convergence_periods_cycle1", "Cycle 1 convergence year", "integer"],
      ["revenue_growth_rate_cycle2_begin", "Cycle 2 growth start", "percent"],
      ["revenue_growth_rate_cycle2_end", "Cycle 2 growth end", "percent"],
      ["length_of_cycle2", "Cycle 2 years", "integer"],
      ["revenue_convergence_periods_cycle2", "Cycle 2 convergence year", "integer"],
      ["revenue_growth_rate_cycle3_begin", "Cycle 3 growth start", "percent"],
      ["revenue_growth_rate_cycle3_end", "Terminal growth", "percent"],
      ["length_of_cycle3", "Cycle 3 years", "integer"],
      ["revenue_convergence_periods_cycle3", "Cycle 3 convergence year", "integer"],
    ],
  },
  {
    title: "Operating Model",
    fields: [
      ["current_sales_to_capital_ratio", "Current sales / capital", "multiple"],
      ["terminal_sales_to_capital_ratio", "Terminal sales / capital", "multiple"],
      ["terminal_operating_margin", "Terminal operating margin", "percent"],
      [
        "additional_return_on_cost_of_capital_in_perpetuity",
        "Excess return in perpetuity",
        "percent",
      ],
      ["current_invested_capital_override", "Invested capital override", "currency"],
    ],
  },
];

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `$${Number(value).toLocaleString(undefined, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}bn`;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatValue(value, type) {
  if (type === "percent") return formatPercent(value);
  if (type === "currency") return formatMoney(value);
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function formatSensitivityInput(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  if (unit === "percent") return formatPercent(value);
  if (unit === "multiple") return `${Number(value).toFixed(2)}x`;
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function formatSignedMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : Number(value) < 0 ? "-" : "";
  return `${sign}${formatMoney(Math.abs(Number(value)))}`;
}

function statusLabel(status) {
  if (status === "awaiting_assumptions") return "Awaiting assumptions";
  if (status === "awaiting_peer_review") return "Awaiting peer review";
  if (status === "valuation_complete") return "Valuation complete";
  if (status === "normalized") return "Financials normalized";
  if (status === "queued") return "Queued";
  if (status === "running") return "Running";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  return status || "Not started";
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

function JsonBlock({ value }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

function Metric({ label, value, tone }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function JobStatusPill({ status }) {
  return <em className={`status ${status ?? "not_started"}`}>{statusLabel(status)}</em>;
}

function InlineMarkdown({ text }) {
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function parseTable(lines, startIndex) {
  const rows = [];
  let index = startIndex;
  while (index < lines.length && lines[index].trim().startsWith("|")) {
    const cells = lines[index]
      .trim()
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim());
    const isSeparator = cells.every((cell) => /^:?-{3,}:?$/.test(cell));
    if (!isSeparator) rows.push(cells);
    index += 1;
  }
  return { rows, nextIndex: index };
}

function normalizeMarkdown(markdown) {
  const text = String(markdown ?? "").trim();
  const fenceMatch = text.match(/^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$/i);
  return fenceMatch ? fenceMatch[1].trim() : text;
}

function MarkdownDocument({ markdown }) {
  if (!markdown) {
    return (
      <div className="empty-detail">
        <Search size={28} />
        <p>Run the workbench to generate this agent output.</p>
      </div>
    );
  }

  const lines = normalizeMarkdown(markdown).split(/\r?\n/);
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^`{3}/.test(trimmed)) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^`{3}/.test(lines[index].trim())) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(
        <pre className="markdown-code" key={`code-${index}`}>
          {codeLines.join("\n")}
        </pre>,
      );
      continue;
    }

    if (trimmed.startsWith("|")) {
      const { rows, nextIndex } = parseTable(lines, index);
      const [header = [], ...body] = rows;
      blocks.push(
        <div className="markdown-table" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {header.map((cell) => (
                  <th key={cell}>{cell}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, rowIndex) => (
                <tr key={`${row.join("-")}-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${cell}-${cellIndex}`}>
                      <InlineMarkdown text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      index = nextIndex;
      continue;
    }

    if (trimmed.startsWith("- ")) {
      const items = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(lines[index].trim().slice(2));
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item) => (
            <li key={item}>
              <InlineMarkdown text={item} />
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^\d+\.\s/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s/, ""));
        index += 1;
      }
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item) => (
            <li key={item}>
              <InlineMarkdown text={item} />
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    if (trimmed.startsWith("### ")) {
      blocks.push(
        <h3 key={`h3-${index}`}>
          <InlineMarkdown text={trimmed.slice(4)} />
        </h3>,
      );
      index += 1;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      blocks.push(
        <h2 key={`h2-${index}`}>
          <InlineMarkdown text={trimmed.slice(3)} />
        </h2>,
      );
      index += 1;
      continue;
    }

    if (trimmed.startsWith("# ")) {
      blocks.push(
        <h1 key={`h1-${index}`}>
          <InlineMarkdown text={trimmed.slice(2)} />
        </h1>,
      );
      index += 1;
      continue;
    }

    blocks.push(
      <p key={`p-${index}`}>
        <InlineMarkdown text={trimmed} />
      </p>,
    );
    index += 1;
  }

  return <article className="markdown-body">{blocks}</article>;
}

function visibleResearchEvents(events = [], markdown = "") {
  const renderedMarkdown = markdown ? normalizeMarkdown(markdown) : "";
  return events.filter((event) => {
    const message = String(event?.message ?? "").trim();
    if (!message) return false;
    if (renderedMarkdown && normalizeMarkdown(message) === renderedMarkdown) return false;
    if (message.includes("\n") || message.length > 280) return false;
    return true;
  });
}

function ResearchPanel({ job, title, icon: Icon }) {
  const visibleEvents = visibleResearchEvents(job?.events, job?.markdown);
  return (
    <section className="panel research-panel">
      <div className="research-header">
        <div className="panel-title">
          <Icon size={18} />
          <h2>{title}</h2>
        </div>
        <JobStatusPill status={job?.status} />
      </div>
      {job?.error && <div className="error-banner compact">{job.error}</div>}
      <MarkdownDocument markdown={job?.markdown} />
      {visibleEvents.length > 0 && (
        <div className="research-events">
          {visibleEvents.map((event) => (
            <span key={`${event.timestamp}-${event.message}`}>{event.message}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function emptyPeer() {
  return {
    company_name: "",
    ticker: "",
    exchange: "",
    country: "United States",
    peer_category: "core",
    rationale: "",
    key_differences: "",
  };
}

function normalizedPeer(peer) {
  const ticker = String(peer.ticker ?? "").trim();
  const companyName = String(peer.company_name ?? "").trim() || ticker;
  return {
    company_name: companyName,
    ticker: ticker || null,
    exchange: String(peer.exchange ?? "").trim() || null,
    country: String(peer.country ?? "").trim() || null,
    peer_category: peer.peer_category || "core",
    rationale: String(peer.rationale ?? "").trim() || "User-selected comparable.",
    key_differences: String(peer.key_differences ?? "").trim() || null,
  };
}

function parsePeerProposal(value) {
  if (!value) return null;
  if (typeof value === "object") {
    return value.suggested_peers ? value : null;
  }
  const text = String(value).trim();
  if (!text) return null;
  const fenceMatch = text.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  const jsonText = fenceMatch ? fenceMatch[1].trim() : text;
  try {
    const parsed = JSON.parse(jsonText);
    return parsed?.suggested_peers ? parsed : null;
  } catch {
    return null;
  }
}

function peerProposalFromJob(job) {
  return (
    parsePeerProposal(job?.pending_input?.payload?.proposal) ??
    parsePeerProposal(job?.peer_proposal) ??
    parsePeerProposal(job?.markdown)
  );
}

function PeerProposalSummary({ proposal }) {
  return (
    <div className="peer-summary">
      <div>
        <span>Target</span>
        <strong>{proposal.target_company || "-"}</strong>
      </div>
      <div>
        <span>Ticker</span>
        <strong>{proposal.target_ticker || "-"}</strong>
      </div>
      <div>
        <span>As of</span>
        <strong>{proposal.as_of_date || "-"}</strong>
      </div>
      <div className="peer-methodology">
        <span>Selection methodology</span>
        <p>{proposal.selection_methodology || "-"}</p>
      </div>
    </div>
  );
}

function PeerReviewPanel({ job, onSubmit, busy }) {
  const proposal = peerProposalFromJob(job);
  const canSubmit = Boolean(job?.pending_input);
  const [peers, setPeers] = useState([]);
  const [comment, setComment] = useState("");
  const [lookupState, setLookupState] = useState({});

  useEffect(() => {
    const suggested = proposal?.suggested_peers ?? [];
    setPeers(suggested.length > 0 ? suggested.map((peer) => ({ ...emptyPeer(), ...peer })) : [emptyPeer()]);
    setLookupState({});
  }, [job?.pending_input?.interrupt_id, job?.job_id]);

  if (!proposal) return null;

  function updatePeer(index, field, value) {
    setPeers((current) =>
      current.map((peer, peerIndex) => (peerIndex === index ? { ...peer, [field]: value } : peer)),
    );
  }

  function removePeer(index) {
    setPeers((current) => current.filter((_, peerIndex) => peerIndex !== index));
  }

  async function fetchPeer(index) {
    const peer = peers[index];
    const query = String(peer?.ticker || peer?.company_name || "").trim();
    if (!query) {
      setLookupState((current) => ({ ...current, [index]: { error: "Enter a name or ticker first." } }));
      return;
    }
    setLookupState((current) => ({ ...current, [index]: { loading: true } }));
    try {
      const result = await api(`/api/company-lookup?query=${encodeURIComponent(query)}`);
      if (result.status !== "success") {
        throw new Error(result.message || "No SEC company match found.");
      }
      setPeers((current) =>
        current.map((currentPeer, peerIndex) =>
          peerIndex === index
            ? {
                ...currentPeer,
                company_name: result.company_name || currentPeer.company_name,
                ticker: result.ticker || currentPeer.ticker,
                exchange: result.exchange || currentPeer.exchange || "",
                country: result.country || currentPeer.country || "United States",
              }
            : currentPeer,
        ),
      );
      setLookupState((current) => ({ ...current, [index]: { message: "Matched SEC company." } }));
    } catch (err) {
      setLookupState((current) => ({ ...current, [index]: { error: err.message } }));
    }
  }

  function submitReview() {
    const selected = peers.map(normalizedPeer).filter((peer) => peer.company_name || peer.ticker);
    onSubmit({ approved: true, selected_peers: selected, comment });
  }

  return (
    <section className="peer-review">
      <div className="peer-review-header">
        <div>
          <h3>{canSubmit ? "Peer Review Required" : "Peer Proposal"}</h3>
          <p>
            {canSubmit
              ? "Edit the comparable-company set before SEC/XBRL collection starts."
              : "This proposal is shown as structured data because the workflow is not waiting for peer review."}
          </p>
        </div>
        <button className="ghost" type="button" disabled={!canSubmit} onClick={() => setPeers((current) => [...current, emptyPeer()])}>
          <Plus size={16} />
          Add peer
        </button>
      </div>
      <PeerProposalSummary proposal={proposal} />
      <div className="peer-table-scroll">
        <table className="peer-table">
          <thead>
            <tr>
              <th>Company name</th>
              <th>Ticker</th>
              <th>Exchange</th>
              <th>Country</th>
              <th>Category</th>
              <th>Rationale</th>
              <th>Key differences</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((peer, index) => {
              const lookup = lookupState[index] ?? {};
              return (
                <tr key={`${peer.company_name}-${peer.ticker}-${index}`}>
                  <td>
                    <input
                      disabled={!canSubmit}
                      placeholder="Company or ticker"
                      value={peer.company_name ?? ""}
                      onChange={(event) => updatePeer(index, "company_name", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      disabled={!canSubmit}
                      placeholder="Ticker"
                      value={peer.ticker ?? ""}
                      onChange={(event) => updatePeer(index, "ticker", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      disabled={!canSubmit}
                      placeholder="Exchange"
                      value={peer.exchange ?? ""}
                      onChange={(event) => updatePeer(index, "exchange", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      disabled={!canSubmit}
                      placeholder="Country"
                      value={peer.country ?? ""}
                      onChange={(event) => updatePeer(index, "country", event.target.value)}
                    />
                  </td>
                  <td>
                    <select disabled={!canSubmit} value={peer.peer_category ?? "core"} onChange={(event) => updatePeer(index, "peer_category", event.target.value)}>
                      <option value="core">Core</option>
                      <option value="secondary">Secondary</option>
                      <option value="broader_reference">Broader</option>
                    </select>
                  </td>
                  <td>
                    <textarea
                      disabled={!canSubmit}
                      value={peer.rationale ?? ""}
                      onChange={(event) => updatePeer(index, "rationale", event.target.value)}
                    />
                  </td>
                  <td>
                    <textarea
                      disabled={!canSubmit}
                      value={peer.key_differences ?? ""}
                      onChange={(event) => updatePeer(index, "key_differences", event.target.value)}
                    />
                  </td>
                  <td>
                    <div className="peer-actions">
                      <button className="icon-button" type="button" disabled={!canSubmit || lookup.loading} onClick={() => fetchPeer(index)} aria-label="Fetch company details" title="Fetch company details">
                        <RefreshCw size={15} />
                      </button>
                      <button className="icon-button" type="button" disabled={!canSubmit} onClick={() => removePeer(index)} aria-label="Remove peer" title="Remove peer">
                        <Trash2 size={15} />
                      </button>
                    </div>
                    {lookup.error && <small className="lookup-error">{lookup.error}</small>}
                    {lookup.message && <small className="lookup-message">{lookup.message}</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {canSubmit && (
        <>
          <label>
            Approval comment
            <textarea value={comment} onChange={(event) => setComment(event.target.value)} />
          </label>
          <button className="primary" type="button" disabled={busy || peers.length === 0} onClick={submitReview}>
            <Send size={16} />
            Approve peers and build Excel
          </button>
        </>
      )}
    </section>
  );
}

function ComparablesPanel({ job, onSubmitPeers, busy }) {
  const visibleEvents = visibleResearchEvents(job?.events, job?.markdown);
  const canDownload = Boolean(job?.comps_excel_artifact && job?.job_id);
  const proposal = peerProposalFromJob(job);
  const showProposalReview = Boolean(proposal && !job?.comps_excel_artifact);
  function downloadExcel() {
    if (!job?.job_id) return;
    window.location.href = `${API_BASE}/api/comparables/${job.job_id}/excel`;
  }

  return (
    <section className="panel research-panel">
      <div className="research-header">
        <div className="panel-title">
          <Table2 size={18} />
          <h2>Comparables</h2>
        </div>
        <div className="research-actions">
          {canDownload && (
            <button className="ghost" type="button" onClick={downloadExcel}>
              <Download size={16} />
              Excel
            </button>
          )}
          <JobStatusPill status={job?.status} />
        </div>
      </div>
      {job?.error && <div className="error-banner compact">{job.error}</div>}
      {showProposalReview ? (
        <PeerReviewPanel job={job} onSubmit={onSubmitPeers} busy={busy} />
      ) : (
        <MarkdownDocument markdown={job?.markdown} />
      )}
      {visibleEvents.length > 0 && (
        <div className="research-events">
          {visibleEvents.map((event) => (
            <span key={`${event.timestamp}-${event.message}`}>{event.message}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function WorkflowSteps({ workflow }) {
  const hasSnapshot = Boolean(workflow?.financial_snapshot);
  const hasAssumptions = Boolean(workflow?.assumptions);
  const hasResult = Boolean(workflow?.valuation_result);
  const hasSensitivity = Boolean(workflow?.sensitivity_result);
  const steps = [
    ["1", "Resolve company", Boolean(workflow?.company_record)],
    ["2", "Normalize historicals", hasSnapshot],
    ["3", "Banker assumptions", hasAssumptions],
    ["4", "Run DCF", hasResult],
    ["5", "Sensitivity", hasSensitivity],
    ["6", "Explain and store", Boolean(workflow?.valuation_explanation)],
  ];
  return (
    <div className="steps">
      {steps.map(([number, label, done], stepIndex) => (
        <div
          className={`step ${done ? "done" : stepIndex === 2 && workflow?.pending_input ? "active" : ""}`}
          key={label}
        >
          <span>{number}</span>
          <p>{label}</p>
        </div>
      ))}
    </div>
  );
}

function WorkflowList({ workflows, selectedId, onSelect }) {
  if (workflows.length === 0) {
    return (
      <div className="empty-state compact">
        <FileText size={22} />
        <p>No DCF workflows yet.</p>
      </div>
    );
  }
  return (
    <div className="workflow-list">
      {workflows.map((workflow) => (
        <button
          key={workflow.request_id}
          className={`workflow-row ${selectedId === workflow.request_id ? "active" : ""}`}
          onClick={() => onSelect(workflow.request_id)}
          type="button"
        >
          <span>
            <strong>{workflow.ticker || workflow.company || "DCF workflow"}</strong>
            <small>
              {workflow.scenario_name || "Scenario"} | {workflow.request_id}
            </small>
          </span>
          <JobStatusPill status={workflow.status} />
        </button>
      ))}
    </div>
  );
}

function formatSankeyAmount(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "$0";
  return `$${Math.round(Number(value) * 1000).toLocaleString()}`;
}

function sankeyAmount(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function sankeyOptionalAmount(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildOperatingFlow(snapshot) {
  const revenue = sankeyAmount(snapshot?.revenue_base);
  if (revenue <= 0) return null;

  const margin = sankeyOptionalAmount(snapshot?.current_operating_margin);
  const operatingProfit = Math.max(
    0,
    sankeyOptionalAmount(snapshot?.operating_income) ?? revenue * (margin ?? 0),
  );
  const reportedGrossProfit = sankeyOptionalAmount(snapshot?.gross_profit);
  const reportedCostOfRevenue = sankeyOptionalAmount(snapshot?.cost_of_revenue);
  const reportedTotalCostsAndExpenses = sankeyOptionalAmount(snapshot?.total_costs_and_expenses);
  const reportedOperatingExpenses = sankeyOptionalAmount(snapshot?.operating_expenses);
  const reportedSga = sankeyOptionalAmount(snapshot?.selling_general_and_admin_expense);
  const reportedAmortization = sankeyOptionalAmount(snapshot?.depreciation_amortization);
  const hasGrossProfitBridge =
    reportedGrossProfit !== null ||
    reportedCostOfRevenue !== null ||
    reportedOperatingExpenses !== null;

  let grossProfit =
    reportedGrossProfit ??
    (reportedCostOfRevenue !== null ? revenue - reportedCostOfRevenue : null);
  if (grossProfit === null && reportedOperatingExpenses !== null) {
    grossProfit = operatingProfit + reportedOperatingExpenses;
  }
  if (grossProfit === null) {
    grossProfit = operatingProfit;
  }
  grossProfit = Math.max(operatingProfit, Math.min(revenue, grossProfit));

  const costOfSales = Math.max(
    0,
    reportedCostOfRevenue ??
      (hasGrossProfitBridge
        ? revenue - grossProfit
        : reportedTotalCostsAndExpenses ?? revenue - operatingProfit),
  );
  const operatingExpenses = Math.max(
    0,
    hasGrossProfitBridge ? reportedOperatingExpenses ?? grossProfit - operatingProfit : 0,
  );
  const sga = Math.min(Math.max(0, reportedSga ?? 0), operatingExpenses);
  const amortization = Math.min(
    Math.max(0, reportedAmortization ?? 0),
    Math.max(0, operatingExpenses - sga),
  );
  const otherExpense = Math.max(0, operatingExpenses - sga - amortization);
  const tax = Math.max(
    0,
    sankeyOptionalAmount(snapshot?.income_tax_expense) ??
      operatingProfit * sankeyAmount(snapshot?.current_effective_tax_rate),
  );
  const afterTaxOperatingProfit = Math.max(0, operatingProfit - tax);

  return {
    revenue,
    grossProfit,
    costOfSales,
    operatingProfit,
    operatingExpenses,
    tax,
    afterTaxOperatingProfit,
    otherExpense,
    sga,
    amortization,
    hasGrossProfitBridge,
  };
}

const SANKEY_LEGEND = [
  ["flow-revenue", "Revenue"],
  ["flow-profit", "Profit / NOPAT"],
  ["flow-cost", "Costs / expenses"],
  ["flow-expense", "Operating expenses"],
  ["flow-tax", "Tax"],
];

function SankeyLegend() {
  return (
    <div className="sankey-legend" aria-label="Sankey legend">
      {SANKEY_LEGEND.map(([tone, label]) => (
        <span key={tone}>
          <i className={tone} aria-hidden="true" />
          {label}
        </span>
      ))}
    </div>
  );
}

function SankeyLabel({ x, y, width, label, value, anchor = "middle" }) {
  const xPosition = Number(x);
  const yPosition = Number(y);
  const labelWidth = Number(width);
  const labelX =
    anchor === "start"
      ? xPosition
      : anchor === "end"
      ? xPosition + labelWidth
      : xPosition + labelWidth / 2;
  return (
    <span
      className={`sankey-label-overlay anchor-${anchor}`}
      style={{
        left: `${(labelX / 1120) * 100}%`,
        top: `${(yPosition / 430) * 100}%`,
        width: `${(labelWidth / 1120) * 100}%`,
      }}
    >
      <strong>{label}</strong>
      {value !== undefined && `: ${value}`}
    </span>
  );
}

function SankeyFlow({ d, value, total, className }) {
  if (value <= 0) return null;
  const width = Math.max(7, Math.min(210, (value / total) * 210));
  return <path className={`sankey-flow ${className}`} d={d} strokeWidth={width} />;
}

function FinancialSankeyPanel({ snapshot }) {
  const flow = buildOperatingFlow(snapshot);
  if (!flow) return null;

  return (
    <section className="panel sankey-panel">
      <div className="sankey-heading">
        <div className="panel-title">
          <LineChart size={18} />
          <h3>Operating Flow</h3>
        </div>
        <SankeyLegend />
      </div>
      <div className="sankey-scroll" role="img" aria-label="Revenue flow to operating profit, taxes, and expenses">
        <div className="sankey-canvas">
          <svg className="sankey-svg" viewBox="0 0 1120 430" aria-hidden="true">
            <SankeyFlow
              d="M96 226 C166 226 216 226 288 226"
              value={flow.revenue}
              total={flow.revenue}
              className="flow-revenue"
            />
            <SankeyFlow
              d="M308 145 C410 145 474 145 580 145"
              value={flow.grossProfit}
              total={flow.revenue}
              className="flow-profit"
            />
            <SankeyFlow
              d="M308 287 C452 287 700 325 1030 325"
              value={flow.costOfSales}
              total={flow.revenue}
              className="flow-cost"
            />
            <SankeyFlow
              d="M600 96 C686 96 735 72 822 72"
              value={flow.operatingProfit}
              total={flow.revenue}
              className="flow-profit"
            />
            <SankeyFlow
              d="M600 176 C690 176 735 178 822 178"
              value={flow.operatingExpenses}
              total={flow.revenue}
              className="flow-expense"
            />
            <SankeyFlow
              d="M842 50 C914 38 972 29 1044 29"
              value={flow.afterTaxOperatingProfit}
              total={flow.revenue}
              className="flow-profit"
            />
            <SankeyFlow
              d="M842 84 C915 84 977 82 1050 82"
              value={flow.tax}
              total={flow.revenue}
              className="flow-tax"
            />
            <SankeyFlow
              d="M842 151 C918 151 984 148 1050 137"
              value={flow.otherExpense}
              total={flow.revenue}
              className="flow-expense"
            />
            <SankeyFlow
              d="M842 198 C918 198 984 206 1050 219"
              value={flow.sga}
              total={flow.revenue}
              className="flow-expense"
            />
            <SankeyFlow
              d="M842 236 C918 236 984 253 1050 269"
              value={flow.amortization}
              total={flow.revenue}
              className="flow-expense"
            />

            <line className="sankey-node node-source" x1="96" y1="86" x2="96" y2="366" />
            <line className="sankey-node node-revenue" x1="308" y1="86" x2="308" y2="366" />
            <line className="sankey-node node-profit" x1="600" y1="70" x2="600" y2="202" />
            <line className="sankey-node node-profit" x1="842" y1="18" x2="842" y2="100" />
            <line className="sankey-node node-expense" x1="842" y1="116" x2="842" y2="254" />
            <line className="sankey-node node-profit" x1="1050" y1="8" x2="1050" y2="50" />
            <line className="sankey-node node-tax" x1="1050" y1="68" x2="1050" y2="96" />
            <line className="sankey-node node-expense" x1="1050" y1="112" x2="1050" y2="156" />
            <line className="sankey-node node-expense" x1="1050" y1="200" x2="1050" y2="238" />
            <line className="sankey-node node-expense" x1="1050" y1="255" x2="1050" y2="282" />
            <line className="sankey-node node-cost" x1="1050" y1="190" x2="1050" y2="382" />
          </svg>
          <div className="sankey-label-layer">
          <SankeyLabel x="18" y="226" width="155" anchor="end" label="Company" value={formatSankeyAmount(flow.revenue)} />
          <SankeyLabel x="195" y="226" width="155" label="Revenue" value={formatSankeyAmount(flow.revenue)} />
          <SankeyLabel
            x="465"
            y="145"
            width="170"
            label={flow.hasGrossProfitBridge ? "Gross Profit" : "Operating Income"}
            value={formatSankeyAmount(flow.grossProfit)}
          />
          {flow.hasGrossProfitBridge && (
            <SankeyLabel x="690" y="72" width="190" label="Operating Profit" value={formatSankeyAmount(flow.operatingProfit)} />
          )}
          {flow.operatingExpenses > 0 && (
            <SankeyLabel x="650" y="178" width="235" label="Operating Expenses" value={formatSankeyAmount(flow.operatingExpenses)} />
          )}
          {flow.afterTaxOperatingProfit > 0 && (
            <SankeyLabel x="910" y="29" width="180" label="NOPAT" value={formatSankeyAmount(flow.afterTaxOperatingProfit)} />
          )}
          {flow.tax > 0 && (
            <SankeyLabel x="970" y="82" width="120" label="Tax" value={formatSankeyAmount(flow.tax)} />
          )}
          {flow.otherExpense > 0 && (
            <SankeyLabel x="895" y="137" width="195" label="Other OpEx" value={formatSankeyAmount(flow.otherExpense)} />
          )}
          {flow.sga > 0 && (
            <SankeyLabel x="895" y="219" width="190" label="SG&A" value={formatSankeyAmount(flow.sga)} />
          )}
          {flow.amortization > 0 && (
            <SankeyLabel x="890" y="269" width="195" label="D&A" value={formatSankeyAmount(flow.amortization)} />
          )}
          {flow.costOfSales > 0 && (
            <SankeyLabel
              x="875"
              y="325"
              width="215"
              label={flow.hasGrossProfitBridge ? "Cost of Sales" : "Total Costs & Expenses"}
              value={formatSankeyAmount(flow.costOfSales)}
            />
          )}
          </div>
        </div>
      </div>
    </section>
  );
}

function SnapshotPanel({ snapshot }) {
  if (!snapshot) return null;
  return (
    <section className="panel">
      <div className="panel-title">
        <Database size={18} />
        <h3>Historical Starting Point</h3>
      </div>
      <div className="metric-grid">
        <Metric label="Revenue base" value={formatMoney(snapshot.revenue_base)} />
        <Metric label="Operating margin" value={formatPercent(snapshot.current_operating_margin)} />
        <Metric label="Total costs & exp." value={formatMoney(snapshot.total_costs_and_expenses)} />
        <Metric label="Effective tax rate" value={formatPercent(snapshot.current_effective_tax_rate)} />
        <Metric label="Cash" value={formatMoney(snapshot.cash_and_non_operating_asset)} />
        <Metric label="Book debt" value={formatMoney(snapshot.debt_value_book)} />
        <Metric label="Invested capital" value={formatMoney(snapshot.current_invested_capital)} />
      </div>
      <div className="source-list">
        {snapshot.sources?.slice(0, 6).map((source) => (
          <div className="source-row" key={`${source.metric}-${source.source}`}>
            <strong>{source.metric}</strong>
            <span>{source.source}</span>
            <small>{source.xbrl_tag || source.notes || "source logged"}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function AssumptionForm({ selected, assumptions, setAssumptions, onSubmit, busy }) {
  if (!selected?.pending_input) return null;
  const controls = selected.pending_input.payload?.required_controls ?? [];
  return (
    <section className="panel assumption-panel">
      <div className="panel-title">
        <CheckCircle2 size={18} />
        <h3>Banker-Owned Assumptions</h3>
      </div>
      <p className="panel-copy">{selected.pending_input.message}</p>
      <div className="control-strip">
        {controls.map((control) => (
          <span key={control}>{control}</span>
        ))}
      </div>
      <div className="assumption-groups">
        <label className="wide-field">
          Scenario name
          <input
            value={assumptions.scenario_name ?? ""}
            onChange={(event) => setAssumptions((current) => ({ ...current, scenario_name: event.target.value }))}
          />
        </label>
        <label>
          Valuation date
          <input
            type="date"
            value={assumptions.valuation_date ?? ""}
            onChange={(event) => setAssumptions((current) => ({ ...current, valuation_date: event.target.value }))}
          />
        </label>
        {ASSUMPTION_GROUPS.map((group) => (
          <div className="field-group" key={group.title}>
            <h4>{group.title}</h4>
            <div className="field-grid">
              {group.fields.map(([name, label, type]) => (
                <label key={name}>
                  {label}
                  <input
                    type="number"
                    step={type === "integer" ? "1" : "0.001"}
                    value={assumptions[name] ?? ""}
                    onChange={(event) =>
                      setAssumptions((current) => ({ ...current, [name]: event.target.value }))
                    }
                  />
                </label>
              ))}
            </div>
          </div>
        ))}
        <label className="wide-field">
          Approval comment
          <textarea
            value={assumptions.approval_comment ?? ""}
            onChange={(event) =>
              setAssumptions((current) => ({ ...current, approval_comment: event.target.value }))
            }
          />
        </label>
      </div>
      <button className="primary" onClick={onSubmit} disabled={busy} type="button">
        <Send size={17} />
        Submit assumptions and run DCF
      </button>
    </section>
  );
}

function ResultPanel({ workflow }) {
  const result = workflow?.valuation_result;
  if (!result) return null;
  const premium = result.implied_premium_discount;
  const terminal = result.terminal_metrics ?? {};
  const table = result.valuation_table ?? [];
  return (
    <>
      <section className="panel result-panel">
        <div className="panel-title">
          <BarChart3 size={18} />
          <h3>DCF Output</h3>
        </div>
        <div className="metric-grid">
          <Metric label="Intrinsic equity value" value={formatMoney(result.intrinsic_equity_value)} tone="strong" />
          <Metric label="Firm value" value={formatMoney(result.firm_value)} />
          <Metric label="Operating asset value" value={formatMoney(result.value_of_operating_assets)} />
          <Metric label="Current equity value" value={formatMoney(result.current_market_equity_value)} />
          <Metric label="Premium / discount" value={formatPercent(premium)} tone={premium >= 0 ? "positive" : "negative"} />
          <Metric label="Terminal FCFF" value={formatMoney(terminal.terminal_fcff)} />
        </div>
        {workflow.valuation_explanation && (
          <div className="explanation">
            <strong>{workflow.valuation_explanation.headline}</strong>
            <p>{workflow.valuation_explanation.limitations?.join(" ")}</p>
          </div>
        )}
      </section>
      <section className="panel table-panel">
        <div className="panel-title">
          <LineChart size={18} />
          <h3>Projection Table</h3>
        </div>
        <div className="projection-table">
          <table>
            <thead>
              <tr>
                <th>Year</th>
                <th>Revenue</th>
                <th>Growth</th>
                <th>Margin</th>
                <th>FCFF</th>
                <th>PV FCFF</th>
                <th>WACC index</th>
              </tr>
            </thead>
            <tbody>
              {table.slice(-8).map((row) => (
                <tr key={`${row.year}-${row.is_terminal}`}>
                  <td>{row.is_terminal ? "TV" : row.year}</td>
                  <td>{formatMoney(row.revenues)}</td>
                  <td>{formatPercent(row.revenueGrowth)}</td>
                  <td>{formatPercent(row.margins)}</td>
                  <td>{formatMoney(row.FCFF)}</td>
                  <td>{formatMoney(row.PVFCFF)}</td>
                  <td>{formatValue(row.cumWACC, "multiple")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function SensitivityPanel({ workflow }) {
  const sensitivity = workflow?.sensitivity_result;
  if (!sensitivity) return null;
  const rows = sensitivity.one_factor_sensitivities ?? [];
  const topDrivers = sensitivity.top_value_drivers ?? [];
  const matrix = sensitivity.matrices?.[0];
  const baseValue = sensitivity.base_case?.intrinsic_equity_value;
  const largestDriver = topDrivers[0];

  return (
    <section className="panel sensitivity-panel">
      <div className="panel-title">
        <SlidersHorizontal size={18} />
        <h3>Sensitivity Analysis</h3>
      </div>
      <div className="metric-grid">
        <Metric label="Base equity value" value={formatMoney(baseValue)} tone="strong" />
        <Metric label="Largest observed driver" value={largestDriver?.label ?? "-"} />
        <Metric label="Largest high / low input move" value={formatSignedMoney(largestDriver?.absolute_swing)} />
      </div>

      <div className="projection-table sensitivity-table">
        <table>
          <thead>
            <tr>
              <th>Driver</th>
              <th>Low input</th>
              <th>Equity value</th>
              <th>Delta</th>
              <th>High input</th>
              <th>Equity value</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.variable}>
                <td>
                  <strong>{row.label}</strong>
                  <small>{row.notes?.[0]}</small>
                </td>
                <td>{formatSensitivityInput(row.low_input_value, row.unit)}</td>
                <td>{row.low_input_status === "success" ? formatMoney(row.low_input_equity_value) : row.low_input_status}</td>
                <td className={row.low_input_delta >= 0 ? "positive-text" : "negative-text"}>
                  {formatSignedMoney(row.low_input_delta)}
                </td>
                <td>{formatSensitivityInput(row.high_input_value, row.unit)}</td>
                <td>{row.high_input_status === "success" ? formatMoney(row.high_input_equity_value) : row.high_input_status}</td>
                <td className={row.high_input_delta >= 0 ? "positive-text" : "negative-text"}>
                  {formatSignedMoney(row.high_input_delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {matrix && (
        <div className="matrix-block">
          <h4>{matrix.name}</h4>
          <div className="projection-table matrix-table">
            <table>
              <thead>
                <tr>
                  <th>{matrix.row_label} / {matrix.column_label}</th>
                  {matrix.columns.map((column) => (
                    <th key={column}>{formatSensitivityInput(column, matrix.column_unit)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((rowValue, rowIndex) => (
                  <tr key={rowValue}>
                    <td>{formatSensitivityInput(rowValue, matrix.row_unit)}</td>
                    {matrix.cells[rowIndex]?.map((cell) => (
                      <td key={`${cell.row_value}-${cell.column_value}`}>
                        <strong>{cell.status === "success" ? formatMoney(cell.equity_value) : "-"}</strong>
                        {cell.status === "success" && <small>{formatPercent(cell.premium_discount)}</small>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="sensitivity-note">{matrix.notes?.join(" ")}</p>
        </div>
      )}
    </section>
  );
}

function MonteCarloPanel({ workflow, distributions, setDistributions, onRun, busy, sampleSize, setSampleSize }) {
  if (!workflow?.valuation_result) return null;
  const latest = workflow.monte_carlo_runs?.at(-1);
  function updateDistribution(index, field, value) {
    setDistributions((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, [field]: value } : item)),
    );
  }
  return (
    <section className="panel">
      <div className="panel-title">
        <LineChart size={18} />
        <h3>Monte Carlo Range</h3>
      </div>
      <div className="mc-toolbar">
        <label>
          Samples
          <input type="number" min="10" max="5000" value={sampleSize} onChange={(event) => setSampleSize(event.target.value)} />
        </label>
        <button className="primary" onClick={onRun} disabled={busy} type="button">
          <Play size={17} />
          Approve distributions and run
        </button>
      </div>
      <div className="distribution-grid">
        {distributions.map((dist, index) => (
          <div className="distribution-row" key={dist.variable}>
            <strong>{dist.variable}</strong>
            <span>{dist.distribution}</span>
            {["low", "mode", "high", "mean", "stdev"].map((field) => (
              <label key={field}>
                {field}
                <input
                  type="number"
                  step="0.001"
                  value={dist[field] ?? ""}
                  onChange={(event) => updateDistribution(index, field, event.target.value === "" ? null : event.target.value)}
                />
              </label>
            ))}
          </div>
        ))}
      </div>
      {latest && (
        <div className="mc-result">
          <Metric
            label="Median equity value"
            value={formatMoney(latest.result.equity_value_distribution.percentiles["50"])}
            tone="strong"
          />
          <Metric
            label="5th / 95th percentile"
            value={`${formatMoney(latest.result.equity_value_distribution.percentiles["5"])} / ${formatMoney(latest.result.equity_value_distribution.percentiles["95"])}`}
          />
          <Metric
            label="Probability above market"
            value={formatPercent(latest.result.probability_above_current_market_value)}
          />
          <div className="driver-list">
            {latest.result.value_drivers?.slice(0, 5).map((driver) => (
              <span key={driver.variable}>
                {driver.variable}: {driver.correlation_to_equity_value.toFixed(2)}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function EventTimeline({ events }) {
  return (
    <section className="panel">
      <div className="panel-title">
        <FileText size={18} />
        <h3>ADK Event Timeline</h3>
      </div>
      <div className="timeline">
        {events?.map((event) => (
          <details className="timeline-row" key={event.id}>
            <summary>
              <span>{event.node_path || event.author || "workflow"}</span>
              {event.long_running_tool_ids?.length > 0 && <em>interrupt</em>}
            </summary>
            {event.message && <p>{event.message}</p>}
            {event.function_call && <JsonBlock value={event.function_call} />}
            {event.output && <JsonBlock value={event.output} />}
          </details>
        ))}
      </div>
    </section>
  );
}

function DcfWorkbenchTab({
  selected,
  assumptions,
  setAssumptions,
  submitAssumptions,
  busy,
  distributions,
  setDistributions,
  runMonteCarlo,
  sampleSize,
  setSampleSize,
}) {
  if (!selected) {
    return (
      <div className="panel empty-detail">
        <Building2 size={30} />
        <p>Run the workbench to create the DCF workflow and request assumptions.</p>
      </div>
    );
  }

  return (
    <section className="tab-content">
      <section className="panel detail-header">
        <div>
          <JobStatusPill status={selected.status} />
          <h2>{selected.financial_snapshot?.company_name || selected.company}</h2>
          <p>
            {selected.scenario_name} | {selected.ticker || "ticker pending"} | {selected.request_id}
          </p>
        </div>
        <WorkflowSteps workflow={selected} />
      </section>

      <FinancialSankeyPanel snapshot={selected.financial_snapshot} />
      <SnapshotPanel snapshot={selected.financial_snapshot} />
      <AssumptionForm
        selected={selected}
        assumptions={assumptions}
        setAssumptions={setAssumptions}
        onSubmit={submitAssumptions}
        busy={busy}
      />
      <ResultPanel workflow={selected} />
      <SensitivityPanel workflow={selected} />
      <MonteCarloPanel
        workflow={selected}
        distributions={distributions}
        setDistributions={setDistributions}
        onRun={runMonteCarlo}
        busy={busy}
        sampleSize={sampleSize}
        setSampleSize={setSampleSize}
      />
      <EventTimeline events={selected.events} />
    </section>
  );
}

function normalizePayload(value) {
  const numericFields = new Set(
    ASSUMPTION_GROUPS.flatMap((group) => group.fields.map(([name]) => name)).concat([
      "risk_free_rate",
      "ERP",
      "equity_value",
    ]),
  );
  const payload = {};
  Object.entries(value).forEach(([key, current]) => {
    if (current === "" || current === undefined) return;
    if (numericFields.has(key)) {
      payload[key] = Number(current);
    } else {
      payload[key] = current;
    }
  });
  return payload;
}

function normalizeDistributions(distributions) {
  return distributions.map((dist) => {
    const next = { ...dist };
    ["value", "mean", "stdev", "low", "mode", "high", "min_value", "max_value"].forEach((field) => {
      if (next[field] === "" || next[field] === null || next[field] === undefined) {
        delete next[field];
      } else {
        next[field] = Number(next[field]);
      }
    });
    return next;
  });
}

function isResearchPending(job) {
  return Boolean(job?.job_id && !["completed", "failed", "awaiting_peer_review"].includes(job.status));
}

export default function App() {
  const [workflows, setWorkflows] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [workflowForm, setWorkflowForm] = useState(WORKFLOW_FORM);
  const [companyResearch, setCompanyResearch] = useState(null);
  const [compsResearch, setCompsResearch] = useState(null);
  const [assumptions, setAssumptions] = useState({});
  const [distributions, setDistributions] = useState([]);
  const [sampleSize, setSampleSize] = useState(500);
  const [activeTab, setActiveTab] = useState("company");
  const [gutterOpen, setGutterOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(
    () => workflows.find((workflow) => workflow.request_id === selectedId) ?? workflows[0],
    [workflows, selectedId],
  );

  async function loadWorkflows() {
    const data = await api(`/api/workflows?actor_id=${encodeURIComponent(DEFAULT_ACTOR_ID)}`);
    setWorkflows(data.workflows);
    setSelectedId((current) => {
      if (current && data.workflows.some((workflow) => workflow.request_id === current)) return current;
      return data.workflows[0]?.request_id ?? null;
    });
  }

  async function refreshResearchJob(type, jobId) {
    const endpoint = type === "company" ? `/api/company-background/${jobId}` : `/api/comparables/${jobId}`;
    const data = await api(endpoint);
    if (type === "company") {
      setCompanyResearch(data.workflow);
    } else {
      setCompsResearch(data.workflow);
    }
  }

  useEffect(() => {
    api("/api/bootstrap")
      .then((data) => {
        setAssumptions(data.sample_assumptions);
        setDistributions(data.sample_distributions);
        return loadWorkflows();
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const suggested = selected?.pending_input?.payload?.suggested_assumptions;
    if (suggested) setAssumptions((current) => ({ ...suggested, ...current, scenario_name: suggested.scenario_name }));
  }, [selected?.request_id]);

  useEffect(() => {
    const pendingJobs = [
      ["company", companyResearch],
      ["comparables", compsResearch],
    ].filter(([, job]) => isResearchPending(job));

    if (pendingJobs.length === 0) return undefined;

    let cancelled = false;
    async function refreshAll() {
      try {
        await Promise.all(
          pendingJobs.map(([type, job]) => {
            if (!job?.job_id || cancelled) return Promise.resolve();
            return refreshResearchJob(type, job.job_id);
          }),
        );
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }

    const timer = window.setInterval(refreshAll, 1200);
    refreshAll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [companyResearch?.job_id, companyResearch?.status, compsResearch?.job_id, compsResearch?.status]);

  async function startWorkbench(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = { actor_id: DEFAULT_ACTOR_ID, ...workflowForm };
      const [background, comps] = await Promise.all([
        api("/api/company-background", { method: "POST", body: JSON.stringify(payload) }),
        api("/api/comparables", { method: "POST", body: JSON.stringify(payload) }),
      ]);
      setCompanyResearch(background.workflow);
      setCompsResearch(comps.workflow);

      const dcf = await api("/api/workflows", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await loadWorkflows();
      setSelectedId(dcf.workflow.request_id);
      setActiveTab("company");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitAssumptions() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/workflows/${selected.request_id}/assumptions`, {
        method: "POST",
        body: JSON.stringify({ actor_id: DEFAULT_ACTOR_ID, assumptions: normalizePayload(assumptions) }),
      });
      await loadWorkflows();
      setSelectedId(data.workflow.request_id);
      setActiveTab("dcf");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitComparablePeers(review) {
    if (!compsResearch?.job_id) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/comparables/${compsResearch.job_id}/peers`, {
        method: "POST",
        body: JSON.stringify({ actor_id: DEFAULT_ACTOR_ID, ...review }),
      });
      setCompsResearch(data.workflow);
      setActiveTab("comparables");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runMonteCarlo() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/workflows/${selected.request_id}/monte-carlo`, {
        method: "POST",
        body: JSON.stringify({
          actor_id: DEFAULT_ACTOR_ID,
          sample_size: Number(sampleSize),
          seed: 42,
          distributions: normalizeDistributions(distributions),
        }),
      });
      await loadWorkflows();
      setSelectedId(data.workflow.request_id);
      setActiveTab("dcf");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    setBusy(true);
    setError("");
    try {
      await api("/api/reset", { method: "POST" });
      setCompanyResearch(null);
      setCompsResearch(null);
      await loadWorkflows();
      setSelectedId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function restartRuntime() {
    setBusy(true);
    setError("");
    try {
      await api("/api/runtime/restart", { method: "POST" });
      setCompanyResearch(null);
      setCompsResearch(null);
      await loadWorkflows();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const activeTabConfig = TABS.find((tab) => tab.id === activeTab) ?? TABS[0];
  const ActiveTabIcon = activeTabConfig.icon;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>M&A Research and DCF Workbench</h1>
          <p>Agent-separated company background, DCF evaluation, and comparables workflows</p>
        </div>
        <div className="topbar-actions">
          <button className="ghost" onClick={restartRuntime} disabled={busy} type="button">
            <RefreshCw size={17} />
            Restart runtime
          </button>
          <button className="ghost" onClick={resetDemo} disabled={busy} type="button">
            <RotateCcw size={17} />
            Reset
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className={`workbench-layout ${gutterOpen ? "" : "gutter-collapsed"}`}>
        <aside className="input-gutter">
          <button
            className="gutter-toggle"
            type="button"
            onClick={() => setGutterOpen((current) => !current)}
            aria-label={gutterOpen ? "Collapse input gutter" : "Expand input gutter"}
            title={gutterOpen ? "Collapse input gutter" : "Expand input gutter"}
          >
            {gutterOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>

          {gutterOpen && (
            <div className="gutter-content">
              <form className="panel workflow-form" onSubmit={startWorkbench}>
                <div className="panel-title">
                  <Building2 size={18} />
                  <h2>Input</h2>
                </div>
                <label>
                  Company or ticker
                  <input
                    value={workflowForm.company}
                    onChange={(event) => setWorkflowForm((current) => ({ ...current, company: event.target.value }))}
                  />
                </label>
                <label>
                  Scenario
                  <input
                    value={workflowForm.scenario_name}
                    onChange={(event) =>
                      setWorkflowForm((current) => ({ ...current, scenario_name: event.target.value }))
                    }
                  />
                </label>
                <div className="segmented">
                  {["sample", "sec"].map((source) => (
                    <button
                      type="button"
                      key={source}
                      className={workflowForm.data_source === source ? "active" : ""}
                      onClick={() => setWorkflowForm((current) => ({ ...current, data_source: source }))}
                    >
                      {source === "sample" ? "Notebook sample" : "Live SEC"}
                    </button>
                  ))}
                </div>
                <button className="primary" type="submit" disabled={busy}>
                  <Play size={17} />
                  Run workflows
                </button>
              </form>

              <section className="panel job-summary">
                <div className="panel-title">
                  <Search size={18} />
                  <h2>Agent Runs</h2>
                </div>
                <div className="job-row">
                  <span>Company background</span>
                  <JobStatusPill status={companyResearch?.status} />
                </div>
                <div className="job-row">
                  <span>DCF workbench</span>
                  <JobStatusPill status={selected?.status} />
                </div>
                <div className="job-row">
                  <span>Comparables</span>
                  <JobStatusPill status={compsResearch?.status} />
                </div>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <FileText size={18} />
                  <h2>DCF Queue</h2>
                </div>
                <WorkflowList workflows={workflows} selectedId={selected?.request_id} onSelect={setSelectedId} />
              </section>
            </div>
          )}
        </aside>

        <section className="main-stage">
          <div className="tab-bar" role="tablist" aria-label="Workflow outputs">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                className={`tab-button ${activeTab === id ? "active" : ""}`}
                key={id}
                onClick={() => setActiveTab(id)}
                role="tab"
                type="button"
                aria-selected={activeTab === id}
              >
                <Icon size={17} />
                <span>{label}</span>
              </button>
            ))}
          </div>

          <div className="active-tab-heading">
            <ActiveTabIcon size={19} />
            <h2>{activeTabConfig.label}</h2>
          </div>

          {activeTab === "company" && (
            <ResearchPanel job={companyResearch} title="Company Background" icon={Building2} />
          )}

          {activeTab === "dcf" && (
            <DcfWorkbenchTab
              selected={selected}
              assumptions={assumptions}
              setAssumptions={setAssumptions}
              submitAssumptions={submitAssumptions}
              busy={busy}
              distributions={distributions}
              setDistributions={setDistributions}
              runMonteCarlo={runMonteCarlo}
              sampleSize={sampleSize}
              setSampleSize={setSampleSize}
            />
          )}

          {activeTab === "comparables" && (
            <ComparablesPanel job={compsResearch} onSubmitPeers={submitComparablePeers} busy={busy} />
          )}
        </section>
      </div>
    </main>
  );
}
