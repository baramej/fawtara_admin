/** @odoo-module **/
/**
 * Fawtara Admin Dashboard — fawtara_admin
 * Oman e-invoicing · Blue theme · Invoice & Billing analytics
 */

import { registry }   from "@web/core/registry";
import { Component, onWillStart, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS }     from "@web/core/assets";

// ── Field lists ───────────────────────────────────────────────────────────────
const JSON_FIELDS = [
    "invoices_by_day",
    "invoices_by_type",
    "invoices_by_client",
    "clearance_trend",
    "vat_by_month",
    "top_clients_table",
    "failed_invoices_list",
    "overage_clients_list",
];

const NUMERIC_FIELDS = [
    "total_clients",
    "active_clients",
    "invoices_today",
    "invoices_this_month",
    "cleared_this_month",
    "failed_this_month",
    "clearance_rate",
    "vat_this_month",
    "total_overage_omr",
    "queued_invoices",
];

function safeParse(val) {
    if (Array.isArray(val) || (val && typeof val === "object")) return val;
    try { return JSON.parse(val || "[]"); } catch { return []; }
}

function fmtOMR(val) {
    if (!val) return "0";
    if (val >= 1000000) return (val / 1000000).toFixed(2) + "M";
    if (val >= 1000)    return (val / 1000).toFixed(1) + "K";
    return val.toFixed(3);
}

