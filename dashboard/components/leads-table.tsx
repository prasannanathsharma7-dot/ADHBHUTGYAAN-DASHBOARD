"use client";

import { useEffect, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { formatProblemCode } from "@/lib/taxonomy";

type Lead = {
  comment_text: string;
  analysis: {
    primary_problem_code: string;
    primary_dosh: string;
    urgency_score: number;
    recommended_service: string;
    lead_status: string;
  };
  channel_title: string;
  author_name: string;
};

const columnHelper = createColumnHelper<Lead>();

const columns = [
  columnHelper.accessor("comment_text", {
    header: "Comment",
    cell: (info) => <span className="line-clamp-2 max-w-md">{info.getValue()}</span>,
  }),
  columnHelper.accessor((row) => row.analysis.primary_problem_code, {
    id: "problem",
    header: "Problem",
    cell: (info) => formatProblemCode(info.getValue()),
  }),
  columnHelper.accessor((row) => row.analysis.primary_dosh, {
    id: "dosh",
    header: "Dosh",
  }),
  columnHelper.accessor((row) => row.analysis.urgency_score, {
    id: "urgency",
    header: "Urgency",
    cell: (info) => <span className="font-semibold">{info.getValue()}/10</span>,
  }),
  columnHelper.accessor((row) => row.analysis.recommended_service, {
    id: "service",
    header: "Recommended Service",
  }),
  columnHelper.accessor((row) => row.analysis.lead_status, {
    id: "status",
    header: "Status",
  }),
  columnHelper.accessor("channel_title", { header: "Channel" }),
];

export default function LeadsTable() {
  const [data, setData] = useState<Lead[]>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/analytics")
      .then((res) => res.json())
      .then((json) => {
        if (json.error) {
          setError(json.error);
        } else {
          setData(json.high_intent_leads ?? []);
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, []);

  const table = useReactTable({
    data,
    columns,
    state: { globalFilter },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  if (loading) return <div className="p-4 text-sm text-muted-foreground">Loading leads…</div>;
  if (error) return <div className="p-4 text-sm text-red-600">{error}</div>;

  return (
    <div className="space-y-3">
      <input
        value={globalFilter}
        onChange={(e) => setGlobalFilter(e.target.value)}
        placeholder="Search leads (dosh, problem, comment text)..."
        className="w-full rounded-md border px-3 py-2 text-sm"
      />
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="cursor-pointer px-3 py-2 text-left font-medium"
                    onClick={header.column.getToggleSortingHandler()}
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
              <tr key={row.id} className="border-t hover:bg-muted/30">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-sm">
        <span>
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
        </span>
        <div className="space-x-2">
          <button
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className="rounded border px-2 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className="rounded border px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
