"use client";

import { useRef, useState } from "react";
import { api, type ImportResult } from "@/lib/api";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote } from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { LinkedAccounts } from "@/components/ui/linked-accounts";

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
            {/* A button, not a div.
                This was a click-only <div>, so the one control on the import
                page -- the page a new user lands on first -- could not be
                reached by keyboard at all. Drag and drop stays on the
                element; the button role is what makes the click target real
                for anyone not using a mouse. */}
            <button
              type="button"
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const dropped = e.dataTransfer.files?.[0];
                if (dropped) setFile(dropped);
              }}
              onClick={() => inputRef.current?.click()}
              aria-label={
                file
                  ? `Chosen file ${file.name}. Activate to choose a different CSV.`
                  : "Choose a CSV file to import, or drop one here"
              }
              className={`w-full cursor-pointer rounded-[10px] border-2 border-dashed px-6 py-12 text-center transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] ${
                dragging
                  ? "border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_7%,transparent)]"
                  : "border-[var(--hairline)] hover:border-[var(--surface-3)]"
              }`}
            >
              <input
                ref={inputRef} type="file" accept=".csv" className="hidden"
                tabIndex={-1}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <>
                  <p className="text-body-lg text-[var(--ink-primary)]">{file.name}</p>
                  <p className="mt-1 text-small text-[var(--ink-muted)]">
                    {(file.size / 1024).toFixed(1)} KB · click to choose another
                  </p>
                </>
              ) : (
                <>
                  <p className="text-body-lg text-[var(--ink-primary)]">
                    Drop a CSV here, or click to choose
                  </p>
                  <p className="mt-1 text-small text-[var(--ink-muted)]">Up to 2 MB</p>
                </>
              )}
            </button>

            <label className="mt-4 flex items-center gap-2.5 text-small text-[var(--ink-secondary)]">
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
              <p className="text-small leading-relaxed text-[var(--ink-secondary)]">
                Required columns: <code className="text-[var(--accent)]">symbol</code>,{" "}
                <code className="text-[var(--accent)]">quantity</code>,{" "}
                <code className="text-[var(--accent)]">average_price</code>. Optional:{" "}
                <code className="text-[var(--accent)]">asset_type</code>,{" "}
                <code className="text-[var(--accent)]">purchase_date</code>.
              </p>
              <pre className="tabular mt-3 overflow-x-auto rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] p-3 text-micro leading-relaxed text-[var(--ink-secondary)]">
{TEMPLATE}
              </pre>
              <ul className="mt-3 space-y-1.5 text-caption leading-relaxed text-[var(--ink-muted)]">
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
              <p className="text-small leading-relaxed text-[var(--ink-secondary)]">
                Prices here are adjusted for splits and bonus issues. If you enter
                the rupee price you actually paid before such an event, the gain
                will be misreported — HDFCBANK bought in 2021 is a live example,
                since its 2025 bonus halved the adjusted price.
              </p>
              <p className="mt-2 text-small leading-relaxed text-[var(--ink-secondary)]">
                The importer compares each cost against the adjusted price on your
                stated purchase date and warns when the two cannot be reconciled.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>
      <LinkedAccounts />
    </>
  );
}

function ImportOutcome({ result }: { result: ImportResult }) {
  return (
    <div className="mt-5">
      <div className="flex items-center gap-2">
        {/* A testable hook. The outcome was previously identified in the
            e2e suite by the bare string "Rejected", which collided the
            moment the results table gained a screen-reader caption
            describing the rejected rows. */}
        <Badge
          tone={result.accepted ? "good" : "critical"}
          data-testid="import-outcome"
        >
          {result.accepted ? "Imported" : "Rejected"}
        </Badge>
        <span className="text-small text-[var(--ink-secondary)]">
          {result.rows_read} rows read
          {result.accepted &&
            ` · ${result.holdings_created} created, ${result.holdings_updated} updated`}
        </span>
      </div>

      {result.errors.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-[8px] border border-[color-mix(in_oklab,var(--critical)_35%,transparent)]">
          <div className="bg-[color-mix(in_oklab,var(--critical)_10%,transparent)] px-3 py-2 text-small text-[#ffb3b3]">
            Nothing was saved. Fix these rows and upload again.
          </div>
          <table className="w-full text-small">
            <caption className="sr-only">
              Rows rejected by the import, with the reason for each
            </caption>
            <thead>
              <tr className="border-b border-[var(--hairline)] text-left text-micro uppercase tracking-[0.07em] text-[var(--ink-muted)]">
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
                className="rounded-[7px] border border-[color-mix(in_oklab,var(--warning)_35%,transparent)] bg-[color-mix(in_oklab,var(--warning)_8%,transparent)] px-3 py-2 text-caption leading-relaxed text-[#e8b84b]">
              {warning}
            </li>
          ))}
        </ul>
      )}

      {result.accepted && (
        <a href="/analysis/overview"
           className="mt-4 inline-block rounded-[8px] bg-[var(--accent)] px-3.5 py-2 text-body font-medium text-[var(--accent-ink)] hover:bg-[#f0b254]">
          See your dashboard
        </a>
      )}
    </div>
  );
}
