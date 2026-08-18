"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";

type View = "home" | "battery" | "ac-power" | "climate" | "tanks" | "events";
type Scenario = "normal" | "shore-loss" | "stale";
type Connection = "online" | "demo" | "offline";
type ApiReading = { value: boolean | number | string | null; unit: string | null; health: string; observed_at: string; age_seconds?: number; source?: string };
type ApiState = { mode?: "demo" | "live"; overall_health: string; collector_online: boolean; generated_at?: string; readings: Record<string, ApiReading> };
type RangeSummary = { min: number; max: number; unit: string | null; samples: number; latest_at: string };
type ApiEvent = { id?: number; event_type: string; severity: string; title: string; detail?: string; occurred_at: string };

const DEMO_VALUES: Record<string, boolean | number | string> = {
  "power.battery.soc":87, "power.battery.current":42, "power.battery.power":543, "power.battery.voltage":13.1,
  "power.ac.connected":true, "power.ac.voltage":121, "power.ac.current":8.4, "power.ac.frequency":60,
  "environment.dog.temperature":73, "environment.coach.temperature":74, "environment.fridge.temperature":37, "environment.freezer.temperature":4,
  "tank.fresh.percent":74, "tank.gray.percent":18, "tank.black.percent":12, "tank.propane.percent":68,
};

const NAV: { id: Exclude<View,"home">; icon: string; glyph?: string; label: string }[] = [
  {id:"battery",icon:"battery",label:"House Battery"}, {id:"ac-power",icon:"ac",glyph:"ϟ",label:"AC Power"},
  {id:"climate",icon:"thermometer",label:"Climate"}, {id:"tanks",icon:"propane",label:"Tanks"}, {id:"events",icon:"event",glyph:"!",label:"Events"},
];

const DEMO_EVENTS: ApiEvent[] = [
  {event_type:"synchronization",severity:"normal",title:"Data synchronized",detail:"RV Whisper · preview data",occurred_at:"2026-08-17T14:42:00-05:00"},
  {event_type:"temperature",severity:"normal",title:"Coach temperature changed",detail:"74°F · stable · preview data",occurred_at:"2026-08-17T14:31:00-05:00"},
  {event_type:"alert",severity:"warning",title:"Power-loss alert delivered",detail:"RV Whisper · preview data",occurred_at:"2026-08-17T14:16:00-05:00"},
  {event_type:"power",severity:"critical",title:"Shore power lost",detail:"Battery load changed to -28 A · preview data",occurred_at:"2026-08-17T14:14:00-05:00"},
  {event_type:"power",severity:"normal",title:"Shore power connected",detail:"121 V · 60.0 Hz · preview data",occurred_at:"2026-08-17T13:58:00-05:00"},
];

function useTelemetry() {
  const [state,setState] = useState<ApiState|null>(null);
  const [connection,setConnection] = useState<Connection>("demo");
  const [ranges,setRanges] = useState<Record<string,RangeSummary>>({});
  const [events,setEvents] = useState<ApiEvent[]>([]);
  useEffect(()=>{
    const base=process.env.NEXT_PUBLIC_DASHBOARD_API_URL??"http://localhost:8080";
    const controller=new AbortController(); let stream:EventSource|null=null;
    const loadDiagnostics=()=>{
      fetch(`${base}/api/history-summary?hours=24`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<{readings:Record<string,RangeSummary>}>:Promise.reject()).then(d=>setRanges(d.readings??{})).catch(()=>undefined);
      fetch(`${base}/api/events?limit=100`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<ApiEvent[]>:Promise.reject()).then(setEvents).catch(()=>undefined);
    };
    fetch(`${base}/api/state`,{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error("API unavailable");return r.json() as Promise<ApiState>}).then(d=>{setState(d);setConnection(d.mode==="demo"?"demo":"online")}).catch(()=>setConnection("demo"));
    loadDiagnostics(); const diagnosticsTimer=window.setInterval(loadDiagnostics,300_000);
    stream=new EventSource(`${base}/api/stream`);
    stream.addEventListener("state",event=>{const payload=JSON.parse((event as MessageEvent).data) as ApiState|{state:ApiState};const next="state" in payload?payload.state:payload;setState(next);setConnection(next.mode==="demo"?"demo":"online")});
    stream.onerror=()=>setConnection(c=>c==="online"?"offline":"demo");
    return()=>{controller.abort();window.clearInterval(diagnosticsTimer);stream?.close()};
  },[]);
  const reading=(path:string):ApiReading|undefined=>state?state.readings[path]:(DEMO_VALUES[path]===undefined?undefined:{value:DEMO_VALUES[path],unit:null,health:"demo",observed_at:"",age_seconds:0,source:"Demo preview"});
  const value=(path:string)=>reading(path)?.value??undefined;
  return {state,connection,reading,value,ranges,events};
}

