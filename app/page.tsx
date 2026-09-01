"use client";

import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";

type View = "home" | "battery" | "ac-power" | "climate" | "tanks" | "events";
type Scenario = "normal" | "shore-loss" | "stale";
type Connection = "online" | "demo" | "offline";
type ApiReading = { value: boolean | number | string | null; unit: string | null; health: string; observed_at: string; age_seconds?: number; source?: string };
type ApiState = { mode?: "demo" | "live"; overall_health: string; collector_online: boolean; generated_at?: string; readings: Record<string, ApiReading> };
type RangeSummary = { min: number; max: number; unit: string | null; samples: number; latest_at: string };
type ApiEvent = { id?: number; event_type: string; severity: string; title: string; detail?: string; occurred_at: string };
type ApiAlert = { id: string; title: string; acknowledged: boolean; created_at: string | null; last_seen_at: string };
type ProfileItem = { id:string; label:string; path:string; home:boolean; tone?:"fresh"|"gray"|"black"|"propane" };
type ProfileSection = { enabled:boolean; label:string };
type DashboardProfile = {
  schema_version:number;
  vehicle:{name:string;subtitle:string;monogram:string};
  sections:{battery:ProfileSection;ac_power:ProfileSection;climate:ProfileSection&{items:ProfileItem[]};tanks:ProfileSection&{items:ProfileItem[]};events:ProfileSection};
  capabilities?:{alert_acknowledgement?:boolean};
};

const DEFAULT_PROFILE: DashboardProfile = {
  schema_version:1,
  vehicle:{name:"Minnie Winnie",subtitle:"Unified systems",monogram:"MW"},
  sections:{
    battery:{enabled:true,label:"House Battery"},ac_power:{enabled:true,label:"AC Power"},
    climate:{enabled:true,label:"Climate",items:[
      {id:"front-room",label:"Front room",path:"environment.front_room.temperature",home:true},
      {id:"bedroom",label:"Bedroom",path:"environment.bedroom.temperature",home:true},
      {id:"refrigerator",label:"Refrigerator",path:"environment.fridge.temperature",home:true},
      {id:"freezer",label:"Freezer",path:"environment.freezer.temperature",home:true},
    ]},
    tanks:{enabled:true,label:"Tanks",items:[
      {id:"fresh",label:"Fresh",path:"tank.fresh.percent",tone:"fresh",home:true},
      {id:"gray",label:"Gray",path:"tank.gray.percent",tone:"gray",home:true},
      {id:"black",label:"Black",path:"tank.black.percent",tone:"black",home:true},
      {id:"propane",label:"Propane",path:"tank.propane.percent",tone:"propane",home:true},
    ]},events:{enabled:true,label:"Events"},
  },
};

