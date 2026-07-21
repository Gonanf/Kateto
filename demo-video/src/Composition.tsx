import {
  AbsoluteFill,
  CalculateMetadataFunction,
  Composition,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import "./index.css";

type Props = {};

const calculateMetadata: CalculateMetadataFunction<Props> = () => {
  return {};
};

export const MyComposition = () => {
  return (
    <Composition
      id="KatetoLiveDemo"
      component={MyComponent}
      durationInFrames={2700}
      fps={30}
      width={1280}
      height={720}
      calculateMetadata={calculateMetadata}
    />
  );
};

export const MyComponent: React.FC<Props> = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const fade = (start: number, end: number) =>
    interpolate(frame, [start, start + 15, end - 15, end], [0, 1, 1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  return (
    <AbsoluteFill className="canvas">
      <Sequence from={0} durationInFrames={270}>
        <TitleScene opacity={fade(0, 270)} />
      </Sequence>
      <Sequence from={240} durationInFrames={570}>
        <RuntimeScene opacity={fade(240, 810)} frame={frame - 240} fps={fps} />
      </Sequence>
      <Sequence from={780} durationInFrames={1050}>
        <TuiScene opacity={fade(780, 1830)} frame={frame - 780} />
      </Sequence>
      <Sequence from={1800} durationInFrames={630}>
        <CoordinationScene opacity={fade(1800, 2430)} frame={frame - 1800} />
      </Sequence>
      <Sequence from={2400} durationInFrames={300}>
        <CloseScene opacity={fade(2400, 2700)} />
      </Sequence>
    </AbsoluteFill>
  );
};

const Avatar: React.FC<{src: string; name: string; role: string; status: string; delay?: number}> = ({src, name, role, status, delay = 0}) => {
  const frame = useCurrentFrame();
  const scale = spring({frame: Math.max(0, frame - delay), fps: 30, config: {damping: 14}});
  return (
    <div className="avatar-card" style={{transform: `scale(${scale})`}}>
      <Img src={staticFile(src)} className="avatar" />
      <div><div className="avatar-name">{name}</div><div className="muted">{role}</div></div>
      <span className={`status ${status === "thinking" ? "thinking" : ""}`}>{status}</span>
    </div>
  );
};

const Header: React.FC<{eyebrow: string; title: string; subtitle: string}> = ({eyebrow, title, subtitle}) => (
  <div className="header-block"><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>
);

const TitleScene: React.FC<{opacity: number}> = ({opacity}) => (
  <AbsoluteFill className="scene title-scene" style={{opacity}}>
    <div className="grid-glow" />
    <div className="eyebrow">OPENAI BUILD WEEK · WORK & PRODUCTIVITY</div>
    <h1 className="hero-title">Kateto</h1>
    <div className="hero-line">An event-driven voice team that turns intent into visible work.</div>
    <div className="pill-row"><span>typed events</span><span>live TUI</span><span>DeepSeek</span><span>workflows</span></div>
    <div className="small-note">A live configuration demo · 01:30</div>
  </AbsoluteFill>
);

const RuntimeScene: React.FC<{opacity: number; frame: number; fps: number}> = ({opacity, frame, fps}) => (
  <AbsoluteFill className="scene" style={{opacity}}>
    <Header eyebrow="01 · LIVE RUNTIME" title="The configuration is real" subtitle="Kateto boots from the existing local config: DeepSeek for reasoning, event plugins for orchestration." />
    <div className="runtime-grid">
      <div className="config-card">
        <div className="card-label">CONFIG / VOICE LLM</div>
        <div className="config-row"><span>provider</span><strong>DeepSeek</strong></div>
        <div className="config-row"><span>model</span><strong>deepseek-v4-flash</strong></div>
        <div className="config-row"><span>endpoint</span><strong>api.deepseek.com</strong></div>
        <div className="secret">●●●●●●●●●●  key stays local</div>
      </div>
      <div className="team-panel">
        <div className="card-label">DISCOVERED VOICES</div>
        <Avatar src="public-jane.svg" name="Jane" role="orchestrator" status="idle" delay={10} />
        <Avatar src="public-doktor.svg" name="Doktor" role="delivery advisor" status="idle" delay={25} />
        <Avatar src="public-conquest.svg" name="Conquest" role="agile facilitator" status="idle" delay={40} />
      </div>
    </div>
    <div className="event-strip" style={{transform: `translateX(${interpolate(frame, [0, 90], [-40, 0], {extrapolateRight: "clamp"})}px)`}}>
      <span className="dot green" /> PluginManager online <span className="arrow">→</span> hot reload <span className="arrow">→</span> MCP servers <span className="arrow">→</span> voices
    </div>
    <div className="caption">No custom pipeline. Every handoff is a typed event.</div>
  </AbsoluteFill>
);

const TuiScene: React.FC<{opacity: number; frame: number}> = ({opacity, frame}) => {
  const zoom = interpolate(frame, [0, 240], [1, 1.04], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill className="scene" style={{opacity}}>
      <Header eyebrow="02 · THE TUI" title="Watch the runtime think" subtitle="Events, plugins, voices, workflows, and MCP servers are visible in one live surface." />
      <div className="tui-wrap" style={{transform: `scale(${zoom})`}}>
        <Img src={staticFile("public-tui-live.png")} className="tui-shot" />
        <div className="callout callout-events"><b>EVENTS</b><span>audio → voice → workflow</span></div>
        <div className="callout callout-tabs"><b>RUNTIME TABS</b><span>Plugins · Voices · Workflows · MCPs</span></div>
      </div>
      <div className="tui-bottom"><span className="live-dot" /> LIVE EVENT STREAM <span className="muted">Every event is retained, bounded, and inspectable.</span></div>
    </AbsoluteFill>
  );
};

const CoordinationScene: React.FC<{opacity: number; frame: number}> = ({opacity, frame}) => {
  const active = Math.min(3, Math.floor(frame / 120));
  const cards = [
    ["01", "audio_input", "audio_data", "silence detected"],
    ["02", "Jane", "workflow_run", "project-initiation"],
    ["03", "Doktor + Conquest", "voice_request", "called by the phase"],
    ["04", "runtime", "workflow_phase_complete", "deliverables + checkpoints"],
  ];
  return (
    <AbsoluteFill className="scene" style={{opacity}}>
      <Header eyebrow="03 · ORCHESTRATION" title="One request, a whole team" subtitle="Jane owns the workflow. Specialists are activated only when the phase calls them." />
      <div className="flow">
        {cards.map(([number, source, event, detail], index) => (
          <div className={`flow-card ${index <= active ? "active" : ""}`} key={number}>
            <div className="flow-num">{number}</div><div className="flow-source">{source}</div><div className="flow-event">{event}</div><div className="muted">{detail}</div>
            {index < cards.length - 1 && <div className="flow-arrow">→</div>}
          </div>
        ))}
      </div>
      <div className="workflow-tree">
        <div className="tree-title">VOICE WORKFLOWS</div>
        <div>▾ Jane · THINKING</div><div className="indent">▾ project-initiation · RUNNING</div><div className="indent2">Phase: Define scope and stakeholders</div><div className="indent2">Checkpoints: 2 / 3 · Task: identify stakeholders</div>
        <div className="tree-voices"><span>Doktor · enabled by event</span><span>Conquest · enabled by event</span></div>
      </div>
    </AbsoluteFill>
  );
};

const CloseScene: React.FC<{opacity: number}> = ({opacity}) => (
  <AbsoluteFill className="scene close-scene" style={{opacity}}>
    <div className="eyebrow">THE RESULT</div><h1 className="close-title">Plans become artifacts.</h1>
    <div className="artifact-row"><div><span>PLAN.md</span><b>scope · objectives · milestones</b></div><div><span>TODO.md</span><b>actionable work items</b></div><div><span>backlog</span><b>prioritized delivery</b></div></div>
    <div className="final-line">Kateto · events all the way down.</div>
  </AbsoluteFill>
);
