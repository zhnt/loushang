import "./App.css";

function App() {
  return (
    <main className="shell">
      <section className="card" aria-labelledby="app-title">
        <p className="eyebrow">GUI-B0 engineering baseline</p>
        <h1 id="app-title">HarnessGUI</h1>
        <p className="summary">
          Product-neutral desktop presentation for Loushang Harness workflows.
        </p>
        <dl className="status" aria-label="Baseline status">
          <div>
            <dt>Mode</dt>
            <dd>Offline shell</dd>
          </div>
          <div>
            <dt>Backend</dt>
            <dd>Not connected</dd>
          </div>
          <div>
            <dt>Runtime</dt>
            <dd>Tauri + React</dd>
          </div>
        </dl>
        <p className="notice">
          This baseline does not start AppHost, make model requests, or present
          sample data as a real session.
        </p>
      </section>
    </main>
  );
}

export default App;
