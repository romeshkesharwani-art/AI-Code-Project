"use client";

import {
  Activity,
  Archive,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  CloudUpload,
  Database,
  File,
  FileText,
  Filter,
  FolderOpen,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  MoreHorizontal,
  Plus,
  Search,
  Send,
  Shield,
  ShieldCheck,
  Sparkles,
  Upload,
  Users,
  X,
} from "lucide-react";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerQuestion,
  archivePolicy,
  getCustomers,
  getCustomerStats,
  getDashboardStats,
  getPolicy,
  getPolicyFileUrl,
  getPolicies,
  ingestSources,
  searchPolicies,
  uploadPolicy,
} from "@/lib/api";
import type { Customer, CustomerStats, DashboardStats } from "@/types/customer";
import type { Policy, SearchFilters, SearchResult } from "@/types/policy";

type Section = "overview" | "library" | "assistant" | "customers";
type Notice = { type: "error" | "success" | "warning"; text: string } | null;

function policyTitle(policy: Policy) {
  return policy.name || policy.policy_name || policy.filename || "Untitled policy";
}

function initials(value?: string) {
  return (value || "Insurance")
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function scorePercent(score: number) {
  return `${Math.round((score > 1 ? score / 100 : score) * 100)}%`;
}

const CUSTOMER_PAGE_SIZE = 15;
const CHART_COLORS = ["#21b6a5", "#3b82f6", "#f59e0b", "#8b5cf6", "#ef4444", "#64748b"];

function Donut({ items, label }: { items: { name: string; count: number }[]; label: string }) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  let offset = 0;
  const stops = items.map((item, index) => {
    const start = total ? (offset / total) * 100 : 0;
    offset += item.count;
    const end = total ? (offset / total) * 100 : 0;
    return `${CHART_COLORS[index % CHART_COLORS.length]} ${start}% ${end}%`;
  });
  return (
    <div className="donut-wrap">
      <div className="donut" style={{ background: total ? `conic-gradient(${stops.join(", ")})` : "#e8ecf2" }}>
        <div className="donut-hole"><strong>{total.toLocaleString()}</strong><span>{label}</span></div>
      </div>
      <ul className="donut-legend">
        {items.map((item, index) => (
          <li key={item.name}>
            <i style={{ background: CHART_COLORS[index % CHART_COLORS.length] }} />
            <span>{item.name.replace(" Insurance", "")}</span>
            <b>{total ? Math.round((item.count / total) * 100) : 0}%</b>
            <em>{item.count}</em>
          </li>
        ))}
      </ul>
    </div>
  );
}

