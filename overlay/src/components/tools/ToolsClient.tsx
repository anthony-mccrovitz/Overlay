"use client";

import { useMemo, useState } from "react";

function toDecimal(american: number): number {
  if (american > 0) return american / 100 + 1;
  return 100 / Math.abs(american) + 1;
}
function toAmerican(decimal: number): string {
  const implied = 1 / decimal;
  if (implied >= 0.5) return `-${Math.round((implied / (1 - implied)) * 100)}`;
  return `+${Math.round(((1 - implied) / implied) * 100)}`;
}
function impliedProb(american: number): number {
  if (american > 0) return 100 / (american + 100);
  return Math.abs(american) / (Math.abs(american) + 100);
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label className="label-muted" style={{ display: "block", marginBottom: 6 }}>
        {label}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mono"
        style={{
          width: "100%",
          background: "var(--bg)",
          border: "1px solid var(--border-hi)",
          color: "var(--text-bright)",
          borderRadius: 4,
          padding: "9px 12px",
          fontSize: 14,
          outline: "none",
        }}
      />
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "8px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</span>
      <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: color || "var(--text-bright)" }}>
        {value}
      </span>
    </div>
  );
}

function ToolPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel" style={{ padding: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-bright)", marginBottom: 16, letterSpacing: "0.02em" }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function EvCalc() {
  const [odds, setOdds] = useState("-110");
  const [prob, setProb] = useState("55");

  const r = useMemo(() => {
    const o = parseInt(odds);
    const p = parseFloat(prob) / 100;
    if (isNaN(o) || isNaN(p) || p <= 0 || p >= 1) return null;
    const implied = impliedProb(o);
    const edge = (p - implied) * 100;
    const dec = toDecimal(o);
    const ev = (p * (dec - 1) - (1 - p)) * 100;
    const kelly = edge > 0 ? (edge / ((dec - 1) * 100)) * 100 : 0;
    return {
      implied: (implied * 100).toFixed(1),
      edge: edge.toFixed(2),
      ev: ev.toFixed(2),
      kelly: kelly.toFixed(1),
    };
  }, [odds, prob]);

  return (
    <ToolPanel title="EV Calculator">
      <Field label="American odds" value={odds} onChange={setOdds} placeholder="-110" />
      <Field label="Model probability %" value={prob} onChange={setProb} placeholder="55" />
      {r && (
        <div style={{ marginTop: 12 }}>
          <Row label="Implied prob" value={`${r.implied}%`} />
          <Row label="Edge" value={`${Number(r.edge) >= 0 ? "+" : ""}${r.edge}%`} color={Number(r.edge) >= 0 ? "var(--green-hi)" : "var(--red-hi)"} />
          <Row label="EV per $100" value={`$${Number(r.ev) >= 0 ? "+" : ""}${r.ev}`} color={Number(r.ev) >= 0 ? "var(--green-hi)" : "var(--red-hi)"} />
          <Row label="Kelly fraction" value={`${r.kelly}%`} color="var(--accent-hi)" />
        </div>
      )}
    </ToolPanel>
  );
}

function ClvCalc() {
  const [open, setOpen] = useState("+120");
  const [close, setClose] = useState("+100");

  const r = useMemo(() => {
    const o = parseInt(open);
    const c = parseInt(close);
    if (isNaN(o) || isNaN(c)) return null;
    const oi = impliedProb(o);
    const ci = impliedProb(c);
    const clv = (ci - oi) * 100;
    return { oi: (oi * 100).toFixed(1), ci: (ci * 100).toFixed(1), clv: clv.toFixed(2) };
  }, [open, close]);

  return (
    <ToolPanel title="CLV Calculator">
      <Field label="Opening odds (American)" value={open} onChange={setOpen} placeholder="+120" />
      <Field label="Closing odds (American)" value={close} onChange={setClose} placeholder="+100" />
      {r && (
        <div style={{ marginTop: 12 }}>
          <Row label="Opening implied" value={`${r.oi}%`} />
          <Row label="Closing implied" value={`${r.ci}%`} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "10px 12px",
              borderRadius: 4,
              marginTop: 10,
              background: Number(r.clv) >= 0 ? "var(--red-dim)" : "var(--green-dim)",
              border: `1px solid ${Number(r.clv) >= 0 ? "rgba(239,68,68,0.3)" : "rgba(34,197,94,0.3)"}`,
            }}
          >
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>CLV%</span>
            <span className="mono" style={{ fontSize: 15, fontWeight: 800, color: Number(r.clv) >= 0 ? "var(--red-hi)" : "var(--green-hi)" }}>
              {Number(r.clv) >= 0 ? "+" : ""}
              {r.clv}% {Number(r.clv) >= 0 ? "(missed close)" : "(beat close)"}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
            Negative CLV = market moved in your favor after you bet = you beat the close.
          </div>
        </div>
      )}
    </ToolPanel>
  );
}

