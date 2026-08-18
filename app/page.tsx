"use client";

import { useEffect, useMemo, useState } from "react";

type View = "home" | "power" | "climate" | "tanks" | "events";
type Scenario = "normal" | "shore-loss" | "stale";
type ApiReading = { value: boolean | number | string | null; unit: string | null; health: string; observed_at: string };
type ApiState = { overall_health: string; collector_online: boolean; readings: Record<string, ApiReading> };

const DEMO_VALUES: Record<string, boolean | number | string> = {
  "power.battery.soc": 87, "power.battery.current": 42, "power.battery.power": 543, "power.battery.voltage": 13.1,
  "power.ac.connected": true, "power.ac.voltage": 121, "power.ac.current": 8.4, "power.ac.frequency": 60,
  "environment.dog.temperature": 73, "environment.coach.temperature": 74, "environment.fridge.temperature": 37, "environment.freezer.temperature": 4,
  "tank.fresh.percent": 74, "tank.gray.percent": 18, "tank.black.percent": 12, "tank.propane.percent": 68,
};

function useTelemetry() {
  const [state, setState] = useState<ApiState | null>(null);
  const [connection, setConnection] = useState<"online" | "demo" | "offline">("demo");
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_DASHBOARD_API_URL ?? "http://localhost:8080";
    const controller = new AbortController();
    let stream: EventSource | null = null;
    fetch(`${base}/api/state`, { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error("API unavailable");
      return response.json() as Promise<ApiState>;
    }).then(data => { setState(data); setConnection("online"); }).catch(() => setConnection("demo"));
    stream = new EventSource(`${base}/api/stream`);
    stream.addEventListener("state", event => {
      const payload = JSON.parse((event as MessageEvent).data) as ApiState | { state: ApiState };
      setState("state" in payload ? payload.state : payload);
      setConnection("online");
    });
    stream.onerror = () => setConnection(current => current === "online" ? "offline" : "demo");
    return () => { controller.abort(); stream?.close(); };
  }, []);
  const value = (path: string) => state?.readings[path]?.value ?? DEMO_VALUES[path];
  return { state, connection, value };
}

const NAV: { id: View; icon: string; label: string }[] = [
  { id: "home", icon: "⌂", label: "Home" },
  { id: "power", icon: "ϟ", label: "Power" },
  { id: "climate", icon: "°", label: "Climate" },
  { id: "tanks", icon: "▰", label: "Tanks" },
  { id: "events", icon: "!", label: "Events" },
];

const EVENT_ROWS = [
  ["2:42 PM", "Data synchronized", "RV Whisper", "normal"],
  ["2:31 PM", "Coach temperature +2°F", "74°F · stable", "normal"],
  ["2:16 PM", "Power-loss alert delivered", "RV Whisper", "warning"],
  ["2:14 PM", "Shore power lost", "Battery load changed to -28 A", "critical"],
  ["1:58 PM", "Shore power connected", "121 V · 60.0 Hz", "normal"],
] as const;

function StatusPill({ label, tone = "ok" }: { label: string; tone?: "ok" | "warn" | "off" }) {
  return <span className={`status-pill ${tone}`}><i aria-hidden="true" />{label}</span>;
}

function SectionHeading({ eyebrow, title, action }: { eyebrow: string; title: string; action?: string }) {
  return <div className="section-heading"><div><span>{eyebrow}</span><h2>{title}</h2></div>{action && <button type="button">{action} →</button>}</div>;
}

