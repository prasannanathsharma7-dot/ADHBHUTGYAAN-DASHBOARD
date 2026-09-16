"use client";

import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { formatProblemCode, LEAD_STATUS_OPTIONS, type LeadStatus } from "@/lib/taxonomy";

export type Lead = {
  id: string;
  comment_text: string;
  analysis: {
    primary_problem_code: string;
    primary_dosh: string;
    urgency_score: number;
    recommended_service: string;
    lead_status: LeadStatus;
  };
  channel_title: string;
  author_name: string;
};

function StatusSelect({ lead, onChange }: { lead: Lead; onChange: (id: string, s: LeadStatus) => void }) {
  const [saving, setSaving] = useState(false);

  async function handleChange(next: LeadStatus) {
    setSaving(true);
    try {
      const res = await fetch("/api/leads/update-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: lead.id, status: next }),
      });
      if (res.ok) onChange(lead.id, next);
    } finally {
      setSaving(false);
    }
  }

  return (
    <select
      value={lead.analysis.lead_status}
      disabled={saving}
      onChange={(e) => handleChange(e.target.value as LeadStatus)}
      className="border border-line bg-panel px-2 py-1 text-xs text-ink disabled:opacity-50"
    >
      {LEAD_STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

export default function LeadsTable({ initialLeads }: { initialLeads: Lead[] }) {
  const [leads, setLeads] = useState(initialLeads);
  const [globalFilter, setGlobalFilter] = useState("");

  function handleStatusChange(id: string, status: LeadStatus) {
    // Optimistic local update; row leaves the "NEW"-only view if it's re-queried later.
    setLeads((prev) =>
      prev.map((l) => (l.id === id ? { ...l, analysis: { ...l.analysis, lead_status: status } } : l))
    );
  }

  const columnHelper = createColumnHelper<Lead>();
  const columns = useMemo(
    () => [
      columnHelper.accessor("comment_text", {
        header: "Comment",
        cell: (info) => <span className="line-clamp-2 max-w-sm">{info.getValue()}</span>,
      }),
      columnHelper.accessor((row) => row.analysis.primary_problem_code, {
        id: "problem",
        header: "Problem",
        cell: (info) => formatProblemCode(info.getValue()),
      }),
      columnHelper.accessor((row) => row.analysis.primary_dosh, { id: "dosh", header: "Dosh" }),
      columnHelper.accessor((row) => row.analysis.urgency_score, {
        id: "urgency",
        header: "Urgency",
        cell: (info) => <span className="font-display text-marigold">{info.getValue()}/10</span>,
      }),
      columnHelper.accessor((row) => row.analysis.recommended_service, {
        id: "service",
        header: "Recommended service",
      }),
      columnHelper.accessor("channel_title", { header: "Channel" }),
      columnHelper.display({
        id: "status",
        header: "Status",
        cell: ({ row }) => <StatusSelect lead={row.original} onChange={handleStatusChange} />,
      }),
    ],
    []
  );

  const table = useReactTable({
    data: leads,
    columns,
    state: { globalFilter },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 15 } },
  });

  if (leads.length === 0) {
    return (
      <div className="border border-line p-6 text-sm text-ink-muted">
        No high-intent leads yet. They appear here once a classified comment shows
        clear booking or price intent — run the enrichment pipeline to populate this.
      </div>
    );
  }

  return (
    <div>
      <input
        value={globalFilter}
        onChange={(e) => setGlobalFilter(e.target.value)}
        placeholder="Search leads by dosh, problem, or comment text"
        className="w-full border border-line bg-panel px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-marigold focus:outline-none"
      />
      <div className="mt-3 overflow-x-auto border border-line">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-line">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="cursor-pointer px-3 py-2 text-left text-xs font-medium text-ink-muted"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{ asc: " ▲", desc: " ▼" }[header.column.getIsSorted() as string] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-line last:border-0 hover:bg-panel/60">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2.5 align-top text-ink">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-ink-muted">
        <span>
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount() || 1}
        </span>
        <div className="space-x-2">
          <button
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className="border border-line px-3 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className="border border-line px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