function OddsConverter() {
  const [input, setInput] = useState("-110");
  const [mode, setMode] = useState<"american" | "decimal" | "fraction" | "implied">("american");

  const r = useMemo(() => {
    const v = input.trim();
    if (!v) return null;
    let am: number | null = null;
    let dec: number | null = null;
    if (mode === "american") {
      const n = parseInt(v);
      if (isNaN(n) || n === 0 || n === -100 || n === 100) return null;
      am = n;
      dec = n > 0 ? n / 100 + 1 : 100 / Math.abs(n) + 1;
    } else if (mode === "decimal") {
      const n = parseFloat(v);
      if (isNaN(n) || n <= 1) return null;
      dec = n;
      const prob = 1 / n;
      am = prob >= 0.5 ? -Math.round((prob / (1 - prob)) * 100) : Math.round(((1 - prob) / prob) * 100);
    } else if (mode === "fraction") {
      const parts = v.split(/[\/\-]/);
      if (parts.length !== 2) return null;
      const [num, den] = parts.map(Number);
      if (isNaN(num) || isNaN(den) || den === 0) return null;
      dec = num / den + 1;
      const prob = 1 / dec;
      am = prob >= 0.5 ? -Math.round((prob / (1 - prob)) * 100) : Math.round(((1 - prob) / prob) * 100);
    } else {
      const n = parseFloat(v);
      if (isNaN(n) || n <= 0 || n >= 100) return null;
      const prob = n / 100;
      am = prob >= 0.5 ? -Math.round((prob / (1 - prob)) * 100) : Math.round(((1 - prob) / prob) * 100);
      dec = 1 / prob;
    }
    if (!dec || !am) return null;
    const prob = 1 / dec;
    const num = Math.round((dec - 1) * 10);
    const den = 10;
    const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
    const g = gcd(num, den);
    return {
      american: am > 0 ? `+${am}` : `${am}`,
      decimal: dec.toFixed(3),
      fraction: `${num / g}/${den / g}`,
      implied: (prob * 100).toFixed(2) + "%",
    };
  }, [input, mode]);

  const MODES = [
    { key: "american", label: "American" },
    { key: "decimal", label: "Decimal" },
    { key: "fraction", label: "Fraction" },
    { key: "implied", label: "Implied %" },
  ] as const;

  return (
    <ToolPanel title="Odds Converter">
      <div
        style={{
          display: "flex",
          gap: 4,
          marginBottom: 12,
          background: "var(--bg)",
          border: "1px solid var(--border-hi)",
          borderRadius: 4,
          padding: 3,
        }}
      >
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => {
              setMode(m.key);
              setInput("");
            }}
            style={{
              flex: 1,
              padding: "5px 0",
              borderRadius: 3,
              fontSize: 11,
              fontWeight: 700,
              cursor: "pointer",
              border: "none",
              background: mode === m.key ? "var(--accent)" : "transparent",
              color: mode === m.key ? "#fff" : "var(--text-secondary)",
              letterSpacing: "0.04em",
            }}
          >
            {m.label}
          </button>
        ))}
      </div>
      <Field
        label={`Enter ${mode} odds`}
        value={input}
        onChange={setInput}
        placeholder={
          mode === "american" ? "-110" : mode === "decimal" ? "1.909" : mode === "fraction" ? "10/11" : "52.38"
        }
      />
      {r ? (
        <div style={{ marginTop: 8 }}>
          {mode !== "american" && <Row label="American" value={r.american} color="var(--accent-hi)" />}
          {mode !== "decimal" && <Row label="Decimal" value={r.decimal} />}
          {mode !== "fraction" && <Row label="Fraction" value={r.fraction} />}
          {mode !== "implied" && <Row label="Implied prob" value={r.implied} />}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
          {mode === "american" && "Enter American odds e.g. -110 or +150"}
          {mode === "decimal" && "Enter decimal odds e.g. 1.909 (must be > 1)"}
          {mode === "fraction" && "Enter fraction e.g. 10/11 or 3/1"}
          {mode === "implied" && "Enter implied probability e.g. 52.38 (no %)"}
        </div>
      )}
    </ToolPanel>
  );
}