function HomeView({ scenario, go, value }: { scenario: Scenario; go: (view: View) => void; value: (path: string) => boolean | number | string | undefined }) {
  const fault = scenario === "shore-loss";
  const stale = scenario === "stale";
  const soc = fault ? 81 : Number(value("power.battery.soc"));
  const current = fault ? -31 : Number(value("power.battery.current"));
  const power = fault ? -401 : Number(value("power.battery.power"));
  const voltage = fault ? 12.8 : Number(value("power.battery.voltage"));
  const temperatures = {
    dog: fault ? 75 : Number(value("environment.dog.temperature")), coach: fault ? 76 : Number(value("environment.coach.temperature")),
    fridge: Number(value("environment.fridge.temperature")), freezer: Number(value("environment.freezer.temperature")),
  };

  return <>
    <section className={`hero-status ${fault ? "fault" : stale ? "stale" : ""}`}>
      <div className="status-emblem" aria-hidden="true">{fault ? "!" : stale ? "…" : "✓"}</div>
      <div className="hero-copy">
        <p>WHOLE-RV STATUS</p>
        <h1>{fault ? "Shore power lost" : stale ? "Data connection stale" : "Systems normal"}</h1>
        {fault && <small>3 minutes ago · Battery is carrying the RV</small>}
        {stale && <small>Last complete update 8 minutes ago</small>}
      </div>
      <span className="updated">{stale ? "Values held for context" : "Updated just now"}</span>
    </section>

    {fault && <section className="fault-summary" aria-label="Shore power fault summary">
      <div><span>Battery</span><strong>81%</strong><small>Currently okay</small></div>
      <div><span>Current</span><strong>-31 A</strong><small>Discharging</small></div>
      <div><span>Dog area</span><strong>75°F</strong><small>Stable</small></div>
      <div><span>Internet</span><strong>Online</strong><small>Remote alerts active</small></div>
      <button type="button" onClick={() => go("power")}>View power →</button>
    </section>}

    <div className="primary-grid">
      <article className={`metric-card battery-card ${stale ? "is-stale" : ""}`}>
        <div className="card-heading"><span>HOUSE BATTERY</span>{stale ? <StatusPill tone="off" label="Stale" /> : <i className="ok-dot" />}</div>
        <div className="battery-main">
          <div><strong>{soc}</strong><sup>%</sup><span className={`trend ${current < 0 ? "negative" : "positive"}`}>{current < 0 ? "↘ Discharging" : "↗ Charging"}</span></div>
          <div className={`battery-ring ${fault ? "fault-ring" : ""}`} style={{"--charge": `${soc}%`} as React.CSSProperties} aria-label={`Battery state of charge ${soc} percent`}><span>{soc}</span></div>
        </div>
        <div className="metric-row"><span><b>{current > 0 ? `+${current}` : current}</b> A</span><span><b>{power}</b> W</span><span><b>{voltage}</b> V</span></div>
      </article>

      <article className={`metric-card shore-card ${fault ? "has-fault" : stale ? "is-stale" : ""}`}>
        <div className="card-heading"><span>AC POWER</span>{fault ? <StatusPill tone="warn" label="Lost" /> : stale ? <StatusPill tone="off" label="Stale" /> : <i className="ok-dot" />}</div>
        <div className="shore-main"><div className="plug-icon">ϟ</div><div><strong>{fault ? "Offline" : "Shore"}</strong><span>{fault ? "Disconnected 3m ago" : "Connected"}</span></div></div>
        <div className="metric-row"><span><b>{fault ? "—" : value("power.ac.voltage")}</b> V</span><span><b>{fault ? "—" : value("power.ac.current")}</b> A</span><span><b>{fault ? "—" : Number(value("power.ac.frequency")).toFixed(1)}</b> Hz</span></div>
      </article>
    </div>

    <article className={`climate-card ${stale ? "is-stale" : ""}`}>
      <div className="card-heading"><span>CLIMATE</span><button type="button" onClick={() => go("climate")}>View details →</button></div>
      <div className="climate-grid">
        <div><span>Dog area</span><strong>{temperatures.dog}°</strong><small>Comfortable</small></div>
        <div><span>Coach</span><strong>{temperatures.coach}°</strong><small>Stable</small></div>
        <div><span>Refrigerator</span><strong>{temperatures.fridge}°</strong><small>Cold</small></div>
        <div><span>Freezer</span><strong>{temperatures.freezer}°</strong><small>Frozen</small></div>
      </div>
    </article>

    <div className="bottom-grid">
      <article className="tank-card">
        <div className="card-heading"><span>TANKS</span><button type="button" onClick={() => go("tanks")}>Details →</button></div>
        <div className="tank-list compact">
          {[["Fresh",Number(value("tank.fresh.percent"))],["Gray",Number(value("tank.gray.percent"))],["Black",Number(value("tank.black.percent"))],["Propane",Number(value("tank.propane.percent"))]].map(([name, level]) => <div key={name}><span>{name}</span><i><em style={{width:`${level}%`}} /></i><b>{level}%</b></div>)}
        </div>
      </article>
      <article className="connection-card">
        <div className="card-heading"><span>CONNECTIONS</span></div>
        <div className="connection-list">
          <div><span className="connection-icon">W</span><p><b>Internet</b><small>RV network</small></p><StatusPill label="Online" /></div>
          <div><span className="connection-icon">R</span><p><b>RV Whisper</b><small>{stale ? "Last sync 8 min ago" : "Last sync 12 sec ago"}</small></p><StatusPill tone={stale ? "off" : "ok"} label={stale ? "Stale" : "Online"} /></div>
        </div>
      </article>
    </div>
  </>;
}

