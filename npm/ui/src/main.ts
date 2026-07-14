import { LitElement, html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";
import { unsafeHTML } from "lit/directives/unsafe-html.js";
import { safeMarkdown } from "./security";
import "./styles.css";

type Route = "overview" | "chat" | "jobs" | "reports" | "connections" | "settings";
type Json = Record<string, any>;
type Message = { role: "user" | "assistant"; content: string };

export const NAV: Array<[Route, string, string]> = [
  ["overview", "Tổng quan", "◈"], ["chat", "Trợ lý", "◇"], ["jobs", "Công việc", "▤"],
  ["reports", "Báo cáo", "▧"], ["connections", "Kết nối", "⌁"], ["settings", "Cài đặt", "⚙"],
];

@customElement("taxsentry-app")
export class TaxSentryApp extends LitElement {
  createRenderRoot() { return this; }

  @state() private ready = false;
  @state() private authenticated = false;
  @state() private csrf = "";
  @state() private version = "";
  @state() private configured = false;
  @state() private route: Route = "overview";
  @state() private data: Json = {};
  @state() private jobs: Json[] = [];
  @state() private report: Json | null = null;
  @state() private connections: Json = {};
  @state() private settingsData: Json = {};
  @state() private messages: Message[] = [];
  @state() private toolStatus = "";
  @state() private busy = false;
  @state() private error = "";
  @state() private loginToken = "";
  @state() private prompt = "";
  @state() private wizard: Json | null = null;
  @state() private wizardStep = 0;
  @state() private gmailPassword = "";
  @state() private telegramToken = "";

  connectedCallback() {
    super.connectedCallback();
    this.boot();
    window.addEventListener("hashchange", this.onHash);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this.onHash);
    super.disconnectedCallback();
  }

  private onHash = () => {
    const candidate = location.hash.slice(1) as Route;
    this.route = NAV.some(([id]) => id === candidate) ? candidate : "overview";
    this.loadRoute();
  };

  private async boot() {
    const code = new URLSearchParams(location.search).get("code");
    if (code) {
      await this.login(code);
      history.replaceState({}, "", location.pathname + location.hash);
    }
    const state = await fetch("/api/bootstrap").then((response) => response.json());
    this.authenticated = state.authenticated;
    this.csrf = state.csrf || "";
    this.configured = state.configured;
    this.version = state.version;
    this.ready = true;
    this.onHash();
    if (this.authenticated && !this.configured) {
      this.route = "connections";
      location.hash = "connections";
      await this.startWizard();
    }
  }

  private async request(path: string, options: RequestInit = {}): Promise<Json> {
    const headers = new Headers(options.headers);
    if (options.body) headers.set("content-type", "application/json");
    if (options.method && options.method !== "GET") headers.set("x-csrf-token", this.csrf);
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) this.authenticated = false;
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  private async login(credential = this.loginToken) {
    this.error = "";
    try {
      const state = await fetch("/api/session", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ credential }) }).then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error);
        return payload;
      });
      this.authenticated = true;
      this.csrf = state.csrf;
      this.loginToken = "";
      await this.loadRoute();
    } catch (error) { this.error = String(error); }
  }

  private async logout() {
    await this.request("/api/session", { method: "DELETE" });
    this.authenticated = false;
  }

  private async loadRoute() {
    if (!this.authenticated) return;
    this.error = "";
    try {
      if (this.route === "overview") this.data = await this.request("/api/overview");
      if (this.route === "jobs") this.jobs = (await this.request("/api/jobs")).jobs;
      if (this.route === "reports") this.report = (await this.request("/api/reports/latest")).report;
      if (this.route === "connections") this.connections = await this.request("/api/connections");
      if (this.route === "settings") this.settingsData = await this.request("/api/settings");
      if (this.route === "chat") this.messages = (await this.request("/api/chat/session")).messages || [];
    } catch (error) { this.error = String(error); }
  }

  private navigate(route: Route) { location.hash = route; }

  private async sendChat(event: Event) {
    event.preventDefault();
    const prompt = this.prompt.trim();
    if (!prompt || this.busy) return;
    this.messages = [...this.messages, { role: "user", content: prompt }, { role: "assistant", content: "" }];
    this.prompt = ""; this.busy = true; this.error = "";
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": this.csrf }, body: JSON.stringify({ prompt }) });
      if (!response.ok || !response.body) throw new Error((await response.json()).error || "Chat failed");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n"); buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line) continue;
          const item = JSON.parse(line);
          if (item.type === "text_delta") {
            const copy = [...this.messages];
            copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + item.text };
            this.messages = copy;
          } else if (item.type === "tool_started") this.toolStatus = `Đang chạy ${item.name}…`;
          else if (item.type === "tool_completed") this.toolStatus = `Hoàn tất ${item.name}`;
          else if (item.type === "error") throw new Error(item.text);
        }
        if (done) break;
      }
    } catch (error) { this.error = String(error); }
    finally { this.busy = false; this.toolStatus = ""; }
  }

  private async resetChat(action: "new" | "clear") {
    if (action === "clear" && !confirm("Xóa context của phiên hiện tại?")) return;
    await this.request("/api/chat/session", { method: "POST", body: JSON.stringify({ action }) });
    this.messages = [];
  }

  private async jobAction(id: string, action: "retry" | "approve") {
    if (!confirm(action === "approve" ? "Duyệt và đưa job vào xử lý lại?" : "Đưa job này vào hàng đợi lại?")) return;
    try { await this.request(`/api/jobs/${id}/${action}`, { method: "POST" }); await this.loadRoute(); }
    catch (error) { this.error = String(error); }
  }

  private async sendReport() {
    if (!this.report || !confirm("Gửi lại báo cáo này qua các kênh đã cấu hình?")) return;
    try { await this.request(`/api/reports/${this.report.job_id}/send`, { method: "POST" }); }
    catch (error) { this.error = String(error); }
  }

  private async serviceAction(action: string) {
    try { const result = await this.request(`/api/service/${action}`, { method: "POST" }); alert(result.detail); }
    catch (error) { this.error = String(error); }
  }

  private async startWizard() {
    try {
      this.wizard = (await this.request("/api/onboarding/start", { method: "POST" })).config;
      this.wizardStep = 0;
    } catch (error) { this.error = String(error); }
  }

  private updateWizard(section: string, key: string, value: any) {
    this.wizard = { ...this.wizard, [section]: { ...this.wizard?.[section], [key]: value } };
  }

  private async verifyWizard() {
    if (!this.wizard) return;
    this.busy = true; this.error = "";
    try {
      await this.request("/api/onboarding/step", { method: "POST", body: JSON.stringify({ patch: this.wizard }) });
      const result = await this.request("/api/onboarding/verify", { method: "POST", body: JSON.stringify({ gmail_password: this.gmailPassword, telegram_token: this.telegramToken }) });
      this.wizard = result.config;
      this.wizardStep = 5;
    } catch (error) { this.error = String(error); }
    finally { this.busy = false; }
  }

  private async commitWizard() {
    try {
      await this.request("/api/onboarding/commit", { method: "POST" });
      this.wizard = null; this.configured = true; this.gmailPassword = ""; this.telegramToken = "";
      this.connections = await this.request("/api/connections");
    } catch (error) { this.error = String(error); }
  }

  private async cancelWizard() {
    await this.request("/api/onboarding/cancel", { method: "POST" });
    this.wizard = null;
  }

  private async startCodexOAuth() {
    try {
      const result = await this.request("/api/oauth/codex/start", { method: "POST", body: JSON.stringify({ device_code: false }) });
      if (result.authUrl) window.open(result.authUrl, "_blank", "noopener");
      if (result.verificationUrl) window.open(result.verificationUrl, "_blank", "noopener");
      const id = result.loginId;
      const timer = window.setInterval(async () => {
        try {
          const status = await this.request(`/api/oauth/codex/${id}`);
          if (status.status === "complete") { clearInterval(timer); alert("Codex đã kết nối."); }
        } catch (error) { clearInterval(timer); this.error = String(error); }
      }, 1200);
    } catch (error) { this.error = String(error); }
  }

  private async saveSettings() {
    try {
      await this.request("/api/settings", { method: "PATCH", body: JSON.stringify(this.settingsData) });
      alert("Đã lưu cài đặt.");
    } catch (error) { this.error = String(error); }
  }

  render() {
    if (!this.ready) return html`<div class="loading-screen"><div class="pulse-mark" aria-label="Đang kết nối">◆</div></div>`;
    if (!this.authenticated) return this.renderLogin();
    const title = NAV.find(([id]) => id === this.route)?.[1] || "Tổng quan";
    return html`<div class="shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">◆</div><div><strong>TaxSentry</strong><small>Control Center</small></div></div>
        <nav class="nav" aria-label="Điều hướng chính">${NAV.map(([id, label, icon]) => html`<button aria-label=${label} class=${this.route === id ? "active" : ""} @click=${() => this.navigate(id)}><span aria-hidden="true">${icon}</span><span>${label}</span></button>`)}</nav>
        <div class="sidebar-foot">v${this.version}<br />Local secure session</div>
      </aside>
      <section class="workspace">
        <header class="topbar"><div><p class="eyebrow">Finance command center</p><h1>${title}</h1></div><div class="actions"><span class="status-pill"><span class="status-dot"></span>Localhost an toàn</span><button class="btn small" @click=${this.logout}>Đăng xuất</button></div></header>
        <main id="main" class="content">${this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing}${this.renderRoute()}</main>
      </section>
    </div>`;
  }

  private renderLogin() {
    return html`<div class="login-screen"><div class="login-card">
      <div class="brand-mark">◆</div><p class="eyebrow">TaxSentry secure access</p><h1>Finance Command Center</h1>
      <p>Nhập operator token. Khi chạy <code>taxsentry start</code>, trình duyệt sẽ được đăng nhập tự động bằng mã dùng một lần.</p>
      ${this.error ? html`<div class="error">${this.error}</div>` : nothing}
      <form @submit=${(event: Event) => { event.preventDefault(); this.login(); }}><div class="field"><label for="token">Operator token</label><input id="token" class="input" type="password" autocomplete="current-password" .value=${this.loginToken} @input=${(event: InputEvent) => this.loginToken = (event.target as HTMLInputElement).value} /></div><button class="btn primary" type="submit">Mở Control Center</button></form>
    </div></div>`;
  }

  private renderRoute(): TemplateResult {
    if (this.route === "chat") return this.renderChat();
    if (this.route === "jobs") return this.renderJobs();
    if (this.route === "reports") return this.renderReports();
    if (this.route === "connections") return this.renderConnections();
    if (this.route === "settings") return this.renderSettings();
    return this.renderOverview();
  }

  private renderOverview() {
    const counts = this.data.job_counts || {}, provider = this.data.provider || {}, latest = this.data.latest_report;
    return html`<section class="grid metrics">
      ${this.metric("Provider", provider.kind || "—", provider.healthy ? "Hoạt động tốt" : "Cần kiểm tra", provider.healthy ? "good" : "warn")}
      ${this.metric("Đã hoàn tất", String(counts.completed || 0), "Jobs gần đây", "good")}
      ${this.metric("Cần duyệt", String(counts.needs_review || 0), "Quyết định của Sếp", counts.needs_review ? "warn" : "")}
      ${this.metric("Độ tin cậy", latest ? `${Math.round((latest.confidence || 0) * 100)}%` : "—", "Báo cáo gần nhất", "")}
    </section><section class="grid two-col">
      <article class="card"><div class="card-header"><h2>Ledger công việc gần đây</h2><button class="btn small" @click=${() => this.navigate("jobs")}>Xem tất cả</button></div>${this.jobsTable(this.data.jobs || [])}</article>
      <article class="card"><div class="card-header"><h2>Sentry Pulse</h2><span class=${provider.healthy ? "good" : "warn"}>${provider.healthy ? "● Healthy" : "● Attention"}</span></div><p><strong>${provider.model || "default"}</strong></p><p class="muted">${provider.detail || "Chưa có health data"}</p><hr style="border:0;border-top:1px solid var(--line);margin:1rem 0"><p class="muted">Gmail: ${this.data.gmail?.enabled ? this.data.gmail.account || "chưa kết nối" : "tắt"}</p><p class="muted">Telegram: ${this.data.telegram?.enabled ? "đang bật" : "tắt"}</p></article>
    </section>`;
  }

  private metric(label: string, value: string, note: string, tone: string) { return html`<article class="card metric"><span class="label">${label}</span><strong class=${tone}>${value}</strong><small>${note}</small></article>`; }

  private jobsTable(items: Json[]) {
    if (!items.length) return html`<div class="empty">Chưa có công việc.</div>`;
    return html`<div class="table-wrap"><table><thead><tr><th>Job</th><th>Trạng thái</th><th>Tiêu đề</th><th>Thời gian</th><th></th></tr></thead><tbody>${items.map((job) => html`<tr><td><code>${job.id.slice(0, 8)}</code></td><td><span class="state ${job.state}">${job.state}</span></td><td>${job.subject}</td><td class="muted">${new Date(job.updated_at).toLocaleString("vi-VN")}</td><td><div class="actions">${job.state === "needs_review" ? html`<button class="btn small primary" @click=${() => this.jobAction(job.id, "approve")}>Duyệt</button>` : nothing}${["failed", "needs_review"].includes(job.state) ? html`<button class="btn small" @click=${() => this.jobAction(job.id, "retry")}>Thử lại</button>` : nothing}</div></td></tr>`)}</tbody></table></div>`;
  }

  private renderChat() {
    return html`<article class="card chat-layout"><div class="messages" aria-live="polite">${this.messages.length ? this.messages.map((message) => html`<div class="message ${message.role}">${unsafeHTML(safeMarkdown(message.content || (this.busy ? "Đang suy nghĩ…" : "")))}</div>`) : html`<div class="empty"><div class="brand-mark" style="margin:0 auto 1rem">◆</div><strong>TaxSentry sẵn sàng</strong><p>Hỏi về báo cáo, rủi ro thuế hoặc trạng thái công việc.</p></div>`}${this.toolStatus ? html`<div class="tool-event">● ${this.toolStatus}</div>` : nothing}</div><div class="composer"><div class="actions" style="margin-bottom:.6rem"><button class="btn small" @click=${() => this.resetChat("new")}>Phiên mới</button><button class="btn small" @click=${() => this.resetChat("clear")}>Xóa context</button></div><form @submit=${this.sendChat}><textarea class="input" aria-label="Tin nhắn" placeholder="Nhập yêu cầu cho TaxSentry…" .value=${this.prompt} @input=${(event: InputEvent) => this.prompt = (event.target as HTMLTextAreaElement).value}></textarea><button class="btn primary" ?disabled=${this.busy}>${this.busy ? "Đang chạy" : "Gửi"}</button></form></div></article>`;
  }

  private renderJobs() { return html`<article class="card"><div class="card-header"><h2>Job ledger</h2><button class="btn small" @click=${() => this.loadRoute()}>Làm mới</button></div>${this.jobsTable(this.jobs)}</article>`; }

  private renderReports() {
    if (!this.report) return html`<div class="card empty">Chưa có báo cáo.</div>`;
    const payload = this.report.payload || {};
    return html`<section class="grid two-col"><article class="card"><div class="card-header"><h2>${this.report.subject || "Báo cáo mới nhất"}</h2><span class="state completed">${Math.round((this.report.confidence || 0) * 100)}% confidence</span></div><p class="report-summary">${payload.executive_summary}</p><h3>Khuyến nghị</h3><div class="risk-list">${(payload.recommendations || []).map((item: Json) => html`<div class="risk"><strong>${item.priority || "ưu tiên"}</strong><br />${item.action}</div>`)}</div></article><aside class="card"><div class="card-header"><h2>Hành động</h2></div><div class="actions"><a class="btn primary" href=${`/api/reports/${this.report.job_id}/download`} target="_blank">Tải PDF</a><button class="btn" @click=${this.sendReport}>Gửi lại</button></div><p class="muted">Người gửi: ${this.report.sender}</p><p class="muted">Tạo lúc: ${new Date(this.report.created_at).toLocaleString("vi-VN")}</p></aside></section>`;
  }

  private renderConnections() {
    if (this.wizard) return this.renderWizard();
    const provider = this.connections.provider || {};
    return html`<section class="grid two-col"><article class="card"><div class="card-header"><h2>Kết nối hệ thống</h2><button class="btn primary" @click=${this.startWizard}>Cấu hình lại</button></div>${this.connectionRow("AI Provider", provider.ok, `${provider.kind || "—"} · ${provider.detail || ""}`)}${this.connectionRow("Gmail", this.connections.gmail?.connected, this.connections.gmail?.enabled ? this.connections.gmail.account || "Chưa kết nối" : "Đã tắt")}${this.connectionRow("Telegram", this.connections.telegram?.connected, this.connections.telegram?.enabled ? "Bot token đã lưu" : "Đã tắt")}</article><aside class="card"><div class="card-header"><h2>Worker service</h2></div><div class="actions"><button class="btn" @click=${() => this.serviceAction("status")}>Trạng thái</button><button class="btn" @click=${() => this.serviceAction("start")}>Khởi động</button><button class="btn" @click=${() => this.serviceAction("stop")}>Dừng</button><button class="btn" @click=${() => this.serviceAction("logs")}>Logs</button></div></aside></section>`;
  }

  private connectionRow(label: string, ok: boolean, detail: string) { return html`<div style="display:flex;justify-content:space-between;gap:1rem;padding:.9rem 0;border-bottom:1px solid var(--line)"><div><strong>${label}</strong><div class="muted">${detail}</div></div><span class=${ok ? "good" : "warn"}>${ok ? "● Ready" : "● Attention"}</span></div>`; }

  private renderWizard() {
    const w = this.wizard!;
    return html`<article class="card" style="max-width:760px;margin:0 auto"><div class="card-header"><div><p class="eyebrow">Guided onboarding</p><h2>Bước ${this.wizardStep + 1} / 6</h2></div><button class="btn small" @click=${this.cancelWizard}>Hủy</button></div><div class="wizard-steps">${[0,1,2,3,4,5].map((step) => html`<span class=${step <= this.wizardStep ? "on" : ""}></span>`)}</div>
      ${this.wizardStep === 0 ? html`<div class="notice">TaxSentry có thể đọc email và gửi báo cáo. Chỉ cấp quyền cần thiết, giữ token bí mật và luôn để Giám đốc duyệt quyết định quan trọng.</div><h3>Chào mừng đến Control Center</h3><p class="muted">Cấu hình chỉ được lưu sau khi tất cả kết nối bắt buộc vượt qua kiểm tra thật.</p>` : nothing}
      ${this.wizardStep === 1 ? html`<div class="field"><label>Provider</label><select class="input" .value=${w.provider.kind} @change=${(e: Event) => this.updateWizard("provider", "kind", (e.target as HTMLSelectElement).value)}><option value="lmstudio">LM Studio</option><option value="codex">Codex / ChatGPT</option></select></div>${w.provider.kind === "codex" ? html`<button class="btn" @click=${this.startCodexOAuth}>Đăng nhập Codex bằng trình duyệt</button>` : html`<div class="field"><label>LM Studio Base URL</label><input class="input" .value=${w.provider.lmstudio_base_url || w.provider.base_url} @input=${(e: InputEvent) => { this.updateWizard("provider", "lmstudio_base_url", (e.target as HTMLInputElement).value); this.updateWizard("provider", "base_url", (e.target as HTMLInputElement).value); }} /></div>`}` : nothing}
      ${this.wizardStep === 2 ? html`<div class="field"><label>Model ID (để trống sẽ tự chọn model đầu tiên)</label><input class="input" .value=${w.provider.model || ""} @input=${(e: InputEvent) => this.updateWizard("provider", "model", (e.target as HTMLInputElement).value)} /></div>` : nothing}
      ${this.wizardStep === 3 ? html`<label class="check"><input type="checkbox" .checked=${w.gmail.enabled} @change=${(e: Event) => this.updateWizard("gmail", "enabled", (e.target as HTMLInputElement).checked)} /> Bật Gmail workflow</label>${w.gmail.enabled ? html`<div class="field"><label>Gmail account</label><input class="input" type="email" .value=${w.gmail.account || ""} @input=${(e: InputEvent) => this.updateWizard("gmail", "account", (e.target as HTMLInputElement).value)} /></div><div class="field"><label>App Password (để trống để dùng keyring hiện tại)</label><input class="input" type="password" .value=${this.gmailPassword} @input=${(e: InputEvent) => this.gmailPassword = (e.target as HTMLInputElement).value} /></div><div class="field"><label>Trusted senders, phân cách dấu phẩy</label><input class="input" .value=${(w.gmail.trusted_senders || []).join(", ")} @input=${(e: InputEvent) => this.updateWizard("gmail", "trusted_senders", (e.target as HTMLInputElement).value.split(",").map(v => v.trim()).filter(Boolean))} /></div><div class="field"><label>Email Giám đốc</label><input class="input" type="email" .value=${w.director.email || ""} @input=${(e: InputEvent) => this.updateWizard("director", "email", (e.target as HTMLInputElement).value)} /></div>` : nothing}` : nothing}
      ${this.wizardStep === 4 ? html`<label class="check"><input type="checkbox" .checked=${w.telegram.enabled} @change=${(e: Event) => this.updateWizard("telegram", "enabled", (e.target as HTMLInputElement).checked)} /> Bật Telegram</label>${w.telegram.enabled ? html`<div class="field"><label>Bot token (để trống để dùng keyring hiện tại)</label><input class="input" type="password" .value=${this.telegramToken} @input=${(e: InputEvent) => this.telegramToken = (e.target as HTMLInputElement).value} /></div><div class="field"><label>Chat IDs, phân cách dấu phẩy</label><input class="input" .value=${(w.director.telegram_chat_ids || []).join(", ")} @input=${(e: InputEvent) => this.updateWizard("director", "telegram_chat_ids", (e.target as HTMLInputElement).value.split(",").map(v => v.trim()).filter(Boolean))} /></div>` : nothing}` : nothing}
      ${this.wizardStep === 5 ? html`<div class="notice">Mọi kiểm tra đã hoàn tất. Nhấn lưu để commit config và secret đã xác minh.</div><h3>${w.provider.kind} · ${w.provider.model || "default"}</h3><p class="muted">Gmail: ${w.gmail.enabled ? w.gmail.account : "tắt"} · Telegram: ${w.telegram.enabled ? "bật" : "tắt"}</p>` : nothing}
      <div class="actions" style="margin-top:1.2rem">${this.wizardStep > 0 && this.wizardStep < 5 ? html`<button class="btn" @click=${() => this.wizardStep--}>Quay lại</button>` : nothing}${this.wizardStep < 4 ? html`<button class="btn primary" @click=${() => this.wizardStep++}>Tiếp tục</button>` : nothing}${this.wizardStep === 4 ? html`<button class="btn primary" ?disabled=${this.busy} @click=${this.verifyWizard}>${this.busy ? "Đang kiểm tra…" : "Kiểm tra kết nối"}</button>` : nothing}${this.wizardStep === 5 ? html`<button class="btn primary" @click=${this.commitWizard}>Lưu cấu hình</button>` : nothing}</div>
    </article>`;
  }

  private renderSettings() {
    const data = this.settingsData;
    if (!data.worker) return html`<div class="card empty">Đang tải…</div>`;
    return html`<section class="grid two-col"><article class="card"><div class="card-header"><h2>Runtime</h2></div><div class="field"><label>Polling interval (giây)</label><input class="input" type="number" min="10" .value=${String(data.worker.poll_seconds)} @input=${(e: InputEvent) => this.settingsData = { ...data, worker: { ...data.worker, poll_seconds: Number((e.target as HTMLInputElement).value) } }} /></div><div class="field"><label>Độ tin cậy báo cáo tối thiểu</label><input class="input" type="number" min="0" max="1" step="0.05" .value=${String(data.report.minimum_confidence)} @input=${(e: InputEvent) => this.settingsData = { ...data, report: { ...data.report, minimum_confidence: Number((e.target as HTMLInputElement).value) } }} /></div><button class="btn primary" @click=${this.saveSettings}>Lưu cài đặt</button></article><aside class="card"><div class="card-header"><h2>Thông tin cấu hình</h2></div><p class="muted">Provider: ${data.provider.kind} / ${data.provider.model || "default"}</p><p class="muted">Ngôn ngữ: ${data.agent.language}</p><p class="muted">Theme: ${data.ui.theme}</p><p class="notice">Đổi provider hoặc credentials tại màn hình Kết nối để luôn có live verification.</p></aside></section>`;
  }
}
