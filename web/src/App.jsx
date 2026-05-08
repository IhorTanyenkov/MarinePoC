import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = import.meta.env.VITE_PORT_TARIFF_API || 'http://127.0.0.1:8787';

const VESSEL_TYPES = [
  ['oil_product_tanker',          'Oil / Product tanker'],
  ['lng_tanker',                  'LNG tanker'],
  ['chemical_gas_tanker',         'Chemical / Gas tanker'],
  ['bulk_carrier',                'Bulk carrier'],
  ['container_deepsea',           'Container ship · Deepsea'],
  ['container_shortsea',          'Container ship · Shortsea / Feeder'],
  ['container_not_scheduled',     'Container ship · Not scheduled'],
  ['general_cargo_deepsea',       'General Cargo · Deepsea'],
  ['general_cargo_shortsea',      'General Cargo · Shortsea / Feeder'],
  ['general_cargo_not_scheduled', 'General Cargo · Not scheduled'],
  ['car_carrier_scheduled',       'Car carrier / Ropax / RoRo · Scheduled'],
  ['car_carrier_not_scheduled',   'Car carrier / Ropax / RoRo · Not scheduled'],
  ['cruise',                      'Cruise ship'],
  ['offshore',                    'Offshore vessel'],
  ['other',                       'Other seagoing vessel'],
];

const SERVICE_TYPES = [
  ['not_scheduled', 'Not scheduled'],
  ['shortsea',      'Shortsea / Feeder'],
  ['deepsea',       'Deepsea'],
];

const COMMODITIES = [
  ['agribulk',               'Agribulk'],
  ['ores',                   'Ores'],
  ['coal',                   'Coal'],
  ['other_dry_bulk',         'Other dry bulk'],
  ['crude_oil',              'Crude oil'],
  ['mineral_oil',            'Mineral oil products'],
  ['other_liquid_bulk',      'Other liquid bulk'],
  ['roll_on_roll_off',       'Roll-on / Roll-off'],
  ['containers_default',     'Containers (default rate)'],
  ['containers_shortsea',    'Containers · Shortsea / Feeder'],
  ['containers_deepsea',     'Containers · Deepsea'],
  ['general_cargo_default',  'Other general cargo (default)'],
  ['general_cargo_shortsea', 'Other general cargo · Shortsea'],
  ['general_cargo_deepsea',  'Other general cargo · Deepsea'],
  ['lng',                    'LNG'],
  ['biomass',                'Biomass'],
  ['scrap',                  'Scrap'],
  ['renewable_fuels',        'Renewable fuels / chemicals'],
];

const GREEN_AWARDS = [
  ['',         'No certificate'],
  ['bronze',   'GAB Bronze'],
  ['silver',   'GAS Silver'],
  ['gold',     'GAG Gold'],
  ['platinum', 'GAP Platinum'],
];

const defaultVessel = {
  vessel_metadata: { name: '', imo: null },
  technical_specs: {
    type: '',
    gross_tonnage: null,
    net_tonnage: null,
    loa_meters: null,
    dwt: null,
  },
  operational_data: {
    port: '',
    service: '',
    days_alongside: null,
    num_operations: null,
    activity: '',
  },
  cargo: {},
  discounts: {
    esi_score: null,
    green_award_certificate: '',
  },
};

const STAGES = [
  { id: 'document_ingest',  n: 1, label: 'Ingest document',     owner: 'tool',  hint: 'Extract page text and source references' },
  { id: 'candidate_extract',n: 2, label: 'Extract candidates',  owner: 'agent', hint: 'Detect candidate charge sections' },
  { id: 'research_clarify', n: 3, label: 'Clarify ambiguity',   owner: 'agent', hint: 'Optional model lookup for ambiguous terms', optional: true },
  { id: 'rule_normalize',   n: 4, label: 'Normalize rules',     owner: 'agent', hint: 'Map candidates to rule pack DSL' },
  { id: 'rule_validate',    n: 5, label: 'Validate',            owner: 'agent', hint: 'Schema check + evidence required' },
  { id: 'tool_compile',     n: 6, label: 'Compile tool',        owner: 'agent', hint: 'Emit nbot.tool_descriptor.v1' },
  { id: 'core_evaluate',    n: 7, label: 'Evaluate',            owner: 'engine',hint: 'Match rules and evaluate formulas' },
  { id: 'explain_trace',    n: 8, label: 'Explain trace',       owner: 'api',   hint: 'Bind evidence, confidence, graph' },
];

function cx(...parts) {
  return parts.filter(Boolean).join(' ');
}