const DEMO_VALUES: Record<string, boolean | number | string> = {
  "power.battery.soc":87, "power.battery.current":42, "power.battery.power":543, "power.battery.voltage":13.1,
  "power.ac.connected":true, "power.ac.voltage":121, "power.ac.current":8.4, "power.ac.frequency":60,
  "environment.front_room.temperature":73, "environment.bedroom.temperature":74, "environment.fridge.temperature":37, "environment.freezer.temperature":4,
  "tank.fresh.percent":74, "tank.gray.percent":18, "tank.black.percent":12, "tank.propane.percent":68,
  "network.internet.online":true, "network.rvwhisper.online":true,
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
  const [alerts,setAlerts] = useState<ApiAlert[]>([]);
  const [profile,setProfile] = useState<DashboardProfile>(DEFAULT_PROFILE);
  useEffect(()=>{
    const base=process.env.NEXT_PUBLIC_DASHBOARD_API_URL??"http://localhost:8080";
    const controller=new AbortController(); let stream:EventSource|null=null;
    const loadDiagnostics=()=>{
      fetch(`${base}/api/history-summary?hours=24`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<{readings:Record<string,RangeSummary>}>:Promise.reject()).then(d=>setRanges(d.readings??{})).catch(()=>undefined);
      fetch(`${base}/api/events?limit=100`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<ApiEvent[]>:Promise.reject()).then(setEvents).catch(()=>undefined);
    };
    const loadAlerts=()=>fetch(`${base}/api/alerts`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<{active:ApiAlert[]}>:Promise.reject()).then(d=>setAlerts(d.active??[])).catch(()=>undefined);
    fetch(`${base}/api/config`,{signal:controller.signal}).then(r=>r.ok?r.json() as Promise<DashboardProfile>:Promise.reject()).then(setProfile).catch(()=>undefined);
    fetch(`${base}/api/state`,{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error("API unavailable");return r.json() as Promise<ApiState>}).then(d=>{setState(d);setConnection(d.mode==="demo"?"demo":"online")}).catch(()=>setConnection("demo"));
    loadDiagnostics(); loadAlerts(); const diagnosticsTimer=window.setInterval(loadDiagnostics,300_000),alertsTimer=window.setInterval(loadAlerts,60_000);
    stream=new EventSource(`${base}/api/stream`);
    stream.addEventListener("state",event=>{const payload=JSON.parse((event as MessageEvent).data) as ApiState|{state:ApiState};const next="state" in payload?payload.state:payload;setState(next);setConnection(next.mode==="demo"?"demo":"online")});
    stream.addEventListener("alerts",event=>{const payload=JSON.parse((event as MessageEvent).data) as {alerts:ApiAlert[]};setAlerts(payload.alerts??[]);loadDiagnostics()});
    stream.onerror=()=>setConnection(c=>c==="online"?"offline":"demo");
    return()=>{controller.abort();window.clearInterval(diagnosticsTimer);window.clearInterval(alertsTimer);stream?.close()};
  },[]);
  const reading=(path:string):ApiReading|undefined=>state?state.readings[path]:(DEMO_VALUES[path]===undefined?undefined:{value:DEMO_VALUES[path],unit:null,health:"demo",observed_at:"",age_seconds:0,source:"Demo preview"});
  const value=(path:string)=>reading(path)?.value??undefined;
  const acknowledgeAlert=async(alertId:string,pin:string)=>{
    const base=process.env.NEXT_PUBLIC_DASHBOARD_API_URL??"http://localhost:8080";
    const response=await fetch(`${base}/api/alerts/${encodeURIComponent(alertId)}/acknowledge`,{
      method:"POST",
      headers:{"Content-Type":"application/json","X-Dashboard-Operator-PIN":pin},
      body:JSON.stringify({confirmation:"stop-repeat-notifications"}),
    });
    const payload=await response.json().catch(()=>({detail:"RV Whisper acknowledgement response was unavailable"})) as {status?:string;detail?:string};
    if(!response.ok)throw new Error(payload.detail||"RV Whisper did not confirm acknowledgement");
    const [alertPayload,eventPayload]=await Promise.all([
      fetch(`${base}/api/alerts`).then(r=>r.json() as Promise<{active:ApiAlert[]}>),
      fetch(`${base}/api/events?limit=100`).then(r=>r.json() as Promise<ApiEvent[]>),
    ]);
    setAlerts(alertPayload.active??[]);setEvents(eventPayload);
    return payload.status||"confirmed";
  };
  return {state,connection,reading,value,ranges,events,alerts,profile,acknowledgeAlert};
}

