import { useCallback, useEffect, useState } from "react";
import { fetchClaim, fetchQueue, postAction } from "./api.js";

const TABS = [
  { key: "open", label: "Open" },
  { key: "escalated", label: "Escalated" },
  { key: "fixed", label: "Fixed" },
];
const STATUS_LABEL = { fail: "Fail", warn: "Warn", pass: "Pass" };
const ACTION_LABEL = { fix: "Marked fixed", escalate: "Escalated", reopen: "Reopened" };

const money = (value) =>
  Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });

const day = (iso) =>
  iso
    ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

function Summary({ queue }) {
  const { summary } = queue;
  const tiles = [
    { label: "Open dollars at risk", value: money(summary.open.dollars_at_risk), strong: true },
    { label: "Open claims", value: summary.open.count },
    { label: "Escalated", value: summary.escalated.count },
    { label: "Fixed", value: summary.fixed.count },
    { label: "Clean, ready to submit", value: `${queue.clean_claims} of ${queue.total_claims}` },
  ];
  return (
    <section className="tiles" aria-label="Summary">
      {tiles.map((tile) => (
        <div className={`tile${tile.strong ? " tile-strong" : ""}`} key={tile.label}>
          <div className="tile-value">{tile.value}</div>
          <div className="tile-label">{tile.label}</div>
        </div>
      ))}
    </section>
  );
}