function BarList({ items }: { items: { name: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <div className="bar-list">
      {items.map((item) => (
        <div className="bar-row" key={item.name}>
          <span title={item.name}>{item.name}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(item.count / max) * 100}%` }} /></div>
          <b>{item.count}</b>
        </div>
      ))}
    </div>
  );
}

function CustomerRows({ customers }: { customers: Customer[] }) {
  return (
    <>
      {customers.map((customer) => (
        <tr key={customer.customer_id}>
          <td className="claim-id">{customer.customer_id}</td>
          <td><div className="person"><span className="person-avatar">{initials(`${customer.first_name} ${customer.last_name}`)}</span><div><strong>{customer.first_name} {customer.last_name}</strong><small>{customer.email}</small></div></div></td>
          <td>{customer.policy_type.replace(" Insurance", "")}</td>
          <td>{customer.policy_id}</td>
          <td>{customer.city}</td>
          <td>{customer.claim_type}</td>
          <td>{formatDate(customer.policy_start_date)}</td>
          <td><span className={`pill pill-${customer.policy_status.toLowerCase()}`}>{customer.policy_status}</span></td>
        </tr>
      ))}
    </>
  );
}

export default function Home() {
  const [section, setSection] = useState<Section>("overview");
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loadingPolicies, setLoadingPolicies] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [knownCategories, setKnownCategories] = useState<string[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [selectedPolicy, setSelectedPolicy] = useState<Policy | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Policy | null>(null);
  const [filterCategory, setFilterCategory] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterCarrier, setFilterCarrier] = useState("");
  const [librarySearch, setLibrarySearch] = useState("");
  const [question, setQuestion] = useState("");
  const [answerLoading, setAnswerLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [answer, setAnswer] = useState("");
  const [abstained, setAbstained] = useState(false);
  const [sources, setSources] = useState<SearchResult[]>([]);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [totalMatches, setTotalMatches] = useState(0);
  const [queryCategory, setQueryCategory] = useState("");
  const [queryCarrier, setQueryCarrier] = useState("");
  const [queryPolicy, setQueryPolicy] = useState("");
  const [uploading, setUploading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerTotal, setCustomerTotal] = useState(0);
  const [customerPage, setCustomerPage] = useState(1);
  const [customerSearch, setCustomerSearch] = useState("");
  const [customerType, setCustomerType] = useState("");
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customerError, setCustomerError] = useState("");
  const [customerStats, setCustomerStats] = useState<CustomerStats | null>(null);
  const [dashStats, setDashStats] = useState<DashboardStats | null>(null);
  const [recentCustomers, setRecentCustomers] = useState<Customer[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadFormRef = useRef<HTMLFormElement>(null);
  const questionInputRef = useRef<HTMLTextAreaElement>(null);

  const loadPolicies = useCallback(async () => {
    setLoadingPolicies(true);
    setPolicyError("");
    try {
      const loadedPolicies = await getPolicies({
        category: filterCategory || undefined,
        status: filterStatus || undefined,
        carrier: filterCarrier || undefined,
        search: librarySearch.trim() || undefined,
      });
      setPolicies(loadedPolicies);
      setKnownCategories((current) => [...new Set([
        ...current,
        ...loadedPolicies.map((policy) => policy.category?.trim()).filter((category): category is string => Boolean(category)),
      ])].sort((left, right) => left.localeCompare(right)));
    } catch (error) {
      setPolicyError(error instanceof Error ? error.message : "Could not load policies.");
    } finally {
      setLoadingPolicies(false);
    }
  }, [filterCategory, filterStatus, filterCarrier, librarySearch]);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  useEffect(() => {
    const handle = window.setTimeout(async () => {
      setCustomersLoading(true);
      setCustomerError("");
      try {
        const result = await getCustomers({
          search: customerSearch.trim() || undefined,
          policy_type: customerType || undefined,
          page: customerPage,
          page_size: CUSTOMER_PAGE_SIZE,
        });
        setCustomers(result.items);
        setCustomerTotal(result.total);
      } catch (error) {
        setCustomerError(error instanceof Error ? error.message : "Could not load customers.");
      } finally {
        setCustomersLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [customerSearch, customerType, customerPage]);

  useEffect(() => {
    void getCustomerStats().then(setCustomerStats).catch(() => undefined);
    void getDashboardStats().then(setDashStats).catch(() => undefined);
    void getCustomers({ page: 1, page_size: 5 }).then((result) => setRecentCustomers(result.items)).catch(() => undefined);
  }, []);

  const carriers = useMemo(
    () => [...new Set(policies.map((policy) => policy.carrier).filter(Boolean) as string[])].sort(),
    [policies],
  );
  const categoryOptions = useMemo(
    () => [...new Set([...knownCategories, filterCategory].filter(Boolean))].sort((left, right) => left.localeCompare(right)),
    [knownCategories, filterCategory],
  );
  const activePolicies = policies.filter((policy) =>
    !policy.status || policy.status.toLowerCase() === "active",
  ).length;
  const expiringSoon = policies.filter((policy) => {
    if (!policy.expires_date) return false;
    const days = (new Date(policy.expires_date).getTime() - Date.now()) / 86400000;
    return days >= 0 && days <= 30;
  }).length;

  function notify(type: "error" | "success" | "warning", text: string) {
    setNotice({ type, text });
    window.setTimeout(() => setNotice(null), 5000);
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>, mode: "answer" | "search" = "answer") {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || answerLoading || searchLoading) return;
    await runQuestion(trimmed, mode);
  }

  async function runQuestion(trimmed: string, mode: "answer" | "search") {
    if (!trimmed || answerLoading || searchLoading) return;
    const filters: SearchFilters = {
      category: queryCategory || undefined,
      carrier: queryCarrier || undefined,
      policy_id: queryPolicy || undefined,
    };
    setAnswer("");
    setSources([]);
    setSearchResults([]);
    setTotalMatches(0);
    if (mode === "answer") setAnswerLoading(true);
    else setSearchLoading(true);
    setSection("assistant");
    try {
      if (mode === "answer") {
        const result = await answerQuestion(trimmed, 5, filters);
        setAnswer(result.answer);
        setAbstained(result.abstained);
        setSources(result.sources || []);
      } else {
        const result = await searchPolicies(trimmed, 10, filters);
        setSearchResults(result.results || []);
        setTotalMatches(result.total);
      }
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Your request could not be completed.");
    } finally {
      setAnswerLoading(false);
      setSearchLoading(false);
    }
  }

  async function openPolicy(policy: Policy) {
    setSelectedPolicy(policy);
    setDetailLoading(true);
    try {
      setSelectedPolicy(await getPolicy(policy.id));
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Could not load policy details.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFile || uploading) return;
    const form = new FormData(event.currentTarget);
    const category = String(form.get("category") || "").trim();
    setUploading(true);
    try {
      await uploadPolicy(uploadFile, {
        name: String(form.get("name") || "").trim() || undefined,
        category: category || undefined,
        carrier: String(form.get("carrier") || "").trim() || undefined,
        effective_date: String(form.get("effective_date") || "") || undefined,
        expires_date: String(form.get("expires_date") || "") || undefined,
      });
      setShowUpload(false);
      setUploadFile(null);
      uploadFormRef.current?.reset();
      if (category) setKnownCategories((current) => [...new Set([...current, category])].sort((left, right) => left.localeCompare(right)));
      notify("success", "Policy uploaded successfully.");
      await loadPolicies();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "The policy could not be uploaded.");
    } finally {
      setUploading(false);
    }
  }

  async function handleIngestSources() {
    if (ingesting) return;
    setIngesting(true);
    try {
      const result = await ingestSources();
      const details = [...result.failed_files, ...result.skipped_files].map((file) =>
        typeof file === "string" ? file : file.filename || file.file || file.path || "unknown file",
      );
      const filenames = details.length ? ` Files: ${details.join(", ")}.` : "";
      const message = `Bundled document indexing finished — ingested ${result.ingested}, skipped ${result.skipped}, failed ${result.failed}.${filenames}`;
      notify(result.failed > 0 ? "error" : result.skipped > 0 ? "warning" : "success", message);
      await loadPolicies();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Bundled documents could not be indexed.");
    } finally {
      setIngesting(false);
    }
  }

  async function confirmArchive() {
    if (!deleteTarget) return;
    try {
      await archivePolicy(deleteTarget.id);
      setDeleteTarget(null);
      setSelectedPolicy(null);
      notify("success", "Policy archived.");
      await loadPolicies();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "The policy could not be archived.");
    }
  }

  function selectFile(file?: File) {
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      notify("error", "Choose a PDF or DOCX file.");
      return;
    }
    setUploadFile(file);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0]);
  }

  function startQuestion(value: string) {
    setQuestion(value);
    setSection("assistant");
    window.setTimeout(() => questionInputRef.current?.focus(), 0);
  }

  const currentTitle = section === "overview" ? "Dashboard" : section === "library" ? "Policies" : section === "customers" ? "Customers" : "RAG Assistant";

  function go(next: Section) {
    setSection(next);
    setMobileNavOpen(false);
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><Shield size={18} strokeWidth={2.4} /></div>
          <span>Assure<b>AI</b></span>
          <button className="mobile-close icon-button" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)}><X size={18} /></button>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          <button className={`nav-item ${section === "overview" ? "nav-active" : ""}`} onClick={() => go("overview")}>
            <LayoutDashboard size={18} /><span>Dashboard</span>
          </button>
          <button className={`nav-item ${section === "library" ? "nav-active" : ""}`} onClick={() => go("library")}>
            <FolderOpen size={18} /><span>Policies</span><span className="nav-count">{policies.length}</span>
          </button>
          <button className={`nav-item ${section === "assistant" ? "nav-active" : ""}`} onClick={() => go("assistant")}>
            <Sparkles size={18} /><span>RAG Assistant</span><span className="nav-new">AI</span>
          </button>
          <button className={`nav-item ${section === "customers" ? "nav-active" : ""}`} onClick={() => go("customers")}>
            <Users size={18} /><span>Customers</span><span className="nav-count">{customerStats?.total ?? customerTotal}</span>
          </button>
        </nav>

        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => notify("success", "Support resources are coming soon.")}>
            <CircleHelp size={18} /><span>Help &amp; Support</span>
          </button>
          <div className="profile-row">
            <div className="profile-avatar">AM</div>
            <div className="profile-copy"><strong>Alex Morgan</strong><span>Claims Manager</span></div>
            <MoreHorizontal size={19} className="muted-icon" />
          </div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} /><strong>{currentTitle}</strong></div>
          <div className="topbar-actions">
            <span className="connection-status"><span className="status-dot" /> All systems operational</span>
            <button className="top-avatar" aria-label="User menu">AM</button>
          </div>
        </header>

        <div className="page-content">
          {section === "overview" && (
            <>
              <div className="page-heading">
                <div><div className="eyebrow">OVERVIEW</div><h1>Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 17 ? "afternoon" : "evening"}, Alex</h1><p>Here’s what’s happening with your policies and customers.</p></div>
                <div className="heading-actions"><button className="button button-secondary" onClick={() => void handleIngestSources()} disabled={ingesting}>{ingesting ? <LoaderCircle size={15} className="spin" /> : <Database size={15} />}{ingesting ? "Indexing…" : "Index bundled docs"}</button><button className="button button-primary" onClick={() => setShowUpload(true)}><Plus size={17} /> Upload policy</button></div>
              </div>

              {policyError && <ErrorBanner message={policyError} onRetry={() => void loadPolicies()} />}
              <div className="metric-grid">
                <MetricCard icon={<FileText size={18} />} label="Total policies" value={dashStats ? String(dashStats.policies) : "—"} note={dashStats ? `${dashStats.indexed_policies} indexed` : "Loading…"} tone="violet" />
                <MetricCard icon={<Users size={18} />} label="Customers" value={customerStats ? customerStats.total.toLocaleString() : "—"} note={customerStats ? `${customerStats.by_status[0]?.count ?? 0} ${customerStats.by_status[0]?.name?.toLowerCase() ?? "active"}` : "Loading…"} tone="mint" />
                <MetricCard icon={<Database size={18} />} label="Indexed passages" value={dashStats ? dashStats.chunks.toLocaleString() : "—"} note="Searchable by the assistant" tone="amber" />
                <MetricCard icon={<Activity size={18} />} label="Policy categories" value={dashStats ? String(dashStats.categories.length) : "—"} note={`${activePolicies} active documents`} tone="blue" />
              </div>

              <div className="dash-grid">
                <section className="panel">
                  <div className="panel-head"><div><h2>Policies by category</h2><p>Documents indexed per category</p></div></div>
                  {dashStats ? <BarList items={dashStats.categories} /> : <p className="panel-empty">Loading…</p>}
                </section>
                <section className="panel">
                  <div className="panel-head"><div><h2>Customer policy types</h2><p>Distribution across customers</p></div></div>
                  {customerStats ? <Donut items={customerStats.by_policy_type} label="Customers" /> : <p className="panel-empty">Loading…</p>}
                </section>
              </div>

              <section className="panel table-panel">
                <div className="panel-head"><div><h2>Recent customers</h2><p>Latest customer policy records</p></div><button className="text-button" onClick={() => go("customers")}>View all <ArrowRight size={14} /></button></div>
                <div className="table-scroll"><table className="data-table"><thead><tr><th>ID</th><th>Customer</th><th>Type</th><th>Policy</th><th>City</th><th>Claim type</th><th>Start date</th><th>Status</th></tr></thead><tbody><CustomerRows customers={recentCustomers} /></tbody></table></div>
              </section>

              <section className="panel table-panel">
                <div className="panel-head"><div><h2>Recently added policies</h2><p>The latest documents in your policy library</p></div><button className="text-button" onClick={() => go("library")}>Browse library <ArrowRight size={14} /></button></div>
                <PolicyTable policies={policies.slice(0, 4)} loading={loadingPolicies} error={policyError} onSelect={openPolicy} onRetry={() => void loadPolicies()} emptyAction={() => setShowUpload(true)} />
              </section>
            </>
          )}

          {section === "customers" && (
            <>
              <div className="page-heading">
                <div><div className="eyebrow">CUSTOMERS</div><h1>Customers</h1><p>Customer records and their policy details.</p></div>
              </div>
              <div className="library-toolbar">
                <label className="library-search"><Search size={17} /><input value={customerSearch} onChange={(event) => { setCustomerSearch(event.target.value); setCustomerPage(1); }} placeholder="Search by name, ID, email, city or policy…" /></label>
                <div className="filter-wrap"><Filter size={15} /><span>Filters</span>
                  <select aria-label="Filter by policy type" value={customerType} onChange={(event) => { setCustomerType(event.target.value); setCustomerPage(1); }}><option value="">All policy types</option>{(customerStats?.by_policy_type ?? []).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
                </div>
              </div>
              {customerError && <ErrorBanner message={customerError} onRetry={() => setCustomerPage(1)} />}
              <section className="panel table-panel">
                <div className="table-scroll">
                  <table className="data-table">
                    <thead><tr><th>ID</th><th>Customer</th><th>Type</th><th>Policy</th><th>City</th><th>Claim type</th><th>Start date</th><th>Status</th></tr></thead>
                    <tbody>
                      {customersLoading ? <tr><td colSpan={8} className="table-note"><LoaderCircle size={16} className="spin" /> Loading customers…</td></tr> : customers.length ? <CustomerRows customers={customers} /> : <tr><td colSpan={8} className="table-note">No customers match your search.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <div className="library-foot"><span>Showing {customers.length ? (customerPage - 1) * CUSTOMER_PAGE_SIZE + 1 : 0}–{(customerPage - 1) * CUSTOMER_PAGE_SIZE + customers.length} of {customerTotal}</span><div className="pagination"><button disabled={customerPage <= 1} onClick={() => setCustomerPage((value) => value - 1)} aria-label="Previous page"><ChevronLeft size={15} /></button><button className="page-current">{customerPage}</button><button disabled={customerPage * CUSTOMER_PAGE_SIZE >= customerTotal} onClick={() => setCustomerPage((value) => value + 1)} aria-label="Next page"><ChevronRight size={15} /></button></div></div>
              </section>
            </>
          )}

          {section === "library" && (
            <>
              <div className="page-heading library-heading">
                <div><div className="eyebrow">YOUR DOCUMENTS</div><h1>Policy library</h1><p>Every policy, organized and ready when you need it.</p></div>
                <div className="heading-actions"><button className="button button-secondary" onClick={() => void handleIngestSources()} disabled={ingesting}>{ingesting ? <LoaderCircle size={15} className="spin" /> : <Database size={15} />}{ingesting ? "Indexing…" : "Index bundled docs"}</button><button className="button button-primary" onClick={() => setShowUpload(true)}><Plus size={17} /> Add a policy</button></div>
              </div>
              <div className="library-summary">
                <div className="library-summary-icon"><BookOpen size={18} /></div>
                <div><strong>{loadingPolicies ? "Loading policies…" : `${policies.length} ${policies.length === 1 ? "policy" : "policies"} in your library`}</strong><span>Search documents or narrow the list with filters.</span></div>
                <span className="library-live"><span className="status-dot" /> Up to date</span>
              </div>
              <div className="library-toolbar">
                <label className="library-search"><Search size={17} /><input value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="Search policies..." /><kbd>⌘ K</kbd></label>
                <div className="filter-wrap"><Filter size={15} /><span>Filters</span>
                  <select aria-label="Filter by category" value={filterCategory} onChange={(event) => setFilterCategory(event.target.value)}><option value="">All categories</option>{categoryOptions.map((category) => <option key={category}>{category}</option>)}</select>
                  <select aria-label="Filter by status" value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}><option value="">All statuses</option><option value="archived">Archived</option><option value="expired">Expired</option><option value="upcoming">Upcoming</option><option value="active">Active</option></select>
                  <select aria-label="Filter by carrier" value={filterCarrier} onChange={(event) => setFilterCarrier(event.target.value)}><option value="">All carriers</option>{carriers.map((carrier) => <option key={carrier}>{carrier}</option>)}</select>
                </div>
              </div>
              <div className="table-card library-table"><PolicyTable policies={policies} loading={loadingPolicies} error={policyError} onSelect={openPolicy} onRetry={() => void loadPolicies()} emptyAction={() => setShowUpload(true)} onDelete={setDeleteTarget} /></div>
              <div className="library-foot"><span>Showing {policies.length} {policies.length === 1 ? "policy" : "policies"}</span><div className="pagination"><button disabled aria-label="Previous page"><ChevronLeft size={15} /></button><button className="page-current">1</button><button disabled aria-label="Next page"><ChevronRight size={15} /></button></div></div>
            </>
          )}

          {section === "assistant" && (
            <>
              <div className="page-heading assistant-heading">
                <div><div className="eyebrow">YOUR POLICY ASSISTANT</div><h1>Answers, with receipts.</h1><p>Ask a question or search your documents directly. Every answer points back to its source.</p></div>
                <div className="assistant-badge"><Sparkles size={16} /><span>AI-powered<br /><b>Grounded in your policies</b></span></div>
              </div>
              <section className="assistant-layout">
                <div className="assistant-main">
                  <form className="question-card" onSubmit={(event) => submitQuestion(event, "answer")}>
                    <label htmlFor="question-input">What would you like to know?</label>
                    <textarea id="question-input" ref={questionInputRef} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask anything about your coverage, exclusions, limits, or claims…" rows={3} />
                    <div className="question-footer"><span><Sparkles size={14} /> Answers based only on your uploaded documents</span><div><button className="button button-secondary compact" type="button" onClick={() => void runQuestion(question.trim(), "search")} disabled={!question.trim() || searchLoading || answerLoading}><Search size={15} /> Search</button><button className="button button-primary compact" type="submit" disabled={!question.trim() || answerLoading || searchLoading}>{answerLoading ? <LoaderCircle size={15} className="spin" /> : <Send size={14} />} Ask Coverwise</button></div></div>
                  </form>
                  <div className="query-filters">
                    <span>Focus your answer</span>
                    <select aria-label="Focus by category" value={queryCategory} onChange={(event) => setQueryCategory(event.target.value)}><option value="">All categories</option>{categoryOptions.map((category) => <option key={category}>{category}</option>)}</select>
                    <select aria-label="Focus by carrier" value={queryCarrier} onChange={(event) => setQueryCarrier(event.target.value)}><option value="">All carriers</option>{carriers.map((carrier) => <option key={carrier}>{carrier}</option>)}</select>
                    <select aria-label="Focus by policy" value={queryPolicy} onChange={(event) => setQueryPolicy(event.target.value)}><option value="">All policies</option>{policies.map((policy) => <option value={policy.id} key={policy.id}>{policyTitle(policy)}</option>)}</select>
                  </div>
                  {(answerLoading || searchLoading) && <div className="result-loading"><LoaderCircle className="spin" size={21} /><div><strong>{answerLoading ? "Reviewing your policies…" : "Searching your documents…"}</strong><span>Finding the most relevant passages for your question.</span></div></div>}
                  {answer && !answerLoading && <AnswerCard answer={answer} abstained={abstained} sources={sources} />}
                  {searchResults.length > 0 && !searchLoading && <SearchResults results={searchResults} total={totalMatches} />}
                  {!answer && !answerLoading && !searchLoading && searchResults.length === 0 && <div className="assistant-empty"><div className="empty-orb"><Sparkles size={20} /></div><h3>Your policy details, at your fingertips.</h3><p>Answers are generated from your documents—not the internet. Ask a question to get started.</p><div className="prompt-chips"><button onClick={() => setQuestion("What are my policy limits?")}>What are my policy limits? <ArrowUpRight size={13} /></button><button onClick={() => setQuestion("What is excluded from my coverage?")}>What is excluded? <ArrowUpRight size={13} /></button></div></div>}
                </div>
                <aside className="assistant-aside">
                  <div className="aside-title"><div className="aside-icon"><FileText size={15} /></div><div><strong>Your sources</strong><span>{sources.length} cited passages</span></div></div>
                  {sources.length ? sources.map((source, index) => <SourceCard key={source.chunk_id} source={source} index={index + 1} />) : <div className="sources-placeholder"><div className="source-lines"><i /><i /><i /><i /></div><p>Sources appear here with every answer, so you can verify the details.</p></div>}
                  <div className="trust-note"><BadgeCheck size={16} /><span>Answers are grounded in your policies. Always confirm important decisions with your insurer.</span></div>
                </aside>
              </section>
            </>
          )}
        </div>
      </section>

      {notice && <div className={`toast ${notice.type}`} role="status"><span>{notice.type === "success" ? <Check size={16} /> : <CircleHelp size={16} />}</span>{notice.text}<button onClick={() => setNotice(null)} aria-label="Dismiss"><X size={15} /></button></div>}

      {showUpload && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !uploading) setShowUpload(false); }}>
        <div className="modal upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
          <div className="modal-heading"><div className="modal-icon"><CloudUpload size={20} /></div><button className="icon-button" onClick={() => setShowUpload(false)} aria-label="Close upload" disabled={uploading}><X size={18} /></button></div>
          <h2 id="upload-title">Add a policy</h2><p>Upload a policy document and we’ll make it searchable.</p>
          <form ref={uploadFormRef} onSubmit={handleUpload}>
            <input ref={fileInputRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden onChange={handleFileChange} />
            <button type="button" className={`dropzone ${dragging ? "dropzone-active" : ""} ${uploadFile ? "dropzone-file" : ""}`} onClick={() => fileInputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); selectFile(event.dataTransfer.files[0]); }}>
              <span className="dropzone-icon">{uploadFile ? <FileText size={22} /> : <Upload size={21} />}</span>
              <strong>{uploadFile ? uploadFile.name : "Click to upload or drag and drop"}</strong>
              <small>{uploadFile ? `${(uploadFile.size / 1024 / 1024).toFixed(2)} MB · Ready to upload` : "PDF or DOCX · Max file size may depend on your server"}</small>
            </button>
            <div className="form-grid"><label>Policy name<input name="name" placeholder="e.g. Comprehensive home cover" /></label><label>Category<select name="category" defaultValue=""><option value="">Select category</option>{categoryOptions.map((category) => <option key={category}>{category}</option>)}</select></label><label>Insurance carrier<input name="carrier" placeholder="e.g. Acme Insurance" /></label><span className="form-spacer" /><label>Effective date<input name="effective_date" type="date" /></label><label>Expiration date<input name="expires_date" type="date" /></label></div>
            <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setShowUpload(false)} disabled={uploading}>Cancel</button><button type="submit" className="button button-primary" disabled={!uploadFile || uploading}>{uploading ? <><LoaderCircle size={15} className="spin" /> Uploading…</> : <><CloudUpload size={16} /> Upload policy</>}</button></div>
          </form>
        </div>
      </div>}

      {selectedPolicy && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedPolicy(null); }}>
        <div className="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
          <div className="modal-heading"><div className={`carrier-avatar ${carrierTone(selectedPolicy.category)}`}>{initials(selectedPolicy.carrier)}</div><button className="icon-button" onClick={() => setSelectedPolicy(null)} aria-label="Close details"><X size={18} /></button></div>
          <div className="eyebrow detail-category">{selectedPolicy.category || "POLICY DOCUMENT"}</div><h2 id="detail-title">{policyTitle(selectedPolicy)}</h2><p className="detail-carrier">{selectedPolicy.carrier || "Carrier not specified"}</p>{detailLoading && <div className="detail-loading"><LoaderCircle size={15} className="spin" /> Refreshing policy details…</div>}
          <div className="detail-meta"><div><span>Status</span><strong><span className={`table-status-dot ${statusTone(selectedPolicy.status)}`} />{selectedPolicy.status || "Active"}</strong></div><div><span>Version</span><strong>{selectedPolicy.version ?? "—"}</strong></div><div><span>Effective date</span><strong>{formatDate(selectedPolicy.effective_date)}</strong></div><div><span>Expires</span><strong>{formatDate(selectedPolicy.expires_date)}</strong></div><div><span>File</span><strong><File size={14} />{selectedPolicy.filename || "Policy document"}</strong></div>{selectedPolicy.policy_series_id && <div><span>Policy series</span><strong>{selectedPolicy.policy_series_id}</strong></div>}</div>
          <div className="modal-actions detail-actions"><a className="button button-secondary" href={getPolicyFileUrl(selectedPolicy.id)} target="_blank" rel="noreferrer"><File size={15} /> Open original file</a><button className="button button-secondary" onClick={() => setSelectedPolicy(null)}>Close</button><button className="button button-danger" onClick={() => { setDeleteTarget(selectedPolicy); setSelectedPolicy(null); }}><Archive size={15} /> Archive policy</button></div>
        </div>
      </div>}

      {deleteTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteTarget(null); }}><div className="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="archive-title">
        <div className="modal-heading"><div className="modal-icon danger-icon"><Archive size={19} /></div><button className="icon-button" onClick={() => setDeleteTarget(null)} aria-label="Close confirmation"><X size={18} /></button></div><h2 id="archive-title">Archive this policy?</h2><p><strong>{policyTitle(deleteTarget)}</strong> will be archived and retained in your policy records.</p><div className="modal-actions"><button className="button button-secondary" onClick={() => setDeleteTarget(null)}>Keep policy</button><button className="button button-danger" onClick={() => void confirmArchive()}><Archive size={15} /> Archive policy</button></div>
      </div></div>}
    </main>
  );
}

function MetricCard({ icon, label, value, note, tone }: { icon: React.ReactNode; label: string; value: string; note: string; tone: string }) {
  return <article className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><span className="metric-note">{note}</span></article>;
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="error-banner"><CircleHelp size={17} /><span>{message}</span><button onClick={onRetry}>Try again <ArrowRight size={13} /></button></div>;
}

function carrierTone(category?: string) {
  const value = (category || "").toLowerCase();
  if (value.includes("auto")) return "tone-blue";
  if (value.includes("home")) return "tone-violet";
  if (value.includes("life")) return "tone-rose";
  if (value.includes("health")) return "tone-mint";
  return "tone-amber";
}

function statusTone(status?: string) {
  const value = (status || "active").toLowerCase();
  if (value === "expired" || value === "inactive" || value === "cancelled") return "status-expired";
  if (value === "archived") return "status-archived";
  if (value === "pending") return "status-pending";
  return "status-active";
}

function PolicyTable({ policies, loading, error, onSelect, onRetry, emptyAction, onDelete }: { policies: Policy[]; loading: boolean; error: string; onSelect: (policy: Policy) => void; onRetry: () => void; emptyAction: () => void; onDelete?: (policy: Policy) => void }) {
  return <div className="table-card">
    <div className="table-scroll"><table><thead><tr><th>POLICY</th><th>CATEGORY</th><th>CARRIER</th><th>STATUS</th><th>EXPIRES</th><th /></tr></thead>
      <tbody>
        {loading && <tr><td colSpan={6}><div className="table-message"><LoaderCircle className="spin" size={19} /> Loading your policies…</div></td></tr>}
        {!loading && !policies.length && <tr><td colSpan={6}><div className="table-empty">{error ? <><CircleHelp size={21} /><strong>Couldn’t load policies</strong><span>{error}</span><button className="text-button" onClick={onRetry}>Try again <ArrowRight size={13} /></button></> : <><div className="empty-file-icon"><FileText size={21} /></div><strong>No policies yet</strong><span>Add your first document to get started.</span><button className="button button-primary compact" onClick={emptyAction}><Plus size={14} /> Add a policy</button></>}</div></td></tr>}
        {!loading && policies.map((policy) => <tr key={policy.id} className="policy-row" onClick={() => onSelect(policy)}>
          <td><div className="policy-cell"><div className={`carrier-avatar ${carrierTone(policy.category)}`}>{initials(policy.carrier)}</div><div><strong>{policyTitle(policy)}</strong><span>{policy.filename || policy.id}</span></div></div></td>
          <td><span className="category-pill">{policy.category || "Uncategorized"}</span></td>
          <td className="carrier-name">{policy.carrier || "—"}</td>
          <td><span className="status-label"><span className={`table-status-dot ${statusTone(policy.status)}`} />{policy.status || "Active"}</span></td>
          <td className="date-cell">{formatDate(policy.expires_date)}</td>
          <td className="row-actions" onClick={(event) => event.stopPropagation()}><button aria-label={`View ${policyTitle(policy)}`} onClick={() => onSelect(policy)}><ArrowUpRight size={16} /></button>{onDelete && <button aria-label={`Archive ${policyTitle(policy)}`} onClick={() => onDelete(policy)}><Archive size={15} /></button>}</td>
        </tr>)}
      </tbody>
    </table></div>
  </div>;
}

function AnswerCard({ answer, abstained, sources }: { answer: string; abstained: boolean; sources: SearchResult[] }) {
  return <article className={`answer-card ${abstained ? "answer-abstained" : ""}`}><div className="answer-topline"><div className="answer-brand"><span><Sparkles size={14} /></span><strong>Coverwise answer</strong><span className="grounded-tag"><BadgeCheck size={12} /> Grounded in your policies</span></div><button className="icon-button" aria-label="Answer options"><MoreHorizontal size={18} /></button></div><div className="answer-copy">{answer.split("\n").filter(Boolean).map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>{abstained && <div className="abstain-note"><CircleHelp size={15} /> There isn’t enough information in the available documents to answer with confidence.</div>}<div className="answer-bottom"><span>{sources.length} source{sources.length === 1 ? "" : "s"} cited</span><span>AI can make mistakes. Verify important details.</span></div></article>;
}

function SourceCard({ source, index }: { source: SearchResult; index: number }) {
  return <article className="source-card"><div className="source-card-head"><div className="source-num">{String(index).padStart(2, "0")}</div><span className="similarity">{scorePercent(source.similarity_score)} match</span></div><strong className="source-title">{source.policy_name || source.filename}</strong><div className="source-meta"><span>{source.section || "Policy passage"}</span>{source.page_number ? <><span className="meta-dot">·</span><span>Page {source.page_number}</span></> : null}</div><blockquote>“{source.content}”</blockquote><div className="source-bottom"><span>{source.carrier || source.category}</span><BadgeCheck size={14} /></div></article>;
}

function SearchResults({ results, total }: { results: SearchResult[]; total: number }) {
  return <section className="search-results"><div className="results-title"><div><h2>Matching passages</h2><p>{total} relevant {total === 1 ? "passage" : "passages"} from your documents</p></div><span className="search-result-count"><Search size={14} /> {total} results</span></div>{results.map((result) => <article className="search-result-card" key={result.chunk_id}><div className="search-result-head"><div><strong>{result.policy_name || result.filename}</strong><span>{result.section || "Policy passage"}{result.page_number ? ` · Page ${result.page_number}` : ""}</span></div><span className="similarity">{scorePercent(result.similarity_score)} match</span></div><p>{result.content}</p><div className="search-result-foot"><span>{result.carrier || result.category}</span><span>{result.filename}</span></div></article>)}</section>;
}