function StatusPill({label,tone="ok"}:{label:string;tone?:"ok"|"warn"|"off"}) { return <span className={`status-pill ${tone}`}><i aria-hidden="true"/>{label}</span> }
function SectionHeading({eyebrow,title,action}:{eyebrow:string;title:string;action?:string}) { return <div className="section-heading"><div><span>{eyebrow}</span><h2>{title}</h2></div>{action&&<small className="detail-window">{action}</small>}</div> }
const numberValue=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?value:Number(value)||0;
function displayNumber(value:unknown,digits=1){if(value===null||value===undefined||value==="")return"—";const n=Number(value);return Number.isFinite(n)?(Number.isInteger(n)?String(n):n.toFixed(digits)):String(value)}
function formatAge(seconds?:number){if(seconds===undefined)return"Age unavailable";if(seconds<60)return`${seconds} sec old`;if(seconds<3600)return`${Math.floor(seconds/60)} min old`;return`${Math.floor(seconds/3600)} hr old`}
function formatTimestamp(timestamp?:string){if(!timestamp)return"Preview value";const date=new Date(timestamp);return Number.isNaN(date.getTime())?"Time unavailable":date.toLocaleString([],{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"})}
function HealthBadge({health}:{health?:string}){const value=health||"unknown";const tone=["normal","demo"].includes(value)?"ok":["warning","stale"].includes(value)?"warn":"off";return <StatusPill label={value} tone={tone}/>}
function ReadingMeta({reading}:{reading?:ApiReading}){return <dl className="reading-meta"><div><dt>Source</dt><dd>{reading?.source||"Not reported"}</dd></div><div><dt>Observed</dt><dd>{formatTimestamp(reading?.observed_at)}</dd></div><div><dt>Freshness</dt><dd>{reading?.health==="demo"?"Preview data":formatAge(reading?.age_seconds)}</dd></div></dl>}
function RangeStrip({summary,unit}:{summary?:RangeSummary;unit?:string|null}){const u=summary?.unit||unit||"";return <div className="range-strip"><span>LAST 24 HOURS</span>{summary?<><div><small>MIN</small><b>{displayNumber(summary.min)}{u}</b></div><div><small>MAX</small><b>{displayNumber(summary.max)}{u}</b></div><div><small>SAMPLES</small><b>{summary.samples}</b></div></>:<p>History will appear after retained live samples are available.</p>}</div>}
function DiagnosticMetric({label,path,reading,summary,fallbackUnit}:{label:string;path:string;reading?:ApiReading;summary?:RangeSummary;fallbackUnit?:string}){const unit=reading?.unit||fallbackUnit||"";return <article className="diagnostic-card" data-path={path}><div className="diagnostic-card-head"><span>{label}</span><HealthBadge health={reading?.health}/></div><strong className="diagnostic-value">{displayNumber(reading?.value)}<small>{unit}</small></strong><RangeStrip summary={summary} unit={unit}/><ReadingMeta reading={reading}/><code>{path}</code></article>}

function HomeView({scenario,connection,value,go}:{scenario:Scenario;connection:Connection;value:(path:string)=>boolean|number|string|undefined;go:(view:View)=>void}){
  const fault=scenario==="shore-loss", stale=scenario==="stale";
  const soc=fault?81:numberValue(value("power.battery.soc")), current=fault?-31:numberValue(value("power.battery.current")), acCurrent=fault?null:numberValue(value("power.ac.current"));
  const climate=[["Dog area",fault?75:numberValue(value("environment.dog.temperature"))],["Coach",fault?76:numberValue(value("environment.coach.temperature"))],["Refrigerator",numberValue(value("environment.fridge.temperature"))],["Freezer",numberValue(value("environment.freezer.temperature"))]] as const;
  const ri=value("network.internet.online"), rr=value("network.rvwhisper.online");
  const internetOnline=typeof ri==="boolean"?ri:connection!=="offline", rvWhisperOnline=!stale&&(typeof rr==="boolean"?rr:connection!=="offline");
  const tanks=[["Fresh",numberValue(value("tank.fresh.percent"))],["Gray",numberValue(value("tank.gray.percent"))],["Black",numberValue(value("tank.black.percent"))],["Propane",numberValue(value("tank.propane.percent"))]] as const;
  return <>
    <section className={`hero-status ${fault?"fault":stale?"stale":""}`}><div className="status-emblem" aria-hidden="true">{fault?"!":stale?"…":"✓"}</div><div className="hero-copy"><p>WHOLE-RV STATUS</p><h1>{fault?"Shore power lost":stale?"Data connection stale":"Systems normal"}</h1>{fault&&<small>3 minutes ago · Battery is carrying the RV</small>}{stale&&<small>Last complete update 8 minutes ago</small>}</div><div className="hero-connectivity" aria-label="Connectivity status"><div className={`connectivity-indicator ${internetOnline?"online":"offline"}`} title={`Internet ${internetOnline?"online":"offline"}`}><span aria-hidden="true" className="signal-icon"><i/><i/><i/></span><small>Internet</small>{!internetOnline&&<b aria-hidden="true">×</b>}</div><div className={`connectivity-indicator ${rvWhisperOnline?"online":"offline"}`} title={`RV Whisper ${rvWhisperOnline?"synchronized":"offline"}`}><span aria-hidden="true" className="sync-icon">↻</span><small>RV Sync</small>{!rvWhisperOnline&&<b aria-hidden="true">×</b>}</div></div></section>
    <div className="home-quadrants">
      <button type="button" onClick={()=>go("battery")} className={`home-quadrant battery-quadrant ${stale?"is-stale":""}`} aria-label="Open House Battery details"><div className="card-heading"><span>HOUSE BATTERY</span>{stale?<StatusPill tone="off" label="Stale"/>:<i className="ok-dot"/>}</div><div className="quadrant-power-layout"><div className={`battery-ring ${fault?"fault-ring":""}`} style={{"--charge":`${soc}%`} as CSSProperties}><span><b>{soc}</b><small>%</small></span></div><div className="quadrant-power-copy"><small>STATE</small><strong className={current<0?"negative":"positive"}>{current<0?"Discharging":"Charging"}</strong><div className="quadrant-metric"><b>{current>0?`+${current}`:current}</b><span>A</span><small>Battery current</small></div></div></div></button>
      <button type="button" onClick={()=>go("ac-power")} className={`home-quadrant ac-quadrant ${fault?"has-fault":stale?"is-stale":""}`} aria-label="Open AC Power details"><div className="card-heading"><span>AC POWER</span>{fault?<StatusPill tone="warn" label="Lost"/>:stale?<StatusPill tone="off" label="Stale"/>:<i className="ok-dot"/>}</div><div className="quadrant-power-layout"><div className={`ac-power-orb ${fault?"offline":""}`} aria-hidden="true">ϟ</div><div className="quadrant-power-copy"><small>SHORE POWER</small><strong className={fault?"negative":"positive"}>{fault?"Disconnected":"Connected"}</strong><div className="quadrant-metric"><b>{acCurrent??"—"}</b><span>A</span><small>AC current</small></div></div></div></button>
      <button type="button" onClick={()=>go("climate")} className={`home-quadrant climate-quadrant ${stale?"is-stale":""}`} aria-label="Open Climate details"><div className="card-heading"><span>CLIMATE</span><i className="ok-dot"/></div><div className="climate-simple-grid">{climate.map(([label,n])=><div key={label}><span>{label}</span><strong>{n}°</strong></div>)}</div></button>
      <button type="button" onClick={()=>go("tanks")} className="home-quadrant tanks-quadrant" aria-label="Open Tanks details"><div className="card-heading"><span>TANKS</span><i className="ok-dot"/></div><div className="tank-columns">{tanks.map(([name,level])=><div className="tank-column" key={name}><span>{name}</span><div className="tank-bucket"><i style={{height:`${level}%`}}/><b>{level}%</b></div></div>)}</div></button>
    </div>
  </>;
}

type DetailProps={scenario:Scenario;reading:(path:string)=>ApiReading|undefined;ranges:Record<string,RangeSummary>};

function BatteryView({scenario,reading,ranges}:DetailProps){
  const fault=scenario==="shore-loss", rawSoc=reading("power.battery.soc"), rawCurrent=reading("power.battery.current");
  const soc=fault?81:numberValue(rawSoc?.value), current=fault?-31:numberValue(rawCurrent?.value);
  const currentReading=fault?{...rawCurrent,value:current,unit:"A",health:"warning"} as ApiReading:rawCurrent;
  const socReading=fault?{...rawSoc,value:soc,unit:"%",health:"warning"} as ApiReading:rawSoc;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENERGY · DIAGNOSTICS" title="House Battery" action="Current readings + retained 24-hour range"/>
    <section className={`detail-hero battery-detail-hero ${fault?"warning":""}`}><div className="battery-ring detail-ring" style={{"--charge":`${soc}%`} as CSSProperties}><span><b>{soc}</b><small>%</small></span></div><div><span>STATE OF CHARGE</span><h3 className={current<0?"negative":"positive"}>{current<0?"Discharging":"Charging"}</h3><p>{current>0?"+":""}{current} A battery current</p></div><HealthBadge health={fault?"warning":rawSoc?.health}/></section>
    <div className="diagnostic-grid four-up"><DiagnosticMetric label="State of charge" path="power.battery.soc" reading={socReading} summary={ranges["power.battery.soc"]} fallbackUnit="%"/><DiagnosticMetric label="Battery current" path="power.battery.current" reading={currentReading} summary={ranges["power.battery.current"]} fallbackUnit="A"/><DiagnosticMetric label="Battery power" path="power.battery.power" reading={reading("power.battery.power")} summary={ranges["power.battery.power"]} fallbackUnit="W"/><DiagnosticMetric label="Battery voltage" path="power.battery.voltage" reading={reading("power.battery.voltage")} summary={ranges["power.battery.voltage"]} fallbackUnit="V"/></div>
    <p className="flow-note"><b>Interpretation:</b> positive shunt current is shown as charging and negative current as discharging. Source-specific solar or alternator flow is omitted until a dedicated mapped reading exists.</p>
  </div>;
}

function AcPowerView({scenario,reading,ranges}:DetailProps){
  const forcedDisconnected=scenario==="shore-loss", connectedReading=reading("power.ac.connected"), connected=!forcedDisconnected&&connectedReading?.value===true;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENERGY · DIAGNOSTICS" title="AC Power" action="Current readings + retained 24-hour range"/>
    <section className={`detail-hero ac-detail-hero ${connected?"":"warning"}`}><div className={`ac-power-orb ${connected?"":"offline"}`} aria-hidden="true">ϟ</div><div><span>SHORE POWER</span><h3 className={connected?"positive":"negative"}>{connected?"Connected":"Disconnected"}</h3><p>{connected?`${displayNumber(reading("power.ac.current")?.value)} A presently reported`:"No AC source presently reported"}</p></div><HealthBadge health={forcedDisconnected?"warning":connectedReading?.health}/></section>
    <div className="diagnostic-grid four-up"><DiagnosticMetric label="AC voltage" path="power.ac.voltage" reading={forcedDisconnected?undefined:reading("power.ac.voltage")} summary={ranges["power.ac.voltage"]} fallbackUnit="V"/><DiagnosticMetric label="AC current" path="power.ac.current" reading={forcedDisconnected?undefined:reading("power.ac.current")} summary={ranges["power.ac.current"]} fallbackUnit="A"/><DiagnosticMetric label="AC frequency" path="power.ac.frequency" reading={forcedDisconnected?undefined:reading("power.ac.frequency")} summary={ranges["power.ac.frequency"]} fallbackUnit="Hz"/><DiagnosticMetric label="AC power" path="power.ac.power" reading={forcedDisconnected?undefined:reading("power.ac.power")} summary={ranges["power.ac.power"]} fallbackUnit="W"/></div>
    <p className="flow-note"><b>AC power is not estimated from volts × amps.</b> The card stays “Not reported” unless RV Whisper supplies a mapped power value, avoiding a misleading real-power calculation.</p>
  </div>;
}

function ClimateView({reading,ranges}:DetailProps){
  const sensors=[["Dog area","dog"],["Coach","coach"],["Refrigerator","fridge"],["Freezer","freezer"]] as const;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENVIRONMENT · DIAGNOSTICS" title="Climate" action="Current readings + retained 24-hour range"/>
    <div className="diagnostic-grid climate-detail-grid">{sensors.map(([label,key])=>{const path=`environment.${key}.temperature`,humidity=reading(`environment.${key}.humidity`),item=reading(path);return <article className="diagnostic-card climate-detail-card" key={key}><div className="diagnostic-card-head"><span>{label}</span><HealthBadge health={item?.health}/></div><strong className="diagnostic-value">{displayNumber(item?.value)}<small>{item?.unit||"°F"}</small></strong><div className="secondary-reading"><span>Humidity</span><b>{humidity?`${displayNumber(humidity.value)}${humidity.unit||"%"}`:"Not reported"}</b></div><RangeStrip summary={ranges[path]} unit={item?.unit||"°F"}/><ReadingMeta reading={item}/><code>{path}</code></article>})}</div>
    <p className="flow-note"><b>Only mapped measurements are shown.</b> Humidity appears automatically when RV Whisper reports and maps it; decorative trend bars and invented humidity values have been removed.</p>
  </div>;
}

function TanksView({reading,ranges}:DetailProps){
  const tanks=[["Fresh water","fresh","fresh"],["Gray water","gray","gray"],["Black water","black","black"],["Propane","propane","propane"]] as const;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="RESOURCES · DIAGNOSTICS" title="Tanks" action="Current readings + retained 24-hour range"/>
    <div className="diagnostic-grid tank-detail-grid">{tanks.map(([label,key,tone])=>{const path=`tank.${key}.percent`,item=reading(path),level=numberValue(item?.value);return <article className="diagnostic-card tank-detail-card" key={key}><div className="diagnostic-card-head"><span>{label}</span><HealthBadge health={item?.health}/></div><div className="tank-detail-reading"><div className={`vertical-gauge ${tone}`}><i style={{height:`${level}%`}}/></div><strong>{displayNumber(item?.value)}<small>{item?.unit||"%"}</small></strong></div><RangeStrip summary={ranges[path]} unit={item?.unit||"%"}/><ReadingMeta reading={item}/><code>{path}</code></article>})}</div>
    <p className="flow-note"><b>Volume estimates are intentionally omitted.</b> Gallons can only be calculated once each tank’s usable capacity and calibrated sender behavior are configured.</p>
  </div>;
}

function EventsView({events,connection}:{events:ApiEvent[];connection:Connection}){
  const rows=events.length?events:DEMO_EVENTS;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="DIAGNOSTICS" title="Events" action={`${rows.length} most recent records`}/><section className="event-card diagnostic-events"><div className="event-date">{events.length?"RV WHISPER / COLLECTOR EVENT LOG":"PREVIEW EVENT LOG · LIVE EVENTS NOT YET AVAILABLE"}</div>{rows.map((event,index)=><div className="event-row rich-event-row" key={event.id??`${event.occurred_at}-${index}`}><time dateTime={event.occurred_at}>{formatTimestamp(event.occurred_at)}</time><i className={event.severity}/><div><strong>{event.title}</strong><small>{event.detail||"No additional detail"}</small></div><span>{event.event_type||"event"}</span><HealthBadge health={event.severity}/></div>)}</section><p className="flow-note"><b>Connection: {connection}.</b> These records provide diagnostic context. RV Whisper remains the independent, authoritative alerting system.</p></div>;
}

export default function Dashboard(){
  const [view,setView]=useState<View>("home"),[scenario,setScenario]=useState<Scenario>("normal"),[clock,setClock]=useState(()=>new Date());
  const telemetry=useTelemetry(); useEffect(()=>{const timer=window.setInterval(()=>setClock(new Date()),30_000);return()=>window.clearInterval(timer)},[]);
  const clockLabel=useMemo(()=>clock.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}),[clock]);
  const detailProps={scenario,reading:telemetry.reading,ranges:telemetry.ranges};
  return <main className={`dashboard-shell scenario-${scenario}`}><header className="topbar"><button className="brand-lockup" type="button" onClick={()=>setView("home")} aria-label="Go to home dashboard"><span className="brand-mark">MW</span><span><strong>Minnie Winnie</strong><small>Unified systems</small></span></button><div className="topbar-right"><label className="scenario-control"><span>Preview state</span><select value={scenario} onChange={event=>setScenario(event.target.value as Scenario)} aria-label="Preview dashboard state"><option value="normal">Normal</option><option value="shore-loss">Shore power lost</option><option value="stale">Stale data</option></select></label><StatusPill tone={scenario==="stale"||telemetry.connection==="offline"?"off":scenario==="shore-loss"?"warn":"ok"} label={scenario==="stale"?"Stale":scenario==="shore-loss"?"Attention":telemetry.connection==="online"?"Live":telemetry.connection==="offline"?"Offline":"Demo"}/><span className="clock">{clockLabel}</span></div></header>
    <nav className="rail" aria-label="Dashboard sections">{NAV.map(item=><button key={item.id} className={`rail-item ${view===item.id?"active":""}`} type="button" onClick={()=>setView(item.id)}><b className={`rail-symbol rail-${item.icon}`} aria-hidden="true">{item.glyph}</b><span>{item.label}</span>{item.id==="events"&&scenario==="shore-loss"&&<i>1</i>}</button>)}</nav>
    <section className="content" aria-live="polite">{view==="home"&&<HomeView scenario={scenario} connection={telemetry.connection} value={telemetry.value} go={setView}/>} {view==="battery"&&<BatteryView {...detailProps}/>} {view==="ac-power"&&<AcPowerView {...detailProps}/>} {view==="climate"&&<ClimateView {...detailProps}/>} {view==="tanks"&&<TanksView {...detailProps}/>} {view==="events"&&<EventsView events={telemetry.events} connection={telemetry.connection}/>}<footer><span>Dashboard visualizes current state</span><b>RV Whisper alerts operate independently</b></footer></section>
  </main>;
}