function currency(value, code = 'ZAR') {
  const amount = Number.isFinite(Number(value)) ? Number(value) : 0;
  const currencyCode = /^[A-Z]{3}$/.test(String(code || '')) ? String(code) : 'USD';
  try {
    return new Intl.NumberFormat('en-ZA', {
      style: 'currency',
      currency: currencyCode,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${code || ''}`.trim();
  }
}

function clockTime() {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date());
}

function apiLink(path) {
  if (!path) return '#';
  if (path.startsWith('http')) return path;
  return `${API}${path}`;
}

function derivePipeline(state, liveCursor) {
  const { documentAnalysis, rules, ruleValidation, toolDescriptor, result, researchDispatch, calcError } = state;

  function liveOverride(idx, base) {
    if (liveCursor == null) return base;
    if (idx === liveCursor) return 'running';
    return base;
  }

  return STAGES.map((stage, idx) => {
    let status = 'idle';
    let summary = stage.hint;
    let badge = null;

    switch (stage.id) {
      case 'document_ingest':
        if (documentAnalysis) {
          status = 'done';
          summary = `${documentAnalysis.filename} · ${documentAnalysis.pages} pages`;
        }
        break;
      case 'candidate_extract':
        if (documentAnalysis?.candidate_terms?.length) {
          status = 'done';
          badge = documentAnalysis.candidate_terms.length;
          summary = `${badge} candidate term${badge === 1 ? '' : 's'} detected`;
        } else if (documentAnalysis) {
          status = 'warn';
          summary = 'No tariff signals detected — manual review needed';
        } else if (rules) {
          status = 'done';
          summary = 'Skipped · using normalized rule pack directly';
        }
        break;
      case 'research_clarify':
        if (researchDispatch) {
          status = researchDispatch.status === 'ready' ? 'done' : 'warn';
          summary = researchDispatch.status === 'ready'
            ? `${researchDispatch.candidate_providers?.length || 0} provider(s) ready`
            : 'No provider configured';
        } else {
          status = 'skipped';
          summary = 'Optional · trigger when ambiguous';
        }
        break;
      case 'rule_normalize':
        if (rules?.rules?.length) {
          status = 'done';
          badge = rules.rules.length;
          summary = `${badge} rules in port_tariff.rule_pack.v1`;
        }
        break;
      case 'rule_validate':
        if (ruleValidation) {
          status = ruleValidation.ok ? 'done' : 'error';
          summary = ruleValidation.message || (ruleValidation.ok ? 'Schema OK' : 'Validation failed');
        } else if (rules) {
          status = 'idle';
          summary = 'Pending';
        }
        break;
      case 'tool_compile':
        if (toolDescriptor) {
          status = 'done';
          summary = toolDescriptor.tool_id;
        }
        break;
      case 'core_evaluate':
        if (calcError) {
          status = 'error';
          summary = calcError;
        } else if (result) {
          status = 'done';
          const applied = result.results?.length || 0;
          const skipped = result.skipped_rules?.length || 0;
          summary = `${applied} applied · ${skipped} skipped`;
        } else {
          summary = 'Press Calculate to evaluate the rule pack';
        }
        break;
      case 'explain_trace':
        if (result?.execution_trace?.length) {
          status = 'done';
          summary = `${result.execution_trace.length} graph nodes resolved`;
        }
        break;
      default:
    }

    return { ...stage, status: liveOverride(idx, status), summary, badge };
  });
}

function StatusDot({ status }) {
  return <span className={cx('s-dot', `s-${status}`)} aria-hidden />;
}

function OwnerTag({ owner }) {
  return <span className={cx('owner-tag', `owner-${owner}`)}>{owner}</span>;
}

function formatElapsed(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function Pipeline({ stages, selectedId, onSelect, extracting, elapsedSec }) {
  const completed = stages.filter((s) => s.status === 'done').length;
  return (
    <section className="pipeline">
      <div className="pipeline-head">
        <div>
          <p className="eyebrow">Agent pipeline</p>
          <h2>Document → callable tariff tool → totals</h2>
          {extracting && (
            <div className="extracting-pill">
              <span className="extracting-spinner" aria-hidden />
              <div>
                <strong>Extracting rules from {extracting.filename}</strong>
                <small>{formatElapsed(elapsedSec)} elapsed · provider reading PDF natively · keep this tab open</small>
              </div>
            </div>
          )}
        </div>
        <div className="pipeline-meter">
          <div className="meter-bar">
            <div className="meter-fill" style={{ width: `${(completed / stages.length) * 100}%` }} />
          </div>
          <span>{completed}/{stages.length} stages complete</span>
        </div>
      </div>

      <div className="pipeline-track">
        <div className="pipeline-line" aria-hidden />
        {stages.map((stage) => (
          <button
            type="button"
            key={stage.id}
            className={cx('p-stage', `s-${stage.status}`, selectedId === stage.id && 'selected')}
            onClick={() => onSelect(stage.id)}
          >
            <span className="p-num">
              <StatusDot status={stage.status} />
              <em>{String(stage.n).padStart(2, '0')}</em>
            </span>
            <strong>{stage.label}</strong>
            <span className="p-meta">
              <OwnerTag owner={stage.owner} />
              {stage.optional && <span className="opt-tag">optional</span>}
              {stage.badge != null && <span className="count-tag">{stage.badge}</span>}
            </span>
            <small>{stage.summary}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function KV({ k, v, mono }) {
  return (
    <div className="kv">
      <span className="kv-k">{k}</span>
      <span className={cx('kv-v', mono && 'mono')}>{String(v ?? '—')}</span>
    </div>
  );
}

function Empty({ msg, action, onAction }) {
  if (action && onAction) {
    return (
      <button type="button" className="empty empty-action" onClick={onAction}>
        <span>{msg}</span>
        <em>{action} →</em>
      </button>
    );
  }
  return <p className="empty">{msg}</p>;
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <main className="shell">
          <section className="card empty-state">
            <p className="eyebrow">UI runtime error</p>
            <h3>The console hit a render error instead of hiding the screen.</h3>
            <pre className="excerpt">{this.state.error.message}</pre>
            <button className="primary" onClick={() => window.location.reload()}>Reload console</button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}

function StageDetail({ stage, state, onClose, onRunResearch, onTriggerUpload }) {
  if (!stage) return null;
  const { documentAnalysis, rules, ruleValidation, toolDescriptor, result, researchDispatch } = state;

  return (
    <section className="stage-detail">
      <header>
        <div>
          <p className="eyebrow">Stage {String(stage.n).padStart(2, '0')} · <OwnerTag owner={stage.owner} /></p>
          <h3>{stage.label}</h3>
          <p className="muted">{stage.hint}</p>
        </div>
        <button className="ghost" onClick={onClose}>Close</button>
      </header>

      <div className="detail-body">
        {stage.id === 'document_ingest' && (
          documentAnalysis ? (
            <div>
              <div className="kv-grid">
                <KV k="Source" v={documentAnalysis.filename} />
                <KV k="Source ID" v={documentAnalysis.source_id} mono />
                <KV k="Pages" v={documentAnalysis.pages} />
                <div className="kv-full">
                  <span className="kv-k">Page links</span>
                  <div className="link-row">
                    {(documentAnalysis.page_links || []).slice(0, 12).map((link) => (
                      <a key={link.url} href={apiLink(link.url)} target="_blank" rel="noreferrer">{link.label}</a>
                    ))}
                  </div>
                </div>
                {documentAnalysis.page_text_preview?.[0] && (
                  <div className="kv-full">
                    <span className="kv-k">First-page preview</span>
                    <pre className="excerpt">{documentAnalysis.page_text_preview[0].text.slice(0, 800) || '(empty)'}</pre>
                  </div>
                )}
              </div>
              {(() => {
                const c = documentAnalysis.classification;
                if (!c) return null;
                const tone = c.document_type === 'port_authority_tariff' ? 'good'
                  : c.document_type === 'unknown' ? 'warn'
                  : 'warn';
                const heading = c.document_type === 'port_authority_tariff' ? 'Looks like a port authority tariff'
                  : c.document_type === 'forwarder_or_agent_fees' ? 'Looks like a forwarder / agent fee sheet'
                  : c.document_type === 'regulatory_text' ? 'Looks like regulatory / statutory text'
                  : c.document_type === 'cargo_contract' ? 'Looks like a charter party / cargo contract'
                  : 'Document type uncertain';
                const sig = c.signals || {};
                return (
                  <div className={cx('next-step', `tone-${tone}`)}>
                    <strong>{heading}</strong>
                    <p>{c.reason}</p>
                    <p className="muted">
                      Confidence {Math.round((c.confidence || 0) * 100)}% ·
                      port-authority {sig.port_authority || 0} · forwarder {sig.forwarder || 0} · regulatory {sig.regulatory || 0} · cargo-contract {sig.cargo_contract || 0}
                    </p>
                  </div>
                );
              })()}
            </div>
          ) : <Empty msg="No document uploaded yet." action="Choose a tariff PDF" onAction={onTriggerUpload} />
        )}

        {stage.id === 'candidate_extract' && (
          documentAnalysis?.candidate_terms?.length ? (
            <div>
              <p className="muted">Lightweight signal scan from page text. Feeds the rule_extraction_agent prompt.</p>
              <div className="chips">
                {documentAnalysis.candidate_terms.map((c) => (
                  <span className="chip" key={c.term}>{c.term}</span>
                ))}
              </div>
              {(() => {
                const gen = documentAnalysis.rule_generation;
                if (!gen) return null;
                const tone = gen.status === 'generated' ? 'good' : gen.status === 'needs_provider_config' ? 'warn' : 'bad';
                const heading = gen.status === 'generated' ? 'Rule extraction succeeded'
                  : gen.status === 'needs_provider_config' ? 'No provider configured'
                  : gen.status === 'validation_failed' ? 'Provider returned invalid rule pack'
                  : 'Rule extraction failed';
                return (
                  <div className={cx('next-step', `tone-${tone}`)}>
                    <strong>{heading}</strong>
                    <p>{gen.message}</p>
                    {gen.provider && (
                      <p className="muted">
                        Provider: <code>{gen.provider.id}</code> · model <code>{gen.provider.model}</code>
                      </p>
                    )}
                  </div>
                );
              })()}
              {(() => {
                const ref = documentAnalysis.refinement;
                if (!ref) return null;
                const tone = ref.status === 'passed' ? 'good'
                  : ref.status === 'refined_partial' ? 'warn'
                  : ref.status === 'refining' ? 'warn'
                  : 'bad';
                const heading = ref.status === 'passed'
                  ? `Self-tests passed (${ref.self_tests_run}/${ref.self_tests_run})`
                  : ref.status === 'refined_partial'
                    ? `Refinement closed some gaps (${ref.self_tests_failed - (ref.post_refine_failed ?? 0)} of ${ref.self_tests_failed} fixed)`
                    : ref.status === 'refining'
                      ? `${ref.self_tests_failed} of ${ref.self_tests_run} self-tests need refinement`
                      : `Refinement could not validate the corrected pack`;
                return (
                  <div className={cx('next-step', `tone-${tone}`)}>
                    <strong>{heading}</strong>
                    {(ref.diffs || []).slice(0, 4).map((d, i) => (
                      <p key={i} className="muted">
                        <code>{d.name}</code>: actual {d.actual_total != null ? d.actual_total.toFixed(2) : 'ERR'} vs expected {d.expected_total.toFixed(2)} {d.missing_amount != null && `(missing ${d.missing_amount.toFixed(2)})`}
                      </p>
                    ))}
                    {ref.refine_result && (
                      <p className="muted">
                        Refine: <code>{ref.refine_result.status}</code>
                        {ref.refine_result.provider && <> · via <code>{ref.refine_result.provider.id}</code></>}
                      </p>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : <Empty msg="No candidates yet. Upload a document above to ingest one." />
        )}

        {stage.id === 'research_clarify' && (
          <div>
            <p className="muted">
              Ask a question about anything in the tariff that needs clarification — definitions, scope, conflicting wording, or unit-of-measure ambiguity. The agent reads the document and answers with cited sources.
            </p>
            {researchDispatch ? (
              <div>
                <div className="kv-grid">
                  <KV k="Status" v={researchDispatch.status} />
                  <KV k="Question" v={researchDispatch.question || researchDispatch.query} />
                  {researchDispatch.provider && <KV k="Answered by" v={`${researchDispatch.provider.id} · ${researchDispatch.provider.model}`} mono />}
                  {researchDispatch.impact_on_rules && <KV k="Impact" v={researchDispatch.impact_on_rules} />}
                </div>
                {(researchDispatch.findings?.length || 0) > 0 && (
                  <div className="findings-list">
                    {researchDispatch.findings.map((f, i) => (
                      <article className="finding" key={i}>
                        <strong>{f.claim}</strong>
                        <div className="finding-meta">
                          {f.source_type && <span className={cx('chip', `chip-${f.source_type}`)}>{f.source_type}</span>}
                          {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer">{f.source_url}</a>}
                          {f.page != null && <span className="muted">p.{f.page}</span>}
                          <span className="muted">{Math.round((f.confidence || 0) * 100)}% confident</span>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
                {(researchDispatch.remaining_uncertainty?.length || 0) > 0 && (
                  <div className="kv-full">
                    <span className="kv-k">Open questions</span>
                    <ul className="uncertainty-list">
                      {researchDispatch.remaining_uncertainty.map((u, i) => (
                        <li key={i}>{u}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {researchDispatch.message && <p className="muted">{researchDispatch.message}</p>}
              </div>
            ) : null}
            <div className="row-actions">
              <button onClick={onRunResearch}>{researchDispatch ? 'Ask another question' : 'Ask a question about this tariff'}</button>
            </div>
          </div>
        )}

        {stage.id === 'rule_normalize' && (
          rules?.rules?.length ? (
            <div>
              <div className="kv-grid">
                <KV k="Schema" v={rules.schema_version} mono />
                <KV k="Currency" v={rules.document?.currency} />
                <KV k="Jurisdiction" v={rules.document?.jurisdiction} />
                <KV k="Rules" v={rules.rules.length} />
              </div>
              <div className="rule-list">
                {rules.rules.map((r) => (
                  <details key={r.id} className="rule">
                    <summary>
                      <span>{r.charge_name}</span>
                      <code>{r.id}</code>
                      <em>{Math.round((r.confidence || 0) * 100)}%</em>
                    </summary>
                    <pre>{JSON.stringify({ applicability: r.applicability, formula: r.formula, evidence: r.evidence }, null, 2)}</pre>
                  </details>
                ))}
              </div>
            </div>
          ) : <Empty msg="No rule pack loaded." />
        )}

        {stage.id === 'rule_validate' && (
          ruleValidation ? (
            <div className={cx('validation-card', !ruleValidation.ok && 'bad')}>
              <strong>{ruleValidation.ok ? 'Schema OK' : 'Validation failed'}</strong>
              <p>{ruleValidation.message}</p>
              <KV k="Rule count" v={ruleValidation.rule_count} />
            </div>
          ) : <Empty msg="Validation has not run yet." />
        )}

        {stage.id === 'tool_compile' && (
          toolDescriptor ? (
            <div>
              <div className="kv-grid">
                <KV k="Tool ID" v={toolDescriptor.tool_id} mono />
                <KV k="Runtime" v={toolDescriptor.runtime} mono />
                <KV k="Endpoint" v={toolDescriptor.endpoint} mono />
                <KV k="Rules" v={toolDescriptor.rule_pack?.rule_count} />
              </div>
              <details>
                <summary>Tool descriptor JSON</summary>
                <pre>{JSON.stringify(toolDescriptor, null, 2)}</pre>
              </details>
            </div>
          ) : <Empty msg="Tool descriptor not yet compiled." />
        )}

        {stage.id === 'core_evaluate' && (
          result ? (
            <div>
              <div className="kv-grid">
                <KV k="Total" v={currency(result.total, result.document?.currency || 'ZAR')} />
                <KV k="Applied" v={result.results?.length || 0} />
                <KV k="Skipped" v={result.skipped_rules?.length || 0} />
                <KV k="Schema" v={result.schema_version} mono />
              </div>
              <div className="rule-eval-list">
                {result.results?.map((row) => (
                  <details key={row.rule_id} className="rule-eval">
                    <summary>
                      <strong>{row.charge_name}</strong>
                      <code>{row.rule_id}</code>
                      <span>{currency(row.amount, row.currency)}</span>
                    </summary>
                    <div className="eval-body">
                      <span className="kv-k">Formula</span>
                      <pre>{JSON.stringify(row.formula, null, 2)}</pre>
                      {!!row.evidence?.length && (
                        <>
                          <span className="kv-k">Evidence</span>
                          {row.evidence.map((e, i) => (
                            <blockquote key={i}><b>p.{e.page}</b> {e.quote}</blockquote>
                          ))}
                        </>
                      )}
                    </div>
                  </details>
                ))}
                {!!result.skipped_rules?.length && (
                  <details className="rule-eval skipped">
                    <summary>
                      <strong>Skipped rules</strong>
                      <span>{result.skipped_rules.length}</span>
                    </summary>
                    <ul className="skipped-list">
                      {result.skipped_rules.map((s) => (
                        <li key={s.rule_id}>
                          <code>{s.rule_id}</code> — {s.charge_name || '—'}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </div>
          ) : <Empty msg="Press Calculate to evaluate the rule pack." />
        )}

        {stage.id === 'explain_trace' && (
          result?.execution_trace?.length ? (
            <ol className="trace-list">
              {result.execution_trace.map((t) => (
                <li key={t.node_id}>
                  <div>
                    <strong>{t.label}</strong>
                    <p className="muted">{t.detail}</p>
                  </div>
                  <div className="trace-meta">
                    <OwnerTag owner={t.owner || 'api'} />
                    <span className={cx('trace-status', `s-${t.status}`)}>{t.status}</span>
                  </div>
                </li>
              ))}
            </ol>
          ) : <Empty msg="No trace yet — calculation has not run." />
        )}
      </div>
    </section>
  );
}

function vesselFromText(text, fallback) {
  try { return JSON.parse(text); } catch { return fallback || {}; }
}

function cargoLinesFromVessel(vessel) {
  const cargo = vessel?.cargo || {};
  const lines = [];
  for (const [key, value] of Object.entries(cargo)) {
    const m = key.match(/^(.+)_tons$/);
    if (m && Number(value) > 0) {
      lines.push({ commodity: m[1], tons: Number(value) });
    }
  }
  if (!lines.length) lines.push({ commodity: '', tons: '' });
  return lines;
}

function vesselFromForm(form, base) {
  const cargo = {};
  for (const line of form.cargoLines || []) {
    if (!line.commodity) continue;
    const tons = Number(line.tons);
    if (!Number.isFinite(tons) || tons <= 0) continue;
    cargo[`${line.commodity}_tons`] = tons;
  }
  const merged = base ? JSON.parse(JSON.stringify(base)) : {};
  merged.vessel_metadata = { ...(merged.vessel_metadata || {}), name: form.name || 'unnamed' };
  merged.technical_specs = {
    ...(merged.technical_specs || {}),
    type: form.type || null,
    gross_tonnage: numOrNull(form.gross_tonnage),
    net_tonnage: numOrNull(form.net_tonnage),
    loa_meters: numOrNull(form.loa_meters),
    dwt: numOrNull(form.dwt),
  };
  merged.operational_data = {
    ...(merged.operational_data || {}),
    port: form.port || null,
    service: form.service || null,
    days_alongside: numOrNull(form.days_alongside),
    num_operations: numOrNull(form.num_operations),
    activity: form.activity || null,
  };
  merged.cargo = cargo;
  merged.discounts = {
    esi_score: numOrNull(form.esi_score),
    green_award_certificate: form.green_award_certificate || null,
  };
  return merged;
}

function numOrNull(v) {
  if (v === '' || v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function formFromVessel(v) {
  return {
    name: v?.vessel_metadata?.name ?? '',
    type: v?.technical_specs?.type ?? '',
    gross_tonnage: v?.technical_specs?.gross_tonnage ?? '',
    net_tonnage: v?.technical_specs?.net_tonnage ?? '',
    loa_meters: v?.technical_specs?.loa_meters ?? '',
    dwt: v?.technical_specs?.dwt ?? '',
    port: v?.operational_data?.port ?? '',
    service: v?.operational_data?.service ?? '',
    days_alongside: v?.operational_data?.days_alongside ?? '',
    num_operations: v?.operational_data?.num_operations ?? '',
    activity: v?.operational_data?.activity ?? '',
    esi_score: v?.discounts?.esi_score ?? '',
    green_award_certificate: v?.discounts?.green_award_certificate ?? '',
    cargoLines: cargoLinesFromVessel(v),
  };
}

function VesselCalculator({ vesselText, setVesselText, knownPorts = [], activePortId = '' }) {
  const [form, setForm] = useState(() => formFromVessel(vesselFromText(vesselText, defaultVessel)));
  const [showJson, setShowJson] = useState(false);

  function patch(next) {
    const merged = { ...form, ...next };
    setForm(merged);
    const vessel = vesselFromForm(merged, vesselFromText(vesselText, defaultVessel));
    setVesselText(JSON.stringify(vessel, null, 2));
  }

  function patchCargo(idx, next) {
    const cargoLines = form.cargoLines.map((line, i) => (i === idx ? { ...line, ...next } : line));
    patch({ cargoLines });
  }

  function addCargo() {
    patch({ cargoLines: [...form.cargoLines, { commodity: '', tons: '' }] });
  }

  function removeCargo(idx) {
    const next = form.cargoLines.filter((_, i) => i !== idx);
    patch({ cargoLines: next.length ? next : [{ commodity: '', tons: '' }] });
  }

  return (
    <div className="calc-form">
      <div className="calc-section">
        <div className="calc-section-head"><h4>Vessel</h4></div>
        <div className="calc-grid-2">
          <div className="calc-field">
            <label>Vessel name</label>
            <input value={form.name} onChange={(e) => patch({ name: e.target.value })} placeholder="EXAMPLE 1" />
          </div>
          <div className="calc-field">
            <label>Type</label>
            <select value={form.type} onChange={(e) => patch({ type: e.target.value })}>
              <option value="">Choose vessel type</option>
              {VESSEL_TYPES.map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </div>
          <div className="calc-field">
            <label>Service</label>
            <select value={form.service} onChange={(e) => patch({ service: e.target.value })}>
              {SERVICE_TYPES.map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </div>
          <div className="calc-field">
            <label>Gross Tonnage</label>
            <div className="calc-field-suffix" data-suffix="GT">
              <input type="number" min="0" value={form.gross_tonnage} onChange={(e) => patch({ gross_tonnage: e.target.value })} />
            </div>
          </div>
          <div className="calc-field">
            <label>Net Tonnage</label>
            <div className="calc-field-suffix" data-suffix="NT">
              <input type="number" min="0" value={form.net_tonnage} onChange={(e) => patch({ net_tonnage: e.target.value })} />
            </div>
          </div>
          <div className="calc-field">
            <label>LOA</label>
            <div className="calc-field-suffix" data-suffix="m">
              <input type="number" min="0" step="0.1" value={form.loa_meters} onChange={(e) => patch({ loa_meters: e.target.value })} />
            </div>
          </div>
          <div className="calc-field">
            <label>Days alongside</label>
            <input type="number" min="0" step="0.01" value={form.days_alongside} onChange={(e) => patch({ days_alongside: e.target.value })} />
          </div>
          <div className="calc-field">
            <label>Port</label>
            {(() => {
              const ready = knownPorts.filter((p) => p.has_rule_pack);
              if (!ready.length) {
                return <input value={form.port} disabled placeholder="Activate a known port first" />;
              }
              const options = ready.map((p) => p.title || p.port_id);
              const current = form.port && options.includes(form.port) ? form.port : (ready.find((p) => p.port_id === activePortId)?.title || options[0]);
              return (
                <select value={current} onChange={(e) => patch({ port: e.target.value })}>
                  {options.map((title) => (
                    <option key={title} value={title}>{title}</option>
                  ))}
                </select>
              );
            })()}
          </div>
        </div>
      </div>

      <div className="calc-divider" />

      <div className="calc-section">
        <div className="calc-section-head">
          <h4>Cargo</h4>
          <small className="muted">Tonnes per commodity</small>
        </div>
        {form.cargoLines.map((line, idx) => (
          <div className="cargo-row" key={idx}>
            <select value={line.commodity} onChange={(e) => patchCargo(idx, { commodity: e.target.value })}>
              <option value="">Choose commodity</option>
              {COMMODITIES.map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
            <div className="calc-field-suffix" data-suffix="t">
              <input type="number" min="0" value={line.tons} onChange={(e) => patchCargo(idx, { tons: e.target.value })} placeholder="0" />
            </div>
            <button type="button" className="icon-x" onClick={() => removeCargo(idx)} aria-label="Remove cargo line">×</button>
          </div>
        ))}
        <button type="button" className="add-cargo" onClick={addCargo}>+ Add cargo line</button>
      </div>

      <div className="calc-divider" />

      <div className="calc-section">
        <div className="calc-section-head"><h4>Discounts</h4></div>
        <div className="calc-grid-2">
          <div className="calc-field">
            <label>ESI score (0–120)</label>
            <input type="number" min="0" max="120" value={form.esi_score} onChange={(e) => patch({ esi_score: e.target.value })} placeholder="leave empty if none" />
          </div>
          <div className="calc-field">
            <label>Green Award certificate</label>
            <select value={form.green_award_certificate} onChange={(e) => patch({ green_award_certificate: e.target.value })}>
              {GREEN_AWARDS.map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <button type="button" className="json-toggle" onClick={() => setShowJson((s) => !s)}>
        {showJson ? '− Hide raw vessel JSON' : '+ Show raw vessel JSON'}
      </button>
      {showJson && (
        <textarea
          value={vesselText}
          onChange={(e) => {
            setVesselText(e.target.value);
            const parsed = vesselFromText(e.target.value, null);
            if (parsed) setForm(formFromVessel(parsed));
          }}
          spellCheck={false}
          rows={14}
        />
      )}
    </div>
  );
}

function InputColumn({
  documentAnalysis,
  knownPorts,
  activePortId,
  vesselText,
  setVesselText,
  busy,
  hasActiveRulePack,
  activeRulePackTitle,
  onUpload,
  onSelectPort,
  onCalculate,
}) {
  const fileRef = useRef(null);
  const canCalculate = hasActiveRulePack && !busy;

  return (
    <section className="card input-col">
      <div className="phase">
        <header className="phase-head">
          <p className="eyebrow">Stages 1–6 · Build</p>
          <h3>Build the calculator</h3>
          <p className="muted">Upload a tariff or pick a known port — the agent extracts, normalizes and compiles the rule pack into a callable tool. No vessel data needed yet.</p>
        </header>

        <div className="field">
          <span className="field-k">Tariff document</span>
          <button type="button" className="dropzone" onClick={() => fileRef.current?.click()}>
            <strong>{documentAnalysis ? documentAnalysis.filename : 'Choose a tariff PDF or text file'}</strong>
            <small>{documentAnalysis ? `${documentAnalysis.pages} pages · source ${documentAnalysis.source_id}` : 'PDF · TXT · MD up to 25 MB'}</small>
          </button>
          <input ref={fileRef} type="file" accept="application/pdf,text/plain,.txt,.md" onChange={onUpload} hidden />
        </div>

        {(() => {
          const ready = knownPorts.filter((p) => p.has_rule_pack);
          const pending = knownPorts.filter((p) => !p.has_rule_pack);
          return (
            <div className="field">
              <span className="field-k">Known ports</span>
              <select value={activePortId || ''} onChange={(e) => onSelectPort(e.target.value)} disabled={!ready.length}>
                <option value="">{ready.length ? 'Switch processed port' : 'No processed ports yet'}</option>
                {ready.map((port) => (
                  <option key={port.port_id} value={port.port_id}>
                    {port.title || port.port_id} · {port.rule_count || 0} rules
                  </option>
                ))}
              </select>
              <small className="muted">
                {ready.length
                  ? 'Switch between processed ports. Upload above to add a new one.'
                  : 'Upload a tariff PDF above to create the first processed port.'}
                {pending.length > 0 && ` · ${pending.length} document${pending.length === 1 ? '' : 's'} awaiting extraction`}
              </small>
            </div>
          );
        })()}

        <div className={cx('phase-state', hasActiveRulePack && 'on')}>
          <span className="s-dot" />
          <div>
            <strong>{hasActiveRulePack ? 'Calculator tool ready' : 'No active rule pack'}</strong>
            <small>{hasActiveRulePack ? (activeRulePackTitle || 'Generated rule pack active') : 'Build or activate a rule pack to enable Calculate.'}</small>
          </div>
        </div>
      </div>

      <div className="phase">
        <header className="phase-head">
          <p className="eyebrow">Stages 7–8 · Run</p>
          <h3>Run a vessel through the tool</h3>
          <p className="muted">Vessel facts feed the calculator once the rule pack is active. Edit below, then Calculate.</p>
        </header>

        <VesselCalculator vesselText={vesselText} setVesselText={setVesselText} knownPorts={knownPorts} activePortId={activePortId} />

        <button className="primary" onClick={onCalculate} disabled={!canCalculate}>
          {busy ? 'Evaluating…' : hasActiveRulePack ? 'Calculate tariffs' : 'Activate a rule pack first'}
        </button>
      </div>
    </section>
  );
}

function ResultColumn({ result, busy, onPickRow }) {
  if (busy && !result) {
    return (
      <section className="card result-col">
        <header className="card-head">
          <p className="eyebrow">Result</p>
          <h3>Evaluating…</h3>
        </header>
        <div className="skeleton-line lg" />
        <div className="skeleton-line" />
        <div className="skeleton-line" />
        <div className="skeleton-line" />
      </section>
    );
  }

  if (!result) {
    return (
      <section className="card result-col empty-state">
        <header className="card-head">
          <p className="eyebrow">Result</p>
          <h3>No calculation yet</h3>
        </header>
        <p className="muted">Upload a tariff PDF — the agent extracts and activates the rule pack automatically. Then press Calculate.</p>
        <div className="proof-pin">
          <strong>Validated example</strong>
          <p>Rotterdam Annex 2 Example 4 — Container Deepsea (GT 75,246, 15,000 t, ESI 35) — reproduces <strong>€21,808.74</strong> to the cent through agent-extracted rules.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="card result-col">
      <header className="card-head between">
        <div>
          <p className="eyebrow">Result · {result.document?.title || 'tariff pack'}</p>
          <h3 className="total-line">{currency(result.total, result.document?.currency || 'ZAR')}</h3>
          <p className="muted">{result.results?.length || 0} charges applied · {result.skipped_rules?.length || 0} skipped</p>
        </div>
      </header>

      <div className="result-list">
        {(result.results || []).map((row) => {
          const missingMatch = row.error && /Missing formula variable:\s*(\S+)/.exec(row.error);
          const missingField = missingMatch ? missingMatch[1] : null;
          const isErrored = row.error && !missingField;
          return (
            <article className={cx('result-row', missingField && 'needs-field', isErrored && 'errored')} key={row.rule_id}>
              <div className="rr-head">
                <div>
                  <strong>{row.charge_name}</strong>
                  <code>{row.rule_id}</code>
                </div>
                <div className="rr-amount">
                  {missingField ? (
                    <span className="needs-pill">Needs vessel field</span>
                  ) : isErrored ? (
                    <span className="bad">Could not evaluate</span>
                  ) : (
                    currency(row.amount, row.currency)
                  )}
                  <small>conf {Math.round((row.confidence || 0) * 100)}%</small>
                </div>
              </div>
              {missingField ? (
                <p className="rr-reason">
                  Add <code>{missingField}</code> to vessel facts (Show raw vessel JSON) to enable this charge.
                </p>
              ) : isErrored ? (
                <p className="rr-reason">{row.error}</p>
              ) : (
                row.reason && <p className="rr-reason">{row.reason}</p>
              )}
              {!!row.evidence_links?.length && (
                <div className="link-row">
                  {row.evidence_links.map((link) => (
                    <a key={`${row.rule_id}-${link.url}`} href={apiLink(link.url)} target="_blank" rel="noreferrer">{link.label}</a>
                  ))}
                </div>
              )}
              <button className="rr-trace" onClick={() => onPickRow('core_evaluate')}>Open in trace ↗</button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ActivityStrip({ events }) {
  return (
    <section className="activity-strip">
      <span className="eyebrow">Activity</span>
      <ul>
        {events.slice(0, 6).map((e) => (
          <li key={e.id} className={cx('act', e.kind)}>
            <span className="act-time">{e.time}</span>
            <span className="act-title">{e.title}</span>
            <span className="act-detail">{e.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SettingsDrawer({ open, models, onClose, onSaved, onEvent }) {
  const providers = models?.providers || [];
  const [providerId, setProviderId] = useState(providers[0]?.id || 'gemini');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (providers.length && !providers.some((p) => p.id === providerId)) {
      setProviderId(providers[0].id);
    }
  }, [providers, providerId]);

  const selected = providers.find((p) => p.id === providerId);

  async function save() {
    setSaving(true);
    onEvent('Saving provider', `${providerId} updated`, 'working');
    try {
      const payload = {
        default_research_provider: providerId,
        providers: [{
          id: providerId,
          model: model || selected?.model,
          api_key: apiKey || undefined,
          enabled: true,
        }],
      };
      const res = await fetch(`${API}/api/models/configure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const next = await res.json();
      onSaved(next);
      setApiKey('');
      onEvent('Provider saved', `${providerId} stored locally`, 'success');
    } catch (e) {
      onEvent('Save failed', e.message, 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className={cx('drawer-scrim', open && 'open')} onClick={onClose} />
      <aside className={cx('drawer', open && 'open')} role="dialog" aria-hidden={!open}>
        <header>
          <div>
            <p className="eyebrow">Settings</p>
            <h3>Model providers</h3>
          </div>
          <button className="ghost" onClick={onClose}>Close</button>
        </header>

        <div className="drawer-body">
          <p className="muted">
            API keys stay on this machine and are used only for tariff extraction and clarification. The calculator itself never calls a model.
          </p>

          <div className="provider-list">
            {providers.map((p) => (
              <button
                type="button"
                key={p.id}
                className={cx('provider-card', providerId === p.id && 'active')}
                onClick={() => setProviderId(p.id)}
              >
                <div>
                  <strong>{p.id}</strong>
                  <small>{p.model || p.kind}</small>
                </div>
                <div className="provider-flags">
                  <span className={cx('flag', p.enabled && 'on')}>{p.enabled ? 'enabled' : 'disabled'}</span>
                  <span className={cx('flag', p.api_key_set && 'on')}>{p.api_key_set ? 'key set' : 'no key'}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="form-grid">
            <label>
              Provider ID
              <input value={providerId} readOnly />
            </label>
            <label>
              Model
              <input
                value={model}
                placeholder={selected?.model || ''}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
            <label className="wide">
              API key
              <input
                type="password"
                value={apiKey}
                placeholder={selected?.api_key_set ? 'Leave blank to keep existing' : 'Paste API key'}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>
          </div>

          <button className="primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save provider'}
          </button>
        </div>
      </aside>
    </>
  );
}

function Topbar({ health, onSettings }) {
  const ok = health?.ok;
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <span /><span /><span />
        </div>
        <div>
          <strong>NBot · Port Tariff Agent</strong>
          <small>Tariff extraction & calculation</small>
        </div>
      </div>
      <div className="topbar-right">
        <div className={cx('health', ok && 'ok')}>
          <span className="hp" />
          {ok ? 'Core online' : 'Core offline'}
        </div>
        <button className="icon-btn" onClick={onSettings} aria-label="Settings">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
          <span>Settings</span>
        </button>
      </div>
    </header>
  );
}

function App() {
  const [health, setHealth] = useState(null);
  const [rules, setRules] = useState(null);
  const [activeRulePack, setActiveRulePack] = useState(null);
  const [knownPorts, setKnownPorts] = useState([]);
  const [activePortId, setActivePortId] = useState('');
  const [ruleValidation, setRuleValidation] = useState(null);
  const [models, setModels] = useState(null);
  const [toolDescriptor, setToolDescriptor] = useState(null);
  const [result, setResult] = useState(null);
  const [calcError, setCalcError] = useState(null);
  const [documentAnalysis, setDocumentAnalysis] = useState(null);
  const [researchDispatch, setResearchDispatch] = useState(null);
  const [vesselText, setVesselText] = useState(JSON.stringify(defaultVessel, null, 2));
  const [busy, setBusy] = useState(false);
  const [liveCursor, setLiveCursor] = useState(null);
  const [extracting, setExtracting] = useState(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!extracting) return undefined;
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, [extracting]);

  const elapsedSec = extracting ? Math.floor((Date.now() - extracting.startedAt) / 1000) : 0;
  const [selectedStage, setSelectedStage] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const sharedFileRef = useRef(null);
  const triggerUpload = () => sharedFileRef.current?.click();
  const [events, setEvents] = useState([
    { id: 1, time: clockTime(), title: 'Console booted', detail: 'Loading core, rules, providers.', kind: 'info' },
  ]);

  const stages = useMemo(
    () => derivePipeline({ documentAnalysis, rules, ruleValidation, toolDescriptor, result, researchDispatch, calcError }, liveCursor),
    [documentAnalysis, rules, ruleValidation, toolDescriptor, result, researchDispatch, calcError, liveCursor],
  );
  const selectedStageObj = stages.find((s) => s.id === selectedStage) || null;

  function logEvent(title, detail, kind = 'info') {
    setEvents((current) => [
      { id: Date.now() + Math.random(), time: clockTime(), title, detail, kind },
      ...current,
    ].slice(0, 20));
  }

  async function load() {
    try {
      const [healthRes, rulesRes, modelsRes, toolsRes, portsRes] = await Promise.all([
        fetch(`${API}/api/health`),
        fetch(`${API}/api/rules`),
        fetch(`${API}/api/models`),
        fetch(`${API}/api/tools`),
        fetch(`${API}/api/ports`),
      ]);
      const h = await healthRes.json();
      const r = await rulesRes.json();
      const m = await modelsRes.json();
      const t = await toolsRes.json();
      const p = await portsRes.json();
      setHealth(h);
      setRules(r);
      setActiveRulePack(r);
      setModels(m);
      setToolDescriptor(t.tools?.[0] || null);
      setKnownPorts(p.ports || []);
      setActivePortId(p.active?.port_id || '');
      logEvent('Core online', `${r.rules?.length || 0} rules · ${(t.tools || []).length} compiled tool(s)`, 'success');
      validatePack(r);
    } catch (e) {
      logEvent('Core offline', e.message, 'error');
    }
  }

  async function validatePack(pack) {
    try {
      const res = await fetch(`${API}/api/rule-pack/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pack),
      });
      const data = await res.json();
      setRuleValidation(data);
      logEvent('Rule pack validated', data.message || '—', data.ok ? 'success' : 'error');
    } catch (e) {
      setRuleValidation({ ok: false, message: e.message });
    }
  }

  async function runLiveCursor(start = 0, end = STAGES.length) {
    for (let i = start; i < end; i++) {
      setLiveCursor(i);
      await new Promise((r) => setTimeout(r, 220));
    }
    setLiveCursor(null);
  }

  const RUN_PHASE_START = STAGES.findIndex((s) => s.id === 'core_evaluate');

  async function calculate() {
    setBusy(true);
    setCalcError(null);
    setResult(null);
    setSelectedStage(null);
    if (!activeRulePack?._runtime?.active_rule_pack_generated && !(activeRulePack?.rules || []).length) {
      const message = 'No generated port rules are active. Upload/activate a rule pack before calculating.';
      setCalcError(message);
      logEvent('Calculation blocked', message, 'warn');
      setBusy(false);
      return;
    }
    logEvent('Calculation started', 'Evaluating vessel against active rule pack', 'working');
    const cursor = runLiveCursor(RUN_PHASE_START, STAGES.length);
    try {
      const vessel = JSON.parse(vesselText);
      const res = await fetch(`${API}/api/calculate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vessel, rule_pack: activeRulePack }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      await cursor;
      setResult(payload);
      logEvent('Calculation complete', `Total ${currency(payload.total, payload.document?.currency || 'ZAR')}`, 'success');
      setSelectedStage('core_evaluate');
    } catch (e) {
      await cursor;
      setCalcError(e.message);
      logEvent('Calculation failed', e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function handleDocumentUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    logEvent('Uploading document', file.name, 'working');

    const startedAt = Date.now();
    setExtracting({ filename: file.name, startedAt });

    let cursorRunning = true;
    const cursorTask = (async () => {
      while (cursorRunning) {
        for (let i = 0; i < RUN_PHASE_START && cursorRunning; i++) {
          setLiveCursor(i);
          await new Promise((r) => setTimeout(r, 240));
        }
      }
      setLiveCursor(null);
    })();

    try {
      const form = new FormData();
      form.append('file', file, file.name);
      const res = await fetch(`${API}/api/document/upload`, { method: 'POST', body: form });
      const payload = await res.json();
      cursorRunning = false;
      await cursorTask;
      setExtracting(null);

      setDocumentAnalysis(payload);
      setKnownPorts(payload.known_ports?.ports || knownPorts);
      if (payload.activated_rule_pack?.rules) {
        setRules(payload.activated_rule_pack.rules);
        setActiveRulePack(payload.activated_rule_pack.rules);
        setToolDescriptor(payload.activated_rule_pack.tools?.tools?.[0] || null);
        setActivePortId(payload.activated_rule_pack.port?.port_id || payload.source_id || '');
        setRuleValidation(payload.activated_rule_pack.validation || null);
      }
      logEvent('Document analyzed', `${payload.pages} pages · ${payload.candidate_terms?.length || 0} signals`, 'success');
      if (payload.rule_generation?.status === 'generated') {
        logEvent('Rule pack generated', payload.rule_generation.message, 'success');
      } else if (payload.rule_generation?.status) {
        logEvent('Rule generation needs attention', payload.rule_generation.message || payload.rule_generation.status, 'warn');
      }
      setSelectedStage('candidate_extract');
    } catch (err) {
      cursorRunning = false;
      await cursorTask;
      setExtracting(null);
      logEvent('Upload failed', err.message, 'error');
    }
  }

  async function selectKnownPort(portId) {
    if (!portId) {
      setActivePortId('');
      return;
    }
    const cursor = runLiveCursor(3, RUN_PHASE_START);
    try {
      const res = await fetch(`${API}/api/ports/${encodeURIComponent(portId)}/activate`, { method: 'POST' });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const payload = await res.json();
      await cursor;
      setActivePortId(portId);
      setRules(payload.rules);
      setActiveRulePack(payload.rules);
      setToolDescriptor(payload.tools?.tools?.[0] || null);
      logEvent('Known port activated', payload.message, 'success');
      validatePack(payload.rules);
    } catch (err) {
      await cursor;
      logEvent('Port activation failed', err.message, 'error');
    }
  }

  async function runResearch() {
    const defaultQuery = rules?.document?.title
      ? `For ${rules.document.title}, list any ambiguous terms, conflicting definitions, or unit-of-measure questions in the rule pack and explain them with page citations.`
      : 'List any ambiguous terms or unit-of-measure questions raised by this tariff document and explain them with page citations.';
    const query = window.prompt('Question for the research agent:', defaultQuery);
    if (!query) return;
    logEvent('Research started', query.slice(0, 80), 'working');
    try {
      const vessel = JSON.parse(vesselText);
      const res = await fetch(`${API}/api/research/clarify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          context: { vessel, rule_pack_hints: { title: rules?.document?.title, currency: rules?.document?.currency } },
        }),
      });
      const payload = await res.json();
      setResearchDispatch(payload);
      const status = payload.status || 'unknown';
      const kind = status === 'answered' ? 'success' : status === 'needs_provider_config' ? 'warn' : 'info';
      logEvent('Research finished', `${status} · ${payload.findings?.length || 0} findings`, kind);
    } catch (err) {
      logEvent('Research failed', err.message, 'error');
    }
  }

  function handleModelsSaved(payload) {
    setModels(payload.models);
    logEvent('Provider settings saved', payload.message || 'Local PoC config updated', 'success');
  }

  useEffect(() => { load(); }, []);

  return (
    <>
      <Topbar health={health} onSettings={() => setSettingsOpen(true)} />

      <main className="shell">
        <Pipeline
          stages={stages}
          selectedId={selectedStage}
          onSelect={setSelectedStage}
          extracting={extracting}
          elapsedSec={elapsedSec}
        />

        {selectedStageObj && (
          <StageDetail
            stage={selectedStageObj}
            state={{ documentAnalysis, rules, ruleValidation, toolDescriptor, result, researchDispatch }}
            onClose={() => setSelectedStage(null)}
            onRunResearch={runResearch}
            onTriggerUpload={triggerUpload}
          />
        )}
        <input ref={sharedFileRef} type="file" accept="application/pdf,text/plain,.txt,.md" onChange={handleDocumentUpload} hidden />

        <div className="dual">
          <InputColumn
            documentAnalysis={documentAnalysis}
            knownPorts={knownPorts}
            activePortId={activePortId}
            vesselText={vesselText}
            setVesselText={setVesselText}
            busy={busy}
            hasActiveRulePack={Boolean(rules?._runtime?.active_rule_pack_generated)}
            activeRulePackTitle={rules?.document?.title}
            onUpload={handleDocumentUpload}
            onSelectPort={selectKnownPort}
            onCalculate={calculate}
          />
          <ResultColumn result={result} busy={busy} onPickRow={setSelectedStage} />
        </div>

        <ActivityStrip events={events} />
      </main>

      <SettingsDrawer
        open={settingsOpen}
        models={models}
        onClose={() => setSettingsOpen(false)}
        onSaved={handleModelsSaved}
        onEvent={logEvent}
      />
    </>
  );
}

createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