function PowerView({ scenario, value }: { scenario: Scenario; value: (path: string) => boolean | number | string | undefined }) {
  const fault = scenario === "shore-loss";
  const soc = fault ? 81 : Number(value("power.battery.soc"));
  const current = fault ? -31 : Number(value("power.battery.current"));
  return <div className="detail-view">
    <SectionHeading eyebrow="ENERGY" title="Power system" action="Last 24 hours" />
    <section className="energy-flow">
      <div className="flow-node source unknown"><span>SOLAR</span><strong>Not available</strong><small>No source telemetry</small></div>
      <i className="flow-line line-top" />
      <div className={`flow-node battery ${fault ? "warning" : ""}`}><span>HOUSE BATTERY</span><strong>{soc}%</strong><small>{current > 0 ? `+${current} A · Charging` : `${current} A · Discharging`}</small></div>
      <i className="flow-line line-left" />
      <i className="flow-line line-right" />
      <div className={`flow-node ac ${fault ? "offline" : ""}`}><span>AC SOURCE</span><strong>{fault ? "Offline" : "Shore"}</strong><small>{fault ? "Lost 3 minutes ago" : "121 V · 8.4 A"}</small></div>
      <div className="flow-node load"><span>NET DC LOAD</span><strong>{Math.abs(Number(fault ? 401 : value("power.battery.power")))} W</strong><small>{fault ? "Battery supplying load" : "Battery net charge"}</small></div>
    </section>
    <p className="flow-note"><b>Source attribution is intentionally conservative.</b> Solar and alternator flows remain hidden until dedicated telemetry is available; net shunt current is never presented as a made-up source flow.</p>
    <div className="power-detail-grid">
      <article><span>Battery voltage</span><strong>{fault ? "12.8" : value("power.battery.voltage")}<small> V</small></strong><em>PowerMon-5S</em></article>
      <article><span>AC frequency</span><strong>{fault ? "—" : Number(value("power.ac.frequency")).toFixed(1)}<small> Hz</small></strong><em>Hughes Watchdog</em></article>
      <article><span>AC draw</span><strong>{fault ? "—" : "1.02"}<small> kW</small></strong><em>Hughes Watchdog</em></article>
    </div>
  </div>;
}

function ClimateView({ value }: { value: (path: string) => boolean | number | string | undefined }) {
  const readings = [["Dog area",`${value("environment.dog.temperature")}°`,"42%","Comfortable"],["Coach",`${value("environment.coach.temperature")}°`,"39%","Stable"],["Refrigerator",`${value("environment.fridge.temperature")}°`,"—","Cold"],["Freezer",`${value("environment.freezer.temperature")}°`,"—","Frozen"]];
  return <div className="detail-view"><SectionHeading eyebrow="ENVIRONMENT" title="Climate" action="72-hour history" />
    <div className="environment-grid">{readings.map(([name,temp,humidity,status], index) => <article key={name}>
      <div className="card-heading"><span>{name.toUpperCase()}</span><i className="ok-dot" /></div><strong>{temp}</strong><small>{humidity !== "—" ? `${humidity} humidity` : "Temperature probe"}</small>
      <div className="spark-bars" aria-label={`${name} recent trend`}>{[42,48,43,52,47,55,51,58,54,60,57, index < 2 ? 62 : 50].map((h,i)=><i key={i} style={{height:`${h}%`}} />)}</div><em>{status} · updated 12 sec ago</em>
    </article>)}</div>
    <section className="limits-card"><div><span>Safety focus</span><strong>Dog area</strong><small>RV Whisper remains responsible for high-temperature alerts.</small></div><div><span>Current limit</span><strong>80°F</strong><small>Warning threshold</small></div><div><span>Sensor health</span><strong>4 / 4</strong><small>All reporting</small></div></section>
  </div>;
}

