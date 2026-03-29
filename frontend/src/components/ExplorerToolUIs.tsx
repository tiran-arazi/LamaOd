import { makeAssistantToolUI } from "@assistant-ui/react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = ["#2563eb", "#16a34a", "#ca8a04", "#dc2626", "#9333ea", "#0891b2"];

function MetadataCard({
  title,
  body,
}: {
  title: string;
  body: unknown;
}) {
  return (
    <details
      className="explorer-tool-card"
      style={{ margin: "0.5rem 0", border: "1px solid #e5e7eb", borderRadius: 8 }}
    >
      <summary
        style={{
          cursor: "pointer",
          padding: "0.5rem 0.75rem",
          background: "#f9fafb",
          fontWeight: 600,
        }}
      >
        {title}
      </summary>
      <pre
        style={{
          margin: 0,
          padding: "0.75rem",
          fontSize: 12,
          overflow: "auto",
          maxHeight: 280,
        }}
      >
        {typeof body === "string" ? body : JSON.stringify(body, null, 2)}
      </pre>
    </details>
  );
}

function QueryResultInner({ result }: { result: unknown }) {
  const data = (result != null && typeof result === "object" ? result : {}) as {
    rows?: Record<string, unknown>[];
    row_count?: number;
    service_path?: string;
    layer_id?: number;
    arcgis_request?: unknown;
    arcgis_error?: unknown;
  };
  const rows = data.rows ?? [];
  const requestDebug = data.arcgis_request;
  const arcgisErr = data.arcgis_error;

  if (!rows.length) {
    return (
      <div>
        {arcgisErr != null && (
          <MetadataCard title="ArcGIS service error" body={arcgisErr} />
        )}
        {requestDebug != null && (
          <MetadataCard title="ArcGIS REST request (exact call)" body={requestDebug} />
        )}
        <p style={{ margin: 0 }}>No rows returned.</p>
      </div>
    );
  }

  const keys = Object.keys(rows[0] ?? {});
  const columnHelper = createColumnHelper<Record<string, unknown>>();
  const columns = keys.map((key) =>
    columnHelper.accessor(key, { header: key, cell: (info) => String(info.getValue() ?? "") }),
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const numericKey =
    keys.find((k) => rows.every((r) => typeof r[k] === "number")) ?? null;

  const chartData =
    numericKey && keys.length >= 2
      ? rows.slice(0, 24).map((r) => {
          const labelKey = keys.find((k) => k !== numericKey) ?? keys[0];
          return {
            name: String(r[labelKey] ?? ""),
            value: Number(r[numericKey!] ?? 0),
          };
        })
      : [];

  return (
    <div className="explorer-query-result">
      {requestDebug != null && (
        <MetadataCard title="ArcGIS REST request (exact call)" body={requestDebug} />
      )}
      {arcgisErr != null && <MetadataCard title="ArcGIS service error" body={arcgisErr} />}
      <p style={{ margin: "0 0 0.5rem", fontSize: 13 }}>
        <strong>{data.row_count ?? rows.length}</strong> rows
        {data.service_path != null && (
          <>
            {" "}
            · <code>{data.service_path}</code> layer {data.layer_id}
          </>
        )}
      </p>
      {chartData.length > 0 && (
        <div style={{ width: "100%", height: 200, marginBottom: "0.75rem" }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="value" fill={COLORS[0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <div style={{ overflow: "auto", maxHeight: 320, border: "1px solid #e5e7eb" }}>
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    style={{
                      textAlign: "left",
                      padding: "6px 8px",
                      borderBottom: "1px solid #e5e7eb",
                      background: "#f3f4f6",
                    }}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} style={{ padding: "6px 8px", borderBottom: "1px solid #f3f4f6" }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VisualizationInner({ result }: { result: unknown }) {
  const r = (result != null && typeof result === "object" ? result : {}) as {
    chart_type?: string;
    title?: string;
    records?: Record<string, unknown>[];
    x_field?: string | null;
    y_field?: string | null;
    label_field?: string | null;
    value_field?: string | null;
  };
  const records = r.records ?? [];
  const title = r.title ?? "Chart";

  if (!records.length) {
    return <p style={{ margin: 0 }}>No records for visualization.</p>;
  }

  if (r.chart_type === "pie" && r.label_field && r.value_field) {
    const pieData = records.map((row, i) => ({
      name: String(row[r.label_field!] ?? ""),
      value: Number(row[r.value_field!] ?? 0),
      fill: COLORS[i % COLORS.length],
    }));
    return (
      <div style={{ width: "100%", height: 280 }}>
        <p style={{ fontWeight: 600, margin: "0 0 0.5rem" }}>{title}</p>
        <ResponsiveContainer width="100%" height="90%">
          <PieChart>
            <Pie data={pieData} dataKey="value" nameKey="name" label />
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  const x = r.x_field ?? Object.keys(records[0] ?? {})[0];
  const y =
    r.y_field ??
    Object.keys(records[0] ?? {}).find((k) => k !== x) ??
    Object.keys(records[0] ?? {})[0];

  const series = records.map((row) => ({
    name: String(row[x!] ?? ""),
    value: Number(row[y!] ?? 0),
  }));

  if (r.chart_type === "line") {
    return (
      <div style={{ width: "100%", height: 280 }}>
        <p style={{ fontWeight: 600, margin: "0 0 0.5rem" }}>{title}</p>
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="value" stroke={COLORS[0]} dot />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: 280 }}>
      <p style={{ fontWeight: 600, margin: "0 0 0.5rem" }}>{title}</p>
      <ResponsiveContainer width="100%" height="90%">
        <BarChart data={series}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="value" fill={COLORS[0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export const ListServicesToolUI = makeAssistantToolUI({
  toolName: "list_services",
  render: ({ result }) => <MetadataCard title="Catalog folder" body={result} />,
});

export const ListLayersToolUI = makeAssistantToolUI({
  toolName: "list_layers",
  render: ({ result }) => <MetadataCard title="Layers" body={result} />,
});

export const GetLayerSchemaToolUI = makeAssistantToolUI({
  toolName: "get_layer_schema",
  render: ({ result }) => <MetadataCard title="Layer schema" body={result} />,
});

export const QueryLayerToolUI = makeAssistantToolUI({
  toolName: "query_layer",
  render: ({ result }) => <QueryResultInner result={result} />,
});

export const SuggestVisualizationToolUI = makeAssistantToolUI({
  toolName: "suggest_visualization",
  render: ({ result }) => <VisualizationInner result={result} />,
});

export function ExplorerToolUIs() {
  return (
    <>
      <ListServicesToolUI />
      <ListLayersToolUI />
      <GetLayerSchemaToolUI />
      <QueryLayerToolUI />
      <SuggestVisualizationToolUI />
    </>
  );
}
