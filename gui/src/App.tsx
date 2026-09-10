import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import "./App.css";
import { createMockAppClient } from "./client/mockAppClient";
import { probeFixtureBridge, type BridgeProbe } from "./client/nativeFixtureBridge";
import type {
  FixturePlaybackPort,
  ReadonlyDocument,
  SessionSnapshot,
} from "./client/model";
import { emptyGuiState, guiReducer } from "./client/state";

interface HarnessGuiProps {
  readonly client: FixturePlaybackPort;
}

export function HarnessGui({ client }: HarnessGuiProps) {
  const [state, dispatch] = useReducer(guiReducer, undefined, emptyGuiState);
  const [notice, setNotice] = useState("Loading fixture snapshot…");
  const [remainingSteps, setRemainingSteps] = useState(0);
  const [bridgeProbe, setBridgeProbe] = useState<BridgeProbe>({
    status: "web-mock",
    label: "Web Mock",
  });
  const submissionCounter = useRef(1);

  useEffect(() => {
    let active = true;
    const unsubscribe = client.subscribe((event) => {
      dispatch({ type: "event.received", event });
      setRemainingSteps(client.remainingFixtureSteps());
    });
    void client.snapshot().then((snapshot) => {
      if (!active) return;
      dispatch({ type: "snapshot.installed", snapshot });
      setNotice("Fixture snapshot installed. No backend is running.");
    });
    void probeFixtureBridge().then((probe) => {
      if (active) setBridgeProbe(probe);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [client]);

  const selectedId = state.local.selectedSessionId;
  const selected = selectedId ? state.remote.sessions[selectedId] : undefined;
  const selectedDocument = selected
    ? findSelectedDocument(
        selected,
        state.local.selectedDocuments[selected.id] ?? null,
      )
    : undefined;

  async function submit(): Promise<void> {
    if (!selected) return;
    const text = state.local.drafts[selected.id] ?? "";
    if (!text.trim()) {
      setNotice("Enter a fixture prompt before sending.");
      return;
    }
    const submissionId = `gui-fixture-submission-${submissionCounter.current++}`;
    const receipt = await client.submitText({
      sessionId: selected.id,
      submissionId,
      text,
    });
    if (!receipt.accepted) {
      setNotice("The fixture rejected this submission.");
      return;
    }
    dispatch({ type: "draft.changed", sessionId: selected.id, value: "" });
    setRemainingSteps(client.remainingFixtureSteps());
    setNotice("Fixture accepted the prompt. Advance it step by step.");
  }

  async function advance(): Promise<void> {
    const step = await client.advanceFixture();
    if (!step) {
      setNotice("No fixture event is waiting.");
      return;
    }
    setRemainingSteps(step.remaining);
    setNotice(`Playback: ${step.label}.`);
  }

  async function interrupt(): Promise<void> {
    if (!selected) return;
    const receipt = await client.interrupt(selected.id);
    setRemainingSteps(client.remainingFixtureSteps());
    setNotice(
      receipt.accepted
        ? "Fixture execution interrupted."
        : (receipt.reason ?? "Interrupt was not accepted."),
    );
  }

  return (
    <main className="app-shell">
      <aside className="session-rail" aria-label="Fixture sessions">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">H</div>
          <div>
            <strong>HarnessGUI</strong>
            <span>Product-neutral shell</span>
          </div>
        </div>
        <div className="fixture-banner">
          <span className="fixture-dot" aria-hidden="true" />
          {state.remote.fixtureLabel || "Offline fixture"}
        </div>
        <nav className="session-list" aria-label="Sessions">
          <p className="section-label">Sessions</p>
          {state.remote.sessionOrder.map((sessionId) => {
            const session = state.remote.sessions[sessionId];
            const isSelected = sessionId === selectedId;
            return (
              <button
                className={`session-item${isSelected ? " selected" : ""}`}
                key={sessionId}
                type="button"
                aria-current={isSelected ? "page" : undefined}
                onClick={() => dispatch({ type: "session.selected", sessionId })}
              >
                <span className="session-title">{session.title}</span>
                <span className={`status-pill ${session.status}`}>
                  {statusLabel(session.status)}
                </span>
                {state.local.unread[sessionId] ? (
                  <span className="unread-dot" aria-label="Unread updates" />
                ) : null}
              </button>
            );
          })}
        </nav>
        <div className="rail-footer">
          <span>Source</span>
          <strong>Fixture only</strong>
          <span>Bridge</span>
          <strong className={`bridge-state ${bridgeProbe.status}`}>
            {bridgeProbe.label}
          </strong>
        </div>
      </aside>

      <section className="conversation-pane" aria-label="Conversation">
        {selected ? (
          <>
            <header className="conversation-header">
              <div>
                <p className="eyebrow">{selected.context.project}</p>
                <h1>{selected.title}</h1>
                <p className="identity-line">
                  {selected.context.applicationId} / {selected.context.muxId} /{" "}
                  {selected.context.memberId}
                </p>
              </div>
              <span className={`connection-chip ${state.remote.connection}`}>
                {connectionLabel(state.remote.connection)}
              </span>
            </header>

            {state.diagnostic ? (
              <div className="diagnostic" role="alert">{state.diagnostic}</div>
            ) : null}

            <div className="transcript" aria-live="polite">
              {selected.messages.map((message) => (
                <article
                  className={`message ${message.role}`}
                  key={message.id}
                  aria-label={`${message.role} message`}
                >
                  <div className="message-meta">
                    <strong>{message.role === "user" ? "You" : "Harness"}</strong>
                    <span>{message.phase}</span>
                  </div>
                  <p>{message.content || "Waiting for fixture output…"}</p>
                </article>
              ))}
            </div>

            <div className="playback-strip" aria-label="Fixture playback controls">
              <div>
                <strong>Deterministic playback</strong>
                <span>{remainingSteps} queued event{remainingSteps === 1 ? "" : "s"}</span>
              </div>
              <button type="button" onClick={() => void advance()}>
                Advance fixture
              </button>
            </div>

            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
            >
              <label htmlFor="message-input">Message for {selected.title}</label>
              <textarea
                id="message-input"
                rows={3}
                value={state.local.drafts[selected.id] ?? ""}
                placeholder="Type a fixture prompt…"
                onChange={(event) =>
                  dispatch({
                    type: "draft.changed",
                    sessionId: selected.id,
                    value: event.currentTarget.value,
                  })
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    void submit();
                  }
                }}
              />
              <div className="composer-actions">
                <p role="status">{notice}</p>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={selected.status !== "running"}
                  onClick={() => void interrupt()}
                >
                  Interrupt
                </button>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={selected.status === "running"}
                >
                  Send
                </button>
              </div>
            </form>
          </>
        ) : (
          <div className="empty-state">No fixture session is available.</div>
        )}
      </section>

      <aside className="context-pane" aria-label="Context and documents">
        {selected ? (
          <>
            <section className="context-card" aria-labelledby="context-title">
              <p className="section-label" id="context-title">Context · fixture</p>
              <dl className="context-grid">
                <div><dt>Root</dt><dd>{selected.context.rootLabel}</dd></div>
                <div><dt>Session</dt><dd>{selected.context.sessionId}</dd></div>
              </dl>
              <div className="capability-list" aria-label="Capabilities">
                {state.remote.capabilities.map((capability) => (
                  <span className={`capability ${capability.availability}`} key={capability.name}>
                    {capability.name} · {capability.version ?? "unavailable"}
                  </span>
                ))}
              </div>
            </section>

            <section className="document-card" aria-labelledby="documents-title">
              <div className="document-heading">
                <div>
                  <p className="section-label" id="documents-title">Read-only documents</p>
                  <strong>{selected.documents.length} fixture item{selected.documents.length === 1 ? "" : "s"}</strong>
                </div>
              </div>
              <div className="document-tabs">
                {selected.documents.map((document) => (
                  <button
                    type="button"
                    key={document.id}
                    className={document.id === selectedDocument?.id ? "active" : ""}
                    aria-pressed={document.id === selectedDocument?.id}
                    onClick={() =>
                      dispatch({
                        type: "document.selected",
                        sessionId: selected.id,
                        documentId: document.id,
                      })
                    }
                  >
                    {document.title}
                  </button>
                ))}
              </div>
              {selectedDocument ? (
                <DocumentView document={selectedDocument} />
              ) : (
                <p className="document-empty">No document is available for this session.</p>
              )}
            </section>
          </>
        ) : null}
      </aside>
    </main>
  );
}

function DocumentView({ document }: { readonly document: ReadonlyDocument }) {
  const lines = document.content.split("\n");
  return (
    <article className="document-view" aria-label={document.title}>
      <header>
        <span>{document.kind}</span>
        <code>{document.revision}</code>
      </header>
      <p className="document-source">{document.sourceLabel}</p>
      <pre>
        {lines.map((line, index) => (
          <span className={diffLineClass(document, line)} key={`${index}-${line}`}>
            {line || " "}{index < lines.length - 1 ? "\n" : ""}
          </span>
        ))}
      </pre>
    </article>
  );
}

function diffLineClass(document: ReadonlyDocument, line: string): string {
  if (document.kind !== "diff") return "";
  if (line.startsWith("+") && !line.startsWith("+++")) return "diff-added";
  if (line.startsWith("-") && !line.startsWith("---")) return "diff-removed";
  if (line.startsWith("@@")) return "diff-hunk";
  return "";
}

function findSelectedDocument(
  session: SessionSnapshot,
  selectedDocumentId: string | null,
): ReadonlyDocument | undefined {
  return (
    session.documents.find((document) => document.id === selectedDocumentId) ??
    session.documents[0]
  );
}

function statusLabel(status: SessionSnapshot["status"]): string {
  const labels: Record<SessionSnapshot["status"], string> = {
    idle: "Idle",
    running: "Running",
    waiting: "Needs input",
    interrupted: "Interrupted",
    failed: "Failed",
  };
  return labels[status];
}

function connectionLabel(connection: string): string {
  const labels: Record<string, string> = {
    "fixture-offline": "Offline fixture",
    connected: "Connected",
    disconnected: "Disconnected",
    "resync-required": "Resync required",
  };
  return labels[connection] ?? connection;
}

function App() {
  const client = useMemo(() => createMockAppClient(), []);
  return <HarnessGui client={client} />;
}

export default App;