function TanksView({ value }: { value: (path: string) => boolean | number | string | undefined }) {
  const tanks = [["Fresh water",Number(value("tank.fresh.percent")),"About 33 gal","fresh"],["Gray water",Number(value("tank.gray.percent")),"About 7 gal","gray"],["Black water",Number(value("tank.black.percent")),"About 4 gal","black"],["Propane",Number(value("tank.propane.percent")),"Sender reading","propane"]] as const;
  return <div className="detail-view"><SectionHeading eyebrow="RESOURCES" title="Tanks & propane" action="Sensor details" />
    <div className="tank-gauge-grid">{tanks.map(([name,value,detail,tone]) => <article key={name}>
      <div className={`vertical-gauge ${tone}`}><i style={{height:`${value}%`}} /></div><div><span>{name}</span><strong>{value}%</strong><small>{detail}</small><em>Normal</em></div>
    </article>)}</div>
    <p className="flow-note"><b>Demonstration values.</b> Tank cards are wired to the normalized model, but remain simulated until the SeeLeveL 709-BTP7 payload is captured and mapped.</p>
  </div>;
}

function EventsView() {
  return <div className="detail-view"><SectionHeading eyebrow="DIAGNOSTICS" title="Alerts & events" action="Filter" />
    <section className="event-card"><div className="event-date">TODAY · AUGUST 17</div>{EVENT_ROWS.map(([time,title,detail,tone]) => <div className="event-row" key={`${time}-${title}`}><time>{time}</time><i className={tone}/><div><strong>{title}</strong><small>{detail}</small></div></div>)}</section>
    <p className="flow-note"><b>Dashboard events are diagnostic context, not alarms.</b> RV Whisper remains the independent, authoritative alerting system.</p>
  </div>;
}

export default function Dashboard() {
  const [view, setView] = useState<View>("home");
  const [scenario, setScenario] = useState<Scenario>("normal");
  const [clock, setClock] = useState(() => new Date());
  const telemetry = useTelemetry();
  useEffect(() => { const timer = window.setInterval(() => setClock(new Date()), 30_000); return () => window.clearInterval(timer); }, []);
  const clockLabel = useMemo(() => clock.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }), [clock]);

  return <main className={`dashboard-shell scenario-${scenario}`}>
    <header className="topbar">
      <button className="brand-lockup" type="button" onClick={() => setView("home")} aria-label="Go to home dashboard"><span className="brand-mark">MW</span><span><strong>Minnie Winnie</strong><small>Unified systems</small></span></button>
      <div className="topbar-right">
        <label className="scenario-control"><span>Preview state</span><select value={scenario} onChange={event => setScenario(event.target.value as Scenario)} aria-label="Preview dashboard state"><option value="normal">Normal</option><option value="shore-loss">Shore power lost</option><option value="stale">Stale data</option></select></label>
        <StatusPill tone={scenario === "stale" || telemetry.connection === "offline" ? "off" : scenario === "shore-loss" ? "warn" : "ok"} label={scenario === "stale" ? "Stale" : scenario === "shore-loss" ? "Attention" : telemetry.connection === "online" ? "Live" : telemetry.connection === "offline" ? "Offline" : "Demo"} />
        <span className="clock">{clockLabel}</span>
      </div>
    </header>
    <nav className="rail" aria-label="Dashboard sections">{NAV.map(item => <button key={item.id} className={`rail-item ${view === item.id ? "active" : ""}`} type="button" onClick={() => setView(item.id)}><b>{item.icon}</b><span>{item.label}</span>{item.id === "events" && scenario === "shore-loss" && <i>1</i>}</button>)}</nav>
    <section className="content" aria-live="polite">
      {view === "home" && <HomeView scenario={scenario} go={setView} value={telemetry.value} />}
      {view === "power" && <PowerView scenario={scenario} value={telemetry.value} />}
      {view === "climate" && <ClimateView value={telemetry.value} />}
      {view === "tanks" && <TanksView value={telemetry.value} />}
      {view === "events" && <EventsView />}
      <footer><span>Dashboard visualizes current state</span><b>RV Whisper alerts operate independently</b></footer>
    </section>
  </main>;
}