interface Leg {
  id: number;
  desc: string;
  odds: string;
}

function ParlayBuilder() {
  const [legs, setLegs] = useState<Leg[]>([
    { id: 1, desc: "", odds: "" },
    { id: 2, desc: "", odds: "" },
  ]);

  const add = () => legs.length < 10 && setLegs((l) => [...l, { id: Date.now(), desc: "", odds: "" }]);
  const remove = (id: number) => setLegs((l) => l.filter((x) => x.id !== id));
  const update = (id: number, field: "desc" | "odds", v: string) =>
    setLegs((l) => l.map((x) => (x.id === id ? { ...x, [field]: v } : x)));

  const r = useMemo(() => {
    const valid = legs.filter((l) => l.odds.trim() !== "");
    if (valid.length < 2) return null;
    const decs = valid.map((l) => toDecimal(parseInt(l.odds))).filter((d) => !isNaN(d) && d > 1);
    if (decs.length < 2) return null;
    const combo = decs.reduce((a, b) => a * b, 1);
    return { combined: toAmerican(combo), payout: ((combo - 1) * 100).toFixed(0), legs: decs.length };
  }, [legs]);

  return (
    <ToolPanel title="Parlay Builder">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {legs.map((leg, i) => (
          <div key={leg.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", width: 18 }}>
              #{i + 1}
            </span>
            <input
              value={leg.desc}
              onChange={(e) => update(leg.id, "desc", e.target.value)}
              placeholder="Pick description"
              style={{
                flex: 1,
                background: "var(--bg)",
                border: "1px solid var(--border-hi)",
                color: "var(--text)",
                borderRadius: 4,
                padding: "7px 10px",
                fontSize: 12,
              }}
            />
            <input
              value={leg.odds}
              onChange={(e) => update(leg.id, "odds", e.target.value)}
              placeholder="Odds"
              className="mono"
              style={{
                width: 78,
                background: "var(--bg)",
                border: "1px solid var(--border-hi)",
                color: "var(--text)",
                borderRadius: 4,
                padding: "7px 10px",
                fontSize: 12,
                textAlign: "center",
              }}
            />
            {legs.length > 1 && (
              <button
                onClick={() => remove(leg.id)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 14 }}
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      <button
        onClick={add}
        style={{
          marginTop: 12,
          padding: "6px 12px",
          background: "var(--accent-dim)",
          border: "1px solid rgba(45,127,255,0.3)",
          color: "var(--accent-hi)",
          borderRadius: 4,
          fontSize: 11,
          fontWeight: 700,
          cursor: "pointer",
          letterSpacing: "0.06em",
        }}
      >
        + ADD LEG
      </button>
      {r && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            background: "var(--bg)",
            borderRadius: 4,
            border: "1px solid var(--border-hi)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Combined ({r.legs} legs)</span>
            <span className="mono pos" style={{ fontSize: 16, fontWeight: 800 }}>
              {r.combined}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>$100 payout</span>
            <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: "var(--text-bright)" }}>
              ${r.payout}
            </span>
          </div>
        </div>
      )}
    </ToolPanel>
  );
}

export function ToolsClient() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
      <EvCalc />
      <ClvCalc />
      <OddsConverter />
      <ParlayBuilder />
    </div>
  );
}
