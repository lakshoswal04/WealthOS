"use client";

import { useRef, useState } from "react";
import { api, type ImportResult } from "@/lib/api";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote } from "@/components/ui";
import { PageHead } from "@/components/ui/shell";

const TEMPLATE = `symbol,asset_type,quantity,average_price,purchase_date
RELIANCE,Equity,40,1150.50,2022-03-15
TCS,Equity,25,3200.00,2022-05-20
NIFTYBEES,ETF,500,185.40,2022-08-12
GOLDBEES,Gold,1200,48.20,2023-02-28
DEBT,Debt,300,52.10,2022-06-01`;

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.importCsv(file, replaceExisting));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function downloadTemplate() {
    const blob = new Blob([TEMPLATE], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "wealthos-holdings-template.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <PageHead
        title="Import holdings"
        lede="Upload a CSV. The whole file is validated before anything is saved, so a single bad row never leaves you with a half-loaded portfolio."
      />

      <div className="grid gap-5 lg:grid-cols-[1.3fr_0.7fr]">
        <Card className="rise">
          <CardHeader title="Upload" />
          <CardBody>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const dropped = e.dataTransfer.files?.[0];
                if (dropped) setFile(dropped);
              }}
              onClick={() => inputRef.current?.click()}
              className={`cursor-pointer rounded-[10px] border-2 border-dashed px-6 py-12 text-center transition-colors ${
                dragging
                  ? "border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_7%,transparent)]"
                  : "border-[var(--hairline)] hover:border-[var(--surface-3)]"
              }`}
            >
              <input
                ref={inputRef} type="file" accept=".csv" className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <>
                  <p className="text-[14px] text-[var(--ink-primary)]">{file.name}</p>
                  <p className="mt-1 text-[12px] text-[var(--ink-muted)]">
                    {(file.size / 1024).toFixed(1)} KB · click to choose another
                  </p>
                </>
              ) : (
                <>
                  <p className="text-[14px] text-[var(--ink-primary)]">
                    Drop a CSV here, or click to choose
                  </p>
                  <p className="mt-1 text-[12px] text-[var(--ink-muted)]">Up to 2 MB</p>
                </>
              )}
            </div>

            <label className="mt-4 flex items-center gap-2.5 text-[12.5px] text-[var(--ink-secondary)]">
              <input
                type="checkbox" checked={replaceExisting}
                onChange={(e) => setReplaceExisting(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--accent)]"
              />
              Replace my current holdings instead of adding to them
            </label>

            <div className="mt-4 flex gap-2">
              <Button onClick={upload} disabled={!file || busy}>
                {busy ? "Validating…" : "Import"}
              </Button>
              <Button variant="ghost" onClick={downloadTemplate}>Download template</Button>
            </div>

            {error && <div className="mt-4"><ErrorNote message={error} /></div>}
            {result && <ImportOutcome result={result} />}
          </CardBody>
        </Card>

        <div className="space-y-5">
          <Card className="rise">
            <CardHeader title="File format" />
            <CardBody>
              <p className="text-[12.5px] leading-relaxed text-[var(--ink-secondary)]">
                Required columns: <code className="text-[var(--accent)]">symbol</code>,{" "}
                <code className="text-[var(--accent)]">quantity</code>,{" "}
                <code className="text-[var(--accent)]">average_price</code>. Optional:{" "}
                <code className="text-[var(--accent)]">asset_type</code>,{" "}
                <code className="text-[var(--accent)]">purchase_date</code>.
              </p>
              <pre className="tabular mt-3 overflow-x-auto rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] p-3 text-[10.5px] leading-relaxed text-[var(--ink-secondary)]">
{TEMPLATE}
              </pre>
              <ul className="mt-3 space-y-1.5 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
                <li>Dates accept 2022-03-15, 15-03-2022, 15/03/2022 or 15-Mar-2022.</li>
                <li>Quantities and prices must be above zero.</li>
                <li>A symbol outside the supported universe rejects the whole file.</li>
                <li>The same symbol twice is merged at weighted average cost.</li>
              </ul>
            </CardBody>
          </Card>

          <Card className="rise">
            <CardHeader title="A note on cost basis" />
            <CardBody>
              <p className="text-[12.5px] leading-relaxed text-[var(--ink-secondary)]">
                Prices here are adjusted for splits and bonus issues. If you enter
                the rupee price you actually paid before such an event, the gain
                will be misreported — HDFCBANK bought in 2021 is a live example,
                since its 2025 bonus halved the adjusted price.
              </p>
              <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--ink-secondary)]">
                The importer compares each cost against the adjusted price on your
                stated purchase date and warns when the two cannot be reconciled.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}

function ImportOutcome({ result }: { result: ImportResult }) {
  return (
    <div className="mt-5">
      <div className="flex items-center gap-2">
        <Badge tone={result.accepted ? "good" : "critical"}>
          {result.accepted ? "Imported" : "Rejected"}
        </Badge>
        <span className="text-[12.5px] text-[var(--ink-secondary)]">
          {result.rows_read} rows read
          {result.accepted &&
            ` · ${result.holdings_created} created, ${result.holdings_updated} updated`}
        </span>
      </div>

      {result.errors.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-[8px] border border-[color-mix(in_oklab,var(--critical)_35%,transparent)]">
          <div className="bg-[color-mix(in_oklab,var(--critical)_10%,transparent)] px-3 py-2 text-[12px] text-[#ffb3b3]">
            Nothing was saved. Fix these rows and upload again.
          </div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[var(--hairline)] text-left text-[10.5px] uppercase tracking-[0.07em] text-[var(--ink-muted)]">
                <th className="px-3 py-1.5 font-medium">Row</th>
                <th className="px-3 py-1.5 font-medium">Field</th>
                <th className="px-3 py-1.5 font-medium">Value</th>
                <th className="px-3 py-1.5 font-medium">Problem</th>
              </tr>
            </thead>
            <tbody>
              {result.errors.map((rowError, i) => (
                <tr key={i} className="border-b border-[var(--hairline)] last:border-0">
                  <td className="tabular px-3 py-1.5 text-[var(--ink-secondary)]">
                    {rowError.row_number || "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[var(--ink-secondary)]">{rowError.field ?? "—"}</td>
                  <td className="tabular px-3 py-1.5 text-[var(--ink-muted)]">{rowError.value ?? "—"}</td>
                  <td className="px-3 py-1.5 text-[#ffb3b3]">{rowError.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result.warnings.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {result.warnings.map((warning, i) => (
            <li key={i}
                className="rounded-[7px] border border-[color-mix(in_oklab,var(--warning)_35%,transparent)] bg-[color-mix(in_oklab,var(--warning)_8%,transparent)] px-3 py-2 text-[11.5px] leading-relaxed text-[#e8b84b]">
              {warning}
            </li>
          ))}
        </ul>
      )}

      {result.accepted && (
        <a href="/overview"
           className="mt-4 inline-block rounded-[8px] bg-[var(--accent)] px-3.5 py-2 text-[13px] font-medium text-[var(--accent-ink)] hover:bg-[#f0b254]">
          See your dashboard
        </a>
      )}
    </div>
  );
}