// ── Component ─────────────────────────────────────────────────────────────────
class FawtaraDashboard extends Component {
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            ...Object.fromEntries(NUMERIC_FIELDS.map(f => [f, 0])),
            ...Object.fromEntries(JSON_FIELDS.map(f => [f, []])),
            loading:      true,
            dashboardId:  null,
            dateFrom:     null,
            dateTo:       null,
            quickFilters: {
                today:     false,
                thisWeek:  false,
                thisMonth: false,
                lastMonth: false,
                thisYear:  false,
            },
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.loadData();
        });

        onMounted(() => {
            if (!this.state.loading) this.renderCharts();
        });
    }

    _allFields() { return [...NUMERIC_FIELDS, ...JSON_FIELDS]; }

    _applyData(record) {
        for (const f of NUMERIC_FIELDS) {
            if (f in record) this.state[f] = record[f] || 0;
        }
        for (const f of JSON_FIELDS) {
            if (f in record) this.state[f] = safeParse(record[f]);
        }
    }

    // ── Data loading ──────────────────────────────────────────────────────────
    async loadData() {
        try {
            const ids = await this.orm.call(
                "fawtara.dashboard.owl", "search", [[]]);
            const id = ids.length
                ? ids[0]
                : await this.orm.call(
                    "fawtara.dashboard.owl", "create", [{}]);
            this.state.dashboardId = id;
            await this._readData(id);
            this.state.loading = false;
            setTimeout(() => this.renderCharts(), 80);
        } catch (err) {
            console.error("Fawtara Dashboard Load Error", err);
            this.state.loading = false;
        }
    }

    async _readData(id) {
        const data = await this.orm.call(
            "fawtara.dashboard.owl", "read",
            [[id], this._allFields()]);
        if (data && data.length) this._applyData(data[0]);
    }

    async applyDateFilter() {
        if (!this.state.dashboardId) return;
        this.state.loading = true;
        try {
            await this.orm.call(
                "fawtara.dashboard.owl", "write",
                [[this.state.dashboardId], {
                    date_from: this.state.dateFrom || false,
                    date_to:   this.state.dateTo   || false,
                }]);
            await this._readData(this.state.dashboardId);
            this.state.loading = false;
            setTimeout(() => this.renderCharts(), 80);
        } catch (err) {
            console.error("Filter error", err);
            this.state.loading = false;
        }
    }

    async clearDateFilter() {
        this.state.dateFrom = null;
        this.state.dateTo   = null;
        this.resetQuickFilters();
        await this.applyDateFilter();
    }

    // ── Quick filters ─────────────────────────────────────────────────────────
    setQuickFilter(filter) {
        this.resetQuickFilters();
        this.state.quickFilters[filter] = true;
        const today = new Date();
        let df, dt;
        switch (filter) {
            case "today":
                df = dt = this._fmt(today);
                break;
            case "thisWeek": {
                const f = new Date(today);
                f.setDate(today.getDate() - today.getDay());
                const l = new Date(today);
                l.setDate(today.getDate() - today.getDay() + 6);
                df = this._fmt(f); dt = this._fmt(l);
                break;
            }
            case "thisMonth":
                df = this._fmt(new Date(today.getFullYear(), today.getMonth(), 1));
                dt = this._fmt(new Date(today.getFullYear(), today.getMonth() + 1, 0));
                break;
            case "lastMonth":
                df = this._fmt(new Date(today.getFullYear(), today.getMonth() - 1, 1));
                dt = this._fmt(new Date(today.getFullYear(), today.getMonth(), 0));
                break;
            case "thisYear":
                df = this._fmt(new Date(today.getFullYear(), 0, 1));
                dt = this._fmt(new Date(today.getFullYear(), 11, 31));
                break;
        }
        this.state.dateFrom = df;
        this.state.dateTo   = dt;
        this.applyDateFilter();
    }

    resetQuickFilters() {
        Object.keys(this.state.quickFilters).forEach(
            k => this.state.quickFilters[k] = false);
    }

    _fmt(d) {
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        this.resetQuickFilters();
    }
    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this.resetQuickFilters();
    }

    // ── Chart helpers ─────────────────────────────────────────────────────────
    _chart(id, type, data, options) {
        const canvas = document.getElementById(id);
        if (!canvas) return;
        const ex = Chart.getChart(canvas);
        if (ex) ex.destroy();
        new Chart(canvas, { type, data, options });
    }

    renderCharts() {
        if (this.state.loading) return;
        try {
            this._chartByDay();
            this._chartByType();
            this._chartByClient();
            this._chartClearanceTrend();
            this._chartVatByMonth();
        } catch (e) { console.error("Chart error", e); }
    }

    _chartByDay() {
        const d = this.state.invoices_by_day;
        this._chart("fwt-chart-by-day", "line", {
            labels: d.map(x => x.day),
            datasets: [{
                label: "Invoices",
                data: d.map(x => x.count),
                borderColor: "#1d4ed8",
                backgroundColor: "rgba(29,78,216,0.12)",
                tension: 0.4,
                fill: true,
                pointBackgroundColor: "#1d4ed8",
            }],
        }, {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        });
    }

    _chartByType() {
        const d = this.state.invoices_by_type;
        this._chart("fwt-chart-by-type", "doughnut", {
            labels: d.map(x => x.label),
            datasets: [{
                data: d.map(x => x.count),
                backgroundColor: ["#1d4ed8","#10b981","#f59e0b","#8b5cf6"],
            }],
        }, {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom" } },
        });
    }

    _chartByClient() {
        const d = this.state.invoices_by_client.slice(0, 8);
        this._chart("fwt-chart-by-client", "bar", {
            labels: d.map(x => x.name),
            datasets: [{
                label: "Invoices",
                data: d.map(x => x.count),
                backgroundColor: "rgba(29,78,216,0.75)",
                borderRadius: 6,
            }],
        }, {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true } },
        });
    }

    _chartClearanceTrend() {
        const d = this.state.clearance_trend;
        this._chart("fwt-chart-clearance", "line", {
            labels: d.map(x => x.month),
            datasets: [
                {
                    label: "Cleared",
                    data: d.map(x => x.cleared),
                    borderColor: "#10b981",
                    backgroundColor: "rgba(16,185,129,0.12)",
                    tension: 0.4,
                    fill: true,
                },
                {
                    label: "Failed",
                    data: d.map(x => x.failed),
                    borderColor: "#ef4444",
                    backgroundColor: "rgba(239,68,68,0.10)",
                    tension: 0.4,
                    fill: true,
                },
            ],
        }, {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "top" } },
        });
    }

    _chartVatByMonth() {
        const d = this.state.vat_by_month;
        this._chart("fwt-chart-vat", "bar", {
            labels: d.map(x => x.month),
            datasets: [{
                label: "VAT (OMR)",
                data: d.map(x => x.vat),
                backgroundColor: "rgba(139,92,246,0.75)",
                borderRadius: 6,
            }],
        }, {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true } },
        });
    }

    // ── Navigation ────────────────────────────────────────────────────────────
    openView(model, name, domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    fmt(val)  { return fmtOMR(val); }
    pct(v, t) { return t ? Math.round(v / t * 100) : 0; }
}

FawtaraDashboard.template = "fawtara_admin.FawtaraDashboard";
registry.category("actions").add("fawtara_dashboard", FawtaraDashboard);