function StatusPill({label,tone="ok"}:{label:string;tone?:"ok"|"warn"|"off"}) { return <span className={`status-pill ${tone}`}><i aria-hidden="true"/>{label}</span> }
function SectionHeading({eyebrow,title,action}:{eyebrow:string;title:string;action?:string}) { return <div className="section-heading"><div><span>{eyebrow}</span><h2>{title}</h2></div>{action&&<small className="detail-window">{action}</small>}</div> }
const numberValue=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?value:Number(value)||0;
const optionalNumber=(value:unknown):number|null=>{if(value===null||value===undefined||value==="")return null;const n=Number(value);return Number.isFinite(n)?n:null};
function displayNumber(value:unknown,digits=1){if(value===null||value===undefined||value==="")return"—";const n=Number(value);return Number.isFinite(n)?(Number.isInteger(n)?String(n):n.toFixed(digits)):String(value)}
function formatAge(seconds?:number){if(seconds===undefined)return"Age unavailable";if(seconds<60)return`${seconds} sec old`;if(seconds<3600)return`${Math.floor(seconds/60)} min old`;return`${Math.floor(seconds/3600)} hr old`}
function formatTimestamp(timestamp?:string){if(!timestamp)return"Preview value";const date=new Date(timestamp);return Number.isNaN(date.getTime())?"Time unavailable":date.toLocaleString([],{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"})}
function HealthBadge({health}:{health?:string}){const value=health||"unknown";const tone=["normal","demo"].includes(value)?"ok":["warning","stale"].includes(value)?"warn":"off";return <StatusPill label={value} tone={tone}/>}
function ReadingMeta({reading}:{reading?:ApiReading}){return <dl className="reading-meta"><div><dt>Source</dt><dd>{reading?.source||"Not reported"}</dd></div><div><dt>Observed</dt><dd>{formatTimestamp(reading?.observed_at)}</dd></div><div><dt>Freshness</dt><dd>{reading?.health==="demo"?"Preview data":formatAge(reading?.age_seconds)}</dd></div></dl>}
function RangeStrip({summary,unit}:{summary?:RangeSummary;unit?:string|null}){const u=summary?.unit||unit||"";return <div className="range-strip"><span>LAST 24 HOURS</span>{summary?<><div><small>MIN</small><b>{displayNumber(summary.min)}{u}</b></div><div><small>MAX</small><b>{displayNumber(summary.max)}{u}</b></div><div><small>SAMPLES</small><b>{summary.samples}</b></div></>:<p>History will appear after retained live samples are available.</p>}</div>}
function DiagnosticMetric({label,path,reading,summary,fallbackUnit}:{label:string;path:string;reading?:ApiReading;summary?:RangeSummary;fallbackUnit?:string}){const unit=reading?.unit||fallbackUnit||"";return <article className="diagnostic-card" data-path={path}><div className="diagnostic-card-head"><span>{label}</span><HealthBadge health={reading?.health}/></div><strong className="diagnostic-value">{displayNumber(reading?.value)}<small>{unit}</small></strong><RangeStrip summary={summary} unit={unit}/><ReadingMeta reading={reading}/><code>{path}</code></article>}

function HomeView({scenario,connection,value,alerts,profile,go}:{scenario:Scenario;connection:Connection;value:(path:string)=>boolean|number|string|undefined;alerts:ApiAlert[];profile:DashboardProfile;go:(view:View)=>void}){
  const fault=scenario==="shore-loss", stale=scenario==="stale";
  const soc=fault?81:optionalNumber(value("power.battery.soc")), current=fault?-31:optionalNumber(value("power.battery.current")), acCurrent=fault?null:optionalNumber(value("power.ac.current"));
  const batteryReported=soc!==null||current!==null, acConnectedValue=fault?false:value("power.ac.connected"), acReported=typeof acConnectedValue==="boolean";
  const climate=profile.sections.climate.items.filter(item=>item.home).slice(0,4).map((item,index)=>[item.label,fault&&index<2?75+index:optionalNumber(value(item.path))] as const);
  const ri=value("network.internet.online"), rr=value("network.rvwhisper.online");
  const internetOnline=typeof ri==="boolean"?ri:null, rvWhisperOnline=!stale&&(typeof rr==="boolean"?rr:connection!=="offline");
  const tanks=profile.sections.tanks.items.filter(item=>item.home).slice(0,4).map(item=>[item.label,optionalNumber(value(item.path))] as const);
  const partial=connection==="online"&&(!batteryReported||!acReported||climate.some(([,n])=>n===null)||tanks.some(([,n])=>n===null));
  const unacknowledged=alerts.filter(alert=>!alert.acknowledged), attention=!fault&&!stale&&unacknowledged.length>0;
  return <>
    <section className={`hero-status ${fault?"fault":stale?"stale":attention?"alert":""}`}><div className="status-emblem" aria-hidden="true">{fault||attention?"!":stale?"…":"✓"}</div><div className="hero-copy"><p>WHOLE-RV STATUS</p><h1>{fault?"Shore power lost":stale?"Data connection stale":attention?`${unacknowledged.length} active ${unacknowledged.length===1?"alert":"alerts"}`:partial?"Live data connected":"Systems normal"}</h1>{fault&&<small>3 minutes ago · Battery is carrying the RV</small>}{stale&&<small>Last complete update 8 minutes ago</small>}{attention&&<small>{unacknowledged[0].title} · Open Events for details</small>}{partial&&!attention&&<small>Only installed and mapped sensors are shown</small>}</div><div className="hero-connectivity" aria-label="Connectivity status"><div className={`connectivity-indicator ${internetOnline===null?"unknown":internetOnline?"online":"offline"}`} title={`Internet ${internetOnline===null?"not reported":internetOnline?"online":"offline"}`}><span aria-hidden="true" className="signal-icon"><i/><i/><i/></span><small>Internet</small>{internetOnline===false&&<b aria-hidden="true">×</b>}</div><div className={`connectivity-indicator ${rvWhisperOnline?"online":"offline"}`} title={`RV Whisper ${rvWhisperOnline?"synchronized":"offline"}`}><span aria-hidden="true" className="sync-icon">↻</span><small>RV Sync</small>{!rvWhisperOnline&&<b aria-hidden="true">×</b>}</div></div></section>
    <div className="home-quadrants">
      {profile.sections.battery.enabled&&<button type="button" onClick={()=>go("battery")} className={`home-quadrant battery-quadrant ${stale?"is-stale":""}`} aria-label={`Open ${profile.sections.battery.label} details`}><div className="card-heading"><span>{profile.sections.battery.label}</span>{stale?<StatusPill tone="off" label="Stale"/>:batteryReported?<i className="ok-dot"/>:<StatusPill tone="off" label="Not reported"/>}</div><div className="quadrant-power-layout"><div className={`battery-ring ${fault?"fault-ring":""} ${soc===null?"unknown":""}`} style={{"--charge":`${soc??0}%`} as CSSProperties}><span><b>{soc===null?"—":displayNumber(soc)}</b>{soc!==null&&<small>%</small>}</span></div><div className="quadrant-power-copy"><small>STATE</small><strong className={current===null?"unknown":current<0?"negative":"positive"}>{current===null?"Not reported":current<0?"Discharging":"Charging"}</strong><div className="quadrant-metric"><b>{current===null?"—":current>0?`+${displayNumber(current)}`:displayNumber(current)}</b>{current!==null&&<span>A</span>}<small>Battery current</small></div></div></div></button>}
      {profile.sections.ac_power.enabled&&<button type="button" onClick={()=>go("ac-power")} className={`home-quadrant ac-quadrant ${fault?"has-fault":stale?"is-stale":""}`} aria-label={`Open ${profile.sections.ac_power.label} details`}><div className="card-heading"><span>{profile.sections.ac_power.label}</span>{fault?<StatusPill tone="warn" label="Lost"/>:stale?<StatusPill tone="off" label="Stale"/>:acReported?<i className="ok-dot"/>:<StatusPill tone="off" label="Not reported"/>}</div><div className="quadrant-power-layout"><div className={`ac-power-orb ${acConnectedValue===false?"offline":""} ${!acReported?"unknown":""}`} aria-hidden="true">ϟ</div><div className="quadrant-power-copy"><small>SHORE POWER</small><strong className={!acReported?"unknown":acConnectedValue?"positive":"negative"}>{!acReported?"Not reported":acConnectedValue?"Connected":"Disconnected"}</strong><div className="quadrant-metric"><b>{acCurrent===null?"—":displayNumber(acCurrent)}</b>{acCurrent!==null&&<span>A</span>}<small>AC current</small></div></div></div></button>}
      {profile.sections.climate.enabled&&<button type="button" onClick={()=>go("climate")} className={`home-quadrant climate-quadrant ${stale?"is-stale":""}`} aria-label={`Open ${profile.sections.climate.label} details`}><div className="card-heading"><span>{profile.sections.climate.label}</span>{climate.some(([,n])=>n!==null)?<i className="ok-dot"/>:<StatusPill tone="off" label="Not reported"/>}</div><div className="climate-simple-grid">{climate.map(([label,n])=><div key={label}><span>{label}</span><strong className={n===null?"unknown":""}>{n===null?"—":`${Math.round(n)}°`}</strong></div>)}</div></button>}
      {profile.sections.tanks.enabled&&<button type="button" onClick={()=>go("tanks")} className="home-quadrant tanks-quadrant" aria-label={`Open ${profile.sections.tanks.label} details`}><div className="card-heading"><span>{profile.sections.tanks.label}</span>{tanks.some(([,n])=>n!==null)?<i className="ok-dot"/>:<StatusPill tone="off" label="Not reported"/>}</div><div className="tank-columns">{tanks.map(([name,level])=><div className="tank-column" key={name}><span>{name}</span><div className="tank-bucket"><i style={{height:`${level??0}%`}}/><b>{level===null?"—":`${displayNumber(level)}%`}</b></div></div>)}</div></button>}
    </div>
  </>;
}

type DetailProps={scenario:Scenario;reading:(path:string)=>ApiReading|undefined;ranges:Record<string,RangeSummary>;profile:DashboardProfile};

function BatteryView({scenario,reading,ranges,profile}:DetailProps){
  const fault=scenario==="shore-loss", rawSoc=reading("power.battery.soc"), rawCurrent=reading("power.battery.current");
  const soc=fault?81:optionalNumber(rawSoc?.value), current=fault?-31:optionalNumber(rawCurrent?.value);
  const currentReading=fault?{...rawCurrent,value:current,unit:"A",health:"warning"} as ApiReading:rawCurrent;
  const socReading=fault?{...rawSoc,value:soc,unit:"%",health:"warning"} as ApiReading:rawSoc;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENERGY · DIAGNOSTICS" title={profile.sections.battery.label} action="Current readings + retained 24-hour range"/>
    <section className={`detail-hero battery-detail-hero ${fault?"warning":""}`}><div className={`battery-ring detail-ring ${soc===null?"unknown":""}`} style={{"--charge":`${soc??0}%`} as CSSProperties}><span><b>{soc===null?"—":displayNumber(soc)}</b>{soc!==null&&<small>%</small>}</span></div><div><span>STATE OF CHARGE</span><h3 className={current===null?"unknown":current<0?"negative":"positive"}>{current===null?"Not reported":current<0?"Discharging":"Charging"}</h3><p>{current===null?"Battery current not reported":`${current>0?"+":""}${displayNumber(current)} A battery current`}</p></div><HealthBadge health={fault?"warning":rawSoc?.health}/></section>
    <div className="diagnostic-grid four-up"><DiagnosticMetric label="State of charge" path="power.battery.soc" reading={socReading} summary={ranges["power.battery.soc"]} fallbackUnit="%"/><DiagnosticMetric label="Battery current" path="power.battery.current" reading={currentReading} summary={ranges["power.battery.current"]} fallbackUnit="A"/><DiagnosticMetric label="Battery power" path="power.battery.power" reading={reading("power.battery.power")} summary={ranges["power.battery.power"]} fallbackUnit="W"/><DiagnosticMetric label="Battery voltage" path="power.battery.voltage" reading={reading("power.battery.voltage")} summary={ranges["power.battery.voltage"]} fallbackUnit="V"/></div>
    <p className="flow-note"><b>Interpretation:</b> positive shunt current is shown as charging and negative current as discharging. Source-specific solar or alternator flow is omitted until a dedicated mapped reading exists.</p>
  </div>;
}

function AcPowerView({scenario,reading,ranges,profile}:DetailProps){
  const forcedDisconnected=scenario==="shore-loss", connectedReading=reading("power.ac.connected"), reported=forcedDisconnected||typeof connectedReading?.value==="boolean", connected=!forcedDisconnected&&connectedReading?.value===true;
  const watchdogError=reading("power.ac.error"),sensorActive=reading("power.ac.sensor_active"),lastSeen=reading("power.ac.last_seen_seconds");
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENERGY · DIAGNOSTICS" title={profile.sections.ac_power.label} action="Current readings + retained 24-hour range"/>
    <section className={`detail-hero ac-detail-hero ${reported&&!connected?"warning":""}`}><div className={`ac-power-orb ${reported&&!connected?"offline":""} ${!reported?"unknown":""}`} aria-hidden="true">ϟ</div><div><span>SHORE POWER</span><h3 className={!reported?"unknown":connected?"positive":"negative"}>{!reported?"Not reported":connected?"Connected":"Disconnected"}</h3><p>{!reported?"No mapped AC sensor is installed":connected?`${displayNumber(reading("power.ac.current")?.value)} A presently reported`:"No AC source presently reported"}</p></div><HealthBadge health={forcedDisconnected?"warning":connectedReading?.health}/></section>
    <div className="diagnostic-grid four-up"><DiagnosticMetric label="AC voltage" path="power.ac.voltage" reading={forcedDisconnected?undefined:reading("power.ac.voltage")} summary={ranges["power.ac.voltage"]} fallbackUnit="V"/><DiagnosticMetric label="AC current" path="power.ac.current" reading={forcedDisconnected?undefined:reading("power.ac.current")} summary={ranges["power.ac.current"]} fallbackUnit="A"/><DiagnosticMetric label="AC frequency" path="power.ac.frequency" reading={forcedDisconnected?undefined:reading("power.ac.frequency")} summary={ranges["power.ac.frequency"]} fallbackUnit="Hz"/><DiagnosticMetric label="AC power" path="power.ac.power" reading={forcedDisconnected?undefined:reading("power.ac.power")} summary={ranges["power.ac.power"]} fallbackUnit="W"/><DiagnosticMetric label="Energy used" path="power.ac.energy_kwh" reading={reading("power.ac.energy_kwh")} summary={ranges["power.ac.energy_kwh"]} fallbackUnit="kWh"/><DiagnosticMetric label="Watchdog signal" path="power.ac.rssi" reading={reading("power.ac.rssi")} summary={ranges["power.ac.rssi"]} fallbackUnit="dBm"/></div>
    <p className="flow-note"><b>Power Watchdog:</b> {watchdogError?String(watchdogError.value):"Error status not reported"} · Sensor {sensorActive?.value===true?"active":sensorActive?.value===false?"offline":"status unknown"} · Last report {lastSeen?`${displayNumber(lastSeen.value)} ${lastSeen.unit||"sec"} ago`:"not reported"}. <b>AC power is supplied directly by the Watchdog and is not estimated from volts × amps.</b></p>
  </div>;
}

function ClimateView({reading,ranges,profile}:DetailProps){
  const sensors=profile.sections.climate.items;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="ENVIRONMENT · DIAGNOSTICS" title={profile.sections.climate.label} action="Current readings + retained 24-hour range"/>
    <div className="diagnostic-grid climate-detail-grid">{sensors.map(sensor=>{const path=sensor.path,base=path.replace(/\.temperature$/,""),humidity=reading(`${base}.humidity`),item=reading(path),battery=reading(`${base}.sensor_battery`),rssi=reading(`${base}.rssi`),active=reading(`${base}.sensor_active`),lastSeen=reading(`${base}.last_seen_seconds`),hasDiagnostics=[battery,rssi,active,lastSeen].some(Boolean);return <article className="diagnostic-card climate-detail-card" key={sensor.id}><div className="diagnostic-card-head"><span>{sensor.label}</span><HealthBadge health={item?.health}/></div><strong className="diagnostic-value">{displayNumber(item?.value)}<small>{item?.unit||"°F"}</small></strong><div className="secondary-reading"><span>Humidity</span><b>{humidity?`${displayNumber(humidity.value)}${humidity.unit||"%"}`:"Not reported"}</b></div>{hasDiagnostics&&<dl className="sensor-diagnostics"><div><dt>Sensor battery</dt><dd>{battery?`${displayNumber(battery.value)}${battery.unit||"%"}`:"—"}</dd></div><div><dt>Signal</dt><dd>{rssi?`${displayNumber(rssi.value)} ${rssi.unit||"dBm"}`:"—"}</dd></div><div><dt>Sensor</dt><dd>{active?.value===true?"Active":active?.value===false?"Inactive":"—"}</dd></div><div><dt>Last report</dt><dd>{lastSeen?`${displayNumber(lastSeen.value)} ${lastSeen.unit||"sec"}`:"—"}</dd></div></dl>}<RangeStrip summary={ranges[path]} unit={item?.unit||"°F"}/><ReadingMeta reading={item}/><code>{path}</code></article>})}</div>
    <p className="flow-note"><b>Only mapped measurements are shown.</b> Humidity appears automatically when RV Whisper reports and maps it; decorative trend bars and invented humidity values have been removed.</p>
  </div>;
}

function TanksView({reading,ranges,profile}:DetailProps){
  const tanks=profile.sections.tanks.items;
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow="RESOURCES · DIAGNOSTICS" title={profile.sections.tanks.label} action="Current readings + retained 24-hour range"/>
    <div className="diagnostic-grid tank-detail-grid">{tanks.map(tank=>{const path=tank.path,item=reading(path),level=numberValue(item?.value);return <article className="diagnostic-card tank-detail-card" key={tank.id}><div className="diagnostic-card-head"><span>{tank.label}</span><HealthBadge health={item?.health}/></div><div className="tank-detail-reading"><div className={`vertical-gauge ${tank.tone||"gray"}`}><i style={{height:`${level}%`}}/></div><strong>{displayNumber(item?.value)}<small>{item?.unit||"%"}</small></strong></div><RangeStrip summary={ranges[path]} unit={item?.unit||"%"}/><ReadingMeta reading={item}/><code>{path}</code></article>})}</div>
    <p className="flow-note"><b>Volume estimates are intentionally omitted.</b> Gallons can only be calculated once each tank’s usable capacity and calibrated sender behavior are configured.</p>
  </div>;
}

function EventsView({events,alerts,connection,acknowledgementEnabled,onAcknowledge}:{events:ApiEvent[];alerts:ApiAlert[];connection:Connection;acknowledgementEnabled:boolean;onAcknowledge:(alertId:string,pin:string)=>Promise<string>}){
  const [selected,setSelected]=useState<ApiAlert|null>(null),[pin,setPin]=useState(""),[busy,setBusy]=useState(false),[feedback,setFeedback]=useState("");
  const rows=events.length?events:connection==="demo"?DEMO_EVENTS:[],unacknowledged=alerts.filter(alert=>!alert.acknowledged),acknowledged=alerts.filter(alert=>alert.acknowledged);
  const closeDialog=()=>{if(busy)return;setSelected(null);setPin("");setFeedback("")};
  const submit=async(event:FormEvent)=>{event.preventDefault();if(!selected||busy)return;setBusy(true);setFeedback("");try{const status=await onAcknowledge(selected.id,pin);setSelected(null);setFeedback(status==="already_acknowledged"?"RV Whisper had already acknowledged this alert; no duplicate request was sent.":"RV Whisper confirmed the acknowledgement.")}catch(error){setFeedback(error instanceof Error?error.message:"Acknowledgement could not be confirmed")}finally{setPin("");setBusy(false)}};
  return <div className="detail-view diagnostic-view"><SectionHeading eyebrow={acknowledgementEnabled?"RV WHISPER · VERIFIED LOCAL CONTROL":"RV WHISPER · READ ONLY"} title="Alerts & Events" action={`${unacknowledged.length} needs attention · ${acknowledged.length} acknowledged`}/>
    {feedback&&<div className="ack-feedback" role="status">{feedback}</div>}
    <section className="active-alert-panel"><div className="active-alert-heading"><div><span>ACTIVE RV WHISPER ALERTS</span><strong>{alerts.length||"None"}</strong></div><small>{acknowledgementEnabled?"One alert at a time · confirmation and operator PIN required":"Acknowledgement and notification delivery remain in RV Whisper"}</small></div>{alerts.length?<div className="active-alert-grid">{alerts.map(alert=><article className={alert.acknowledged?"acknowledged":"unacknowledged"} key={alert.id}><StatusPill tone={alert.acknowledged?"off":"warn"} label={alert.acknowledged?"Acknowledged":"Needs attention"}/><strong>{alert.title}</strong><small>Active since {formatTimestamp(alert.created_at??undefined)}</small><p>{alert.acknowledged?"Still active; repeat notifications are silenced in RV Whisper.":"RV Whisper notifications remain active until acknowledged or cleared."}</p>{acknowledgementEnabled&&!alert.acknowledged&&<button className="acknowledge-button" type="button" onClick={()=>{setSelected(alert);setFeedback("")}}>Acknowledge</button>}</article>)}</div>:<p className="no-active-alerts">No RV Whisper trigger conditions are currently active.</p>}</section>
    <section className="event-card diagnostic-events"><div className="event-date">{connection==="demo"?"PREVIEW EVENT LOG":"LOCAL ALERT TRANSITIONS & COLLECTOR EVENTS"}</div>{rows.length?rows.map((event,index)=><div className="event-row rich-event-row" key={event.id??`${event.occurred_at}-${index}`}><time dateTime={event.occurred_at}>{formatTimestamp(event.occurred_at)}</time><i className={event.severity}/><div><strong>{event.title}</strong><small>{event.detail||"No additional detail"}</small></div><span>{event.event_type||"event"}</span><HealthBadge health={event.severity}/></div>):<p className="empty-event-log">No alert transitions or collector events have been recorded yet.</p>}</section><p className="flow-note"><b>RV Whisper remains authoritative.</b> A dashboard acknowledgement stops repeat notifications for only the current alert instance; it does not clear the condition, disable its rule, or interrupt RV Whisper monitoring.</p>
    {selected&&<div className="ack-dialog-backdrop"><section className="ack-dialog" role="dialog" aria-modal="true" aria-labelledby="ack-dialog-title"><form onSubmit={submit}><span>CONFIRM RV WHISPER ACTION</span><h3 id="ack-dialog-title">Acknowledge “{selected.title}”?</h3><p>This stops repeat RV Whisper notifications for this active alert. The condition remains active and visible, and its alert rule stays enabled.</p><label><b>Operator PIN</b><input type="password" inputMode="numeric" pattern="[0-9]*" minLength={4} maxLength={12} required value={pin} onChange={event=>setPin(event.target.value)} autoComplete="off"/></label>{feedback&&<small className="ack-error" role="alert">{feedback}</small>}<div><button type="button" onClick={closeDialog} disabled={busy}>Cancel</button><button type="submit" className="confirm" disabled={busy||pin.length<4}>{busy?"Verifying…":"Acknowledge alert"}</button></div></form></section></div>}
  </div>;
}

export default function Dashboard(){
  const [view,setView]=useState<View>("home"),[scenario,setScenario]=useState<Scenario>("normal"),[clock,setClock]=useState(()=>new Date());
  const telemetry=useTelemetry(); useEffect(()=>{const timer=window.setInterval(()=>setClock(new Date()),30_000);return()=>window.clearInterval(timer)},[]);
  useEffect(()=>{document.title=`${telemetry.profile.vehicle.name} Systems`},[telemetry.profile.vehicle.name]);
  const clockLabel=useMemo(()=>clock.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}),[clock]);
  const sectionFor=(id:Exclude<View,"home">)=>id==="battery"?telemetry.profile.sections.battery:id==="ac-power"?telemetry.profile.sections.ac_power:telemetry.profile.sections[id];
  const nav=NAV.filter(item=>sectionFor(item.id).enabled).map(item=>({...item,label:sectionFor(item.id).label}));
  const detailProps={scenario,reading:telemetry.reading,ranges:telemetry.ranges,profile:telemetry.profile},unacknowledged=telemetry.alerts.filter(alert=>!alert.acknowledged).length,attention=scenario==="shore-loss"||unacknowledged>0;
  return <main className={`dashboard-shell scenario-${scenario}`}><header className="topbar"><button className="brand-lockup" type="button" onClick={()=>setView("home")} aria-label="Go to home dashboard"><span className="brand-mark">{telemetry.profile.vehicle.monogram}</span><span><strong>{telemetry.profile.vehicle.name}</strong><small>{telemetry.profile.vehicle.subtitle}</small></span></button><div className="topbar-right"><label className="scenario-control"><span>Preview state</span><select value={scenario} onChange={event=>setScenario(event.target.value as Scenario)} aria-label="Preview dashboard state"><option value="normal">Normal</option><option value="shore-loss">Shore power lost</option><option value="stale">Stale data</option></select></label><StatusPill tone={scenario==="stale"||telemetry.connection==="offline"?"off":attention?"warn":"ok"} label={scenario==="stale"?"Stale":attention?"Attention":telemetry.connection==="online"?"Live":telemetry.connection==="offline"?"Offline":"Demo"}/><span className="clock">{clockLabel}</span></div></header>
    <nav className="rail" aria-label="Dashboard sections">{nav.map(item=><button key={item.id} className={`rail-item ${view===item.id?"active":""}`} type="button" onClick={()=>setView(item.id)}><b className={`rail-symbol rail-${item.icon}`} aria-hidden="true">{item.glyph}</b><span>{item.label}</span>{item.id==="events"&&(scenario==="shore-loss"||unacknowledged>0)&&<i>{unacknowledged||1}</i>}</button>)}</nav>
    <section className="content" aria-live="polite">{view==="home"&&<HomeView scenario={scenario} connection={telemetry.connection} value={telemetry.value} alerts={telemetry.alerts} profile={telemetry.profile} go={setView}/>} {view==="battery"&&<BatteryView {...detailProps}/>} {view==="ac-power"&&<AcPowerView {...detailProps}/>} {view==="climate"&&<ClimateView {...detailProps}/>} {view==="tanks"&&<TanksView {...detailProps}/>} {view==="events"&&<EventsView events={telemetry.events} alerts={telemetry.alerts} connection={telemetry.connection} acknowledgementEnabled={telemetry.profile.capabilities?.alert_acknowledgement===true} onAcknowledge={telemetry.acknowledgeAlert}/>}<footer><span>Dashboard visualizes current state</span><b>RV Whisper alerts operate independently</b></footer></section>
  </main>;
}