function QueueTable({ items, selectedId, onSelect }) {
  if (items.length === 0) {
    return <p className="empty">Nothing here. Claims land in this list when you act on them.</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Claim</th>
            <th>Member</th>
            <th>Service</th>
            <th>Date of service</th>
            <th className="num">Billed</th>
            <th className="num">At risk ▾</th>
            <th>Result</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr
              key={item.claim_id}
              className={item.claim_id === selectedId ? "selected" : ""}
              onClick={() => onSelect(item.claim_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(item.claim_id);
                }
              }}
              tabIndex={0}
              aria-selected={item.claim_id === selectedId}
            >
              <td className="num muted">{index + 1}</td>
              <td className="mono">{item.claim_id}</td>
              <td>
                {item.member_name}
                {!item.member_resolved && <span className="muted"> (not on roster)</span>}
              </td>
              <td title={item.service_description ?? ""}>
                <span className="mono">{item.service_code}</span> × {item.units}
              </td>
              <td>{day(item.date_of_service)}</td>
              <td className="num">{money(item.billed_amount)}</td>
              <td className="num strong">{money(item.dollars_at_risk)}</td>
              <td>
                <StatusBadge status={item.status} />
              </td>
              <td>
                {item.findings.map((finding) => (
                  <span className={`chip chip-${finding.status}`} key={finding.rule_id}>
                    {finding.rule_name}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{children ?? "—"}</dd>
    </div>
  );
}

function ClaimPanel({ claimId, onClose, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    setNote("");
    fetchClaim(claimId)
      .then((body) => !cancelled && setDetail(body))
      .catch((problem) => !cancelled && setError(problem.message));
    return () => {
      cancelled = true;
    };
  }, [claimId]);

  const act = async (action) => {
    setBusy(true);
    setError(null);
    try {
      setDetail(await postAction(claimId, action, note.trim()));
      setNote("");
      onChanged();
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="panel" aria-label={`Claim ${claimId}`}>
      <header className="panel-header">
        <div>
          <h2 className="mono">{claimId}</h2>
          {detail && (
            <p className="muted">
              {detail.member_name} · {detail.service_code} × {detail.units} · {day(detail.date_of_service)}
            </p>
          )}
        </div>
        <button className="ghost" onClick={onClose} aria-label="Close claim">
          ✕
        </button>
      </header>

      {error && <p className="error">{error}</p>}
      {!detail && !error && <p className="muted">Loading…</p>}

      {detail && (
        <>
          <div className="panel-money">
            <div>
              <span className="tile-value">{money(detail.dollars_at_risk)}</span>
              <span className="muted"> at risk of {money(detail.billed_amount)} billed</span>
            </div>
            <span className={`work work-${detail.work_status}`}>{detail.work_status}</span>
          </div>

          <h3>Rule trace</h3>
          <ol className="trace">
            {detail.trace.map((step) => (
              <li key={step.rule_id} className={`trace-${step.status}`}>
                <div className="trace-head">
                  <StatusBadge status={step.status} />
                  <span className="trace-name">{step.rule_name}</span>
                </div>
                <p>{step.reason}</p>
              </li>
            ))}
          </ol>

          <h3>Claim</h3>
          <dl className="fields">
            <Field label="Patient on claim">{detail.claim.patient_name_on_claim}</Field>
            <Field label="Member ID on claim">{detail.claim.medicaid_id_on_claim}</Field>
            <Field label="Roster member">
              {detail.member ? `${detail.member.name} (${detail.member.medicaid_id ?? "no ID"})` : "No match"}
            </Field>
            <Field label="Provider">{detail.claim.provider_name}</Field>
            <Field label="Auth # on claim">{detail.claim.auth_number}</Field>
            <Field label="Auth window">
              {detail.authorization
                ? `${day(detail.authorization.start_date)} – ${
                    detail.authorization.end_date ? day(detail.authorization.end_date) : "open-ended"
                  } · ${detail.authorization.units_approved ?? "?"} units · ${detail.authorization.status}`
                : null}
            </Field>
            <Field label="Entered">{day(detail.claim.created_date)}</Field>
          </dl>

          <h3>Action</h3>
          <label className="note">
            <span className="muted">Note (optional)</span>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="What was corrected, or who needs to look"
              maxLength={500}
            />
          </label>
          <div className="actions">
            {detail.work_status === "open" ? (
              <>
                <button className="primary" disabled={busy} onClick={() => act("fix")}>
                  Mark fixed
                </button>
                <button disabled={busy} onClick={() => act("escalate")}>
                  Escalate
                </button>
              </>
            ) : (
              <>
                {detail.work_status === "escalated" && (
                  <button className="primary" disabled={busy} onClick={() => act("fix")}>
                    Mark fixed
                  </button>
                )}
                <button disabled={busy} onClick={() => act("reopen")}>
                  Reopen
                </button>
              </>
            )}
          </div>

          {detail.history.length > 0 && (
            <>
              <h3>History</h3>
              <ul className="history">
                {detail.history.map((entry, index) => (
                  <li key={index}>
                    <strong>{ACTION_LABEL[entry.action] ?? entry.action}</strong>{" "}
                    <span className="muted">{new Date(entry.acted_at).toLocaleString()}</span>
                    {entry.note && <div>{entry.note}</div>}
                  </li>
                ))}
              </ul>
            </>
          )}

          <p className="muted footnote">
            Evaluated as of {day(detail.as_of)} with ruleset {detail.ruleset_version}.
          </p>
        </>
      )}
    </aside>
  );
}

export default function App() {
  const [tab, setTab] = useState("open");
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(() => {
    fetchQueue(tab)
      .then((body) => {
        setQueue(body);
        setError(null);
      })
      .catch((problem) => setError(problem.message));
  }, [tab]);

  useEffect(load, [load]);

  return (
    <div className={`layout${selectedId ? " with-panel" : ""}`}>
      <main>
        <header className="page-header">
          <div>
            <h1>Claims work queue</h1>
            {queue && (
              <p className="muted">
                {queue.payer} · ruleset {queue.ruleset_version} · as of {day(queue.as_of)}
              </p>
            )}
          </div>
        </header>

        {error && <p className="error">Could not load the queue: {error}</p>}
        {!queue && !error && <p className="muted">Loading…</p>}

        {queue && (
          <>
            <Summary queue={queue} />
            <nav className="tabs" aria-label="Work status">
              {TABS.map(({ key, label }) => (
                <button
                  key={key}
                  className={key === tab ? "tab active" : "tab"}
                  onClick={() => setTab(key)}
                  aria-pressed={key === tab}
                >
                  {label} <span className="count">{queue.summary[key].count}</span>
                </button>
              ))}
            </nav>
            <QueueTable items={queue.items} selectedId={selectedId} onSelect={setSelectedId} />
          </>
        )}
      </main>

      {selectedId && (
        <ClaimPanel claimId={selectedId} onClose={() => setSelectedId(null)} onChanged={load} />
      )}
    </div>
  );
}
